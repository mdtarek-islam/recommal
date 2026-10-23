"""Leakage ablation: remove lexicon keywords from game text before SBERT encoding.

Game lexicon themes come from keywords in the same text that SBERT encodes. A model can then
score well by matching the literal keywords. This module masks those keywords in test-split
game texts, so the evaluation measures retrieval without the label source in the input.
Anime themes come from MAL genre labels, not from the synopsis, so anime text stays unchanged.
"""

from __future__ import annotations

import logging
import re

import numpy as np
import pandas as pd

from src.config import SETTINGS, SiameseConfig
from src.ingest.themes import _KEYWORD_PATTERNS  # Read-only use of the lexicon owned by ingestion.

log = logging.getLogger(__name__)

_PATTERNS: tuple[re.Pattern[str], ...] = tuple(p for patterns in _KEYWORD_PATTERNS.values() for p in patterns)
_SPACES = re.compile(r"\s{2,}")


def mask_keywords(text: str) -> str:
    """Return `text` with every theme lexicon keyword removed."""
    for pattern in _PATTERNS:
        text = pattern.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def masked_rows(items: pd.DataFrame, splits: np.ndarray) -> np.ndarray:
    """Return the global row indices of test-split games, whose text the ablation masks."""
    return np.flatnonzero((items["domain"].to_numpy() == "game") & (splits == "test"))


def masked_embeddings(items: pd.DataFrame, splits: np.ndarray, embeddings: np.ndarray) -> np.ndarray:
    """Return a copy of `embeddings` with test games re-encoded from keyword-masked text.

    Cache the re-encoded rows in artefacts, because encoding takes minutes on CPU.
    """
    from src.embeddings.sbert import encode_texts

    rows = masked_rows(items, splits)
    path = SETTINGS.paths.masked_test_embeddings
    cached = np.load(path) if path.exists() else None
    if cached is not None and np.array_equal(cached["rows"], rows):
        vectors = cached["embeddings"].astype(np.float32)
    else:
        log.info("Re-encoding %d masked test game texts", len(rows))
        texts = [mask_keywords(t) for t in items["model_text"].to_numpy()[rows]]
        vectors = encode_texts(texts)
        np.savez(path, rows=rows, embeddings=vectors.astype(np.float16))
    out = embeddings.copy()
    out[rows] = vectors
    return out


def masked_inputs(items: pd.DataFrame, splits: np.ndarray, embeddings: np.ndarray, cfg: SiameseConfig) -> np.ndarray:
    """Return encoder inputs with test-game text keyword-masked in every feature block.

    SBERT rows come from `masked_embeddings`. With TF-IDF input, the fitted TF-IDF + SVD
    pipeline (training split only) transforms the same masked texts.
    """
    from src.embeddings.features import combine, model_inputs, tfidf_features, transform_tfidf

    sbert = masked_embeddings(items, splits, embeddings)
    if cfg.input_features == "sbert":
        return model_inputs(items, splits, sbert, cfg)
    rows = masked_rows(items, splits)
    tfidf = tfidf_features(items, splits, cfg.tfidf_dim).copy()
    tfidf[rows] = transform_tfidf([mask_keywords(t) for t in items["model_text"].to_numpy()[rows]], cfg.tfidf_dim)
    return combine(sbert, tfidf)
