#!/usr/bin/env bash
# Event: PreToolUse and PostToolUse (Edit|Write). Also runs manually.
# Purpose: Scan skill files for hidden Unicode and prompt-injection patterns.
# Modes: no argument = pre (scan skills and the incoming text), post = scan the written file,
#        all = scan every skill file without stdin.
# Exit codes: 0 = clean or not a skill path, 2 = finding (or jq missing).
cd "$CLAUDE_PROJECT_DIR" || exit 2
. "$CLAUDE_PROJECT_DIR/.claude/hooks/_common.sh"

mode="${1:-pre}"
SKILLS_DIR="$CLAUDE_PROJECT_DIR/.claude/skills"
UNICODE_RE='[\x{200B}-\x{200D}\x{2060}\x{FEFF}\x{E0000}-\x{E007F}]'
INJECT_RE='ignore (all )?previous instructions|system prompt override|curl[^|]*\|\s*(ba)?sh|wget[^|]*\|\s*(ba)?sh|eval\(atob|nc -e|base64 -d\s*\|'

findings=""

# Scan one file. Add each finding to $findings.
scan_file() {
  local f="$1" label="$2"
  if LC_ALL=C.UTF-8 grep -qP "$UNICODE_RE" "$f" 2>/dev/null; then
    findings+="hidden Unicode: $label"$'\n'
  fi
  if grep -qiE -e "$INJECT_RE" "$f" 2>/dev/null; then
    findings+="injection pattern: $label ($(grep -niE -e "$INJECT_RE" "$f" | head -1 | cut -c1-120))"$'\n'
  fi
}

scan_all() {
  [ -d "$SKILLS_DIR" ] || return 0
  while IFS= read -r f; do
    scan_file "$f" "$(rel_path "$f")"
  done < <(find "$CLAUDE_PROJECT_DIR/.claude/skills" -type f \( -name '*.md' -o -name '*.sh' -o -name '*.py' -o -name '*.js' -o -name '*.ts' \))
}

report() {
  if [ -n "$findings" ]; then
    echo "Blocked: skill scan found unsafe content." >&2
    printf '%s' "$findings" >&2
    exit 2
  fi
  exit 0
}

if [ "$mode" = "all" ]; then
  scan_all
  report
fi

require_jq || exit 2
input=$(cat)
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // ""')
case "$(norm_path "$file_path")" in
  .claude/skills/*|*/.claude/skills/*) ;;
  *) exit 0 ;;
esac

if [ "$mode" = "post" ]; then
  [ -f "$file_path" ] && scan_file "$file_path" "$(rel_path "$file_path")"
  report
fi

# Pre mode: scan the current skill tree and the text that the tool will write.
scan_all
tmp=$(mktemp)
printf '%s' "$input" | jq -r '.tool_input | (.content // .new_string // "")' > "$tmp"
scan_file "$tmp" "incoming text for $(rel_path "$file_path")"
rm -f "$tmp"
report
