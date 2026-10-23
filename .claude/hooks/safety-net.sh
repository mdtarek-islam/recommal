#!/usr/bin/env bash
# Event: PreToolUse (Bash).
# Purpose: Block destructive shell commands. The user must run them manually.
# Exit codes: 0 = allow, 2 = block (destructive command or jq missing).
cd "$CLAUDE_PROJECT_DIR" || exit 2
. "$CLAUDE_PROJECT_DIR/.claude/hooks/_common.sh"
require_jq || exit 2

DANGER_RE='\brm\b|\brmdir\b|\bunlink\b|git clean|git reset --hard|git push (-f|--force)|git branch -D|git checkout -- \.'

cmd=$(cat | jq -r '.tool_input.command // ""')

if printf '%s' "$cmd" | grep -Eq -e "$DANGER_RE"; then
  {
    echo "Blocked: destructive command."
    printf 'Command: %s\n' "$cmd"
    echo "Tell the user to run this command manually if it is necessary."
  } >&2
  exit 2
fi
exit 0
