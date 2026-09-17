#!/usr/bin/env bash
# Apply the prepared changes to an Aegis checkout, in order, one marker per step.
#   .aegis/changes/universal-01/apply_all.sh <repository-root> [last-step]
# A step whose marker exists is skipped: steps 1-3 landed in TASK-UNBLOCK-02 and were extended
# there, so re-running their patches would compare against text that has since moved on.
set -euo pipefail
ROOT="$(cd "${1:?usage: apply_all.sh <repository-root> [last-step]}" && pwd)"
LAST="${2:-5}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export AEGIS_PATCH_ROOT="$ROOT"
cd "$ROOT"
markers="$ROOT/.aegis/changes/universal-01.applied.d"
mkdir -p "$markers"

step() {  # step <n> <title> <function>
  local n="$1" title="$2" fn="$3"
  if [ "$n" -gt "$LAST" ]; then return 0; fi
  if [ -f "$markers/step-$n" ]; then echo "== $n. $title — already applied ($(cat "$markers/step-$n"))"; return 0; fi
  echo "== $n. $title"
  "$fn"
  date -u +%Y-%m-%dT%H:%M:%SZ > "$markers/step-$n"
}

s1() { python3 "$HERE/patch_round3_advisory.py"; }
s2() { python3 "$HERE/patch_hook_simplify.py"; python3 "$HERE/tests_hook_simplify.py"; }
s3() { python3 "$HERE/patch_round3_security.py"; python3 "$HERE/tests_round3_security.py"; }
s4() {
  python3 "$HERE/patch_lenses.py"
  grep -q "class LensesAreData" tests/test_aegis.py || cat "$HERE/tests_lenses.py" >> tests/test_aegis.py
  python3 "$HERE/patch_lenses_tests_existing.py"
  python3 "$HERE/patch_lenses_docs.py"
}
s5() {
  python3 "$HERE/patch_task2.py"
  grep -q "class DetectionDeclarationsAreHonest" tests/test_aegis.py || cat "$HERE/tests_task2.py" >> tests/test_aegis.py
  python3 "$HERE/patch_task2_docs.py"
}

step 1 "design advisories (TASK-UNBLOCK-01 round 3)" s1
step 2 "commit hook: exact bookkeeping match" s2
step 3 "security round 3" s3
step 4 "ADR-3: lenses, roles, engines as data" s4
step 5 "B2: honesty, tests-ran, spec markers, adapters, delta packet" s5

echo "== verify syntax"
python3 -m compileall -q scripts/aegis/aegis_cli
for f in hooks/pre-commit-gate.sh hooks/protect-paths.sh scripts/aegis/external-lens.sh scripts/aegis/codex-lens.sh; do
  if [ -f "$f" ]; then bash -n "$f"; fi
done
node -e 'const fs=require("fs");const s=fs.readFileSync("workflows/aegis-task.js","utf8").replace(/^export const meta/m,"const meta");const A=Object.getPrototypeOf(async function(){}).constructor;new A("args","agent","parallel","pipeline","phase","log",s);'
echo "== migrate (recompile, refresh protocol copies)"; ./scripts/aegis/aegis migrate
echo "applied through step $LAST"
