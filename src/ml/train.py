"""Train the Siamese network with contrastive loss.

Run: python -m src.ml.train [--seed N] [--no-hard-negatives] [--tag NAME] [--set FIELD=VALUE ...]
Output: artefacts/siamese.pt (best validation MAP@K) and artefacts/training_history.json.
With --tag, write artefacts/siamese_<tag>.pt and artefacts/training_history_<tag>.json instead.
`--set` overrides one `SiameseConfig` field for an ablation, for example `--set theme_weight=0`.

Objectives (`SiameseConfig.objective`):
- "pairs" (siamese-v2): contrastive loss over pairs mined once per run.
- "inbatch" (siamese-v3): each step samples `batch_size` anime and `batch_size` games from the
  training split and scores all anime-game pairs. The loss is a weighted sum of the balanced
  contrastive loss, a relevance-weighted InfoNCE loss and a theme BCE head.
Theme labels come from the training split only. Epochs are selected on validation MAP@K.
With `ensemble_size` n > 1, n encoders train with seeds seed..seed+n-1 and their cosines are averaged.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import time
from dataclasses import asdict, fields, replace
from typing import Any

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, TensorDataset

from src.config import SEED, SETTINGS, SiameseConfig, get_device, set_seed
from src.embeddings.features import model_inputs
from src.embeddings.sbert import load_embeddings
from src.evaluation.evaluate import evaluate_both, pair_loss, siamese_vectors
from src.ml.data import assign_splits, mine_bidirectional, theme_matrix
from src.ml.losses import (
    contrastive_loss,
    inbatch_contrastive_loss,
    jaccard_torch,
    relevance_infonce,
    theme_bce,
)
from src.ml.siamese import EnsembleEncoder, SiameseEncoder, SiameseNetwork, build_model

log = logging.getLogger(__name__)


def train_epoch(
    model: SiameseNetwork,
    loader: DataLoader[tuple[torch.Tensor, ...]],
    embeddings: torch.Tensor,
    optimiser: torch.optim.Optimizer,
    margin: float,
) -> float:
    model.train()
    device = embeddings.device
    total, count = 0.0, 0
    for (batch,) in loader:
        batch = batch.to(device)
        cos, _, _ = model(embeddings[batch[:, 0]], embeddings[batch[:, 1]])
        loss = contrastive_loss(cos, batch[:, 2], margin)
        optimiser.zero_grad(set_to_none=True)
        loss.backward()
        optimiser.step()
        total += loss.item() * len(batch)
        count += len(batch)
    return total / max(count, 1)


def multitask_loss(
    encoder: SiameseEncoder,
    xa: torch.Tensor,
    xg: torch.Tensor,
    ta: torch.Tensor,
    tg: torch.Tensor,
    cfg: SiameseConfig,
) -> tuple[torch.Tensor, dict[str, float]]:
    """Return the weighted in-batch loss for anime inputs `xa` and game inputs `xg`, and its parts."""
    assert xa.shape[1] == xg.shape[1] == encoder.input_dim, f"bad input shapes {xa.shape}, {xg.shape}"
    assert ta.shape == (len(xa), tg.shape[1]) and tg.shape[0] == len(xg), "theme matrices do not match inputs"
    za, zg = encoder(xa), encoder(xg)
    assert za.shape[1] == zg.shape[1] == encoder.proj_dim, "unexpected embedding width"
    cosine = za @ zg.T
    jaccard = jaccard_torch(ta, tg)
    threshold = SETTINGS.relevance.jaccard_threshold
    parts: dict[str, torch.Tensor] = {}
    if cfg.contrastive_weight:
        parts["contrastive"] = cfg.contrastive_weight * inbatch_contrastive_loss(cosine, jaccard, threshold, cfg.margin)
    if cfg.infonce_weight:
        parts["infonce"] = cfg.infonce_weight * relevance_infonce(
            cosine, jaccard, threshold, cfg.temperature, cfg.graded_gamma
        )
    if cfg.theme_weight:
        logits = encoder.theme_logits(torch.cat([za, zg]))
        parts["theme"] = cfg.theme_weight * theme_bce(logits, torch.cat([ta, tg]))
    assert parts, "every loss weight is zero"
    total = torch.stack(list(parts.values())).sum()
    return total, {name: float(value.detach()) for name, value in parts.items()}


def _epoch_order(rows: np.ndarray, needed: int, rng: np.random.Generator) -> np.ndarray:
    """Return at least `needed` rows: whole shuffled passes over `rows`, concatenated."""
    passes = -(-needed // len(rows))
    return np.concatenate([rng.permutation(rows) for _ in range(passes)])


def train_epoch_inbatch(
    encoder: SiameseEncoder,
    inputs: torch.Tensor,
    themes: torch.Tensor,
    anime_rows: np.ndarray,
    game_rows: np.ndarray,
    optimiser: torch.optim.Optimizer,
    cfg: SiameseConfig,
    rng: np.random.Generator,
) -> dict[str, float]:
    """Run `cfg.steps_per_epoch` in-batch steps and return the mean loss and its parts."""
    encoder.train()
    device = inputs.device
    b = cfg.batch_size
    anime_order = _epoch_order(anime_rows, cfg.steps_per_epoch * b, rng)
    game_order = _epoch_order(game_rows, cfg.steps_per_epoch * b, rng)
    sums: dict[str, float] = {}
    for step in range(cfg.steps_per_epoch):
        a = torch.from_numpy(anime_order[step * b : (step + 1) * b]).to(device)
        g = torch.from_numpy(game_order[step * b : (step + 1) * b]).to(device)
        loss, parts = multitask_loss(encoder, inputs[a], inputs[g], themes[a], themes[g], cfg)
        optimiser.zero_grad(set_to_none=True)
        loss.backward()
        optimiser.step()
        for name, value in {"loss": float(loss.detach()), **parts}.items():
            sums[name] = sums.get(name, 0.0) + value
    return {name: value / cfg.steps_per_epoch for name, value in sums.items()}


def labelled_train_rows(items: pd.DataFrame, splits: np.ndarray, themes: np.ndarray, domain: str) -> np.ndarray:
    """Return global rows of labelled training items of one domain."""
    mask = (items["domain"].to_numpy() == domain) & (splits == "train") & (themes.sum(axis=1) > 0)
    return np.flatnonzero(mask)


def validation_pairs(
    items: pd.DataFrame, splits: np.ndarray, themes: np.ndarray, embeddings_np: np.ndarray, cfg: SiameseConfig
) -> np.ndarray:
    """Mine validation pairs. In-batch runs use the fixed mining protocol, so losses stay comparable."""
    mining = SETTINGS.siamese if cfg.objective == "inbatch" else cfg
    return mine_bidirectional(items, splits, themes, embeddings_np, "val", seed=SEED + 100, cfg=mining)


def fit(
    items: pd.DataFrame,
    splits: np.ndarray,
    themes: np.ndarray,
    embeddings_np: np.ndarray,
    cfg: SiameseConfig,
    seed: int = SEED,
    val_pairs: np.ndarray | None = None,
) -> tuple[SiameseNetwork, dict[str, Any]]:
    """Train one model, select the epoch on validation MAP@K and return it with a summary."""
    set_seed(seed)
    k = SETTINGS.evaluation.k
    device = get_device()
    assert cfg.objective in ("pairs", "inbatch"), f"unknown objective {cfg.objective!r}"
    inbatch = cfg.objective == "inbatch"
    inputs_np = model_inputs(items, splits, embeddings_np, cfg)
    if val_pairs is None:
        val_pairs = validation_pairs(items, splits, themes, embeddings_np, cfg)
    if inbatch:
        train_pairs = np.zeros((0, 3), dtype=np.int64)
        anime_rows = labelled_train_rows(items, splits, themes, "anime")
        game_rows = labelled_train_rows(items, splits, themes, "game")
        themes_t = torch.from_numpy(themes).to(device)
        rng = np.random.default_rng(seed)
        log.info("In-batch training: %d anime, %d games; val pairs=%d", len(anime_rows), len(game_rows),
                 len(val_pairs))  # fmt: skip
    else:
        train_pairs = mine_bidirectional(items, splits, themes, embeddings_np, "train", seed=seed, cfg=cfg)
        log.info("Pairs: train=%d (pos %.1f%%), val=%d", len(train_pairs), 100 * train_pairs[:, 2].mean(),
                 len(val_pairs))  # fmt: skip

    inputs = torch.from_numpy(inputs_np).to(device)
    generator = torch.Generator().manual_seed(seed)
    model = build_model(cfg).to(device)
    assert isinstance(model.encoder, SiameseEncoder)
    optimiser = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimiser, mode="max", factor=0.5, patience=2)

    eval_kwargs = {"max_queries": SETTINGS.evaluation.max_queries}
    baseline = evaluate_both(embeddings_np, items, splits, themes, "val", **eval_kwargs)["mean"][f"map@{k}"]
    log.info("Validation MAP@%d of raw SBERT cosine: %.4f", k, baseline)

    best_map, best_state, best_epoch, stale = -1.0, None, 0, 0
    history = []
    start = time.perf_counter()
    for epoch in range(1, cfg.max_epochs + 1):
        parts: dict[str, float] = {}
        if inbatch:
            parts = train_epoch_inbatch(model.encoder, inputs, themes_t, anime_rows, game_rows, optimiser, cfg, rng)
            train_loss = parts.pop("loss")
        else:
            if cfg.resample_pairs and epoch > 1:
                train_pairs = mine_bidirectional(items, splits, themes, embeddings_np, "train", seed=seed + epoch,
                                                 cfg=cfg)  # fmt: skip
            loader = DataLoader(TensorDataset(torch.from_numpy(train_pairs)), batch_size=cfg.batch_size,
                                shuffle=True, generator=generator)  # fmt: skip
            train_loss = train_epoch(model, loader, inputs, optimiser, cfg.margin)
        val_loss = pair_loss(model, inputs_np, val_pairs, cfg.margin)
        val_map = evaluate_both(siamese_vectors(model, inputs_np), items, splits, themes, "val",
                                **eval_kwargs)["mean"][f"map@{k}"]  # fmt: skip
        scheduler.step(val_map)
        history.append({"epoch": epoch, "train_loss": train_loss, **parts, "val_loss": val_loss,
                        f"val_map@{k}": val_map, "lr": optimiser.param_groups[0]["lr"]})  # fmt: skip
        log.info("epoch %02d train_loss=%.4f %s val_loss=%.4f val_map@%d=%.4f", epoch, train_loss,
                 " ".join(f"{n}={v:.4f}" for n, v in parts.items()), val_loss, k, val_map)  # fmt: skip
        if val_map > best_map + 1e-4:
            best_map, best_epoch, stale = val_map, epoch, 0
            best_state = copy.deepcopy(model.state_dict())  # A copy, not a live reference.
        else:
            stale += 1
            if stale >= cfg.patience:
                log.info("Early stop at epoch %d", epoch)
                break

    assert best_state is not None
    model.load_state_dict(best_state)
    summary = {
        "seed": seed,
        "config": asdict(cfg),
        "best_epoch": best_epoch,
        "best_val_map": best_map,
        "sbert_val_map": baseline,
        "best_val_loss": pair_loss(model, inputs_np, val_pairs, cfg.margin),
        "train_pairs": len(train_pairs),
        "val_pairs": len(val_pairs),
        "minutes": (time.perf_counter() - start) / 60,
        "history": history,
    }
    return model, summary


def fit_ensemble(
    items: pd.DataFrame,
    splits: np.ndarray,
    themes: np.ndarray,
    embeddings_np: np.ndarray,
    cfg: SiameseConfig,
    seed: int = SEED,
) -> tuple[SiameseNetwork, dict[str, Any]]:
    """Train `cfg.ensemble_size` encoders with consecutive seeds and average their cosines."""
    val_pairs = validation_pairs(items, splits, themes, embeddings_np, cfg)
    if cfg.ensemble_size <= 1:
        return fit(items, splits, themes, embeddings_np, cfg, seed, val_pairs)
    members, summaries = [], []
    for offset in range(cfg.ensemble_size):
        model, summary = fit(items, splits, themes, embeddings_np, cfg, seed + offset, val_pairs)
        assert isinstance(model.encoder, SiameseEncoder)
        members.append(model.encoder)
        summaries.append(summary)
    ensemble = SiameseNetwork(EnsembleEncoder(members))
    inputs_np = model_inputs(items, splits, embeddings_np, cfg)
    k = SETTINGS.evaluation.k
    val_map = evaluate_both(siamese_vectors(ensemble, inputs_np), items, splits, themes, "val",
                            max_queries=SETTINGS.evaluation.max_queries)["mean"][f"map@{k}"]  # fmt: skip
    summary = {
        "seed": seed,
        "config": asdict(cfg),
        "member_seeds": [s["seed"] for s in summaries],
        "member_val_map": [s["best_val_map"] for s in summaries],
        "best_val_map": val_map,
        "sbert_val_map": summaries[0]["sbert_val_map"],
        "best_val_loss": pair_loss(ensemble, inputs_np, val_pairs, cfg.margin),
        "minutes": sum(s["minutes"] for s in summaries),
        "members": summaries,
    }
    log.info("Ensemble of %d: val MAP@%d=%.4f (members %s)", cfg.ensemble_size, k, val_map,
             ", ".join(f"{m:.4f}" for m in summary["member_val_map"]))  # fmt: skip
    return ensemble, summary


def parse_overrides(pairs: list[str], cfg: SiameseConfig) -> SiameseConfig:
    """Return `cfg` with FIELD=VALUE overrides applied, cast to the type of the current value."""
    names = {f.name for f in fields(cfg)}
    changes: dict[str, Any] = {}
    for pair in pairs:
        name, _, raw = pair.partition("=")
        assert name in names, f"unknown SiameseConfig field {name!r}"
        current = getattr(cfg, name)
        changes[name] = raw.lower() in ("1", "true", "yes") if isinstance(current, bool) else type(current)(raw)
    return replace(cfg, **changes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--no-hard-negatives", action="store_true", help="Ablation: random negatives only.")
    parser.add_argument("--tag", default="", help="Save as an ablation checkpoint with this tag.")
    parser.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE",
                        help="Override one SiameseConfig field (repeatable).")  # fmt: skip
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    paths, k = SETTINGS.paths, SETTINGS.evaluation.k
    cfg = replace(SETTINGS.siamese, hard_negative_fraction=0.0) if args.no_hard_negatives else SETTINGS.siamese
    cfg = parse_overrides(args.set, cfg)
    items = pd.read_parquet(paths.items)
    embeddings_np = load_embeddings()
    assert embeddings_np.shape == (len(items), SETTINGS.embedding.dim), "embeddings do not match items"
    splits = assign_splits(items)
    themes = theme_matrix(items["themes"])

    model, summary = fit_ensemble(items, splits, themes, embeddings_np, cfg, seed=args.seed)
    paths.artefact_dir.mkdir(parents=True, exist_ok=True)
    members = len(model.encoder.members) if isinstance(model.encoder, EnsembleEncoder) else 1
    torch.save({"state_dict": model.state_dict(), "config": asdict(cfg), "members": members,
                "model_version": SETTINGS.model_version, "seed": args.seed, "val_map": summary["best_val_map"],
                "sbert_val_map": summary["sbert_val_map"]}, paths.checkpoint(args.tag))  # fmt: skip
    history_name = f"training_history_{args.tag}.json" if args.tag else "training_history.json"
    (paths.artefact_dir / history_name).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info("Best val MAP@%d=%.4f at epoch %s (SBERT %.4f); val loss=%.4f", k, summary["best_val_map"],
             summary.get("best_epoch", "per member"), summary["sbert_val_map"], summary["best_val_loss"])  # fmt: skip


if __name__ == "__main__":
    main()
