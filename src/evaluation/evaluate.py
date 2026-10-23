"""Evaluate cross-domain retrieval against theme-based ground truth.

Run: python -m src.evaluation.evaluate
Output: artefacts/metrics.json and a Markdown table on stdout.

Protocol: queries are labelled test items of one domain; the candidate pool is the labelled
test items of the other domain. A candidate is relevant when the theme Jaccard reaches the
configured threshold. Items without themes are excluded, because their relevance is unknown.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

from src.config import SEED, SETTINGS, V2_FIELD_DEFAULTS, SiameseConfig, get_device, set_seed
from src.embeddings.features import model_inputs
from src.embeddings.sbert import load_embeddings
from src.evaluation.leakage import masked_embeddings, masked_inputs, masked_rows
from src.evaluation.metrics import map_at_k, precision_at_k, recall_at_k
from src.evaluation.retrieval import top_k
from src.ingest.themes import THEMES
from src.ml.data import DomainView, assign_splits, domain_view, jaccard_block, mine_bidirectional, theme_matrix
from src.ml.losses import contrastive_loss
from src.ml.siamese import EnsembleEncoder, SiameseEncoder, SiameseNetwork, build_model, encode

log = logging.getLogger(__name__)

Result = dict[str, dict[str, float]]
PairBonus = Callable[[np.ndarray, np.ndarray], np.ndarray]
DIRECTIONS = (("anime", "game"), ("game", "anime"))


def _labelled(view: DomainView) -> DomainView:
    keep = view.labelled
    return DomainView(rows=view.rows[keep], themes=view.themes[keep])


def retrieval_metrics(
    vectors: np.ndarray,
    queries: DomainView,
    candidates: DomainView,
    k: int,
    max_queries: int | None = None,
    popularity: np.ndarray | None = None,
    popularity_weight: float = 0.0,
    seed: int = SEED,
    bonus: PairBonus | None = None,
) -> dict[str, float]:
    """Return MAP@k, P@k, Recall@k and the relevance base rate for one direction.

    `bonus(query_rows, candidate_rows)` returns an extra score block, for example the
    metadata-assisted theme agreement. It must not read the themes of the query rows.
    """
    queries, candidates = _labelled(queries), _labelled(candidates)
    if max_queries and len(queries.rows) > max_queries:
        pick = np.sort(np.random.default_rng(seed).choice(len(queries.rows), max_queries, replace=False))
        queries = DomainView(rows=queries.rows[pick], themes=queries.themes[pick])
    adjust = None
    prior = None
    if popularity is not None and popularity_weight:
        prior = popularity_weight * popularity[candidates.rows].astype(np.float32)
    if prior is not None or bonus is not None:
        q_rows, c_rows = queries.rows, candidates.rows

        def adjust(scores: np.ndarray, block: slice) -> np.ndarray:
            if prior is not None:
                scores = scores + prior
            if bonus is not None:
                scores = scores + bonus(q_rows[block], c_rows)
            return scores

    idx, _ = top_k(vectors[queries.rows], vectors[candidates.rows], k, adjust=adjust)
    jac = jaccard_block(queries.themes, candidates.themes) >= SETTINGS.relevance.jaccard_threshold
    relevance = np.take_along_axis(jac, idx, axis=1)
    n_relevant = jac.sum(axis=1)
    return {
        f"map@{k}": map_at_k(relevance, n_relevant, k),
        f"p@{k}": precision_at_k(relevance, k),
        f"recall@{k}": recall_at_k(relevance, n_relevant, k),
        "base_rate": float(jac.mean()),
        "queries": len(queries.rows),
        "candidates": len(candidates.rows),
    }


def evaluate_both(
    vectors: np.ndarray, items: pd.DataFrame, splits: np.ndarray, themes: np.ndarray, split: str, **kwargs: object
) -> dict[str, dict[str, float]]:
    """Run retrieval_metrics for anime->game and game->anime and add their mean."""
    k = SETTINGS.evaluation.k
    out = {}
    for src, dst in DIRECTIONS:
        q = domain_view(items, splits, themes, src, split)
        c = domain_view(items, splits, themes, dst, split)
        out[f"{src}->{dst}"] = retrieval_metrics(vectors, q, c, k, **kwargs)  # type: ignore[arg-type]
    out["mean"] = {key: float(np.mean([out[d][key] for d in out])) for key in (f"map@{k}", f"p@{k}", f"recall@{k}")}
    return out


def popularity_prior(items: pd.DataFrame) -> np.ndarray:
    """Return log-popularity scaled to [0, 1] within each domain."""
    log_pop = np.log1p(items["popularity"].clip(lower=0).to_numpy(dtype=np.float64))
    prior = np.zeros(len(items), dtype=np.float32)
    for domain in items["domain"].unique():
        mask = items["domain"].to_numpy() == domain
        top = log_pop[mask].max() or 1.0
        prior[mask] = log_pop[mask] / top
    return prior


def tfidf_svd_vectors(items: pd.DataFrame, splits: np.ndarray, dim: int = 128) -> np.ndarray:
    """TF-IDF + truncated SVD baseline (dissertation baseline). Fit on training items only."""
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize

    texts = items["model_text"].tolist()
    train = np.flatnonzero(splits == "train")
    vectoriser = TfidfVectorizer(
        max_features=30000, ngram_range=(1, 2), stop_words="english", min_df=2, sublinear_tf=True, dtype=np.float32
    )
    svd = TruncatedSVD(n_components=dim, random_state=SEED)
    svd.fit(vectoriser.fit_transform([texts[i] for i in train]))
    return normalize(svd.transform(vectoriser.transform(texts))).astype(np.float32)


def config_from_checkpoint(checkpoint: dict[str, Any]) -> SiameseConfig:
    """Rebuild the training config. Fill fields that siamese-v2 checkpoints lack with v2 values."""
    return SiameseConfig(**{**V2_FIELD_DEFAULTS, **checkpoint["config"]})


def load_model(path: Path | None = None) -> SiameseNetwork:
    """Load a checkpoint and rebuild the network with the dimensions it was trained with."""
    checkpoint = torch.load(path or SETTINGS.paths.model_weights, map_location=get_device(), weights_only=True)
    model = build_model(config_from_checkpoint(checkpoint), members=checkpoint.get("members", 1))
    model.load_state_dict(checkpoint["state_dict"])
    return model.to(get_device())


def siamese_vectors(model: SiameseNetwork, embeddings: np.ndarray) -> np.ndarray:
    device = get_device()
    return encode(model, torch.from_numpy(embeddings).to(device)).cpu().numpy()


@torch.inference_mode()
def pair_loss(
    model: SiameseNetwork, embeddings: np.ndarray, pairs: np.ndarray, margin: float = SETTINGS.siamese.margin
) -> float:
    """Return the mean contrastive loss over (i, j, label) pairs in eval mode."""
    model.eval()
    device = get_device()
    total, count = 0.0, 0
    for start in range(0, len(pairs), 8192):
        batch = pairs[start : start + 8192]
        x1 = torch.from_numpy(embeddings[batch[:, 0]]).to(device)
        x2 = torch.from_numpy(embeddings[batch[:, 1]]).to(device)
        y = torch.from_numpy(batch[:, 2]).to(device)
        cos, _, _ = model(x1, x2)
        total += float(contrastive_loss(cos, y, margin)) * len(batch)
        count += len(batch)
    return total / max(count, 1)


def random_vectors(n: int, dim: int, seed: int) -> np.ndarray:
    """Return n random unit vectors. Their ranking is independent of the content."""
    vectors = np.random.default_rng(seed).standard_normal((n, dim)).astype(np.float32)
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def summarise(runs: list[Result]) -> dict[str, object]:
    """Return the mean and sample standard deviation of mean MAP@K and Recall@K over runs."""
    k = SETTINGS.evaluation.k
    out: dict[str, object] = {"n": len(runs)}
    for key in (f"map@{k}", f"recall@{k}"):
        values = np.array([run["mean"][key] for run in runs])
        std = float(values.std(ddof=1)) if len(values) > 1 else 0.0
        out[key] = {"mean": float(values.mean()), "std": std, "values": values.tolist()}
    return out


def checkpoint_config(path: Path | None = None) -> tuple[SiameseConfig, dict[str, Any]]:
    """Return the training config and the raw metadata of a checkpoint."""
    checkpoint = torch.load(path or SETTINGS.paths.model_weights, map_location="cpu", weights_only=True)
    return config_from_checkpoint(checkpoint), checkpoint


def member_encoders(model: SiameseNetwork) -> list[SiameseEncoder]:
    """Return the encoders of an ensemble, or the single encoder."""
    encoder = model.encoder
    if isinstance(encoder, EnsembleEncoder):
        return [m for m in encoder.members if isinstance(m, SiameseEncoder)]
    return [encoder]


@torch.inference_mode()
def predicted_themes(model: SiameseNetwork, inputs: np.ndarray, batch_size: int = 4096) -> np.ndarray:
    """Return (n, len(THEMES)) theme probabilities, averaged over ensemble members, in eval mode."""
    model.eval()
    device = get_device()
    members = member_encoders(model)
    assert all(m.theme_head is not None for m in members), "the model has no theme head"
    out = np.zeros((len(inputs), len(THEMES)), dtype=np.float32)
    for start in range(0, len(inputs), batch_size):
        x = torch.from_numpy(inputs[start : start + batch_size]).to(device)
        probs = torch.stack([torch.sigmoid(m.theme_logits(m(x))) for m in members]).mean(dim=0)
        out[start : start + batch_size] = probs.cpu().numpy()
    return out


def theme_agreement_bonus(query_probs: np.ndarray, catalogue_themes: np.ndarray, weight: float) -> PairBonus:
    """Return a bonus: `weight` times the soft Jaccard of predicted query themes and catalogue candidate themes.

    Query themes are model predictions. Only candidate themes come from catalogue metadata.
    """

    def bonus(q_rows: np.ndarray, c_rows: np.ndarray) -> np.ndarray:
        p, t = query_probs[q_rows], catalogue_themes[c_rows]
        inter = p @ t.T
        union = p.sum(axis=1, keepdims=True) + t.sum(axis=1) - inter
        return np.asarray(weight * inter / np.maximum(union, 1e-6), dtype=np.float32)

    return bonus


def metadata_assisted(
    model: SiameseNetwork,
    vectors: np.ndarray,
    inputs: np.ndarray,
    items: pd.DataFrame,
    splits: np.ndarray,
    themes: np.ndarray,
) -> dict[str, object]:
    """Select the theme-agreement weight on validation, then report the test score once."""
    ev = SETTINGS.evaluation
    key = f"map@{ev.k}"
    probs = predicted_themes(model, inputs)
    val = {
        w: evaluate_both(vectors, items, splits, themes, "val", max_queries=ev.max_queries,
                         bonus=theme_agreement_bonus(probs, themes, w))["mean"][key]
        for w in ev.metadata_weights
    }  # fmt: skip
    best = max(val, key=lambda w: val[w])
    test = evaluate_both(vectors, items, splits, themes, "test", max_queries=ev.max_queries,
                         bonus=theme_agreement_bonus(probs, themes, best))  # fmt: skip
    return {
        "description": "Cosine plus weight * soft Jaccard(predicted query themes, catalogue themes of candidates). "
        "Uses candidate metadata at query time; not an embedding-only score.",
        "val_map_by_weight": {str(w): v for w, v in val.items()},
        "selected_weight": best,
        "test": test,
    }


def ablations(
    items: pd.DataFrame,
    splits: np.ndarray,
    themes: np.ndarray,
    embeddings: np.ndarray,
    results: dict[str, Result],
    model: SiameseNetwork,
    cfg: SiameseConfig,
) -> dict[str, object]:
    """Run the ablations: keyword leakage, random seeds, ensemble members, training seeds, earlier models."""
    paths, ev = SETTINGS.paths, SETTINGS.evaluation
    key = f"map@{ev.k}"
    inputs_cache: dict[tuple[str, int], np.ndarray] = {}

    def test(vectors: np.ndarray) -> Result:
        return evaluate_both(vectors, items, splits, themes, "test", max_queries=ev.max_queries)

    def inputs_for(tag_cfg: SiameseConfig) -> np.ndarray:
        key = (tag_cfg.input_features, tag_cfg.tfidf_dim)
        if key not in inputs_cache:
            inputs_cache[key] = model_inputs(items, splits, embeddings, tag_cfg)
        return inputs_cache[key]

    def checkpoint_result(path: Path) -> Result:
        tag_cfg, _ = checkpoint_config(path)
        return test(siamese_vectors(load_model(path), inputs_for(tag_cfg)))

    masked_sbert = masked_embeddings(items, splits, embeddings)
    masked = masked_inputs(items, splits, embeddings, cfg)
    leak = {"sbert_cosine": test(masked_sbert), "siamese": test(siamese_vectors(model, masked))}
    out: dict[str, object] = {
        "keyword_masked_test": {
            "description": "Test game texts with lexicon keywords removed, in every input block. "
            "Anime text is unchanged.",
            "masked_games": len(masked_rows(items, splits)),
            "input_features": cfg.input_features,
            **leak,
            "map_drop": {name: results[name]["mean"][key] - leak[name]["mean"][key] for name in leak},
        },
        "random_seeds": {
            "dim": model.encoder.proj_dim,
            **summarise([test(random_vectors(len(items), model.encoder.proj_dim, SEED + s))
                         for s in range(ev.random_seeds)]),
        },
    }  # fmt: skip
    members = member_encoders(model)
    if len(members) > 1:
        inputs = inputs_for(cfg)
        runs = [test(siamese_vectors(SiameseNetwork(m), inputs)) for m in members]
        out["ensemble_members"] = {"description": "Each ensemble member alone (single-model seed spread).",
                                   **summarise(runs)}  # fmt: skip
    seed_paths = [paths.checkpoint(f"seed{s}") for s in ev.extra_train_seeds]
    if all(p.exists() for p in seed_paths):
        runs = [results["siamese"]] + [checkpoint_result(p) for p in seed_paths]
        out["training_seeds"] = {"seeds": [SEED, *ev.extra_train_seeds], **summarise(runs)}
    previous = {tag: checkpoint_result(paths.checkpoint(tag)) for tag in ev.comparison_tags
                if paths.checkpoint(tag).exists()}  # fmt: skip
    if previous:
        out["previous_models"] = previous
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    set_seed()
    paths, ev = SETTINGS.paths, SETTINGS.evaluation
    items = pd.read_parquet(paths.items)
    embeddings = load_embeddings()
    splits = assign_splits(items)
    themes = theme_matrix(items["themes"])
    kwargs = {"max_queries": ev.max_queries}

    cfg, checkpoint = checkpoint_config()
    model = load_model()
    inputs = model_inputs(items, splits, embeddings, cfg)
    learned = siamese_vectors(model, inputs)
    prior = popularity_prior(items)
    dim = model.encoder.proj_dim

    def test(vectors: np.ndarray, **extra: object) -> Result:
        return evaluate_both(vectors, items, splits, themes, "test", **kwargs, **extra)

    results = {
        "random": test(random_vectors(len(items), dim, SEED)),
        "tfidf_svd": test(tfidf_svd_vectors(items, splits, SETTINGS.siamese.proj_dim)),
        "sbert_cosine": test(embeddings),
        "siamese": test(learned),
        "siamese_popularity": test(learned, popularity=prior, popularity_weight=ev.popularity_weight),
    }
    test_pairs = mine_bidirectional(items, splits, themes, embeddings, "test", seed=SEED + 200)
    report: dict[str, Any] = {
        "protocol": {
            "relevance": f"theme Jaccard >= {SETTINGS.relevance.jaccard_threshold}",
            "candidates": "labelled test items of the other domain",
            "k": ev.k,
            "max_queries_per_direction": ev.max_queries,
            "selection": "all model and weight choices on the validation split",
            "model_version": checkpoint.get("model_version", SETTINGS.model_version),
            "embedding_model": SETTINGS.embedding.model_name,
            "siamese_config": checkpoint["config"],
            "ensemble_members": checkpoint.get("members", 1),
            "seed": checkpoint.get("seed", SEED),
            "val_map": checkpoint.get("val_map"),
        },
        "test_contrastive_loss": pair_loss(model, inputs, test_pairs, cfg.margin),
        "test_pairs": len(test_pairs),
        "results": results,
    }
    if cfg.theme_weight > 0:
        report["metadata_assisted"] = metadata_assisted(model, learned, inputs, items, splits, themes)
    report["ablations"] = ablations(items, splits, themes, embeddings, results, model, cfg)
    paths.metrics.write_text(json.dumps(report, indent=2), encoding="utf-8")
    key = f"map@{ev.k}"
    print(f"| model | anime->game {key} | game->anime {key} | mean {key} | mean recall@{ev.k} |")
    print("|---|---|---|---|---|")
    for name, res in results.items():
        print(
            f"| {name} | {res['anime->game'][key]:.4f} | {res['game->anime'][key]:.4f} | "
            f"{res['mean'][key]:.4f} | {res['mean'][f'recall@{ev.k}']:.4f} |"
        )
    print(f"Test contrastive loss: {report['test_contrastive_loss']:.4f} on {report['test_pairs']} pairs")
    print(f"Relevance base rate (anime->game): {results['random']['anime->game']['base_rate']:.4f}")
    if "metadata_assisted" in report:
        meta = report["metadata_assisted"]
        print(f"Metadata-assisted (weight {meta['selected_weight']}): {meta['test']['mean'][key]:.4f}")
    print(json.dumps(report["ablations"], indent=1))


if __name__ == "__main__":
    main()
