#!/usr/bin/env bash
# Event: statusLine.
# Purpose: Print "<model> | $<cost> | <git branch>". Add BUDGET when the cost passes CLAUDE_BUDGET_USD (default 5).
# Exit codes: 0 always. This script writes no state files.
cd "$CLAUDE_PROJECT_DIR" 2>/dev/null || true
. "$CLAUDE_PROJECT_DIR/.claude/hooks/_common.sh" 2>/dev/null
if ! require_jq 2>/dev/null; then echo "statusline: install jq"; exit 0; fi

input=$(cat)
model=$(printf '%s' "$input" | jq -r '.model.display_name // "unknown"')
cost=$(printf '%s' "$input" | jq -r '.cost.total_cost_usd // 0')
branch=$(git branch --show-current 2>/dev/null)
budget="${CLAUDE_BUDGET_USD:-5}"

line=$(printf '%s | $%.2f | %s' "$model" "$cost" "${branch:-no-branch}")
if awk -v c="$cost" -v b="$budget" 'BEGIN { exit !(c > b) }'; then
  line="$line | BUDGET"
fi
printf '%s\n' "$line"
