---
name: caveman
description: Compress agent output to save tokens. Use for scout reports, QA summaries and status updates that another agent reads.
---

# Caveman output mode

Write the shortest output that keeps every fact.

## Rules

1. Drop greetings, preambles, recaps and closing offers.
2. Drop articles and filler words when the meaning stays clear.
3. Use fragments. Use `file:line` instead of prose locations.
4. Use one line for each finding. Put the verdict first: `PASS`, `FAIL`, `WARN`.
5. Keep code, paths, commands, numbers and error text exact. Do not compress them.
6. Do not drop a caveat that changes a decision.

## Example

Before: "I have looked through the repository and it seems that the Streamlit entry point is located in app.py at the root."

After: `entry: app.py (root)`
