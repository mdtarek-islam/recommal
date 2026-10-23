---
name: ml-reproducibility
description: Reproducibility and evaluation discipline for PyTorch and sentence-transformers experiments. Use before you train, evaluate or report an ML result in Recommal.
---

# ML reproducibility

## Before training

1. Call `set_seed()` from `src/config.py`. Do not seed in other places.
2. Read every hyperparameter from `src/config.py`. Do not write a number inline.
3. Split each domain once with `assign_splits()`. Fit every transform (TF-IDF, SVD, scalers) on the training split only.
4. Fix the relevance definition and the metric before the first run. Record them in the metrics file.
5. Check that model inputs do not contain the label source. Genre text must not enter the SBERT input when genres define relevance.

## During training

1. Assert tensor shapes at each model boundary.
2. Use one `torch.device` from `get_device()`. Move data with `.to(device)`.
3. Run evaluation under `model.eval()` and `torch.inference_mode()`.
4. Keep the best checkpoint with `copy.deepcopy(model.state_dict())`. A bare `state_dict()` is a live reference.
5. Stop early on a validation metric. Never select on the test split.

## Reporting

1. Report every baseline on the same split, candidate pool and metric: random, TF-IDF+SVD, raw SBERT, the model.
2. Report the relevance base rate, so a reader can judge the metric.
3. Report the real value when a target is missed, with the cause. Never redefine a metric to meet a target.
4. Write results to `artefacts/metrics.json`. Quote numbers only from that file.
5. State threats to validity: weak labels, lexicon coverage, domain shift, single seed.

## Testing

1. Unit-test the loss formula and each metric against hand-computed values.
2. Unit-test model output shapes, norms and value ranges.
3. Keep unit tests under 30 seconds and free of downloads.
