# Claude Code governance scaffold: blueprint

This file lists each part of the Recommal scaffold, its role and its setup.
Part B is one reusable prompt for a new repository. It includes every fix found in Recommal.

---

## Part A. Inventory

### A1. Project memory and self-governance

| Item | Path | Role | Setup |
|---|---|---|---|
| Project rules | `CLAUDE.md` | Loads into every session. Six sections: scope and stack, writing standards, routing, domain rules, data rules, self-governance. | Keep it at 110 lines or fewer. Do not duplicate rules that other config files hold. |
| Self-governance | `CLAUDE.md` section 6 | A 4-step check before any edit to `CLAUDE.md`: deduplication, line cap, STE100 compression, user approval with the exact diff. | Copy the section word for word. |
| Guard hook | `.claude/hooks/guard-claude-md.sh` | Blocks an edit that goes over the cap or duplicates a rule. `--audit` mode checks the whole file in CI. | Set `MAX_LINES` and `DEDUP_PATHS`. |
| Local runbook | `LOCAL_RUNBOOK.md` (gitignored) | Explains how to run the project on this machine: `.env` names, commands, recovery. | Write it, and never commit it. |

### A2. Settings (`.claude/settings.json`)

| Key | Value | Why |
|---|---|---|
| `model` | `opus` | Gives the main session the strongest planner. |
| `permissions.defaultMode` | `plan` | Every session starts read-only until you approve a plan. |
| `permissions.deny` | `Read(./.env)`, `Read(./.env.local)`, `Read(./.env.*.local)`, `Read(./.streamlit/secrets.toml)`, `Read(./**/secrets/**)`, `Read(./**/*.pem)`, `Read(./**/*.key)`, `Read(./**/id_rsa*)`, `Read(./**/id_ed25519*)` | Keeps secrets out of context. **Fix:** do not deny `Read(./.env*)`. It also blocks `.env.example`, and Claude then cannot create the template. |
| `env` | `DISABLE_TELEMETRY=1`, `DISABLE_ERROR_REPORTING=1`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `MAX_THINKING_TOKENS=16000` | Sets privacy and the token budget. |
| `statusLine` | `bash "$CLAUDE_PROJECT_DIR/.claude/hooks/statusline.sh"` | Shows the model, the cost and the branch. |
| `hooks` | See A3. | — |
| Plugins | None | **Fix:** do not declare the same Supabase MCP or skill both as a plugin and in `.mcp.json`. The duplicates conflict. |
| `.claude/settings.local.json.example` | `{}` | Template for personal overrides. The real file is gitignored. |

### A3. Hooks (`.claude/hooks/`, bash, parsed with `jq`)

All hooks `cd "$CLAUDE_PROJECT_DIR"`, source `_common.sh` and exit 2 to block.

| Script | Event and matcher | What it does |
|---|---|---|
| `_common.sh` | Sourced by the others | Holds the shared secret regex `SECRET_RE` and `require_jq()`. `require_jq()` falls back to the winget folder when `jq` is not on PATH. |
| `redact-prompt.sh` | UserPromptSubmit | Blocks a prompt that contains a secret, and prints a redacted copy. |
| `block-secret-files.sh` | PreToolUse `Read\|Grep\|Glob\|Bash\|Edit\|Write\|NotebookEdit` | Blocks secret paths (`.env`, `secrets.toml`, keys) and tool input that contains a secret. **Fix:** allow `.env.example` and `secrets.toml.example`. |
| `safety-net.sh` | PreToolUse `Bash` | Blocks `rm`, `rmdir`, `unlink`, `git clean`, `git reset --hard`, force-push, `git branch -D` and `git checkout -- .`. You run these yourself. |
| `scan-skill.sh` | Pre and PostToolUse `Edit\|Write`; `all` mode in CI | Finds zero-width or tag Unicode and prompt-injection phrases in skills. **Fix:** run `grep -P` with `LC_ALL=C.UTF-8`. |
| `guard-claude-md.sh` | PreToolUse `Edit\|Write`; `--audit` in CI | Enforces the line cap and deduplication for `CLAUDE.md`. |
| `ipc-bus.sh` | UserPromptSubmit `sync`, PreToolUse `pre`, PostToolUse `post` | Coordinates parallel sessions (see A8). |
| `statusline.sh` | statusLine | Prints `<model> \| $<cost> \| <branch>`, plus `BUDGET` above `CLAUDE_BUDGET_USD`. |

### A4. MCP servers (`.mcp.json`)

| Server | Config | Role | Setup |
|---|---|---|---|
| context7 | `cmd /c npx -y @upstash/context7-mcp@<pinned>` | Current library docs. Agents query it before they use an API. | **Fix (Windows):** wrap stdio servers in `cmd /c`. Pin the version. |
| playwright | `cmd /c npx -y @playwright/mcp@<pinned> --headless` | Browser smoke tests and screenshots for QA. | Pin the version, and use `--headless`. |
| supabase | `type: http`, `https://mcp.supabase.com/mcp?read_only=true&project_ref=<ref>` | Read-only database inspection, advisors and logs. | Scope it to one project and keep it read-only. Authorise it once through `/mcp` (OAuth). Only the data agent gets `mcp__supabase__*`. |

### A5. Agents (the "office", `.claude/agents/*.md`)

The frontmatter has `name`, `description` ("PROACTIVELY use this agent ..."), `model`, `tools`, `skills` and `memory: project`.

| Agent | Model | Owns | Tools and skills |
|---|---|---|---|
| `repo-scout` | haiku | Read-only maps of files, symbols, owners | Read, Glob, Grep, Bash; `caveman` |
| `ml-research-architect` | opus | `src/ml/`, `src/embeddings/`, `src/evaluation/`, config | + context7; `ml-reproducibility`, `stop-slop` |
| `data-db-optimiser` | opus | `src/ingest/`, `src/db/`, `db/` | + context7, supabase MCP; `supabase`, `supabase-postgres-best-practices`, `stop-slop` |
| `streamlit-ui-ux` | opus | `app.py`, `src/ui/`, `src/ab_testing/`, `.streamlit/` | + context7; `streamlit-ui-polish`, `stop-slop` |
| `qa-cyber-ci-auditor` | sonnet | Tests, lint, types, security, CI, Playwright | + playwright MCP; `caveman` |
| `academic-critic-docs` | sonnet | README, docs, docstrings, critique, runbook | `stop-slop` |

**Fix:** a new agent type is not callable until you restart Claude Code.
**Fix:** each agent body must say "Do not write to the live database or push without explicit user approval".

### A6. Commands (`.claude/commands/*.md`)

| Command | Role |
|---|---|
| `/orchestrate <task>` | Runs a task in four stages. Stage 1: scout, context7 checks and a plan of 15 lines or fewer, then stop for approval. Stage 2: shared contracts. Stage 3: parallel builders on their own paths. Stage 4: QA (one fix loop), docs review, then `senior-commit`. |
| `/governance-audit` | Report-only PASS/WARN/FAIL check of the scaffold: line cap, dedup, hooks executable, LF endings, skill hashes, pinned MCP versions, gitignore coverage. |
| `/promote-memory` | Proposes durable lessons from gitignored `agent-memory/` for the committed `knowledge/` files, after user approval. |
| `/sync-content` | Applies `docs/context/updates.yaml` to the single config module and verifies the result. |

### A7. Skills (`.claude/skills/<name>/SKILL.md`) and `skills-lock.json`

| Skill | Source | Role |
|---|---|---|
| `caveman` | local | Compresses agent-to-agent output. |
| `stop-slop` | local | Removes filler; enforces British English and ASD-STE100. |
| `senior-commit` | local | Conventional Commits, staging by file name, no `.env` or weights, no AI trailers, no push unless asked. |
| `ml-reproducibility` | local | Seeds, splits, baselines, leakage checks, seed spread. |
| `streamlit-ui-polish` | local | Layout, accessibility, state and caching rules. |
| `supabase` | vendored, pinned to a commit SHA | Supabase product guidance. |
| `supabase-postgres-best-practices` | vendored, pinned to a commit SHA | Schema, RLS, index and pooling rules. |

`skills-lock.json` records `source`, `ref` (`HEAD` for local, commit SHA for vendored), `path` and the sha256 of `SKILL.md`.
**Fix:** `.gitattributes` must force LF on skills and the lock file, or the hashes change on Windows checkout.

### A8. IPC (`.claude/ipc/`, gitignored)

`ipc-bus.sh` runs at three points:
- `pre`: locks the target file and blocks when another session holds a lock younger than 3 minutes.
- `post`: releases the lock and logs the update.
- `sync`: adds recent events to the prompt as context.

**Fix:** show only events from the last 2 hours in `sync`. Older entries repeat on every prompt and waste tokens.

### A9. Agent memory and knowledge

| Path | Committed | Role |
|---|---|---|
| `.claude/agent-memory/<agent>/` | No | Each agent writes session lessons here (`memory: project`). |
| `.claude/knowledge/<agent>.md` | Yes | Durable lessons that `/promote-memory` copies in after approval. |

### A10. CI/CD (`.github/`)

`ci.yml`:
- Triggers on push and pull request to `main`, with `permissions: contents: read`.
- Uses a concurrency group with cancel-in-progress.
- Pins action versions.

Job `checks` (15 minutes):
1. Checkout with `fetch-depth: 0`.
2. gitleaks CLI, with the tarball sha256 verified. **Fix:** use the CLI. `gitleaks-action` needs a licence for organisations.
3. Regex secret scan, with the same `SECRET_RE` as `_common.sh`.
4. Set up Python with the pip cache.
5. Install. **Fix:** `pip install --upgrade pip "setuptools>=83.0.0"` first, because the runner's setuptools fails `pip-audit`. **Fix:** install torch from the CPU index (`--index-url https://download.pytorch.org/whl/cpu`). The `torch ... could not be audited` line is informational.
6. `pip-audit --skip-editable`.
7. bandit: fail on medium or higher, warn on low. Document each skipped test ID.
8. ruff, mypy, pytest and `compileall`.
9. App boot and Playwright smoke test. Upload the QA artefacts on failure.

Job `governance`: `guard-claude-md.sh --audit` and `scan-skill.sh all`.

`dependabot.yml`: weekly updates for `pip` and `github-actions`. Expect PRs that bump the pinned actions. Merge them after CI passes.

### A11. CodeRabbit (`.coderabbit.yaml`)

- Sets `language: en-GB`, `profile: assertive`, `request_changes_workflow: true` and `poem: false`.
- Auto-reviews pull requests to `main`, but not drafts.
- Path filters exclude build output, `.venv`, weights, datasets, archives, lock files and `.claude/ipc`.
- Path instructions:
  - `**/*.py`: language rules, no hardcoded secrets or URLs, shape checks, cache rules, parameterised SQL, no raw exception text in the UI.
  - `.claude/**`: hook injection, hidden Unicode, model routing, `$CLAUDE_PROJECT_DIR` use, `jq` only.
  - `CLAUDE.md`: 110-line cap and deduplication.
  - `.github/**`: least privilege and pinned actions.

### A12. Git hygiene

| File | Content |
|---|---|
| `.gitignore` | Merge, do not overwrite: append to the standard Python template. Ignore `.venv/`, weights (`*.pt *.pth *.bin *.safetensors *.onnx`), `.env.*` with `!.env.example`, `.streamlit/secrets.toml` with `!...example`, archives, `data/`, `artefacts/`, `LOCAL_RUNBOOK.md`. Ignore only the Claude runtime state: `.claude/qa/`, `.claude/agent-memory/`, `.claude/ipc/`, `.claude/settings.local.json`, `.playwright-mcp/`. |
| `.gitattributes` | `*.sh text eol=lf`, `.claude/skills/** text eol=lf`, `skills-lock.json text eol=lf`. |
| `.dockerignore` | Same secret, data and weight exclusions, plus `.git`, `.claude`, `tests`, `docs`. |

### A13. Sustenance and maintenance

| Cadence | Action |
|---|---|
| Each change | `/orchestrate`, then `senior-commit` on a feature branch. Open a PR; CodeRabbit and CI review it. |
| After a PR merge | `git switch main && git pull --ff-only` before you push anything from `main`. Never force-push. |
| Weekly | Merge Dependabot PRs after CI passes. Re-pin MCP versions in `.mcp.json` by hand. |
| Monthly | `/governance-audit`, then `/promote-memory`. Re-check vendored skill SHAs and recompute `skills-lock.json` hashes. |
| Long jobs | Run in the background, save a checkpoint per unit of work, and keep the laptop on mains power. |

### A14. Deployment note

- Streamlit needs a persistent WebSocket, so it cannot run on Vercel serverless.
- Deploy the Docker image to Render (free plan; `render.yaml`, health check `/_stcore/health`).
- Point a subdomain at it with a CNAME record in your DNS (for example Vercel DNS).
- Free-tier services sleep when idle.

---

## Part B. Reusable setup prompt

Copy everything between the lines. Replace each `{PLACEHOLDER}`.

---

```text
MASTER SETUP PROMPT: Claude Code governance scaffold for {PROJECT_NAME}

Context
- Project: {ONE_PARAGRAPH_DESCRIPTION}.
- Stack: {LANGUAGE_AND_VERSION}, {FRAMEWORKS}, {DATABASE}, {UI}. Environment: Windows 11, virtual env at .venv (activate with .venv\Scripts\activate), package manager {uv|pip}.
- Language: British English and ASD-STE100 (active voice, imperative verbs, sentences under 20 words) in all docs, comments, commit messages and UI text. No emojis and no marketing adjectives in any file.
- Use free-tier services, open-weight models and OSS tools only.

Process
1. Start in Plan Mode. Read the repository first. Show a plan of 25 lines or fewer. Wait for my approval.
2. Merge with existing files; never overwrite them. Show me any conflict.
3. Work on branch chore/claude-governance-scaffold. Commit with the senior-commit skill. Do not push.

Preconditions (check them; stop and tell me if one fails)
- jq is installed and on PATH (winget install jqlang.jq, then restart the terminal). Hooks must still find it in %LOCALAPPDATA%\Microsoft\WinGet\Packages when PATH is stale.
- Git Bash is available, because hooks run with bash.
- Node.js is available for npx-based MCP servers.
- Project files are local, not OneDrive online-only placeholders.

Build these files

1. CLAUDE.md, 110 lines or fewer, six sections:
   (1) Project Scope and Stack, including targets and the pipeline order;
   (2) Language and Writing Standards;
   (3) Token Efficiency and Subagent Routing: scout with haiku, build with opus agents in their own paths, test and review with sonnet, never exceed high effort, query context7 before an unchecked API, invoke senior-commit before the final report;
   (4) Domain Style Rules for {DOMAIN};
   (5) Data and Architecture Rules: one config module, secrets from env or st.secrets only, no weights or datasets in git, numbered migrations;
   (6) Self-Governance. Copy section 6 exactly:
   "Before you add or modify any line in CLAUDE.md, execute this 4-step check: 1. Deduplication Check: verify the rule does not exist in .claude/settings.json, .mcp.json, .claude/agents/*.md, .claude/commands/*.md or .claude/skills/**/SKILL.md. 2. Token Cap: keep CLAUDE.md under 110 lines; compress or remove an obsolete rule before you add one. 3. STE100 Compression: write the change as one imperative sentence. 4. User Approval: show the exact diff and get confirmation before you write."

2. .claude/settings.json:
   - model opus and permissions.defaultMode plan.
   - Deny Read for ./.env, ./.env.local, ./.env.*.local, ./.streamlit/secrets.toml, ./**/secrets/**, ./**/*.pem, ./**/*.key, ./**/id_rsa*, ./**/id_ed25519*.
   - Do NOT deny ./.env* as a wildcard, because that blocks creating .env.example.
   - env: DISABLE_TELEMETRY=1, DISABLE_ERROR_REPORTING=1, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1, MAX_THINKING_TOKENS=16000.
   - statusLine, and the hooks below, each invoked as bash "$CLAUDE_PROJECT_DIR/.claude/hooks/<script>.sh".
   - Do not declare plugins that duplicate .mcp.json servers or vendored skills.
   Also add .claude/settings.local.json.example containing {}.

3. Hooks in .claude/hooks/. Each one starts with a header comment (event, purpose, exit codes), runs cd "$CLAUDE_PROJECT_DIR", sources _common.sh and parses JSON with jq only. Each one exits 2 to block, and blocks when jq is missing, except ipc-bus and statusline.
   - _common.sh: SECRET_RE covering Anthropic, OpenAI, Supabase sbp_, GitHub ghp_/github_pat_, AWS AKIA, Google AIza, Slack xox and PEM private keys. Also require_jq() with the winget fallback.
   - redact-prompt.sh (UserPromptSubmit): block a prompt with a secret.
   - block-secret-files.sh (PreToolUse Read|Grep|Glob|Bash|Edit|Write|NotebookEdit): block secret paths and secret content, but ALLOW *.example files.
   - safety-net.sh (PreToolUse Bash): block rm, rmdir, unlink, git clean, git reset --hard, force-push, git branch -D and git checkout -- . . Tell the user to run them manually; never work around the block.
   - scan-skill.sh (Pre/PostToolUse Edit|Write; "all" mode): find hidden Unicode (U+200B-200D, U+2060, U+FEFF, U+E0000-E007F) and injection phrases in .claude/skills. Run grep -P with LC_ALL=C.UTF-8.
   - guard-claude-md.sh (PreToolUse Edit|Write; --audit mode): enforce 110 lines and deduplication.
   - ipc-bus.sh (UserPromptSubmit sync, PreToolUse pre, PostToolUse post): use file locks in .claude/ipc, block on a lock younger than 3 minutes held by another session, and keep an event log. sync shows only events from the last 2 hours, at most 8 lines.
   - statusline.sh: print "<model> | $<cost> | <branch>", plus BUDGET above CLAUDE_BUDGET_USD (default 5).

4. .mcp.json, with pinned versions:
   - context7: cmd /c npx -y @upstash/context7-mcp@<pinned>.
   - playwright: cmd /c npx -y @playwright/mcp@<pinned> --headless.
   - {OPTIONAL} supabase: type http, url https://mcp.supabase.com/mcp?read_only=true&project_ref={REF}.
   On Windows, wrap every stdio server in cmd /c. Tell me to authorise HTTP servers once with /mcp.

5. Agents in .claude/agents/, each with frontmatter name, description ("PROACTIVELY use this agent ..."), model, tools, skills and memory: project. Each body lists its owned paths, its Definition of Done, and "Do not write to a live database, push or deploy without explicit user approval".
   - repo-scout (haiku, read-only, caveman).
   - {BUILDER_1} (opus), {BUILDER_2} (opus), {BUILDER_3} (opus), each with its own paths.
   - qa-cyber-ci-auditor (sonnet, playwright MCP, caveman).
   - academic-critic-docs (sonnet, stop-slop).
   Give the database MCP to the data agent only. After you create the agents, tell me to restart Claude Code so the agent types load.

6. .claude/knowledge/<agent>.md for each agent, with a header and the first repository map. .claude/agent-memory/ stays gitignored.

7. Commands in .claude/commands/:
   - /orchestrate (four stages: plan and stop; contracts; parallel builders; QA with one fix loop, docs review, senior-commit).
   - /governance-audit (report only).
   - /promote-memory.
   - /sync-content.

8. Skills in .claude/skills/<name>/SKILL.md:
   - Local: caveman, stop-slop, senior-commit, plus domain skills {DOMAIN_SKILLS}.
   - senior-commit: Conventional Commits; subject of 72 characters or fewer; stage files by name (never git add . or -A); never stage .env, secrets, weights, datasets, archives or .claude/ipc; no AI or Co-Authored-By trailers; no emojis; no push unless asked.
   - Vendor external skills only from a pinned commit SHA.
   - Write skills-lock.json with source, ref, path and the sha256 of each SKILL.md. Run scan-skill.sh all after.

9. .gitattributes: *.sh, .claude/skills/** and skills-lock.json as text eol=lf.

10. .gitignore: merge into the existing file. Add .venv/, weights, .env.* with !.env.example, secrets.toml with !secrets.toml.example, archives, data/, artefacts/, LOCAL_RUNBOOK.md, and the Claude runtime state only (.claude/qa/, .claude/agent-memory/, .claude/ipc/, .claude/settings.local.json, .playwright-mcp/). Commit the rest of .claude/.

11. .github/workflows/ci.yml:
   - Triggers: push and PR to main. permissions contents: read. A concurrency group with cancel-in-progress. Pinned action versions.
   - Job checks: checkout (fetch-depth 0); gitleaks CLI with a verified sha256 (not gitleaks-action); a regex secret scan with the same SECRET_RE; setup-python with the pip cache; install with "python -m pip install --upgrade pip 'setuptools>=83.0.0'" FIRST (the runner's setuptools fails pip-audit), then torch from the CPU index if needed; pip-audit --skip-editable; bandit (fail medium+, warn low, document each skip); ruff; mypy; pytest; compileall; app boot and Playwright smoke test; upload artefacts on failure.
   - Job governance: guard-claude-md.sh --audit and scan-skill.sh all.

12. .github/dependabot.yml: weekly updates for pip and github-actions.

13. .coderabbit.yaml:
   - language en-GB, profile assertive, request_changes_workflow true, poem false. Auto-review PRs to main, but not drafts.
   - path_filters exclude build output, .venv, weights, data, archives, lock files and .claude/ipc.
   - path_instructions for **/*.py, .claude/**, CLAUDE.md and .github/** (as in the Recommal file).

14. Templates: .env.example and .streamlit/secrets.toml.example, with variable names and no values. Keep one mapping of env names in the config module, and add a test that the names match the template.

15. LOCAL_RUNBOOK.md (gitignored): .env names and where to get each value, run commands, recovery steps.

Verification (run each one and report PASS or FAIL)
- jq --version.
- bash -n on every hook.
- Hooks are LF.
- Each hook blocks a test secret and allows a clean input.
- .env.example is creatable.
- safety-net blocks "rm -rf x".
- guard-claude-md.sh --audit passes.
- scan-skill.sh all passes.
- skills-lock.json hashes match.
- CLAUDE.md is 110 lines or fewer.
- JSON and YAML files parse.
- No secret pattern exists in tracked files.
- git check-ignore confirms that .env, weights and .claude/ipc are ignored and that .claude/agents is not.
- Tests, lint and typecheck pass.

Final report
- List the files created and merged, the verification table and the manual actions left for me: authorise MCP servers, restart Claude Code, create .env, enable CodeRabbit on the repository.
- Then commit with senior-commit.

Standing rules for later sessions
- Never write to a live database, push or deploy without my explicit approval.
- After a PR merges, run git pull --ff-only on main before pushing from it. Never force-push.
- Run long jobs in the background with a checkpoint per unit of work.
- Report failures with their output. Do not claim a target is met unless a measured number shows it.
```
