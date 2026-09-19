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

# Before the payload is read: a project with no `.aegis/` is not governed by Aegis. Reading
# first meant that in such a project — a plugin installed globally, another checkout in the
# same session — a missing python3 refused every write in the name of a framework that was
# not there. A hook that cannot check refuses; a hook with nothing to check is silent.
root="${CLAUDE_PROJECT_DIR:-$PWD}"
[ -d "$root/.aegis" ] || exit 0

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

if [ -z "$path" ]; then
  # An empty path means the payload parsed to nothing — no python3, or a shape this hook does
  # not know. A hook that cannot read what it is judging refuses, like the git hooks.
  command -v python3 >/dev/null 2>&1 || {
    echo "Aegis cannot check this write: python3 is not on PATH, so the tool payload cannot be read." >&2
    exit 2
  }
  # python3 is here and the payload still yielded nothing: the matcher is `Edit|Write|
  # NotebookEdit`, all of which carry a path, so this is a shape the hook has not seen. Refuse
  # only while a task is focused, which is the only time there is a lease to enforce. Refusing
  # unconditionally would turn any change in the tool payload into "no agent may write
  # anywhere"; refusing never would leave the enforced case to a shape nobody has checked.
  if [ -f "$root/.aegis/runs/ACTIVE" ]; then
    echo "Aegis cannot check this write: the tool payload carries no file path, and a task holds a write lease." >&2
    echo "Release the lease to work as the orchestrator, or report the payload shape — a lease that cannot be checked is not a lease." >&2
    exit 2
  fi
  exit 0
fi

aegis="${CLAUDE_PLUGIN_ROOT:-$root}/scripts/aegis/aegis"
[ -x "$aegis" ] || {
  echo "Aegis cannot check this write: the CLI is not at $aegis. A hook that cannot check refuses; run ./install.sh or fix CLAUDE_PLUGIN_ROOT." >&2
  exit 2
}

if reason="$("$aegis" --root "$root" lease check --path "$path" 2>&1)"; then
  exit 0
fi
printf '%s\n' "$reason" >&2
exit 2
