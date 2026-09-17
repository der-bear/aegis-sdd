#!/usr/bin/env bash
# Run the deterministic gate before a commit or push reaches the repository.
#
# The commit is the right interception point. A per-edit hook fires constantly and catches
# nothing a gate would not, while the commit is the moment work claims to be finished.
#
# Deterministic checks only (--no-run): drift, registries, environment coverage, task
# ownership, requirement coverage, documentation freshness, budgets. Test suites belong to
# the task gate and to CI, not to every commit.
set -uo pipefail

payload="$(cat)"
command_text="$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    print((json.load(sys.stdin).get("tool_input") or {}).get("command", ""))
except Exception:
    print("")
' 2>/dev/null)"

# Cheap pre-filter: only a command mentioning commit or push is worth a Python start-up.
case "$command_text" in
  *commit*|*push*) ;;
  *) exit 0 ;;
esac

root="${CLAUDE_PROJECT_DIR:-$PWD}"
[ -d "$root/.aegis" ] || exit 0

aegis="${CLAUDE_PLUGIN_ROOT}/scripts/aegis/aegis"
[ -x "$aegis" ] || exit 0

# `aegis commit-scope` decides: none (not a git commit or push), exempt (exactly the workflow's
# bookkeeping commit), gate (anything else). An empty answer — the CLI failed — runs the gate.
scope="$(printf '%s' "$command_text" | "$aegis" --root "$root" commit-scope 2>/dev/null)"
case "$scope" in
  none|exempt) exit 0 ;;
esac

if output="$("$aegis" --root "$root" gate --stage merge --no-run 2>&1)"; then
  exit 0
fi

{
  echo "Aegis gate failed — this commit would leave the project inconsistent."
  printf '%s\n' "$output" | tail -30
  echo
  echo "Fix the findings above. The only exempt command is the bookkeeping commit:"
  echo "  git commit -q -m \"chore(<TASK>): task manifest\" -- .aegis/runs/<TASK>"
  echo "A switch anyone can set would be the absence of a gate."
} >&2
exit 2
