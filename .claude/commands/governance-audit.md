---
description: Audit the Claude Code governance scaffold. Report only; change nothing.
---

Do not edit any file. Run each check and report one line each: `PASS`, `WARN` or `FAIL`.

1. CLAUDE.md size and duplicates: run `bash "$CLAUDE_PROJECT_DIR/.claude/hooks/guard-claude-md.sh" --audit`.
2. Skill safety: run `bash "$CLAUDE_PROJECT_DIR/.claude/hooks/scan-skill.sh" all`.
3. Unpinned skills: list each folder in `.claude/skills/` that has no entry in `skills-lock.json`. Recompute the sha256 of each `SKILL.md` and compare it with `computedHash`.
4. Hook wiring: list each `.claude/hooks/*.sh` file (except `_common.sh`) that `.claude/settings.json` does not reference.
5. Stale locks: list each file in `.claude/ipc/locks/` with a `ts` older than 180 seconds.
6. Agent routing: confirm `repo-scout` uses haiku, `qa-cyber-ci-auditor` and `academic-critic-docs` use sonnet, and `ml-research-architect`, `data-db-optimiser` and `streamlit-ui-ux` use opus.
7. Report the total of PASS, WARN and FAIL results on the last line.
