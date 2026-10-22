#!/usr/bin/env bash
# Event: PreToolUse (Edit|Write). Also runs in CI and /governance-audit with --audit.
# Purpose: Keep CLAUDE.md at 110 lines or fewer and free of rules that other config files hold.
# Modes: no argument = check the pending Edit or Write on stdin,
#        --audit = check every line of the current CLAUDE.md without stdin.
# Exit codes: 0 = allow, 2 = block (over the cap, duplicate rule or jq missing).
cd "$CLAUDE_PROJECT_DIR" || exit 2
. "$CLAUDE_PROJECT_DIR/.claude/hooks/_common.sh"

MAX_LINES=110
DEDUP_PATHS=(.claude/agents .claude/skills .claude/commands .claude/settings.json)

# Block when a line longer than 30 characters already exists in another config file.
check_dedup() {
  local line trimmed hit
  while IFS= read -r line; do
    trimmed=$(printf '%s' "$line" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')
    [ "${#trimmed}" -gt 30 ] || continue
    hit=$(grep -rFl -- "$trimmed" "${DEDUP_PATHS[@]}" 2>/dev/null | head -1)
    if [ -n "$hit" ]; then
      echo "Blocked: CLAUDE.md duplicates a rule that $hit already holds:" >&2
      printf '  %s\n' "$trimmed" >&2
      exit 2
    fi
  done <<< "$1"
}

check_cap() {
  if [ "$1" -gt "$MAX_LINES" ]; then
    echo "Blocked: CLAUDE.md would have $1 lines. The limit is $MAX_LINES. Compress or remove a rule first." >&2
    exit 2
  fi
}

if [ "${1:-}" = "--audit" ]; then
  [ -f CLAUDE.md ] || { echo "CLAUDE.md is missing." >&2; exit 2; }
  check_cap "$(count_lines "$(cat CLAUDE.md)")"
  check_dedup "$(cat CLAUDE.md)"
  echo "CLAUDE.md audit passed: $(count_lines "$(cat CLAUDE.md)") lines, no duplicate rules."
  exit 0
fi

require_jq || exit 2
input=$(cat)
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // ""')
case "$(norm_path "$file_path")" in
  *claude.md) ;;
  *) exit 0 ;;
esac

tool=$(printf '%s' "$input" | jq -r '.tool_name // ""')
current=""
[ -f "$file_path" ] && current=$(cat "$file_path")

if [ "$tool" = "Write" ]; then
  new_text=$(printf '%s' "$input" | jq -r '.tool_input.content // ""')
  total=$(count_lines "$new_text")
  added=$(grep -vxF -f <(printf '%s\n' "$current") <<< "$new_text" || true)
else
  old_text=$(printf '%s' "$input" | jq -r '.tool_input.old_string // ""')
  new_text=$(printf '%s' "$input" | jq -r '.tool_input.new_string // ""')
  total=$(( $(count_lines "$current") - $(count_lines "$old_text") + $(count_lines "$new_text") ))
  added=$(grep -vxF -f <(printf '%s\n' "$old_text") <<< "$new_text" || true)
fi

check_cap "$total"
check_dedup "$added"
exit 0
