Test split. Relevance: theme Jaccard >= 0.5. K = 10. Model version: `siamese-v2`. Seed: 42.

| Model | MAP@10 anime->game | MAP@10 game->anime | Mean MAP@10 | Mean P@10 | Mean Recall@10 |
|---|---|---|---|---|---|
| Random vectors | 0.0144 | 0.0122 | 0.0133 | 0.0348 | 0.0025 |
| TF-IDF + SVD | 0.0483 | 0.0458 | 0.0470 | 0.0921 | 0.0130 |
| Raw SBERT cosine | 0.0335 | 0.0425 | 0.0380 | 0.0820 | 0.0112 |
| Siamese | 0.0602 | 0.0842 | 0.0722 | 0.1358 | 0.0189 |
| Siamese + popularity prior | 0.0549 | 0.0875 | 0.0712 | 0.1317 | 0.0168 |

Base rate of a relevant candidate: 0.0357 (anime->game), 0.0349 (game->anime). Test contrastive loss: 0.0575 on 154536 pairs.

| Ablation | Mean MAP@10 | Note |
|---|---|---|
| Keyword-masked test games, raw SBERT | 0.0340 | Drop of 0.0041 |
| Keyword-masked test games, Siamese | 0.0636 | Drop of 0.0086 |
| No hard negatives, Siamese | 0.1027 | Test score. Selection used validation |
| Random vectors, 5 seeds | 0.0131 | Standard deviation 0.0005 |
| Siamese, 3 training seeds | 0.0766 | Standard deviation 0.0045 |
