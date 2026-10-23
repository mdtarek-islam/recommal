"""Losses for the Siamese encoder.

- `contrastive_loss`: Hadsell, Chopra and LeCun (2006) on cosine distance, over pairs.
- `inbatch_contrastive_loss`: the same formula over all anime-game pairs of a batch, class-balanced.
- `relevance_infonce`: cross-domain InfoNCE with relevance-weighted (optionally graded) targets.
- `theme_bce`: auxiliary multi-label theme classification.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F


def contrastive_loss(cosine: torch.Tensor, label: torch.Tensor, margin: float) -> torch.Tensor:
    """Return the mean contrastive loss.

    D = 1 - cos(z1, z2), in [0, 2].
    L = y * D^2 + (1 - y) * max(0, m - D)^2, with y = 1 for a similar pair.
    """
    assert cosine.shape == label.shape, f"shape mismatch: {tuple(cosine.shape)} vs {tuple(label.shape)}"
    distance = 1.0 - cosine
    label = label.to(cosine.dtype)
    positive = label * distance.pow(2)
    negative = (1.0 - label) * torch.clamp(margin - distance, min=0.0).pow(2)
    return (positive + negative).mean()


def jaccard_torch(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    """Return the pairwise Jaccard similarity of two multi-hot matrices."""
    assert a.ndim == 2 and b.ndim == 2 and a.shape[1] == b.shape[1], f"bad shapes {a.shape}, {b.shape}"
    inter = a @ b.T
    union = a.sum(dim=1, keepdim=True) + b.sum(dim=1) - inter
    return torch.where(union > 0, inter / union.clamp(min=1e-12), torch.zeros_like(inter))


def inbatch_contrastive_loss(
    cosine: torch.Tensor, jaccard: torch.Tensor, threshold: float, margin: float
) -> torch.Tensor:
    """Return the class-balanced contrastive loss over a (Ba, Bg) cosine matrix.

    Positives: Jaccard >= threshold. Negatives: Jaccard == 0. Other pairs are ignored,
    as in pair mining. The result is the mean of the positive mean and the negative mean,
    which matches the 50/50 positive share of mined pairs.
    """
    assert cosine.shape == jaccard.shape, f"shape mismatch: {tuple(cosine.shape)} vs {tuple(jaccard.shape)}"
    distance = 1.0 - cosine
    pos, neg = jaccard >= threshold, jaccard == 0
    terms = []
    if pos.any():
        terms.append(distance[pos].pow(2).mean())
    if neg.any():
        terms.append(torch.clamp(margin - distance[neg], min=0.0).pow(2).mean())
    return torch.stack(terms).mean() if terms else cosine.sum() * 0.0


def relevance_targets(jaccard: torch.Tensor, threshold: float, gamma: float) -> torch.Tensor:
    """Return unnormalised target weights: 1[J >= threshold] when gamma is 0, else J ** gamma."""
    if gamma <= 0:
        return (jaccard >= threshold).to(jaccard.dtype)
    return jaccard.clamp(min=0.0).pow(gamma)


def _soft_cross_entropy(logits: torch.Tensor, weights: torch.Tensor) -> torch.Tensor:
    """Return the mean soft-target cross-entropy over rows that have a positive target."""
    keep = weights.sum(dim=1) > 0
    if not keep.any():
        return logits.sum() * 0.0
    targets = weights[keep] / weights[keep].sum(dim=1, keepdim=True)
    return -(targets * F.log_softmax(logits[keep], dim=1)).sum(dim=1).mean()


def relevance_infonce(
    cosine: torch.Tensor, jaccard: torch.Tensor, threshold: float, temperature: float, gamma: float = 0.0
) -> torch.Tensor:
    """Return the symmetric cross-domain InfoNCE loss with relevance-weighted targets.

    Each anime row is a softmax over the batch games, and each game column a softmax over
    the batch anime. The target distribution is proportional to `relevance_targets`.
    """
    assert cosine.shape == jaccard.shape, f"shape mismatch: {tuple(cosine.shape)} vs {tuple(jaccard.shape)}"
    assert temperature > 0, "temperature must be positive"
    logits = cosine / temperature
    weights = relevance_targets(jaccard, threshold, gamma)
    return 0.5 * (_soft_cross_entropy(logits, weights) + _soft_cross_entropy(logits.T, weights.T))


def theme_bce(logits: torch.Tensor, themes: torch.Tensor) -> torch.Tensor:
    """Return the mean multi-label binary cross-entropy of theme logits."""
    assert logits.shape == themes.shape, f"shape mismatch: {tuple(logits.shape)} vs {tuple(themes.shape)}"
    return F.binary_cross_entropy_with_logits(logits, themes.to(logits.dtype))
