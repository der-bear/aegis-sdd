#!/usr/bin/env bash
# Run a review lens on any AI engine and record it like any other lens.
#
#   scripts/aegis/external-lens.sh <TASK-ID> <lens> <engine-label> [--stdin] -- <command> [args...]
#
#   scripts/aegis/external-lens.sh TASK-042-01 security gemini:2.5-pro -- gemini -p
#   scripts/aegis/external-lens.sh TASK-042-01 security claude:opus -- claude -p --model opus
#   scripts/aegis/external-lens.sh TASK-042-01 security ollama:qwen3 --stdin -- ollama run qwen3
#
# The engine is whatever the project has; nothing in Aegis requires a particular one. The
# command receives one self-contained prompt from `aegis lens prompt --with-contract` — the
# review contract, the lens focus, this lens's own prior findings, the packet and the diff —
# as its last argument, or on stdin with --stdin, and must print a reply containing one JSON
# object. Provenance is attached here, never echoed by the model: --lens, --reviewer, --digest.
set -euo pipefail

task="${1:?usage: external-lens.sh <TASK-ID> <lens> <engine-label> [--stdin] -- <command> [args...]}"
lens="${2:?lens name}"
label="${3:?engine label, for example gemini:2.5-pro}"
shift 3
mode="argument"
if [ "${1:-}" = "--stdin" ]; then mode="stdin"; shift; fi
[ "${1:-}" = "--" ] && shift
[ "$#" -gt 0 ] || { echo "give the engine command after --" >&2; exit 1; }

plugin="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
root="$plugin"
[ -d "$PWD/.aegis" ] && root="$PWD"
aegis="$(command -v aegis || echo "$plugin/scripts/aegis/aegis")"
[ -f "$root/.aegis/runs/$task/manifest.json" ] || { echo "no task $task" >&2; exit 1; }

# The digest is taken before the engine runs: an edit during the review makes the record fail
# rather than bind a verdict to code the reviewer never saw.
digest="$("$aegis" --root "$root" lens plan "$task" | python3 -c 'import json,sys;print(json.load(sys.stdin)["diff_digest"])')"
prompt="$("$aegis" --root "$root" lens prompt "$task" "$lens" --with-contract)"

# The engine's stderr stays visible: an auth error, a missing binary or an argument over the
# platform's limit must say so, not exit silently with the engine's code. A prompt over
# ~100 KB goes on stdin whatever the mode: a single argv is capped at 128 KiB on Linux.
if [ "$mode" = "stdin" ] || [ "${#prompt}" -gt 100000 ]; then
  reply="$(printf '%s' "$prompt" | "$@")" || { echo "$label: the engine failed (exit $?) — see its output above" >&2; exit 1; }
else
  reply="$("$@" "$prompt")" || { echo "$label: the engine failed (exit $?) — see its output above" >&2; exit 1; }
fi
report="$(printf '%s' "$reply" | python3 -c 'import re,sys; t=sys.stdin.read(); m=re.search(r"\{[\s\S]*\}", t); print(m.group(0) if m else "")')"
[ -n "$report" ] || { echo "$label returned no JSON report" >&2; exit 1; }
printf '%s' "$report" | "$aegis" --root "$root" lens record "$task" --lens "$lens" --reviewer "$label" --digest "$digest"
