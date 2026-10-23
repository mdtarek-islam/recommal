"""Splits, theme matrices and training pair mining."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.config import SEED, SETTINGS, SiameseConfig
from src.evaluation.retrieval import top_k
from src.ingest.themes import THEMES

SPLITS = ("train", "val", "test")


def assign_splits(items: pd.DataFrame, seed: int = SEED) -> np.ndarray:
    """Return a split label for each row. Split each domain separately (70/15/15)."""
    cfg = SETTINGS.split
    labels = np.empty(len(items), dtype=object)
    rng = np.random.default_rng(seed)
    for domain in sorted(items["domain"].unique()):
        idx = np.flatnonzero(items["domain"].to_numpy() == domain)
        idx = idx[rng.permutation(len(idx))]
        n_train = round(cfg.train * len(idx))
        n_val = round(cfg.val * len(idx))
        labels[idx[:n_train]] = "train"
        labels[idx[n_train : n_train + n_val]] = "val"
        labels[idx[n_train + n_val :]] = "test"
    return labels


def theme_matrix(themes: pd.Series) -> np.ndarray:
    """Return an (n, len(THEMES)) float32 multi-hot matrix."""
    index = {t: i for i, t in enumerate(THEMES)}
    matrix = np.zeros((len(themes), len(THEMES)), dtype=np.float32)
    for row, values in enumerate(themes):
        for theme in values:
            matrix[row, index[theme]] = 1.0
    return matrix


def jaccard_block(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Return the pairwise Jaccard similarity of two multi-hot matrices."""
    inter = a @ b.T
    union = a.sum(axis=1, keepdims=True) + b.sum(axis=1) - inter
    return np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)


@dataclass(frozen=True)
class DomainView:
    """Rows of one domain within one split."""

    rows: np.ndarray  # Global row indices into items / embeddings.
    themes: np.ndarray  # Multi-hot theme matrix for `rows`.

    @property
    def labelled(self) -> np.ndarray:
        return self.themes.sum(axis=1) > 0


def domain_view(items: pd.DataFrame, splits: np.ndarray, themes: np.ndarray, domain: str, split: str) -> DomainView:
    mask = (items["domain"].to_numpy() == domain) & (splits == split)
    rows = np.flatnonzero(mask)
    return DomainView(rows=rows, themes=themes[rows])


def iter_relevance(queries: DomainView, candidates: DomainView, chunk: int = 256) -> Iterator[tuple[slice, np.ndarray]]:
    """Yield (query slice, Jaccard block) over labelled queries against all candidates."""
    for start in range(0, len(queries.rows), chunk):
        block = slice(start, min(len(queries.rows), start + chunk))
        yield block, jaccard_block(queries.themes[block], candidates.themes)


def mine_pairs(
    queries: DomainView,
    candidates: DomainView,
    embeddings: np.ndarray,
    seed: int,
    cfg: SiameseConfig = SETTINGS.siamese,
) -> np.ndarray:
    """Return an (n, 3) int64 array of (query row, candidate row, label) pairs.

    Positives: candidates with Jaccard >= threshold.
    Negatives: labelled candidates with Jaccard == 0. A `cfg.hard_negative_fraction` share are
    hard: the nearest such candidates in raw SBERT space. The rest are random.
    Unlabelled candidates are never negatives.
    """
    threshold = SETTINGS.relevance.jaccard_threshold
    rng = np.random.default_rng(seed)
    cand_labelled = candidates.labelled
    n_hard = round(cfg.neg_per_item * cfg.hard_negative_fraction)
    q_emb = embeddings[queries.rows]
    c_emb = embeddings[candidates.rows]
    pairs: list[tuple[int, int, int]] = []
    for block, jac in iter_relevance(queries, candidates):
        nearest = top_k(q_emb[block], c_emb, cfg.hard_negative_pool)[0] if n_hard else None
        for offset, row_jac in enumerate(jac):
            q = block.start + offset
            if not queries.labelled[q]:
                continue
            pos = np.flatnonzero(row_jac >= threshold)
            neg_mask = (row_jac == 0) & cand_labelled
            if len(pos) == 0 or not neg_mask.any():
                continue
            for c in rng.choice(pos, size=min(cfg.pos_per_item, len(pos)), replace=False):
                pairs.append((queries.rows[q], candidates.rows[c], 1))
            hard = [] if nearest is None else [int(c) for c in nearest[offset] if neg_mask[c]][:n_hard]
            neg_mask[hard] = False
            pool = np.flatnonzero(neg_mask)
            n_rand = min(cfg.neg_per_item - len(hard), len(pool))
            for c in hard + [int(c) for c in rng.choice(pool, size=n_rand, replace=False)]:
                pairs.append((queries.rows[q], candidates.rows[c], 0))
    return np.asarray(pairs, dtype=np.int64).reshape(-1, 3)


def mine_bidirectional(
    items: pd.DataFrame,
    splits: np.ndarray,
    themes: np.ndarray,
    embeddings: np.ndarray,
    split: str,
    seed: int,
    cfg: SiameseConfig = SETTINGS.siamese,
) -> np.ndarray:
    """Mine anime->game and game->anime pairs within one split and shuffle them."""
    anime = domain_view(items, splits, themes, "anime", split)
    games = domain_view(items, splits, themes, "game", split)
    pairs = np.concatenate([
        mine_pairs(anime, games, embeddings, seed, cfg),
        mine_pairs(games, anime, embeddings, seed + 1, cfg),
    ])  # fmt: skip
    return pairs[np.random.default_rng(seed + 2).permutation(len(pairs))]
