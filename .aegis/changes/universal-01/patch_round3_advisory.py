import os, sys, io
ROOT = os.environ["AEGIS_PATCH_ROOT"]
def patch(rel, old, new, count=1):
    p=f"{ROOT}/{rel}"; t=io.open(p,encoding="utf-8").read()
    if new and new in t:
        print("already",rel); return
    n=t.count(old)
    if n!=count: sys.exit(f"{rel}: expected {count}, found {n}:\n{old[:220]!r}")
    io.open(p,"w",encoding="utf-8").write(t.replace(old,new)); print("patched",rel)
# design F: `aegis diff` named as the lens input in the three protocols
patch("skills/review/SKILL.md", '''All lenses in parallel, each in a clean context, each read-only. Give each one: the task id,
the diff, and the path to the acceptance criteria. Do not summarise the diff for them —
a summary hides exactly the detail a reviewer is for.''', '''All lenses in parallel, each in a clean context, each read-only. Give each one the task id,
`aegis packet <TASK-ID>` and `aegis diff <TASK-ID>` — exactly the files the digest covers;
`git diff` misses new untracked files the digest includes. Do not summarise the diff for
them — a summary hides exactly the detail a reviewer is for.''')
patch("skills/build/SKILL.md", '''This unions the task's declared change kinds with kinds detected from the actual diff, so a''', '''Hand each lens `aegis packet <TASK-ID>` and `aegis diff <TASK-ID>` — the diff over exactly
the files the digest covers.

This unions the task's declared change kinds with kinds detected from the actual diff, so a''')
patch("agents/aegis-orchestrator.md", '''aegis lens plan <ID>              # -> exactly which lenses, and why
                                  # dispatch them in parallel; each returns JSON''', '''aegis lens plan <ID>              # -> exactly which lenses, and why
aegis diff <ID>                   # -> the diff every lens reads (what the digest covers)
                                  # dispatch them in parallel with packet + diff; each returns JSON''')

# design F: ADR-2 consequences name the baseline
patch(".aegis/decisions/ADR-2-scale-and-onboarding.md", '''Approving A + B adds nothing to the kernel and removes an environment override, a second round
budget, a phantom artifact and a side effect.''', '''Approving A + B adds one piece of configuration the kernel reads — the adoption baseline, built
during B (see the amendments) — and removes an environment override, a second round budget, a
phantom artifact, a side effect and the index form of the commit hook's exemption.''')

# design F: contracts and help say the current shapes
patch(".aegis/specs/unblock-cycle/spec.md", '''- `aegis commit-scope`: shell command on stdin → `exempt | index | gate`.
- Stored lens record: adds `report_tokens`; findings may carry `reopened_in`, `disposition_by`
  (`lens | human`) and `reconciliation_rejected`.''', '''- `aegis commit-scope`: shell command on stdin → `exempt | gate`.
- `aegis diff <TASK>`: unified diff over the digest's file set.
- `aegis lens record <TASK> --lens <name> [--reviewer <who>] [--digest <d>]`; `aegis lens
  disposition <TASK> <id> <value> --reason <why> --by <who>`.
- Stored lens record: adds `report_tokens`; findings may carry `reopened_in`, `disposition_by`
  (`lens`, or the `--by` name) and `reconciliation_rejected`.''')
patch("scripts/aegis/aegis_cli/__main__.py", '''help="read a shell command on stdin; print exempt|index|gate for the commit hook")''',
      '''help="read a shell command on stdin; print exempt|gate for the commit hook")''')

# design F: R-21 defines which names are not a person — and engine/model names count too
patch(".aegis/specs/unblock-cycle/spec.md", '''R-21. `aegis lens disposition` shall require `--by`; a finding that came back shall stay blocking
      until a disposition whose `--by` is neither the lens, the task's builder nor a framework
      agent. The name is a recorded claim, not an authentication.''', '''R-21. `aegis lens disposition` shall require `--by`; a finding that came back shall stay blocking
      until a disposition whose `--by` is not the task's builder and not a name the framework
      recognises as an agent or engine: `lens`, `lens-*`, `aegis-*`, `claude*`, `codex*`,
      `gemini*`, `gpt-*`, `opus*`, `sonnet*`, `haiku*`, or any `engine:model` label containing a
      colon. The name is a recorded claim, not an authentication.''')
patch("scripts/aegis/aegis_cli/flow.py",
      '''FRAMEWORK_AGENT = re.compile(r"^(lens|lens-.*|aegis-.*|codex:.*|claude.*)$", re.IGNORECASE)''',
      '''# Names that are recognisably not a person: the framework's agents, common engine and model
# families, and any `engine:model` reviewer label. A person's name rarely contains a colon.
FRAMEWORK_AGENT = re.compile(
    r"^(lens|lens-.*|aegis-.*|claude.*|codex.*|gemini.*|gpt-.*|opus.*|sonnet.*|haiku.*|.*:.*)$",
    re.IGNORECASE)''')
print("advisory fixes applied")
