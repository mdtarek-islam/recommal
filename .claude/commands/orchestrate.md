---
description: Plan, build and verify a change with the six-agent Recommal office in four stages.
argument-hint: <task description>
---

Run this task through the office: $ARGUMENTS

1. Stage 1, plan (read-only):
   - Call `repo-scout` to map the files and owners for the task.
   - Query context7 for each library API that the plan uses.
   - Show a plan of 15 lines or fewer. List the files for each agent.
   - Stop. Wait for user approval.
2. Stage 2, foundation:
   - Call one agent for shared contracts first: data and schema go to `data-db-optimiser`; model and config go to `ml-research-architect`.
3. Stage 3, parallel build:
   - Call `ml-research-architect`, `data-db-optimiser` and `streamlit-ui-ux` in parallel.
   - Give each agent only its own paths from `CLAUDE.md` section 3.
4. Stage 4, verify and review:
   - Call `qa-cyber-ci-auditor`. If a check fails, send the failure to the owner agent once, then call `qa-cyber-ci-auditor` again.
   - Call `academic-critic-docs` to review methodology and update the docs.
5. Report the result in 10 lines or fewer, then invoke `senior-commit`.
