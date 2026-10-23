from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
import torch

from src.config import SETTINGS, set_seed
from src.evaluation.leakage import mask_keywords
from src.ingest.themes import keyword_themes
from src.ml.data import DomainView, assign_splits, jaccard_block, mine_pairs, theme_matrix
from src.ml.losses import contrastive_loss
from src.ml.siamese import SiameseEncoder, SiameseNetwork, build_model, encode


def test_siamese_forward_shapes_and_unit_norm() -> None:
    set_seed()
    model = SiameseNetwork(SiameseEncoder(input_dim=16, hidden_dim=32, proj_dim=8)).eval()
    x1, x2 = torch.randn(4, 16), torch.randn(4, 16)
    cos, z1, z2 = model(x1, x2)
    assert cos.shape == (4,) and z1.shape == (4, 8) and z2.shape == (4, 8)
    assert torch.allclose(z1.norm(dim=1), torch.ones(4), atol=1e-5)
    assert torch.all(cos.abs() <= 1.0 + 1e-5)


def test_siamese_output_can_be_negative() -> None:
    """A linear output layer must allow negative cosine (the notebook's final ReLU did not)."""
    set_seed()
    encoder = SiameseEncoder(input_dim=16, hidden_dim=32, proj_dim=8).eval()
    z = encode(SiameseNetwork(encoder), torch.randn(64, 16))
    assert (z < 0).any()


def test_siamese_rejects_wrong_input_dimension() -> None:
    model = SiameseNetwork(SiameseEncoder(input_dim=16, hidden_dim=32, proj_dim=8))
    with pytest.raises(AssertionError):
        model(torch.randn(2, 15), torch.randn(2, 15))


def test_contrastive_loss_matches_formula() -> None:
    cos = torch.tensor([1.0, 0.2, 0.9, -0.5])
    label = torch.tensor([1, 1, 0, 0])
    margin = 0.5
    # D = [0, 0.8, 0.1, 1.5]; positives D^2; negatives max(0, m - D)^2.
    expected = (0.0 + 0.64 + 0.16 + 0.0) / 4
    assert contrastive_loss(cos, label, margin).item() == pytest.approx(expected)


def test_contrastive_loss_is_zero_for_ideal_pairs() -> None:
    cos = torch.tensor([1.0, -1.0])
    assert contrastive_loss(cos, torch.tensor([1, 0]), margin=0.5).item() == 0.0


def test_contrastive_loss_gradient_pulls_positive_pair_together() -> None:
    cos = torch.tensor([0.0], requires_grad=True)
    contrastive_loss(cos, torch.tensor([1]), margin=0.5).backward()
    assert cos.grad is not None and cos.grad.item() < 0  # Increasing cos lowers the loss.


def test_jaccard_block() -> None:
    a = np.array([[1, 1, 0], [0, 0, 0]], dtype=np.float32)
    b = np.array([[1, 0, 0], [1, 1, 1]], dtype=np.float32)
    np.testing.assert_allclose(jaccard_block(a, b), [[0.5, 2 / 3], [0.0, 0.0]])


def test_assign_splits_is_deterministic_and_per_domain() -> None:
    items = pd.DataFrame({"domain": ["anime"] * 100 + ["game"] * 200})
    first, second = assign_splits(items), assign_splits(items)
    assert (first == second).all()
    for domain, n in (("anime", 100), ("game", 200)):
        labels = first[items["domain"] == domain]
        assert (labels == "train").sum() == round(SETTINGS.split.train * n)


def test_mine_pairs_labels_follow_theme_overlap() -> None:
    themes = theme_matrix(pd.Series([["action", "sci_fi"], ["action", "sci_fi"], ["romance"], ["romance"], []]))
    embeddings = np.eye(5, 4, dtype=np.float32)
    queries = DomainView(rows=np.array([0]), themes=themes[[0]])
    candidates = DomainView(rows=np.array([1, 2, 3, 4]), themes=themes[[1, 2, 3, 4]])
    pairs = mine_pairs(queries, candidates, embeddings, seed=0)
    positives = set(pairs[pairs[:, 2] == 1, 1])
    negatives = set(pairs[pairs[:, 2] == 0, 1])
    assert positives == {1}
    assert negatives <= {2, 3}  # Row 4 has no themes, so it is never a negative.


def test_mine_pairs_without_hard_negatives_keeps_negative_count() -> None:
    themes = theme_matrix(pd.Series([["action"], ["action"], ["romance"], ["comedy"], ["drama"], ["horror"]]))
    embeddings = np.eye(6, 4, dtype=np.float32)
    queries = DomainView(rows=np.array([0]), themes=themes[[0]])
    candidates = DomainView(rows=np.arange(1, 6), themes=themes[1:])
    cfg = replace(SETTINGS.siamese, hard_negative_fraction=0.0, neg_per_item=3)
    pairs = mine_pairs(queries, candidates, embeddings, seed=0, cfg=cfg)
    assert (pairs[:, 2] == 0).sum() == 3
    assert set(pairs[pairs[:, 2] == 1, 1]) == {1}


def test_build_model_uses_config_dimensions() -> None:
    cfg = replace(SETTINGS.siamese, hidden_dim=32, proj_dim=16)
    model = build_model(cfg)
    out = encode(model, torch.randn(3, SETTINGS.embedding.dim))
    assert out.shape == (3, 16)


def test_mask_keywords_removes_every_lexicon_theme() -> None:
    text = "A cozy farming game with magic, dragons, zombies and haunted ruins. Build a farm."
    assert keyword_themes(text)
    masked = mask_keywords(text)
    assert keyword_themes(masked) == set()
    assert "game" in masked


def test_jaccard_torch_matches_numpy() -> None:
    from src.ml.losses import jaccard_torch

    a = np.array([[1, 1, 0], [0, 0, 0]], dtype=np.float32)
    b = np.array([[1, 0, 0], [1, 1, 1]], dtype=np.float32)
    got = jaccard_torch(torch.from_numpy(a), torch.from_numpy(b)).numpy()
    np.testing.assert_allclose(got, jaccard_block(a, b), atol=1e-6)


def test_inbatch_contrastive_loss_is_class_balanced() -> None:
    from src.ml.losses import inbatch_contrastive_loss

    cos = torch.tensor([[0.5, 0.9], [0.0, 0.2]])
    jac = torch.tensor([[1.0, 0.0], [0.3, 0.0]])  # One positive, two negatives, one ignored (0.3).
    # Positive D = 0.5 -> 0.25. Negatives D = 0.1, 0.8 with m = 0.5 -> 0.16, 0. Mean of means.
    expected = (0.25 + (0.16 + 0.0) / 2) / 2
    assert inbatch_contrastive_loss(cos, jac, threshold=0.5, margin=0.5).item() == pytest.approx(expected)


def test_relevance_infonce_hand_computed() -> None:
    from src.ml.losses import relevance_infonce

    cos = torch.tensor([[1.0, 0.0], [0.0, 0.0]])
    jac = torch.tensor([[1.0, 0.0], [0.0, 0.0]])  # Row 1 and column 2 have no positive and are skipped.
    t = 0.5
    row = -torch.log_softmax(torch.tensor([2.0, 0.0]), 0)[0]  # Anime 0 -> game 0.
    col = -torch.log_softmax(torch.tensor([2.0, 0.0]), 0)[0]  # Game 0 -> anime 0.
    expected = 0.5 * (row + col)
    assert relevance_infonce(cos, jac, threshold=0.5, temperature=t).item() == pytest.approx(expected.item())


def test_relevance_targets_binary_and_graded() -> None:
    from src.ml.losses import relevance_targets

    jac = torch.tensor([[0.0, 0.25, 0.5, 1.0]])
    assert relevance_targets(jac, 0.5, 0.0).tolist() == [[0.0, 0.0, 1.0, 1.0]]
    np.testing.assert_allclose(relevance_targets(jac, 0.5, 2.0).numpy(), [[0.0, 0.0625, 0.25, 1.0]])


def test_relevance_infonce_prefers_relevant_ranking() -> None:
    from src.ml.losses import relevance_infonce

    jac = torch.eye(3)
    good = relevance_infonce(torch.eye(3), jac, threshold=0.5, temperature=0.1)
    bad = relevance_infonce(1.0 - torch.eye(3), jac, threshold=0.5, temperature=0.1)
    assert good.item() < bad.item()


def test_theme_bce_hand_computed() -> None:
    from src.ml.losses import theme_bce

    logits = torch.zeros(2, 3)
    assert theme_bce(logits, torch.ones(2, 3)).item() == pytest.approx(float(np.log(2.0)))
    with pytest.raises(AssertionError):
        theme_bce(logits, torch.ones(2, 2))


def test_theme_head_shapes() -> None:
    from src.ingest.themes import THEMES

    set_seed()
    encoder = SiameseEncoder(input_dim=16, hidden_dim=32, proj_dim=8, n_themes=len(THEMES))
    z = encoder(torch.randn(5, 16))
    assert encoder.theme_logits(z).shape == (5, len(THEMES))
    assert SiameseEncoder(input_dim=16, hidden_dim=32, proj_dim=8).theme_head is None


def test_ensemble_encoder_averages_member_cosines() -> None:
    from src.ml.siamese import EnsembleEncoder

    set_seed()
    members = [SiameseEncoder(input_dim=16, hidden_dim=32, proj_dim=8).eval() for _ in range(3)]
    ensemble = EnsembleEncoder(members).eval()
    x1, x2 = torch.randn(4, 16), torch.randn(4, 16)
    with torch.inference_mode():
        got = (ensemble(x1) * ensemble(x2)).sum(dim=1)
        expected = torch.stack([(m(x1) * m(x2)).sum(dim=1) for m in members]).mean(dim=0)
        assert torch.allclose(ensemble(x1).norm(dim=1), torch.ones(4), atol=1e-5)
    assert ensemble.proj_dim == 24
    assert torch.allclose(got, expected, atol=1e-5)


def test_build_model_with_theme_head_and_members() -> None:
    from src.ml.siamese import EnsembleEncoder

    cfg = replace(SETTINGS.siamese, hidden_dim=32, proj_dim=16, theme_weight=1.0)
    model = build_model(cfg, members=2)
    assert isinstance(model.encoder, EnsembleEncoder)
    assert all(m.theme_head is not None for m in model.encoder.members)
    assert encode(model, torch.randn(3, SETTINGS.embedding.dim)).shape == (3, 32)


def test_multitask_loss_backpropagates_into_all_parts() -> None:
    from src.ingest.themes import THEMES
    from src.ml.train import multitask_loss

    set_seed()
    cfg = replace(SETTINGS.siamese, objective="inbatch", infonce_weight=1.0, theme_weight=1.0)
    encoder = SiameseEncoder(input_dim=16, hidden_dim=32, proj_dim=8, n_themes=len(THEMES))
    themes = torch.zeros(4, len(THEMES))
    themes[[0, 2], 0] = 1.0
    themes[[1, 3], 1] = 1.0
    loss, parts = multitask_loss(encoder, torch.randn(2, 16), torch.randn(2, 16), themes[:2], themes[2:], cfg)
    loss.backward()
    assert set(parts) == {"contrastive", "infonce", "theme"}
    assert encoder.theme_head is not None and encoder.theme_head.weight.grad is not None
    assert encoder.residual.weight.grad is not None


def test_parse_overrides_casts_types() -> None:
    from src.ml.train import parse_overrides

    cfg = parse_overrides(["theme_weight=0.5", "objective=inbatch", "resample_pairs=true", "batch_size=64"],
                          SETTINGS.siamese)  # fmt: skip
    assert (cfg.theme_weight, cfg.objective, cfg.resample_pairs, cfg.batch_size) == (0.5, "inbatch", True, 64)
    with pytest.raises(AssertionError):
        parse_overrides(["no_such_field=1"], SETTINGS.siamese)


def test_combine_features_is_unit_norm() -> None:
    from src.embeddings.features import combine

    rng = np.random.default_rng(0)
    a = rng.standard_normal((4, 6)).astype(np.float32)
    b = rng.standard_normal((4, 3)).astype(np.float32)
    a /= np.linalg.norm(a, axis=1, keepdims=True)
    b /= np.linalg.norm(b, axis=1, keepdims=True)
    out = combine(a, b)
    assert out.shape == (4, 9)
    np.testing.assert_allclose(np.linalg.norm(out, axis=1), 1.0, atol=1e-5)
    assert combine(a, None) is a


def test_recommend_excludes_text_flagged_adult_targets() -> None:
    from src.evaluation.recommend import recommend
    from src.ingest.adult import refine_adult

    items = pd.DataFrame({
        "domain": ["anime", "game", "game"],
        "item_id": [1, 2, 3],
        "title": ["Detective Story", "Night Club", "Puzzle Quest"],
        "synopsis": ["A student finds a notebook.", "An uncensored hentai game with nudity.", "Solve puzzles."],
        "is_adult": [False, False, False],
    })  # fmt: skip
    vectors = np.array([[1.0, 0.0], [1.0, 0.0], [0.6, 0.8]], dtype=np.float32)
    prior = np.zeros(3, dtype=np.float32)
    unrefined = recommend(vectors, items, prior, "control", top_n=1)
    assert unrefined.loc[unrefined["source_id"] == 1, "target_id"].tolist() == [2]
    items["is_adult"] = refine_adult(items)
    assert items["is_adult"].tolist() == [False, True, False]
    refined = recommend(vectors, items, prior, "control", top_n=1)
    assert refined.loc[refined["source_id"] == 1, "target_id"].tolist() == [3]
