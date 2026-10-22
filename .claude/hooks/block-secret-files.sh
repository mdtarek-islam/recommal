#!/usr/bin/env bash
# Event: PreToolUse (Read|Grep|Glob|Bash|Edit|Write|NotebookEdit).
# Purpose: Block access to secret files and block tool input that contains a secret.
# Exit codes: 0 = allow, 2 = block (secret path, secret content or jq missing).
cd "$CLAUDE_PROJECT_DIR" || exit 2
. "$CLAUDE_PROJECT_DIR/.claude/hooks/_common.sh"
require_jq || exit 2

PATH_RE='(^|[/\\ ])\.env(\.[A-Za-z0-9_-]+)?($|[ "'"'"'])|\.streamlit/secrets\.toml|secrets/|id_rsa|id_ed25519|\.pem$|\.key$'

input=$(cat)
targets=$(printf '%s' "$input" | jq -r '.tool_input // {}
  | [.file_path, .notebook_path, .path, .pattern, .command]
  | map(select(type == "string" and . != "")) | .[]')

# Remove the allowed example files, then test what is left.
checked=$(printf '%s\n' "$targets" | tr '\\' '/' \
  | sed -e 's#secrets\.toml\.example##g' -e 's#\.env\.example##g')

if printf '%s\n' "$checked" | grep -Eq -e "$PATH_RE"; then
  echo "Blocked: the tool call targets a secret file (.env, secrets.toml, keys)." >&2
  echo "Use .env.example or .streamlit/secrets.toml.example for templates." >&2
  exit 2
fi

if printf '%s' "$input" | jq -r '.tool_input // {} | tostring' | grep -Eq -e "$SECRET_RE"; then
  echo "Blocked: the tool input contains a secret value. Read secrets from environment variables." >&2
  exit 2
fi
exit 0
