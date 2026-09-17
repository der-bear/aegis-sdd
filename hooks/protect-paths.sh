#!/usr/bin/env bash
# Refuse writes to paths that are compiled or human-owned.
#
# Scope is deliberately narrow. A hook cannot authenticate which agent is calling it, so it
# cannot enforce "only the doc-manager writes registries" — claiming otherwise would be
# security theatre. It blocks only what *nobody* should write by hand: compiled output and
# the constitution and the answers it is compiled from. Role-scoped ownership is enforced
# where it can actually be verified:
# the write lease, checked against the diff by `aegis check trace`.
#
# Exit 2 blocks the tool call and returns stderr to the model as the reason.
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

# A relative path must be judged like an absolute one. Matching only `*/.aegis/...` meant
# `.aegis/generated/policy.json` sailed through the check written to stop exactly that.
case "$path" in
  /*) ;;
  *) path="${CLAUDE_PROJECT_DIR:-$PWD}/$path" ;;
esac

# Resolve `..` before matching: `.aegis/registry/../constitution.md` is the constitution,
# and matching the literal string let it through the check written to stop exactly that.
path="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$path" 2>/dev/null || printf '%s' "$path")"

# APFS and NTFS are case-insensitive by default: `.aegis/Answers.json` is the same file.
shopt -s nocasematch
case "$path" in
  */.aegis/generated/*)
    echo "Blocked: .aegis/generated/ is compiled from .aegis/answers.json." >&2
    echo "Change the answer instead:  aegis answer <question-id> <value>" >&2
    echo "Hand edits here are overwritten by the next compile and fail 'aegis check drift'." >&2
    exit 2
    ;;
  */.aegis/answers.json)
    echo "Blocked: .aegis/answers.json changes through 'aegis answer <question-id> <value>'." >&2
    echo "Frozen zones and autonomy limits live there; an edit would unfreeze a path with no" >&2
    echo "record of who decided it. A human changes those answers." >&2
    exit 2
    ;;
  */.aegis/constitution.md)
    echo "Blocked: the constitution is written by a human, not by an agent." >&2
    echo "Propose the change in your report; a human edits this file directly." >&2
    exit 2
    ;;
esac

exit 0
