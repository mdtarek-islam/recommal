"""Build the encoder input matrix from SBERT and optional TF-IDF + SVD features.

Run: python -m src.embeddings.features
Output: artefacts/tfidf_svd_inputs.npz and artefacts/tfidf_svd_model.joblib.

The TF-IDF vocabulary and the SVD basis are fitted on training items only.
Validation and test items are only transformed, so no statistic of them enters the fit.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np
import pandas as pd

from src.config import SEED, SETTINGS, SiameseConfig, set_seed

log = logging.getLogger(__name__)

INPUT_FEATURES = ("sbert", "sbert+tfidf")


def fit_tfidf_svd(texts: list[str], dim: int) -> Any:
    """Return a fitted TF-IDF -> SVD -> L2-normalise pipeline."""
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import Normalizer

    cfg = SETTINGS.features
    pipeline = make_pipeline(
        TfidfVectorizer(max_features=cfg.tfidf_max_features, ngram_range=(1, 2), stop_words="english",
                        min_df=cfg.tfidf_min_df, sublinear_tf=True, dtype=np.float32),
        TruncatedSVD(n_components=dim, random_state=SEED),
        Normalizer(),
    )  # fmt: skip
    pipeline.fit(texts)
    return pipeline


def tfidf_features(items: pd.DataFrame, splits: np.ndarray, dim: int) -> np.ndarray:
    """Return (n, dim) float32 TF-IDF + SVD features. Load the cache when the split matches."""
    import joblib

    paths = SETTINGS.paths
    train = np.flatnonzero(splits == "train")
    if paths.tfidf_inputs(dim).exists():
        cached = np.load(paths.tfidf_inputs(dim))
        if np.array_equal(cached["train_rows"], train) and cached["features"].shape[0] == len(items):
            return cached["features"].astype(np.float32)
    start = time.perf_counter()
    texts = items["model_text"].tolist()
    pipeline = fit_tfidf_svd([texts[i] for i in train], dim)
    features = pipeline.transform(texts).astype(np.float32)
    paths.artefact_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, paths.tfidf_model(dim))
    np.savez(paths.tfidf_inputs(dim), train_rows=train, features=features)
    log.info("Fitted TF-IDF + SVD on %d training texts in %.1f min", len(train), (time.perf_counter() - start) / 60)
    return features


def transform_tfidf(texts: list[str], dim: int) -> np.ndarray:
    """Transform new texts with the cached pipeline. Call `tfidf_features` first."""
    import joblib

    pipeline = joblib.load(SETTINGS.paths.tfidf_model(dim))
    return np.asarray(pipeline.transform(texts), dtype=np.float32)


def combine(sbert: np.ndarray, tfidf: np.ndarray | None) -> np.ndarray:
    """Concatenate unit-norm feature blocks and rescale the result to unit norm."""
    assert sbert.ndim == 2, f"expected a 2-D SBERT matrix, got {sbert.shape}"
    if tfidf is None:
        return sbert
    assert tfidf.shape[0] == sbert.shape[0], f"row mismatch: {sbert.shape} vs {tfidf.shape}"
    return (np.concatenate([sbert, tfidf], axis=1) / np.sqrt(2.0)).astype(np.float32)


def input_dim(cfg: SiameseConfig) -> int:
    """Return the encoder input width for the input features in `cfg`."""
    assert cfg.input_features in INPUT_FEATURES, f"unknown input features {cfg.input_features!r}"
    extra = cfg.tfidf_dim if cfg.input_features == "sbert+tfidf" else 0
    return SETTINGS.embedding.dim + extra


def model_inputs(items: pd.DataFrame, splits: np.ndarray, sbert: np.ndarray, cfg: SiameseConfig) -> np.ndarray:
    """Return the encoder input matrix for the input features in `cfg`."""
    assert cfg.input_features in INPUT_FEATURES, f"unknown input features {cfg.input_features!r}"
    tfidf = tfidf_features(items, splits, cfg.tfidf_dim) if cfg.input_features == "sbert+tfidf" else None
    out = combine(sbert, tfidf)
    assert out.shape == (len(items), input_dim(cfg)), f"unexpected input shape {out.shape}"
    return out


def main() -> None:
    from src.ml.data import assign_splits

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    set_seed()
    items = pd.read_parquet(SETTINGS.paths.items, columns=["domain", "model_text"])
    features = tfidf_features(items, assign_splits(items), SETTINGS.siamese.tfidf_dim)
    log.info("TF-IDF + SVD features: %s", features.shape)


if __name__ == "__main__":
    main()
