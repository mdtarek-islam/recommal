#!/usr/bin/env bash
# Event: UserPromptSubmit.
# Purpose: Block a prompt that contains a secret. Print a redacted copy to stderr.
# Exit codes: 0 = allow, 2 = block (secret found or jq missing).
cd "$CLAUDE_PROJECT_DIR" || exit 2
. "$CLAUDE_PROJECT_DIR/.claude/hooks/_common.sh"
require_jq || exit 2

input=$(cat)
prompt=$(printf '%s' "$input" | jq -r '.prompt // ""')

if printf '%s' "$prompt" | grep -Eq -e "$SECRET_RE"; then
  redacted=$(printf '%s' "$prompt" | sed -E "s/$SECRET_RE/[REDACTED]/g")
  {
    echo "Blocked: the prompt contains a secret. Remove it and send the prompt again."
    echo "Redacted prompt:"
    printf '%s\n' "$redacted"
  } >&2
  exit 2
fi
exit 0
