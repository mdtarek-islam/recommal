"""Two-tower Siamese network with a shared encoder.

Changes from the dissertation notebook, each motivated by an observed defect:
1. The output layer is linear. A final ReLU restricted embeddings to the positive orthant,
   so cosine scores collapsed towards 1.0 and stored similarities read "100%".
2. A linear residual path keeps the SBERT geometry; the MLP path learns the cross-domain shift.
3. LayerNorm replaces BatchNorm, so single-item inference behaves the same as training.

siamese-v3 adds an optional linear theme head on the unit embedding (multi-task training)
and `EnsembleEncoder`, which averages the cosine similarity of several encoders.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import nn

from src.config import SETTINGS, SiameseConfig
from src.embeddings.features import input_dim as feature_dim
from src.ingest.themes import THEMES


class SiameseEncoder(nn.Module):
    def __init__(
        self,
        input_dim: int = SETTINGS.embedding.dim,
        hidden_dim: int = SETTINGS.siamese.hidden_dim,
        proj_dim: int = SETTINGS.siamese.proj_dim,
        dropout: float = SETTINGS.siamese.dropout,
        n_themes: int = 0,
    ) -> None:
        super().__init__()
        self.input_dim = input_dim
        self.proj_dim = proj_dim
        self.theme_head = nn.Linear(proj_dim, n_themes) if n_themes else None
        self.residual = nn.Linear(input_dim, proj_dim, bias=False)
        self.mlp = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, proj_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        assert x.ndim == 2 and x.shape[1] == self.input_dim, f"expected (B, {self.input_dim}), got {tuple(x.shape)}"
        return F.normalize(self.residual(x) + self.mlp(x), dim=1)

    def theme_logits(self, z: torch.Tensor) -> torch.Tensor:
        """Return theme logits for unit embeddings `z`. Requires a theme head."""
        assert self.theme_head is not None, "this encoder has no theme head"
        assert z.ndim == 2 and z.shape[1] == self.proj_dim, f"expected (B, {self.proj_dim}), got {tuple(z.shape)}"
        return self.theme_head(z)


class EnsembleEncoder(nn.Module):
    """Concatenate unit embeddings of several encoders and divide by sqrt(n).

    The output has unit norm. Its dot product equals the mean cosine of the members.
    """

    def __init__(self, members: list[SiameseEncoder]) -> None:
        super().__init__()
        assert members, "an ensemble needs at least one member"
        self.members = nn.ModuleList(members)
        self.input_dim = members[0].input_dim
        self.proj_dim = sum(m.proj_dim for m in members)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        parts = [member(x) for member in self.members]
        return torch.cat(parts, dim=1) / float(len(parts)) ** 0.5


class SiameseNetwork(nn.Module):
    """Apply one shared encoder to both inputs and return their cosine similarity."""

    def __init__(self, encoder: SiameseEncoder | EnsembleEncoder | None = None) -> None:
        super().__init__()
        self.encoder = encoder or SiameseEncoder()

    def forward(self, x1: torch.Tensor, x2: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        assert x1.shape == x2.shape, f"pair shapes differ: {tuple(x1.shape)} vs {tuple(x2.shape)}"
        z1, z2 = self.encoder(x1), self.encoder(x2)
        return (z1 * z2).sum(dim=1), z1, z2


def build_encoder(cfg: SiameseConfig = SETTINGS.siamese) -> SiameseEncoder:
    """Return one encoder with the input features, dimensions and theme head in `cfg`."""
    return SiameseEncoder(input_dim=feature_dim(cfg), hidden_dim=cfg.hidden_dim,
                          proj_dim=cfg.proj_dim, dropout=cfg.dropout,
                          n_themes=len(THEMES) if cfg.theme_weight > 0 else 0)  # fmt: skip


def build_model(cfg: SiameseConfig = SETTINGS.siamese, members: int = 1) -> SiameseNetwork:
    """Return a Siamese network with the dimensions in `cfg`; with `members` > 1, an ensemble."""
    if members == 1:
        return SiameseNetwork(build_encoder(cfg))
    return SiameseNetwork(EnsembleEncoder([build_encoder(cfg) for _ in range(members)]))


@torch.inference_mode()
def encode(model: SiameseNetwork, embeddings: torch.Tensor, batch_size: int = 4096) -> torch.Tensor:
    """Project SBERT embeddings into the learned space in eval mode."""
    model.eval()
    parts = [model.encoder(embeddings[i : i + batch_size]) for i in range(0, len(embeddings), batch_size)]
    return torch.cat(parts) if parts else embeddings.new_zeros((0, model.encoder.proj_dim))
