"""Chunked exact nearest-neighbour search over L2-normalised embeddings."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

ScoreAdjust = Callable[[np.ndarray, slice], np.ndarray]


def top_k(
    queries: np.ndarray,
    candidates: np.ndarray,
    k: int,
    chunk: int = 512,
    adjust: ScoreAdjust | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (indices, scores) of the k highest dot products for each query, best first.

    `adjust(scores, query_slice)` may modify a (chunk, n_candidates) score block in place,
    for example to mask candidates or to add a popularity prior.
    """
    assert queries.ndim == 2 and candidates.ndim == 2, "expected 2-D embedding matrices"
    assert queries.shape[1] == candidates.shape[1], "query and candidate dimensions differ"
    n, m = len(queries), len(candidates)
    k = min(k, m)
    indices = np.empty((n, k), dtype=np.int64)
    scores = np.empty((n, k), dtype=np.float32)
    cand_t = np.ascontiguousarray(candidates.T, dtype=np.float32)
    for start in range(0, n, chunk):
        block = slice(start, min(n, start + chunk))
        sims = queries[block].astype(np.float32) @ cand_t
        if adjust is not None:
            sims = adjust(sims, block)
        part = np.argpartition(-sims, k - 1, axis=1)[:, :k]
        part_scores = np.take_along_axis(sims, part, axis=1)
        order = np.argsort(-part_scores, axis=1, kind="stable")
        indices[block] = np.take_along_axis(part, order, axis=1)
        scores[block] = np.take_along_axis(part_scores, order, axis=1)
    return indices, scores
