"""Ranking metrics for cross-domain retrieval."""

from __future__ import annotations

import numpy as np


def average_precision_at_k(relevance: np.ndarray, n_relevant: int, k: int) -> float:
    """Return AP@k for one ranked list.

    AP@k = (1 / min(R, k)) * sum_{i<=k} P@i * rel_i, where R is the number of relevant items
    in the whole candidate pool. Return 0.0 when R is 0.
    """
    if n_relevant <= 0:
        return 0.0
    rel = np.asarray(relevance[:k], dtype=bool)
    if not rel.any():
        return 0.0
    hits = np.cumsum(rel)
    precision_at_i = hits / np.arange(1, len(rel) + 1)
    return float((precision_at_i * rel).sum() / min(n_relevant, k))


def map_at_k(relevance: np.ndarray, n_relevant: np.ndarray, k: int) -> float:
    """Return the mean AP@k over queries that have at least one relevant candidate."""
    mask = np.asarray(n_relevant) > 0
    if not mask.any():
        return 0.0
    scores = [average_precision_at_k(r, int(n), k) for r, n in zip(relevance[mask], n_relevant[mask], strict=True)]
    return float(np.mean(scores))


def precision_at_k(relevance: np.ndarray, k: int) -> float:
    return float(np.asarray(relevance)[:, :k].mean())


def recall_at_k(relevance: np.ndarray, n_relevant: np.ndarray, k: int) -> float:
    mask = np.asarray(n_relevant) > 0
    if not mask.any():
        return 0.0
    hits = np.asarray(relevance)[mask, :k].sum(axis=1)
    return float(np.mean(hits / np.asarray(n_relevant)[mask]))
