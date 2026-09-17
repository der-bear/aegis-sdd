import os, sys, io
ROOT = os.environ["AEGIS_PATCH_ROOT"]
def patch(rel, old, new, count=1):
    p=f"{ROOT}/{rel}"; t=io.open(p,encoding="utf-8").read()
    if new and new in t:
        print("already",rel); return
    n=t.count(old)
    if n!=count: sys.exit(f"{rel}: expected {count}, found {n}:\n{old[:220]!r}")
    io.open(p,"w",encoding="utf-8").write(t.replace(old,new)); print("patched",rel)
R="README.md"
patch(R, '''| `lens-correctness` | sonnet | read-only + **Bash** | `review-lens` |
| `lens-security` | sonnet | read-only, no Bash | `review-lens` |
| `lens-design` | sonnet | read-only, no Bash | `review-lens` |

Three lenses, not five. Documentation obligations are checked deterministically and more
cheaply by `aegis check docs`; architecture and chain-consistency were one question asked at
two moments. `lens-correctness` is separate precisely because it is **the only one with
`Bash`** — the others cannot execute anything, and that is a property, not an instruction.''', '''| `lens-runner` | sonnet | read-only + **Bash** | `review-lens` + a lens file |
| `lens-auditor` | sonnet | read-only, no Bash | `review-lens` + a lens file |

A role is a tool set. Two builders are two instances of `aegis-builder`, not a new role, and
the two lens profiles differ only in `Bash` — the auditor cannot execute anything, which is a
property, not an instruction.

### Lenses are files

What a lens looks for lives in `lenses/<name>.md`: a focus, and the triggers that select it —
`always_from`, `kinds` and `paths` against the strictness, and `project_types`. A project adds
its own in `.aegis/lenses/` without touching the framework. `aegis lens plan` computes which
apply; `aegis lens prompt <TASK> <lens>` briefs whichever engine runs it.

| Lens | Profile | Selected by |
|---|---|---|
| correctness | `lens-runner` | always |
| security | `lens-auditor` | routes, auth, dependencies, migrations; money from `standard`; always at `strict` |
| design | `lens-auditor` | feature close; contracts, cross-module, migrations, money, concurrency from `standard`; auth at `strict` |
| accessibility | `lens-auditor` | web-saas: interface files, from `standard` |
| data-integrity | `lens-auditor` | data-etl: migrations and pipeline files |

Documentation obligations are not a lens: `aegis check docs` answers them deterministically.''')
patch(R, '''## Mixed ecosystem: Claude and Codex

`aegis init` writes both `CLAUDE.md` and `AGENTS.md`, and exports the runner-neutral
protocols to `.agents/skills/`, where Codex discovers them itself.

"The builder is never the final reviewer" holds literally, with a different engine, in one
command:

```bash
scripts/aegis/codex-lens.sh TASK-042-01 security
```

It hands Codex the same `review-lens` protocol a Claude lens gets, together with the diff
and the spec, and records the result through `aegis lens record` — with provenance attached
by the script, not echoed by the model.''', '''## Any runner, any second engine — or none

`aegis init` writes both `CLAUDE.md` and `AGENTS.md`, and exports the runner-neutral
protocols to `.agents/skills/`, the Agent Skills location Codex and other runners discover.
The runner changes; `.aegis/` and the CLI do not.

"The builder is never the final reviewer" needs a context that did not build the change. A
second engine strengthens that, and nothing requires one. If you have one, record its command
once — `aegis answer q.core.second-engine '"gemini -p"'` — and run a lens on it:

```bash
scripts/aegis/external-lens.sh TASK-042-01 security gemini:2.5-pro -- gemini -p
scripts/aegis/external-lens.sh TASK-042-01 security claude:opus -- claude -p --model opus
scripts/aegis/codex-lens.sh TASK-042-01 security      # Codex defaults for the same script
```

The engine gets the same self-contained brief a Claude lens gets (`aegis lens prompt
--with-contract`), and the report goes through `aegis lens record` — with provenance attached
by the script, not echoed by the model.''')

A="docs/ARCHITECTURE.md"
patch(A, '''Everything else is a protocol. The practical consequence: `lens-correctness` exists
separately not because correctness is important, but because it is **the only lens with
`Bash`**. The others cannot execute anything, and that cannot be overridden at dispatch.
Tooling is what a profile is for.''', '''Everything else is a protocol. The practical consequence: there are two lens profiles,
`lens-runner` and `lens-auditor`, and they differ only in `Bash` — the auditor cannot execute
anything, and that cannot be overridden at dispatch. What a lens looks for is not a profile at
all: it is a file in `lenses/`, and a project adds one without touching the framework (ADR-3).
Tooling is what a profile is for.''')
patch(A, '''```
lenses = matrix[always] ∪ ⋃ matrix[kind]   for kind ∈ (declared ∪ detected)
```
''', '''```
lenses = matrix[always] ∪ ⋃ matrix[kind]   for kind ∈ (declared ∪ detected)
                        ∪ { lens | its paths match a changed file }
```

The matrix is data. Each `lenses/<name>.md` — a project's `.aegis/lenses/` wins — declares
from which strictness it is always on, from which strictness each change kind or path selects
it, and for which project types it exists. The compiler turns the files into
`policy.lens_matrix`, so the fan-out stays a script's answer and a new lens is one file.
''')
patch(A, '''**With Codex and other runners.** `aegis init` also writes `AGENTS.md` and exports the
runner-neutral protocols to `.agents/skills/`, where Codex discovers them. The runner
changes; `.aegis/` and the CLI do not. Codex as a reviewer fits naturally: it returns the
same JSON shape as a lens and is recorded by the same `aegis lens record`, which makes
"the builder is never the final reviewer" literal — a different engine.''', '''**With other runners and engines.** `aegis init` also writes `AGENTS.md` and exports the
runner-neutral protocols to `.agents/skills/`, where Codex and other Agent Skills runners
discover them. The runner changes; `.aegis/` and the CLI do not. A second reviewing engine —
any CLI that takes a prompt — runs a lens through `scripts/aegis/external-lens.sh` and is
recorded by the same `aegis lens record`. None is required: independence means a context that
did not build the change, and a different engine only strengthens it (ADR-3).''')

patch("skills/review/SKILL.md", '''Only `lens-correctness` has `Bash`. The other two cannot execute anything, which is what
makes their read-only status a property rather than an instruction.''', '''Each lens goes to the profile the plan names — `lens-runner` for a lens that executes,
`lens-auditor` otherwise — briefed by `aegis lens prompt <TASK-ID> <lens>`, which carries its
focus and its own prior findings. The auditor cannot execute anything, which is what makes its
read-only status a property rather than an instruction. A second engine, if the project has
one, runs the same brief through `scripts/aegis/external-lens.sh`.''')
patch("skills/plan/SKILL.md", '''`aegis check requirements --feature <name>` and a `lens-design` pass in `closing` mode over''',
      '''`aegis check requirements --feature <name>` and the design lens in `closing` mode over''')
patch("skills/spec/SKILL.md", '''<!-- the builder's test list; lens-correctness runs them -->''', '''<!-- the builder's test list; the correctness lens runs them -->''')
patch("skills/build/SKILL.md", '''route. Run exactly the lenses it names — dispatch them in parallel, each in a clean context.''', '''route. Run exactly the lenses it names — dispatch them in parallel, each in a clean context,
to the profile the plan names and briefed by `aegis lens prompt <TASK-ID> <lens>`.''')
patch("agents/aegis-orchestrator.md", '''                                  # dispatch them in parallel with packet + diff; each returns JSON''', '''                                  # dispatch each to its plan profile, briefed by
                                  # `aegis lens prompt <ID> <lens>`; each returns JSON''')
patch(".aegis/decisions/ADR-3-lenses-roles-engines-are-data.md", '''Status: accepted — built as its own task after TASK-UNBLOCK-01 closes''', '''Status: accepted — implemented in TASK-UNIVERSAL-01''')
print("lens docs applied")
