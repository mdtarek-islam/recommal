"""Encode item text with a pre-trained SBERT model.

Run: python -m src.embeddings.sbert
Output: artefacts/sbert_embeddings.npy, float16, row order equal to items.parquet.
Embeddings are L2-normalised, so a dot product equals cosine similarity.
"""

from __future__ import annotations

import logging
import time

import numpy as np
import pandas as pd

from src.config import SETTINGS, get_device, set_seed

log = logging.getLogger(__name__)


def encode_texts(texts: list[str], model_name: str | None = None, batch_size: int | None = None) -> np.ndarray:
    """Return an (n, dim) float32 array of L2-normalised SBERT embeddings."""
    import torch
    from sentence_transformers import SentenceTransformer

    cfg = SETTINGS.embedding
    model = SentenceTransformer(model_name or cfg.model_name, device=str(get_device()))
    model.eval()
    with torch.inference_mode():
        embeddings = model.encode(
            texts,
            batch_size=batch_size or cfg.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=True,
        )
    assert embeddings.shape == (len(texts), cfg.dim), f"unexpected embedding shape {embeddings.shape}"
    return np.asarray(embeddings, dtype=np.float32)


def load_embeddings() -> np.ndarray:
    """Load the persisted embeddings as float32."""
    return np.load(SETTINGS.paths.embeddings).astype(np.float32)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    set_seed()
    paths = SETTINGS.paths
    items = pd.read_parquet(paths.items, columns=["model_text"])
    log.info("Encoding %d texts with %s", len(items), SETTINGS.embedding.model_name)
    start = time.perf_counter()
    embeddings = encode_texts(items["model_text"].tolist())
    paths.artefact_dir.mkdir(parents=True, exist_ok=True)
    np.save(paths.embeddings, embeddings.astype(np.float16))
    log.info("Saved %s to %s in %.1f min", embeddings.shape, paths.embeddings, (time.perf_counter() - start) / 60)


if __name__ == "__main__":
    main()
