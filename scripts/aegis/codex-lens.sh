#!/usr/bin/env bash
# Codex defaults for external-lens.sh, kept so existing commands still work. Any other engine —
# or none — goes through external-lens.sh directly; nothing in Aegis requires Codex.
#
#   scripts/aegis/codex-lens.sh <TASK-ID> <lens> [model]
set -euo pipefail
task="${1:?usage: codex-lens.sh <TASK-ID> <lens> [model]}"
lens="${2:?lens name}"
model="${3:-gpt-5.6-sol}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$here/external-lens.sh" "$task" "$lens" "codex:$model" -- \
  codex exec --sandbox read-only -m "$model" -c model_reasoning_effort=xhigh
