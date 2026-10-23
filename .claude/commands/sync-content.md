---
description: Apply docs/context/updates.yaml to the single configuration module and verify.
---

1. Read only `docs/context/updates.yaml`. Do not scan other files for context.
2. If `changes` is empty, report "No updates" and stop.
3. Apply each change to the single configuration module that `CLAUDE.md` names. If the module does not exist, stop and report.
4. If a change touches a model parameter (`model.*`) or a schema parameter (`schema.*`), call `ml-research-architect` (model) or `data-db-optimiser` (schema) to update the dependent code.
5. Call `qa-cyber-ci-auditor`.
6. Report the result in under 40 words.
