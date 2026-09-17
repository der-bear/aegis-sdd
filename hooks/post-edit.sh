#!/usr/bin/env bash
# Path-keyed validation after an edit. Runs only the check the touched path can break.
#
# Gates that live outside the routine path get skipped exactly when they matter, so
# selection is mechanical here rather than something an agent has to remember.
set -uo pipefail

payload="$(cat)"
path="$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    print((json.load(sys.stdin).get("tool_input") or {}).get("file_path", ""))
except Exception:
    print("")
' 2>/dev/null)"

[ -n "$path" ] || exit 0
root="${CLAUDE_PROJECT_DIR:-$PWD}"
aegis="${CLAUDE_PLUGIN_ROOT}/scripts/aegis/aegis"
[ -x "$aegis" ] && [ -d "$root/.aegis" ] || exit 0

case "$path" in
  */.aegis/registry/*.json)  "$aegis" --root "$root" check registry ;;
  */interview/*.json)        "$aegis" --root "$root" check banks ;;
  */.aegis/answers.json)     "$aegis" --root "$root" check drift ;;
  */SKILL.md|*/agents/*.md)  "$aegis" --root "$root" check budget ;;
  *) exit 0 ;;
esac
