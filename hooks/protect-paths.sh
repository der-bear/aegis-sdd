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

root="${CLAUDE_PROJECT_DIR:-$PWD}"

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
  # An empty path means the payload parsed to nothing — no python3, or a shape this hook
  # does not know. A hook that cannot read what it is judging refuses, like the git hooks —
  # but only where Aegis governs. Refusing without that test meant that in a project with no
  # `.aegis/`, a machine without python3 could not write a single file, in the name of a
  # framework that was not there. Path matching below stays unconditional: compiled output is
  # compiled output in whatever checkout it sits.
  if [ -d "$root/.aegis" ] && ! command -v python3 >/dev/null 2>&1; then
    echo "Aegis cannot check this write: python3 is not on PATH, so the tool payload cannot be read." >&2
    exit 2
  fi
  # python3 is here and the payload still yielded nothing. Unlike the lease hook, this one does
  # not refuse: what it guards is compiled output, and the barrier for that is `aegis check
  # drift` at every gate stage, which reads the files rather than the payload. Refusing every
  # write on an unfamiliar payload shape would cost more than it protects, and the protection
  # does not depend on this hook. That is the honest boundary, not an oversight.
  exit 0
fi

# A relative path must be judged like an absolute one. Matching only `*/.aegis/...` meant
# `.aegis/generated/policy.json` sailed through the check written to stop exactly that.
case "$path" in
  /*) ;;
  *) path="$root/$path" ;;
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
