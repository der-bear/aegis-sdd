#!/usr/bin/env bash
# Refuse a write outside the focused task's lease.
#
# This is the difference between "the builder should stay inside its lease" and "the builder
# cannot leave it". Without this, exclusivity is a sentence in a prompt, and a prompt is not
# an invariant — the collision it prevents is discovered at merge, if at all.
#
# Inert when no task is focused, so the orchestrator and a human work unrestricted.
# There is deliberately no environment-variable override: an unauthenticated one
# disables the check for anything that can set a variable, which is everything.
set -uo pipefail

payload="$(cat)"
path="$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    print(""); raise SystemExit
inp = data.get("tool_input") or {}
print(inp.get("file_path") or inp.get("notebook_path") or "")
' 2>/dev/null)"

[ -n "$path" ] || exit 0

root="${CLAUDE_PROJECT_DIR:-$PWD}"
[ -d "$root/.aegis" ] || exit 0
aegis="${CLAUDE_PLUGIN_ROOT:-$root}/scripts/aegis/aegis"
[ -x "$aegis" ] || exit 0

if reason="$("$aegis" --root "$root" lease check --path "$path" 2>&1)"; then
  exit 0
fi
printf '%s\n' "$reason" >&2
exit 2
