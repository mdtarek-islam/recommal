# ml-research-architect knowledge

Durable lessons for `ml-research-architect`. `/promote-memory` adds entries after user approval.

## Dissertation baseline defects (2026-10-22)

- The notebook labelled pairs with SBERT cosine on the same input embeddings. The 0.99 AUC is circular. Use theme-Jaccard relevance from `src/ingest/themes.py` instead.
- The notebook input text included genre-cluster words. Genres are now the label source, so `model_text` holds title and synopsis only.
- `best_state = model.state_dict()` kept a live reference, so the "best" checkpoint was the last epoch.
- The encoder ended in ReLU then L2 norm. Cosine scores collapsed towards 1.0 ("100% match" for unrelated titles).
- The dissertation loss was BCE on scaled cosine, not contrastive loss.

## Environment

- The machine is Windows ARM64 (Snapdragon X, 32 GB RAM, no CUDA). The venv Python is x64 under emulation; CPU torch wheels work.
- SBERT model: `sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions.
