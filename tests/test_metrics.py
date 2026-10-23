import numpy as np
import pytest

from src.evaluation.metrics import average_precision_at_k, map_at_k, precision_at_k, recall_at_k
from src.evaluation.retrieval import top_k


def test_average_precision_perfect_ranking() -> None:
    assert average_precision_at_k(np.array([1, 1, 0, 0]), n_relevant=2, k=4) == 1.0


def test_average_precision_hand_computed() -> None:
    # Hits at ranks 1 and 3; R = 2: (1/1 + 2/3) / 2.
    assert average_precision_at_k(np.array([1, 0, 1, 0]), n_relevant=2, k=4) == pytest.approx((1 + 2 / 3) / 2)


def test_average_precision_normalises_by_min_r_k() -> None:
    # R = 10 but k = 2: a perfect top-2 scores 1.0.
    assert average_precision_at_k(np.array([1, 1]), n_relevant=10, k=2) == 1.0


def test_average_precision_without_relevant_items() -> None:
    assert average_precision_at_k(np.array([0, 0]), n_relevant=0, k=2) == 0.0


def test_map_ignores_queries_without_relevant_items() -> None:
    relevance = np.array([[1, 0], [0, 0]])
    assert map_at_k(relevance, np.array([1, 0]), k=2) == 1.0


def test_precision_and_recall() -> None:
    relevance = np.array([[1, 0, 1], [0, 0, 1]])
    assert precision_at_k(relevance, 3) == pytest.approx(0.5)
    assert recall_at_k(relevance, np.array([2, 4]), 3) == pytest.approx((1.0 + 0.25) / 2)


def test_top_k_returns_sorted_neighbours() -> None:
    queries = np.array([[1.0, 0.0]], dtype=np.float32)
    candidates = np.array([[0.0, 1.0], [1.0, 0.0], [0.7, 0.7]], dtype=np.float32)
    idx, scores = top_k(queries, candidates, k=2)
    assert idx.tolist() == [[1, 2]]
    assert scores[0, 0] >= scores[0, 1]


def test_top_k_adjust_can_mask_candidates() -> None:
    queries = np.array([[1.0, 0.0]], dtype=np.float32)
    candidates = np.array([[1.0, 0.0], [0.5, 0.5]], dtype=np.float32)

    def mask_first(scores: np.ndarray, _: slice) -> np.ndarray:
        scores[:, 0] = -np.inf
        return scores

    idx, _ = top_k(queries, candidates, k=1, adjust=mask_first)
    assert idx.tolist() == [[1]]
