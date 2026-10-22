---
name: senior-commit
description: Commit work with Conventional Commits. Use before every final report that changes files.
---

# Senior commit

## Procedure

1. Run `git status --short` and `git diff --stat`. Read the change list.
2. If the current branch is `main`, create a branch first: `git switch -c <type>/<short-kebab-topic>`.
3. Stage each file by name: `git add path/one path/two`. Do not use `git add .`, `git add -A` or `git commit -a`.
4. Do not stage `.env*`, `.streamlit/secrets.toml`, model weights, datasets, archives or `.claude/ipc/`.
5. Run `git diff --cached --stat` and confirm the staged list matches the intent.
6. Write the message in Conventional Commits format:
   - Subject: `<type>(<scope>): <imperative summary>`, 72 characters or fewer, no full stop.
   - Types: feat, fix, refactor, perf, test, docs, build, ci, chore.
   - Body: wrap at 72 characters. State what changed and why, in British English and ASD-STE100.
7. Do not add AI attribution trailers. Do not add `Co-Authored-By` lines that name an AI tool.
8. Do not add emojis.
9. Commit with a heredoc so that the message keeps its line breaks.
10. Do not push unless the user asks.
11. Report the branch, the commit hash and the subject line.
