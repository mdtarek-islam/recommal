"""Run named configurations over several seeds and record validation MAP@K only.

Run: python -m src.ml.sweep --name NAME [--seeds 42 43 44] [--set FIELD=VALUE ...]
Output: one JSON line per seed appended to artefacts/sweep_results.jsonl.

The sweep never reads the test split. It saves no checkpoints.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict

import numpy as np
import pandas as pd

from src.config import SEED, SETTINGS
from src.embeddings.sbert import load_embeddings
from src.ml.data import assign_splits, theme_matrix
from src.ml.train import fit, parse_overrides, validation_pairs

log = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[SEED, *SETTINGS.evaluation.extra_train_seeds])
    parser.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    paths, k = SETTINGS.paths, SETTINGS.evaluation.k
    cfg = parse_overrides(args.set, SETTINGS.siamese)
    items = pd.read_parquet(paths.items)
    embeddings = load_embeddings()
    splits = assign_splits(items)
    themes = theme_matrix(items["themes"])
    val_pairs = validation_pairs(items, splits, themes, embeddings, cfg)
    scores = []
    for seed in args.seeds:
        _, summary = fit(items, splits, themes, embeddings, cfg, seed, val_pairs)
        scores.append(summary["best_val_map"])
        record = {"name": args.name, "overrides": args.set, "seed": seed, f"val_map@{k}": summary["best_val_map"],
                  "best_epoch": summary["best_epoch"], "val_loss": summary["best_val_loss"],
                  "minutes": summary["minutes"], "config": asdict(cfg)}  # fmt: skip
        with (paths.artefact_dir / "sweep_results.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    log.info("SWEEP %s: val MAP@%d mean=%.4f std=%.4f over %d seeds %s", args.name, k, float(np.mean(scores)),
             float(np.std(scores, ddof=1)) if len(scores) > 1 else 0.0, len(scores),
             [round(s, 4) for s in scores])  # fmt: skip


if __name__ == "__main__":
    main()
