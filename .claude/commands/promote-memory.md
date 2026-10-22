---
description: Propose durable agent memory lessons for the committed knowledge files.
---

1. For each agent in `repo-scout`, `streamlit-ui-builder`, `ml-data-pipeline` and `qa-auditor`:
   - Read `.claude/agent-memory/<agent>/MEMORY.md` and the files that it links. Skip agents with no memory.
   - Read `.claude/knowledge/<agent>.md`.
2. Select only lessons that are durable and not obvious from the code, git history or `CLAUDE.md`.
3. Reject secrets, personal data, session-only state and duplicates of existing knowledge.
4. Show one unified diff for each `.claude/knowledge/<agent>.md` file.
5. Stop. Wait for user approval.
6. Apply only the approved diffs. Do not edit the raw memory files.
