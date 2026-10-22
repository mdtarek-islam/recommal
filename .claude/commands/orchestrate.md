---
description: Plan, build and verify a change with the Recommal subagents in four stages.
argument-hint: <task description>
---

Run this task through the subagents: $ARGUMENTS

1. Stage 1, plan (read-only):
   - Call `repo-scout` to map the files and owners for the task.
   - Query context7 for each library API that the plan uses.
   - Show a plan of 15 lines or fewer. List the files for each agent.
   - Stop. Wait for user approval.
2. Stage 2, foundation:
   - Call one agent for shared work first: schema, config or data contracts go to `ml-data-pipeline`; shared UI state goes to `streamlit-ui-builder`.
3. Stage 3, parallel build:
   - Call `streamlit-ui-builder` and `ml-data-pipeline` in parallel.
   - Give each agent a list of folders that does not overlap with the other list.
4. Stage 4, verify:
   - Call `qa-auditor`. If a check fails, send the failure to the owner agent once, then call `qa-auditor` again.
5. Report the result in 10 lines or fewer, then invoke `senior-commit`.
