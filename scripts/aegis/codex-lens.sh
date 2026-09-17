#!/usr/bin/env bash
# Run a review lens on Codex and record it like any other lens.
#
# This is what makes "builder ≠ final reviewer" literal rather than aspirational: the
# reviewer is a different engine, not a different context of the same one. The report goes
# through `aegis lens record`, so it gets the same schema, the same diff binding and the same
# per-lens reconciliation as a Claude lens. Two engines word the same defect differently, so
# their findings do not collapse to one id; a person reads both.
#
#   scripts/aegis/codex-lens.sh <TASK-ID> <lens> [model]
#
# Requires the `codex` CLI. Everything it needs about how to review lives in the protocol
# file, which is the same file the Claude lens is given.
set -euo pipefail

task="${1:?usage: codex-lens.sh <TASK-ID> <security|correctness|design> [model]}"
lens="${2:?lens name}"
model="${3:-gpt-5.6-sol}"

plugin="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# The project being reviewed and the framework are different directories in every real
# installation; conflating them sent the script looking for the CLI inside the project.
root="$plugin"
[ -d "$PWD/.aegis" ] && root="$PWD"
aegis="$(command -v aegis || echo "$plugin/scripts/aegis/aegis")"

protocol="$root/.aegis/protocols/review-lens.md"
[ -f "$protocol" ] || protocol="$plugin/skills/review-lens/SKILL.md"
[ -f "$protocol" ] || { echo "cannot find the review-lens protocol" >&2; exit 1; }

manifest="$root/.aegis/runs/$task/manifest.json"
[ -f "$manifest" ] || { echo "no task $task" >&2; exit 1; }

# The same diff the digest covers, from the one function that builds it.
diff="$("$aegis" --root "$root" diff "$task")"
[ -n "$diff" ] || { echo "nothing to review for $task" >&2; exit 1; }

digest="$("$aegis" --root "$root" lens plan "$task" |
          python3 -c 'import json,sys;print(json.load(sys.stdin)["diff_digest"])')"

# A re-review reconciles this lens's own prior findings by id; the recorder refuses one that
# leaves an open finding unaccounted for.
prior="$(python3 - "$root/.aegis/runs/$task/reviews/$lens.json" <<'PY'
import json, os, sys
path = sys.argv[1]
if os.path.exists(path):
    for f in json.load(open(path)).get("findings", []):
        print(f"{f['id']} [{f.get('disposition', 'open')}] {f['message'][:160]}")
PY
)"
reconcile=""
if [ -n "$prior" ]; then
  reconcile="Work in two phases, in this order. PHASE 1: review the diff fresh and write \"findings\".
PHASE 2: only then reconcile the previous findings of this lens in a top-level \"reconciled\" list,
one entry per open id: {\"id\": \"<id>\", \"followup\": \"resolved\" or \"unresolved\", \"evidence\": \"<one line>\"}.
Never copy a prior id into \"findings\".

Previous findings of this lens, by id:
$prior
"
fi

prompt="$(cat "$protocol")

Your lens is: $lens. Do not include lens, reviewer or diff_digest — the recorder attaches them.
$reconcile

Task: $task
Task manifest: $(cat "$manifest")

Requirements this task must satisfy, in full:
$(cat "$root/.aegis/specs/$(python3 -c "import json;print(json.load(open('$manifest')).get('feature',''))")/spec.md" 2>/dev/null || echo "(no spec found)")

Diff under review:
$diff

Return ONLY the JSON object. No prose before or after it."

report="$(codex exec --sandbox read-only -m "$model" \
          -c model_reasoning_effort=xhigh "$prompt" 2>/dev/null | \
          python3 -c 'import re,sys; t=sys.stdin.read(); m=re.search(r"\{[\s\S]*\}", t); print(m.group(0) if m else "")')"

[ -n "$report" ] || { echo "codex returned no JSON report" >&2; exit 1; }
printf '%s' "$report" | "$aegis" --root "$root" lens record "$task" --lens "$lens" --reviewer "codex:$model" --digest "$digest"
