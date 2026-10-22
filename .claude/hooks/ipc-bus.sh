#!/usr/bin/env bash
# Event: UserPromptSubmit (sync), PreToolUse Edit|Write (pre), PostToolUse Edit|Write (post).
# Purpose: Coordinate parallel Claude sessions with file locks and a shared event log.
#   pre  = lock the target file; block when another session holds a lock younger than 3 minutes.
#   post = release the lock and log the update.
#   sync = give the recent events to Claude as additional context.
# Exit codes: 0 = allow, 2 = block (file locked by another session).
# A missing jq does not block. This script coordinates work; it does not enforce security.
cd "$CLAUDE_PROJECT_DIR" || exit 0
. "$CLAUDE_PROJECT_DIR/.claude/hooks/_common.sh"
require_jq || exit 0

mode="${1:-sync}"
IPC_DIR="$CLAUDE_PROJECT_DIR/.claude/ipc"
LOCK_DIR="$IPC_DIR/locks"
EVENTS="$IPC_DIR/events.log"
BOARD="$IPC_DIR/board.json"
LOCK_TTL=180
mkdir -p "$LOCK_DIR"
touch "$EVENTS"

input=$(cat)
session=$(printf '%s' "$input" | jq -r '.session_id // "unknown"')

write_board() {
  jq -n --rawfile events "$EVENTS" --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{updated_at: $now, recent_events: ($events | split("\n") | map(select(. != "")))}' > "$BOARD"
}

if [ "$mode" = "sync" ]; then
  [ -s "$EVENTS" ] || exit 0
  context=$( { echo "Recent file updates from Claude sessions in this project:"; cat "$EVENTS"; } | jq -Rs .)
  printf '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":%s}}\n' "$context"
  exit 0
fi

file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // ""')
[ -n "$file_path" ] || exit 0
key=$(norm_path "$file_path" | sha1sum | cut -d' ' -f1)
lock="$LOCK_DIR/$key.json"
now=$(date +%s)

if [ "$mode" = "pre" ]; then
  if [ -f "$lock" ]; then
    owner=$(jq -r '.session_id // ""' "$lock" 2>/dev/null)
    ts=$(jq -r '.ts // 0' "$lock" 2>/dev/null)
    if [ -n "$owner" ] && [ "$owner" != "$session" ] && [ $(( now - ts )) -lt "$LOCK_TTL" ]; then
      echo "Blocked: session ${owner:0:8} edits $(rel_path "$file_path") now. Try again in $(( LOCK_TTL - (now - ts) )) seconds." >&2
      exit 2
    fi
  fi
  jq -n --arg s "$session" --arg p "$(rel_path "$file_path")" --argjson t "$now" \
    '{session_id: $s, path: $p, ts: $t}' > "$lock"
  exit 0
fi

if [ "$mode" = "post" ]; then
  rm -f "$lock"
  printf '[%s] %s updated %s\n' "$(date +%H:%M:%S)" "${session:0:8}" "$(rel_path "$file_path")" >> "$EVENTS"
  tail -n 8 "$EVENTS" > "$EVENTS.tmp" && mv -f "$EVENTS.tmp" "$EVENTS"
  write_board
  exit 0
fi
exit 0
