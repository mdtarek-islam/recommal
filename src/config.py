"""Single source of truth for paths, hyperparameters and runtime settings.

Read every tunable value from this module. Do not write values inline elsewhere.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED = 42
DOMAINS = ("anime", "game")


def _path_env(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default


@dataclass(frozen=True)
class Paths:
    """File system locations. Override each one with an environment variable."""

    raw_dir: Path = field(default_factory=lambda: _path_env("RECOMMAL_RAW_DIR", PROJECT_ROOT / "data" / "raw"))
    processed_dir: Path = field(
        default_factory=lambda: _path_env("RECOMMAL_PROCESSED_DIR", PROJECT_ROOT / "data" / "processed")
    )
    artefact_dir: Path = field(default_factory=lambda: _path_env("RECOMMAL_ARTEFACT_DIR", PROJECT_ROOT / "artefacts"))

    @property
    def anime_dump(self) -> Path:
        return self.raw_dir / "sql" / "animes_db.sql"

    @property
    def steam_dump(self) -> Path:
        return self.raw_dir / "sql" / "steam_games.sql"

    @property
    def items(self) -> Path:
        return self.processed_dir / "items.parquet"

    @property
    def embeddings(self) -> Path:
        return self.artefact_dir / "sbert_embeddings.npy"

    @property
    def model_weights(self) -> Path:
        return self.artefact_dir / "siamese.pt"

    @property
    def metrics(self) -> Path:
        return self.artefact_dir / "metrics.json"

    @property
    def recommendations(self) -> Path:
        return self.artefact_dir / "recommendations.parquet"

    @property
    def masked_test_embeddings(self) -> Path:
        """SBERT embeddings of test games with lexicon keywords masked (leakage ablation)."""
        return self.artefact_dir / "sbert_test_masked.npz"

    def tfidf_inputs(self, dim: int) -> Path:
        """TF-IDF + SVD input features with `dim` components, fitted on the training split only."""
        return self.artefact_dir / f"tfidf_svd_inputs_{dim}.npz"

    def tfidf_model(self, dim: int) -> Path:
        """Fitted TF-IDF vectoriser and SVD, kept to transform keyword-masked text."""
        return self.artefact_dir / f"tfidf_svd_model_{dim}.joblib"

    def checkpoint(self, tag: str = "") -> Path:
        """Return the main checkpoint path, or an ablation checkpoint path for `tag`."""
        return self.artefact_dir / f"siamese_{tag}.pt" if tag else self.model_weights


@dataclass(frozen=True)
class TextConfig:
    """Text cleaning limits."""

    max_model_chars: int = 2000  # Text sent to SBERT. MiniLM truncates at 256 word pieces.
    max_stored_chars: int = 800  # Synopsis stored in Supabase. Keeps the free tier under 500 MB.


@dataclass(frozen=True)
class EmbeddingConfig:
    """SBERT settings. The dissertation used all-MiniLM-L6-v2 (384 dimensions)."""

    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    dim: int = 384
    batch_size: int = 128


@dataclass(frozen=True)
class FeatureConfig:
    """Extra encoder input: TF-IDF + truncated SVD of `model_text`, fitted on training items only."""

    tfidf_max_features: int = 30000
    tfidf_min_df: int = 2


@dataclass(frozen=True)
class RelevanceConfig:
    """Ground truth: two items are relevant when their theme Jaccard reaches the threshold.

    Fixed on 2026-10-22 from base rates only, before any model result.
    Sample: 2,000 labelled anime against all 115,407 labelled games.
    Base rate at Jaccard >= 0.5: 4.2% (anime->game), 3.9% (game->anime).
    Expected random MAP@10: 0.017 and 0.014. The rate is far below 15%, so the metric
    discriminates. Action and adventure dominate games (51% and 49%), but the Jaccard
    threshold already dilutes them. The protocol therefore stays unchanged.
    """

    jaccard_threshold: float = 0.5
    min_themes: int = 1


@dataclass(frozen=True)
class SplitConfig:
    train: float = 0.70
    val: float = 0.15
    test: float = 0.15


@dataclass(frozen=True)
class SiameseConfig:
    """Siamese network and training hyperparameters.

    The defaults are the siamese-v3 configuration, selected on mean validation MAP@10 over
    three seeds (artefacts/tuning_log.md). `V2_FIELD_DEFAULTS` rebuilds older checkpoints.
    pos_per_item, neg_per_item and the hard-negative settings define the fixed pair-mining
    protocol for the reported validation and test contrastive loss.
    """

    hidden_dim: int = 512
    proj_dim: int = 128
    dropout: float = 0.7
    margin: float = 0.5
    lr: float = 1e-3
    weight_decay: float = 1e-2
    batch_size: int = 512
    max_epochs: int = 50
    patience: int = 5
    pos_per_item: int = 4
    neg_per_item: int = 4
    hard_negative_fraction: float = 0.5
    hard_negative_pool: int = 50
    resample_pairs: bool = False  # Mine fresh training pairs each epoch.
    objective: str = "inbatch"  # "pairs": mined pairs (v2); "inbatch": all anime-game pairs of a sampled batch.
    input_features: str = "sbert+tfidf"  # "sbert" or "sbert+tfidf".
    tfidf_dim: int = 256  # SVD components of the TF-IDF input block.
    contrastive_weight: float = 1.0  # Balanced contrastive loss over in-batch pairs (J >= threshold vs J == 0).
    infonce_weight: float = 1.0  # Cross-domain InfoNCE with relevance-weighted targets.
    theme_weight: float = 1.0  # Auxiliary multi-label theme head (BCE).
    temperature: float = 0.1  # InfoNCE temperature.
    graded_gamma: float = 0.0  # 0: binary InfoNCE targets; > 0: target weight Jaccard ** gamma.
    steps_per_epoch: int = 160  # In-batch steps per epoch; batch_size items of each domain per step.
    ensemble_size: int = 5  # Encoders trained with consecutive seeds; their cosines are averaged.


# Values of fields that siamese-v2 checkpoints do not store. They rebuild those models unchanged.
V2_FIELD_DEFAULTS: dict[str, object] = {
    "objective": "pairs",
    "input_features": "sbert",
    "tfidf_dim": 256,
    "contrastive_weight": 1.0,
    "infonce_weight": 0.0,
    "theme_weight": 0.0,
    "temperature": 0.05,
    "graded_gamma": 0.0,
    "steps_per_epoch": 160,
    "ensemble_size": 1,
}


@dataclass(frozen=True)
class EvalConfig:
    k: int = 10
    top_n: int = 5  # Recommendations stored for each item.
    popularity_weight: float = 0.05  # Variant B re-ranking weight.
    max_queries: int = 2000
    random_seeds: int = 5  # Seeds averaged for the random baseline ablation.
    # Base seeds of extra ensembles for the seed-variance ablation (checkpoints seed<N>). With 5 members,
    # 42, 47 and 52 give disjoint member seeds 42-46, 47-51 and 52-56.
    extra_train_seeds: tuple[int, ...] = (47, 52)
    # Earlier checkpoints evaluated on the same test protocol for comparison (siamese_<tag>.pt).
    comparison_tags: tuple[str, ...] = ("v2", "v2_no_hard", "v2_seed43", "v2_seed44")
    # Weights of predicted-query-theme vs catalogue-candidate-theme agreement; selected on validation.
    metadata_weights: tuple[float, ...] = (0.0, 0.05, 0.1, 0.2, 0.5, 1.0)


@dataclass(frozen=True)
class DatabaseConfig:
    pool_min: int = 1
    pool_max: int = 5
    connect_timeout_s: int = 10


@dataclass(frozen=True)
class Settings:
    paths: Paths = field(default_factory=Paths)
    text: TextConfig = field(default_factory=TextConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    relevance: RelevanceConfig = field(default_factory=RelevanceConfig)
    split: SplitConfig = field(default_factory=SplitConfig)
    siamese: SiameseConfig = field(default_factory=SiameseConfig)
    features: FeatureConfig = field(default_factory=FeatureConfig)
    evaluation: EvalConfig = field(default_factory=EvalConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    model_version: str = "siamese-v3"


SETTINGS = Settings()

# A/B experiment definition. The variant names are stable; never rename them.
AB_EXPERIMENT = "rec_layout_v1"
AB_VARIANTS = ("control", "explained")

# Hosts that may serve cover images over https. A "*." entry matches any subdomain.
# The UI shows a placeholder for every other URL.
IMAGE_HOST_ALLOWLIST = ("cdn.myanimelist.net", "cdn.akamai.steamstatic.com", "*.steamstatic.com")


def set_seed(seed: int = SEED) -> None:
    """Set the Python, NumPy and PyTorch seeds."""
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch
    except ImportError:
        return
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


def get_device() -> torch.device:
    """Return the best available device. Move models and tensors with `.to(device)`."""
    import torch

    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")
