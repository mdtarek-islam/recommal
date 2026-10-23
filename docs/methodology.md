# Methodology

This document describes the rebuilt Recommal pipeline. Every tunable value lives in `src/config.py`.
Result numbers appear only in the Results section. They come from `artefacts/metrics.json`, `artefacts/training_history*.json` and `artefacts/tuning_log.md`.

## 1. Problem statement

Recommal recommends across domains. A user picks an anime and receives video games, or the reverse.
The system maps both domains into one latent space. Cosine similarity in that space ranks candidates.

The system uses content only. It has no interaction history. Two inputs describe each item: a title and a synopsis.

## 2. Data

| Source | Format | Use |
|---|---|---|
| MyAnimeList (MAL) | PostgreSQL dump `sql/animes_db.sql` | Anime items and genres |
| Steam | PostgreSQL dump `sql/steam_games.sql` | Game items and genres |
| MAL API, Steam Store API | REST (`src/ingest/rest_clients.py`) | Optional refresh, with backoff and jitter |

`python -m src.ingest.build_dataset` parses the dumps and writes `data/processed/items.parquet`.
The build flags adult items. It drops non-game Steam software, anime music videos, promotional videos and commercials, and items without a synopsis.
It removes duplicates with the same domain, normalised title and synopsis prefix.
`src/evaluation/recommend.py` never recommends adult items to a non-adult source item.

Item counts: 152,911 items in total. These are 16,967 anime and 135,944 games.
Items with at least one theme: 15,522 anime and 115,407 games.

## 3. Weak supervision: the theme taxonomy

The original pipeline labelled pairs with SBERT cosine similarity. That label is not independent of the model input.
The rebuild defines relevance from a fixed taxonomy of 23 canonical themes (`THEMES` in `src/ingest/themes.py`).

- **Anime themes.** The map `ANIME_GENRE_THEMES` converts MAL genres to canonical themes. One genre can give several themes.
- **Game themes.** The union of two sources gives the themes of a game.
  1. The map `STEAM_GENRE_THEMES` converts six Steam genres.
  2. A keyword lexicon scans the title and description. A theme applies only when at least `MIN_KEYWORD_HITS = 2` distinct keywords match.

Two items are relevant when the Jaccard similarity of their theme sets reaches 0.5 (`RelevanceConfig.jaccard_threshold`).
Items with no theme are unlabelled. Training and evaluation exclude them as queries, candidates and negatives.

## 4. Model input

The SBERT input text is the title and the synopsis only (`_model_text` in `src/ingest/build_dataset.py`).
Genre labels and cluster descriptions do not enter the input.
The encoder is `sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions, run in eval mode under `torch.inference_mode()`.

## 5. Model

`SiameseEncoder` in `src/ml/siamese.py` shares weights between both towers.

- Residual path: a bias-free linear map from 384 to 128 dimensions.
- MLP path: Linear(384, 512), LayerNorm, GELU, Dropout(0.1), Linear(512, 128).
- Output: the sum of both paths, with no final activation, then L2 normalisation.

LayerNorm replaces BatchNorm, so single-item inference matches training behaviour.
The linear output allows negative components. Cosine scores can then use the full range from -1 to 1.

## 6. Loss

`contrastive_loss` in `src/ml/losses.py` follows Hadsell, Chopra and LeCun (2006). With cosine similarity `cos`:

```
D = 1 - cos(z1, z2)                     # D in [0, 2]
L = y * D^2 + (1 - y) * max(0, m - D)^2
```

Here `y = 1` for a relevant pair, `y = 0` for a non-relevant pair, and `m` is the margin (`SiameseConfig.margin = 0.5`).
The loss is the mean over the batch.

## 7. Pair mining and hard negatives

`mine_pairs` in `src/ml/data.py` builds pairs in both directions (anime to game, game to anime) inside one split.

- Positives: up to 4 candidates per query with Jaccard at least 0.5.
- Negatives: 4 labelled candidates per query with Jaccard exactly 0.
- Half of the negatives are hard. They are the nearest zero-overlap candidates in raw SBERT space (pool of 50). The other half are random.

Candidates with a Jaccard between 0 and 0.5 are neither positive nor negative. This leaves a margin around the decision boundary.

## 8. Splits and early stopping

`assign_splits` splits each domain separately into 70% train, 15% validation and 15% test. The seed is 42.
Pairs are mined inside each split. No item appears in two splits.

Training uses AdamW with `ReduceLROnPlateau`. It evaluates validation MAP@10 each epoch.
Training keeps a deep copy of the best state. It stops after `patience = 5` epochs without improvement of at least 1e-4.

## 9. Evaluation protocol

`src/evaluation/evaluate.py` evaluates on the test split only. A query is a labelled test item of one domain.
The candidate pool is the labelled test items of the other domain. A candidate is relevant when Jaccard is at least 0.5.
Metrics are MAP@10, precision@10 and recall@10, averaged over both directions.
A query with no relevant candidate is excluded from MAP and recall. The report records the relevance base rate.
Each direction samples at most `max_queries = 2000` queries with a fixed seed.

### Baselines

| Name | Description |
|---|---|
| `random` | Random unit vectors, 64 dimensions |
| `tfidf_svd` | TF-IDF (1 to 2 grams) with 128-dimension truncated SVD, fitted on training items only |
| `sbert_cosine` | Cosine similarity of raw SBERT embeddings |
| `siamese` | The trained model |
| `siamese_popularity` | The trained model with a log-popularity prior (weight 0.05) |

The test contrastive loss is reported on mined test pairs.

## 10. A/B test design

The experiment `rec_layout_v1` has two variants. Assignment is deterministic and stateless (`src/ab_testing/cohort.py`).

| Variant | Content |
|---|---|
| `control` | Cards ranked by latent cosine similarity |
| `explained` | Cards ranked with the popularity prior, each with its shared themes |

Hypothesis H1: the `explained` variant raises the thumbs-up rate.

- **Identity.** Each user id is lower-cased and hashed with SHA-256 and the secret salt `RECOMMAL_AB_SALT`. Telemetry stores the hash only.
- **Events.** The table `ab_test_events` stores `exposure`, `feedback` and `search` events. Feedback uses `relevance` of +1 or -1.
- **Unit and metric.** The unit is the user. The primary metric is the share of exposed users with at least one thumbs-up, per variant.
- **Test.** A two-proportion z-test, two-sided, alpha = 0.05.
- **Minimum sample size.** Fix it before launch. Use `n = 2 * (1.96 + 0.84)^2 * p * (1 - p) / d^2` per variant. Here `p` is the pooled expected rate and `d` is the minimum detectable difference.
  Record `p` and `d` in the experiment log before the first exposure. Do not stop early on a significant interim result.
- **Confound.** The `explained` variant changes two things: the ranking prior and the explanation. The test cannot separate them.

## 11. Threats to validity

1. **Noisy game themes.** The lexicon labels games from description text. Single words such as "secret" or "student" can fire. Precision is not measured.
2. **Text-derived labels.** Game themes come from the same text that SBERT encodes. The model can match keywords, not meaning. Anime themes come from curated genres. The two label sources differ in kind.
3. **Jaccard threshold.** The value 0.5 is a design choice. Results can change at other values. Report a sensitivity check.
4. **Few seeds.** One data split (seed 42) serves all runs. Three training seeds exist for the final configuration. Three seeds give a rough spread only.
5. **Thematic, not experiential, similarity.** Theme overlap does not measure play experience or enjoyment.
6. **Popularity bias.** Popular items dominate catalogues and reviews. The prior in `siamese_popularity` reinforces this.
7. **Pool size.** The test pool holds 15% of one domain. Metrics from a small pool differ from metrics over the full catalogue.
8. **No user study.** The A/B test is small and uses prototype traffic. Offline metrics do not prove user benefit.

## Results

All numbers come from the test split unless stated. Protocol: theme Jaccard at least 0.5, K = 10, at most 2,000 queries per direction, model version `siamese-v2`, seed 42.
Candidates are the labelled test items of the other domain: 17,315 games for anime queries and 2,309 anime for game queries.

### Main table

| Model | anime->game MAP@10 | game->anime MAP@10 | Mean MAP@10 | Mean P@10 | Mean Recall@10 |
|---|---|---|---|---|---|
| Random | 0.0144 | 0.0122 | 0.0133 | 0.0349 | 0.0025 |
| TF-IDF + SVD | 0.0483 | 0.0458 | 0.0470 | 0.0921 | 0.0130 |
| Raw SBERT cosine | 0.0335 | 0.0425 | 0.0380 | 0.0820 | 0.0112 |
| Siamese | 0.0602 | 0.0842 | 0.0722 | 0.1358 | 0.0189 |
| Siamese + popularity prior | 0.0549 | 0.0875 | 0.0712 | 0.1317 | 0.0168 |

- **Base rate.** A random candidate is relevant with probability 0.0357 (anime->game) and 0.0349 (game->anime). This is about 3.5%.
- **Test contrastive loss.** 0.0575 on 154,536 mined test pairs.
- **Recall@10.** Recall is low for every model. Each query has hundreds of relevant candidates, and a list of 10 items holds only a few of them.

### Ablations

| Ablation | Mean MAP@10 | Note |
|---|---|---|
| Keyword-masked test games, raw SBERT | 0.0340 | Drop of 0.0041 from 0.0380 |
| Keyword-masked test games, Siamese | 0.0636 | Drop of 0.0086 from 0.0722 |
| No hard negatives, Siamese | 0.1027 | Test score. Selection used validation. See Discussion |
| Random vectors, 5 seeds | 0.0131 | Standard deviation 0.0005 |

Masking removes the lexicon keywords from the test game text (20,391 games) and re-encodes it. Anime text is unchanged.
The drop is larger for the Siamese model than for raw SBERT, so the Siamese model uses the keywords more.
The Siamese model still scores 0.0636 against 0.0340 for raw SBERT on masked text.

### Seed spread

| Seed | Test mean MAP@10 | Test mean Recall@10 |
|---|---|---|
| 42 | 0.0722 | 0.0189 |
| 43 | 0.0765 | 0.0205 |
| 44 | 0.0811 | 0.0197 |
| Mean | 0.0766 | 0.0197 |
| Standard deviation | 0.0045 | 0.0008 |

The three seeds change only the training run. The data split stays fixed. The standard deviation is a rough estimate.

### Tuning (validation split only)

Selection metric: mean validation MAP@10. The tuning log states that test results were not read while tuning.
Raw SBERT scores 0.0431 on the same validation data. Minutes come from `training_history*.json`.

| Run | Change | Best epoch | Val MAP@10 | Val loss | Minutes |
|---|---|---|---|---|---|
| 1 | Defaults (lr 1e-3, dropout 0.1, margin 0.5) | 1 | 0.0968 | 0.0567 | 7.7 |
| 2 | lr 3e-4, dropout 0.3 | 5 | 0.0901 | 0.0587 | 42.2 |
| 3 | 16 positives and 16 negatives per item | 1 | 0.0885 | 0.0591 | 30.0 |
| 4 | Hidden 256, projection 64, dropout 0.3, weight decay 1e-2 | 6 | 0.0901 | 0.0584 | 5.9 |
| 5 | Margin 1.0 (loss scale differs) | 1 | 0.0844 | 0.2251 | 5.0 |
| 6 (final) | Run 1 retrained, same result | 1 | 0.0968 | 0.0567 | 88.8 |

Models trained after selection:

| Model | Best epoch | Val MAP@10 | Val loss |
|---|---|---|---|
| No hard negatives | 1 | 0.0985 | 0.0478 |
| Seed 43 | 2 | 0.0807 | 0.0568 |
| Seed 44 | 3 | 0.0903 | 0.0606 |

Validation MAP@10 across seeds ranges from 0.0807 to 0.0968. This range exceeds every difference between tuning runs.
The tuning runs therefore do not separate the configurations reliably.
`tuning_log.md` lists 13 minutes for run 1 and 35 for run 3. The JSON files record 7.7 and 30.0. The table uses the JSON values.

### Runtime

| Step | Observed time |
|---|---|
| SBERT embeddings (152,911 items) | 158.9 min |
| Training, one run | 4 to 89 min (the 89 min run shared the CPU) |
| Masked re-encoding of test games | 49.2 min |
| Recommendations written | 1,529,110 rows |

Hardware: Snapdragon X laptop with Python under x64 emulation. Times differ on other machines.

## Discussion

### The MAP@10 target is not met

`CLAUDE.md` sets MAP@10 at least 0.82 and contrastive loss at most 0.15. The test loss of 0.0575 meets the loss target.
The Siamese MAP@10 of 0.0722 does not meet the MAP target. This protocol cannot meet the target, for three reasons.

1. **Weak labels.** Relevance comes from genres and a keyword lexicon. Themes are coarse, and lexicon precision is unmeasured.
2. **Many relevant items per query.** About 3.5% of candidates are relevant. That is hundreds of items per query in a pool of 2,309 to 17,315.
3. **Ceiling effect.** Theme sets overlap partly by chance. No model can rank all relevant items first when the labels do not separate items. The achievable MAP@10 is unknown.

The Siamese model scores 5.4 times the random baseline (0.0722 against 0.0133). It also beats TF-IDF + SVD (0.0470) and raw SBERT (0.0380).
These gaps exceed the seed spread of 0.0045. No significance test between models exists yet.

### Comparison with the dissertation

The dissertation reports an AUC near 0.99. That number is not comparable with MAP@10 here, for two reasons.
First, the labels were circular. They came from SBERT cosine similarity, and SBERT vectors also fed the model (see `docs/dissertation-critique.md`, F1).
Second, the task differed. AUC scores a pair classifier. MAP@10 scores a ranked list against independent labels.
This work does not show that the new system beats the old one. The two systems answer different questions on different labels.

### What the numbers show and do not show

- The Siamese model ranks theme-similar items above chance and above two baselines, under noisy labels.
- Keyword masking lowers the score, so part of the gain comes from lexicon keywords in game text.
- The numbers do not show user benefit. No user study or A/B result exists.
- The numbers do not show that themes capture play experience (threat 5).
- Game->anime scores higher than anime->game. The two directions use different candidate pools, so compare them with care.

### Example quality

The top-5 cosine scores for the control variant in `recommendations.parquet` lie between 0.91 and 0.99 (1st and 99th percentile; minimum 0.745).
Such scores carry little ranking information for a reader. The UI therefore no longer shows absolute percentages.
The Stardew Valley example is poor. The item table tags it `mystery` and `slice_of_life`. The mystery tag is a lexicon error.
This document does not trace the lexicon keyword that caused the error.

### Model selection decision

The no-hard-negatives model scores 0.1027 on the test split. The selected model scores 0.0722.
The selection rule used validation MAP@10, fixed before training. On validation the two models score 0.0985 and 0.0968.
That gap of 0.0017 lies inside the seed spread (0.0807 to 0.0968). Choosing by test score would use the test set for model selection.
The pre-registered model (run 1 configuration, with hard negatives) stays the shipped model.
The test result for the no-hard-negatives model is a hypothesis for the next round, not a finding.
The test gap is much larger than the validation gap. No analysis of the cause exists.

## Next steps (validated by evidence)

1. **Multi-seed model selection.** The seed spread (0.0807 to 0.0968 on validation) exceeds the tuning differences. Select by the mean over at least 5 seeds.
2. **Graded relevance.** A binary Jaccard threshold of 0.5 discards information. Use NDCG@10 with Jaccard as the gain. Report threshold sensitivity.
3. **Human-labelled evaluation sample.** Label a sample of query-candidate pairs by hand. Measure how far theme relevance matches human judgement.
4. **Lexicon precision check.** Label 200 game theme assignments by hand. The Stardew Valley case shows that errors exist.
5. **Hard-negative ablation as a validation-selected candidate.** Run the no-hard-negatives configuration over several seeds. Promote it only if it wins on validation means.
