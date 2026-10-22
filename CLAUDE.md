# Recommal

## 1. Project Scope and Stack

Recommal is a cross-domain multimedia recommender. It maps anime and video games into one shared latent space.

- Model: Siamese Neural Network over BERT embeddings (PyTorch, HuggingFace Transformers), trained with contrastive loss.
- Data: REST API ingestion and cleaning into Supabase PostgreSQL.
- UI: Streamlit (`app.py`). Database and auth helpers: `auth_utils.py`.
- Infrastructure: Docker, AWS and agents where they add value. No deploy target is set.
- Environment: Python 3.13+, `.venv` (activate with `.venv\Scripts\activate`), Windows 11.
- Package manager: uv when `pyproject.toml` exists; pip with `requirements.txt` until then.
- Baseline targets:
  - Mean Average Precision (MAP) >= 0.82.
  - Contrastive loss <= 0.15.
  - 100,000+ cleaned REST API records.
- The repository holds no training code yet. The app reads precomputed rows from `siamese_recommendations`.

## 2. Language and Writing Standards

- Write all docs, comments, docstrings, commit messages and UI text in British English.
- Apply ASD-STE100: active voice, imperative verbs, sentences under 20 words.
- Do not use marketing adjectives or emojis in any file, log line or commit.

## 3. Token Efficiency and Subagent Routing

- Scout first with `repo-scout` (haiku) for any task that needs repository context.
- Build second with `streamlit-ui-builder` or `ml-data-pipeline` (opus), each in its own folders.
- Test last with `qa-auditor` (sonnet).
- Use `/orchestrate` for a change that touches both the UI and the data layer.
- Read only the line ranges you need; use Grep and Glob before Read.
- Query context7 before you use an API that you have not checked in this session.
- Never exceed `high` thinking effort.
- Invoke `senior-commit` before the final report.

## 4. Domain and ML Style Rules

- Set the Python, NumPy and PyTorch random seeds from the config module before training or evaluation.
- Create one `torch.device` object and move models and tensors with `.to(device)`; never call `.cuda()` directly.
- Read batch size, embedding size and margin from the config module; never write them inline.
- Assert embedding tensor shapes before each similarity or loss computation.
- Run BERT inference under `model.eval()` and `torch.inference_mode()`.
- Retry REST API calls with exponential backoff and jitter on HTTP 429 and 5xx responses.
- Respect `Retry-After` headers and log each retry with the endpoint and attempt number.
- Cache database reads with `@st.cache_data(ttl=...)` and cache connections and models with `@st.cache_resource`.
- Never cache data that is specific to one user with `@st.cache_resource`.
- Log the A/B cohort, a hashed user id, the query and the recommendation ids for each results view.
- Use parameterised SQL with `%s` placeholders only.
- Show a fixed error message in the UI and log the exception; never pass raw exception text to `st.error`.
- Return the database connection to a pool or close it in a `finally` block.
- Replace the 10-table `steam_games_chunk_*` UNION with one view or table before you add game queries.
- TODO: add project-specific overrides here after review.

## 5. Data and Architecture Rules

- Keep one source-of-truth config and schema module at `recommal/config.py`; create it when the first setting moves out of code.
- Read credentials, API URLs and Supabase keys from environment variables or `st.secrets` only.
- Never hardcode personal strings, emails, API URLs, Supabase keys or `.streamlit/secrets.toml` values in source code.
- Keep model weights (`*.pt`, `*.pth`, `*.bin`, `*.safetensors`, `*.onnx`) and datasets out of git; record their storage location in the config module.
- Put each database schema change in a numbered migration file under `db/migrations/`.

## 6. Self-Governance

Before you add or modify any line in `CLAUDE.md`, execute this 4-step check:
1. **Deduplication Check**: Verify the rule does not exist in `.claude/settings.json`, `.mcp.json`, `.claude/agents/*.md`, `.claude/commands/*.md` or `.claude/skills/**/SKILL.md`.
2. **Token Cap**: Keep `CLAUDE.md` under 110 lines. Compress or remove an obsolete rule before you add one.
3. **STE100 Compression**: Write the change as one imperative sentence.
4. **User Approval**: Show the exact diff and get confirmation before you write.
