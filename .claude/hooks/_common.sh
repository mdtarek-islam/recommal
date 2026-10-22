#!/usr/bin/env bash
# Event: none. Other hook scripts source this file.
# Purpose: Define the shared secret regex, path helpers and the jq lookup.
# Exit codes: none. The caller decides the exit code.

SECRET_RE='sk-ant-[A-Za-z0-9_-]{15,}|sk-(proj-)?[A-Za-z0-9]{20,}|sbp_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|xox[baprs]-[0-9A-Za-z-]{10,}|-----BEGIN [A-Z ]+PRIVATE KEY-----'

# Find jq. Fall back to the winget package folder when PATH is stale.
require_jq() {
  command -v jq >/dev/null 2>&1 && return 0
  local base c
  base=$(cygpath -u "${LOCALAPPDATA:-}" 2>/dev/null || printf '%s' "${LOCALAPPDATA:-}")
  for c in "$base"/Microsoft/WinGet/Packages/jqlang.jq_*/jq.exe; do
    if [ -x "$c" ]; then PATH="$(dirname "$c"):$PATH"; return 0; fi
  done
  echo "jq is missing. Install it: winget install jqlang.jq, brew install jq, or apt install jq." >&2
  return 1
}

# Print a path with forward slashes and in lowercase.
norm_path() {
  printf '%s' "$1" | tr '\\' '/' | tr '[:upper:]' '[:lower:]'
}

# Print a path relative to the project root. Keep the input when it is outside the root.
rel_path() {
  local p root
  p=$(printf '%s' "$1" | tr '\\' '/')
  root=$(printf '%s' "$CLAUDE_PROJECT_DIR" | tr '\\' '/')
  case "$(norm_path "$p")" in
    "$(norm_path "$root")"/*) printf '%s' "${p:${#root}+1}" ;;
    *) printf '%s' "$p" ;;
  esac
}

# Count lines. Count a last line that has no newline.
count_lines() {
  printf '%s' "$1" | awk 'END { print NR }'
}
