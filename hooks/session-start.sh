#!/usr/bin/env bash
# Re-establish where the work stands. A resumed or compacted session has no memory of the
# task it was in the middle of; this is the cheapest way to give it back.
set -uo pipefail

root="${CLAUDE_PROJECT_DIR:-$PWD}"
[ -d "$root/.aegis" ] || exit 0

aegis="${CLAUDE_PLUGIN_ROOT}/scripts/aegis/aegis"
[ -x "$aegis" ] || exit 0

echo "--- Aegis ---"
"$aegis" --root "$root" status 2>/dev/null || true
notes="$root/.aegis/memory/NOTES.md"
[ -f "$notes" ] && echo "  working notes: .aegis/memory/NOTES.md"
echo "  read .aegis/generated/index/INDEX.md before searching the repository"
exit 0
