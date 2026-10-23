# Dissertation critique

This review judges the original pipeline against a UK First-Class (70+) and Distinction rubric.
Sources: the dissertation text `main.md` and the notebook export `ai_pipeline.txt` (cell numbers below).
The review covers label validity, leakage, baselines, ablations, variance and threats to validity.

Severity: BLOCKER stops a First-Class mark. MAJOR lowers it. MINOR needs a fix but does not change the mark band.

## Summary

The work shows a complete system: ingestion, embeddings, a Siamese model, a database and a Streamlit app.
The central claim is weak. The reported AUC of about 0.998 (`main.md` lines 1382-1385, 1403) measures how well the model reproduces SBERT similarity.
It does not measure recommendation quality. The author notes the "circularity risk" (`main.md` line 1604) but does not remove it.

## Findings

### F1. BLOCKER: circular labels

- **Evidence.** Cell 11 (`build_pairs`) takes the top 2 SBERT cosine neighbours as positives and the bottom 2 as negatives. The same SBERT vectors feed the model.
  Cells 14 to 17 train on these pairs. Cells 14 to 16 report AUC 0.9921 to 0.9998.
  Cell 15 picks the F1 threshold 0.320 on validation labels. Cell 25 reuses 0.32 for the model comparison table.
- **Effect.** The task is to regress a function of the input. High AUC is expected and carries no information about relevance.
  `main.md` line 1403 reads the gap to the standard NN (AUC 0.84) as a "substantial performance advantage". The gap reflects label construction.
- **Rebuild.** Labels come from a theme taxonomy independent of the embeddings (`src/ingest/themes.py`). Evaluation uses MAP@10 against Jaccard relevance (`src/evaluation/evaluate.py`).
  The raw SBERT cosine baseline shows how much the model adds.

### F2. BLOCKER: label text inside the model input

- **Evidence.** Cell 2 (lines 94-130) and cell 21 (line 1440) build the SBERT text from `cluster_genre_descriptions + synopsis + title`.
  The genre cluster text is a direct summary of the category that defines similarity in the discussion chapter.
- **Effect.** Any genre-based notion of relevance leaks into the input.
- **Rebuild.** `_model_text` in `src/ingest/build_dataset.py` uses title and synopsis only.

### F3. MAJOR: early stopping restores the wrong weights

- **Evidence.** Cell 15 line 723 and cell 16 line 905 assign `best_state = model.state_dict()`. The call returns a live reference.
  Cell 14 line 569 stores `'state': model.state_dict()` in the same way.
- **Effect.** The saved state equals the last epoch. Patience logic has no effect. Reported best-epoch metrics do not match the saved weights.
- **Rebuild.** `src/ml/train.py` line 93 uses `copy.deepcopy`.

### F4. MAJOR: embedding collapse and the "100%" similarities

- **Evidence.** Cells 13, 17 and 18 end the projection tower with `nn.ReLU()` and then L2 normalise (lines 451-454, 1073-1078, 1223-1228).
  All components become non-negative. Cosine similarity of any two vectors is then 0 or higher and tends to 1.
  `top_5_recs.csv` shows the effect: Cowboy Bebop receives five games, all at 100 percent, with no thematic link ("Dragon of Legends", "Mirage: Beyond The Screen").
  Rows 1, 3, 4, 5 and 6 of the file score every recommendation at 100.
- **Rebuild.** `src/ml/siamese.py` uses a linear output and a residual path. Scores use the range from -1 to 1.

### F5. MAJOR: loss does not match the methodology

- **Evidence.** `main.md` lines 1099 and 1204 describe a contrastive or margin-based loss. Cell 14 line 538 and cell 15 line 638 use `BCEWithLogitsLoss`, with `pos_weight` in cell 15.
  The text formula at line 1099 also swaps the label convention: it weights `(1-y)` on `D^2`, yet defines `y = 1` as similar.
- **Effect.** The thesis describes one method and reports another.
- **Rebuild.** `src/ml/losses.py` implements the contrastive loss with an explicit margin from `src/config.py`.

### F6. MAJOR: evaluation does not test retrieval

- **Evidence.** The chapter reports AUC, F1, accuracy and precision (`main.md` lines 1446 to 1471). The system ranks items, so the evaluation needs MAP@K, recall@K or NDCG@K.
  The CLAUDE.md target MAP >= 0.82 has no matching notebook result.
- **Rebuild.** `src/evaluation/metrics.py` computes MAP@10, precision@10 and recall@10 per direction.

### F7. MAJOR: baselines are weak or not comparable

- **Evidence.** The TF-IDF+SVD baseline (AUC 0.9866, `main.md` line 1463) uses labels derived from SBERT cosine, so it also solves a different task than ranking.
  The standard NN (cells 27 to 33, AUC about 0.84) is a classifier on TF-IDF features. No random baseline and no raw SBERT cosine baseline exist.
- **Rebuild.** `evaluate.py` reports random, TF-IDF+SVD fitted on training items only, raw SBERT cosine, and the model.

### F8. MAJOR: no ablation, one seed in the final model

- **Evidence.** The k-fold cells (cell 16) report fold variance, but all folds share one label function and one embedding.
  No ablation removes the cluster text, the hard negatives or the residual path.
- **Rebuild.** Partly closed. The Results section of `docs/methodology.md` reports three training seeds (standard deviation 0.0045), a no-hard-negatives ablation and a keyword-masked ablation.
  Open: the residual-path ablation, lexicon thresholds 1 and 3, and more than three seeds.

### F9. MAJOR: possible fold leakage

- **Evidence.** `main.md` lines 1370 to 1373 admit that preprocessing can leak across folds. Cluster centroids (cells 2 to 4, elbow plots at `main.md` lines 909 to 957) fit on the full corpus before the split.
- **Rebuild.** TF-IDF and SVD fit on training items only. The taxonomy needs no fitted parameters.

### F10. MINOR: BatchNorm with single-item inference

- **Evidence.** Cells 13, 17 and 18 use `BatchNorm1d` in the encoder. The app encodes single items.
- **Rebuild.** LayerNorm.

### F11. MINOR: database design and app queries

- **Evidence.** `auth_utils.py` line 160 onward in the original app unions 10 `steam_games_chunk_*` tables for each lookup (free-tier sharding).
  Line 217 uses `ILIKE %s ... LIMIT 1`, which returns an arbitrary match. The app issues one query per recommendation (N+1).
- **Rebuild.** One `steam_games` table in `db/migrations/001_initial_schema.sql`. Queries live in `src/db/queries.py`.

### F12. MINOR: reporting

- **Evidence.** The dissertation reports results from 4 folds with F1 selected on validation. It gives no confidence interval and no significance test between models.
- **Rebuild.** Report paired bootstrap intervals over queries before the final write-up. This is open work.

## Rubric view

| Criterion | Original | After rebuild |
|---|---|---|
| Problem framing | Clear | Clear |
| Label validity | Circular (F1, F2) | Independent taxonomy, noisy (see Threats) |
| Evaluation fit | Classification metrics (F6) | Ranking metrics |
| Baselines | Weak (F7) | Four baselines |
| Reproducibility | Notebook state, live references (F3) | Seeds, config module, tests |
| Critical reflection | Limitation named, not resolved | Threats listed; two ablations and 3 seeds reported; more open |

## Path to a First

1. Done: the Results section of `docs/methodology.md` reports `artefacts/metrics.json`. The MAP@10 target of 0.82 is not met (0.0722).
2. Partly done: no-hard-negatives and keyword-masked ablations exist. Add no residual path, and lexicon thresholds 1 and 3.
3. Partly done: 3 seeds exist (mean 0.0766, standard deviation 0.0045). Run 5 seeds.
4. Hand-label 200 game themes. Report lexicon precision.
5. State the A/B sample size before launch.
