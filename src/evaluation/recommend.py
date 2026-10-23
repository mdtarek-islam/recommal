"""Generate top-N cross-domain recommendations for every item.

Run: python -m src.evaluation.recommend
Output: artefacts/recommendations.parquet with one row per (variant, source item, rank).

Variants (A/B experiment `rec_layout_v1`):
- control:   pure latent cosine similarity.
- explained: latent similarity plus a small log-popularity prior. The UI also explains
             each card with the shared themes.
Non-adult items never receive adult recommendations.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from src.config import AB_VARIANTS, SETTINGS, set_seed
from src.embeddings.features import model_inputs
from src.embeddings.sbert import load_embeddings
from src.evaluation.evaluate import checkpoint_config, load_model, popularity_prior, siamese_vectors
from src.evaluation.retrieval import top_k
from src.ingest.adult import refine_adult
from src.ml.data import assign_splits

log = logging.getLogger(__name__)


def recommend(vectors: np.ndarray, items: pd.DataFrame, prior: np.ndarray, variant: str, top_n: int) -> pd.DataFrame:
    """Return recommendations for all items of both domains for one variant."""
    weight = SETTINGS.evaluation.popularity_weight if variant == "explained" else 0.0
    adult = items["is_adult"].to_numpy(dtype=bool)
    frames = []
    for src, dst in (("anime", "game"), ("game", "anime")):
        q_rows = np.flatnonzero(items["domain"].to_numpy() == src)
        c_rows = np.flatnonzero(items["domain"].to_numpy() == dst)
        c_prior = weight * prior[c_rows]
        c_adult = adult[c_rows]

        def adjust(
            scores: np.ndarray,
            block: slice,
            q_rows: np.ndarray = q_rows,
            c_prior: np.ndarray = c_prior,
            c_adult: np.ndarray = c_adult,
        ) -> np.ndarray:
            scores += c_prior
            safe = ~adult[q_rows[block]]
            scores[np.ix_(safe, c_adult)] = -np.inf
            return scores

        idx, _ = top_k(vectors[q_rows], vectors[c_rows], top_n, adjust=adjust)
        target_rows = c_rows[idx]
        cosine = np.einsum("nd,nkd->nk", vectors[q_rows], vectors[target_rows])
        n = len(q_rows)
        frames.append(pd.DataFrame({
            "variant": variant,
            "source_domain": src,
            "source_id": np.repeat(items["item_id"].to_numpy()[q_rows], top_n),
            "rank": np.tile(np.arange(1, top_n + 1, dtype=np.int16), n),
            "target_domain": dst,
            "target_id": items["item_id"].to_numpy()[target_rows].ravel(),
            "score": cosine.ravel().astype(np.float32),
        }))  # fmt: skip
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    set_seed()
    paths = SETTINGS.paths
    items = pd.read_parquet(paths.items)
    before = int(items["is_adult"].sum())
    items["is_adult"] = refine_adult(items)  # Text signals catch adult games that the source flag misses.
    log.info("Adult items: %d from the source flag, %d after text refinement", before, int(items["is_adult"].sum()))
    cfg, checkpoint = checkpoint_config()
    inputs = model_inputs(items, assign_splits(items), load_embeddings(), cfg)
    vectors = siamese_vectors(load_model(), inputs)
    prior = popularity_prior(items)
    recs = pd.concat(
        [recommend(vectors, items, prior, v, SETTINGS.evaluation.top_n) for v in AB_VARIANTS], ignore_index=True
    )
    recs["model_version"] = checkpoint.get("model_version", SETTINGS.model_version)
    recs.to_parquet(paths.recommendations, index=False)
    log.info("Wrote %d recommendation rows to %s", len(recs), paths.recommendations)


if __name__ == "__main__":
    main()
