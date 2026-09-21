# Aegis SDD

A spec-driven development framework for agent teams. A Claude Code plugin plus a
zero-dependency CLI.

One idea decides everything else: **whatever must happen every time is executed by a script,
not requested in a prompt.** A script costs no tokens, always fires, and gives the same
answer twice. Agents do what scripts cannot — write code, and notice what no checklist
anticipated.

---

## Install

```bash
git clone <repo> ~/aegis-sdd && ~/aegis-sdd/install.sh
claude --plugin-dir ~/aegis-sdd
```

`install.sh` puts `aegis` in `~/.local/bin`. That matters: every command in the
documentation, in generated task packets and in the protocols is written as `aegis …`, and
without it on PATH each one would have to be translated into a path — which breaks the
moment a different runner or CI reads the same instruction.

No dependencies: Python 3.9+, standard library.

## Start

```bash
cd your-project
aegis init
aegis git-hooks install
aegis gate --stage bootstrap
aegis interview
```

`init` reads manifests, lockfiles, the Makefile and CI, then scaffolds and compiles. It does
not install the git hooks and does not run the bootstrap gate: both are the next two commands,
because a check that installs itself is one nobody decided to have; `check setup` warns while
the hooks are missing. `init` establishes packages with their **real** test and lint commands,
the project type, environment variables, routes, migration and test paths.

`interview` turns what is left into a conversation: only what detection could not answer,
in batches of three, irreversible decisions first, each with a default and the reason it is
being asked.

```
Read from the repository — confirm as one screen (2 items):
  q.core.project-type = "web-saas"   (frontend and server frameworks together)
  q.core.commands = {"shop": {"test": "npm run test", "lint": "npm run lint"}}

8 question(s) left, in 3 batch(es); irreversible ones first.
Batch 1:
  Which decisions may agents take without asking you? [irreversible]
    options: code-style, internal-refactors, new-dependencies, schema-changes, public-contracts
    default: ["code-style", "internal-refactors"]
    why:     This is the escalation boundary every builder is held to. It is the one setting
             worth your attention even in a hurry.
    record:  aegis answer q.core.autonomy-limits <value>
```

Answer with `aegis answer <question> <value>` — values are validated against the question,
so a typo is refused rather than compiled into configuration that means nothing.

Then write `.aegis/constitution.md` yourself. `check drift` catches an edit to
it, and `aegis check setup` fails while it is still the template — but nothing verifies who
wrote the prose, so a signature at the end is the only record that a human did.

## Work

```bash
aegis next
```

Prints **one** next action, computed from state on disk. That is why the loop survives
context compaction, a different runner, and Monday morning:

```
next: review TASK-042-01  [agent]
  why: required lenses have not run: security
  run: aegis lens plan TASK-042-01
  then: dispatch the security lens to its plan profile, briefed by `aegis lens prompt TASK-042-01 security`
```

`aegis next --run` executes the step when it is a self-contained `aegis` command — the task
gate, the merge gate and `aegis land`, which moves the mainline — and stops where a person or an
agent is needed.

The full cycle, as slash commands in Claude Code:

```
/aegis:spec checkout        # spec.md with verifiable R-* requirements
/aegis:plan checkout        # architecture options → ADR → architecture.md
/aegis:tasks checkout       # decomposition into manifests with write leases
/aegis:build TASK-042-01    # packet → builder → lenses → refinement → docs → gate → commit → land
```

Run the orchestrator as the session agent, not as a subagent:

```bash
claude --agent aegis-orchestrator
```

Claude Code removes `AskUserQuestion` from every subagent and `Agent` at the delegation
depth limit, so an orchestrator spawned as a subagent can neither ask you anything nor
delegate — it silently degrades into a builder holding the wrong prompt.

## What it does for you

| Problem | Mechanism |
|---|---|
| Agents edit the same files and collide | An exclusive **write lease** per task, held from `claim` to `merge`; claiming a lease another task holds is refused, and a write outside one is caught by `check trace` at the merge boundary |
| Every builder gets a differently worded brief | `aegis packet` **generates** the task packet from the spec and the manifest |
| "Which reviews should run" is a judgement call | `aegis lens plan` computes it from declared **and** detected change kinds |
| Review findings get lost between rounds | Stable finding ids, carried dispositions, and detection of a "fixed" finding that came back |
| A review stops describing the code | The report quotes the digest it was given; an edit afterwards to a file whose kinds select that lens invalidates it, and any edit to the contract under `.aegis/` invalidates every lens |
| Diagrams drift from the code | Content digest of the sources a diagram watches — a date can be edited, a digest cannot |
| Documentation accumulates | Anything outside the doc profile is a gate finding, not a bonus |
| Configuration drifts | `answers.json` → `generated/` by a pure function; hand edits are blocked and detected |
| The gate cannot run on a legacy repo | Three stages, and the change-sensitive checks scoped to the diff rather than the repository |

## Any kind of project

Detection covers Node (npm/pnpm/yarn/bun), Python, Go, Rust, Maven, Gradle, Ruby, PHP,
.NET, Elixir, Swift, Scala, Deno, CMake and Haskell — each with a test asserting the exact
command a developer in that ecosystem would actually run. Also covered by tests: a polyglot
monorepo yielding one package per buildable unit, a root `Makefile` taking priority over
anything inferred, and an **unknown stack** — a repository with no recognisable manifest
still initialises and passes its gate. Where there is no manifest but there is CI, commands
come from CI: that is the version which has to work.

The question set composes rather than branches: `core`, plus the pack for the detected
project type, plus `context/brownfield` when there is existing code. A web SaaS is asked
about tenancy; a data pipeline about personal data; a library about its compatibility
promise. Supporting a new kind of project is one JSON file in `interview/project-type/`,
usually with `extends` — no agent and no engine changes.

Profiles scale the machinery: **S** is one builder, two registries and one lens on ordinary
task work — correctness; security joins it on a route, auth, dependency or data-migration
change, and design when a feature closes. **L** is three builders, every registry and a strict
review matrix, where correctness and security are always on. A profile can shrink as readily
as grow.

## Roles

Protocols live in `skills/`; an agent is a profile of tools and a model, not a container of
knowledge. The same protocol file is read by Claude Code (through `skills:` frontmatter),
by Codex (through the path in `AGENTS.md`) and by a person.

An agent is created for exactly two reasons: **a narrow task that should not flood the
session's context**, or **an auditor that must be unbiased**.

| Role | Model | Tools | Protocol |
|---|---|---|---|
| `aegis-orchestrator` | opus | full + `Agent` | — (it is the session) |
| `aegis-builder` | sonnet | + Edit/Write/Bash, `isolation: worktree` | `build-task` |
| `aegis-doc-manager` | sonnet | + Edit/Write/Bash | `doc-sync` |
| `aegis-explorer` | sonnet | read-only + Bash | — |
| `lens-runner` | sonnet | read-only + **Bash** | `review-lens` + a lens file |
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

Documentation obligations are not a lens: `aegis check docs` answers them deterministically.

## Any runner, any second engine — or none

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
by the script, not echoed by the model. Finding ids are derived from the claim text, which
holds within one reviewer's rounds; two different engines wording the same defect
differently produce two findings, and reconciliation is explicit rather than assumed.

For multi-agent runners, `workflows/aegis-task.js` ships with the plugin:
`Workflow({name: "aegis-task", args: "TASK-042-01"})` runs the same cycle. The fan-out comes
from `aegis lens plan`, so more agents changes the executor, not a single invariant.

## Token cost, measured

```
$ aegis budget
CLAUDE.md + imported rules   ≈628 tokens (cap 2000)
AGENTS.md chain              5413 bytes (cap 32768 — the limit Codex truncates at)
metadata for 14 protocols    ≈843 tokens
aegis-builder startup       ≈1219 tokens (cap 12000)
```

A test compares these four figures against what `aegis budget` prints, within five per cent,
because a measured number in a document is a claim like any other: this table was a third
under the truth until the test existed.

Always in context: roughly **1.5k tokens** — the pointer file with its compiled rules, plus
the one-line description of every protocol. A role preloads exactly one protocol — its own
procedure, needed in every task. Everything else `aegis packet` passes as **paths**:
frontmatter `skills:` injects a whole body whether or not the task needs it, while a path
costs a dozen tokens and is read only when the agent reaches the work it governs.

Honest limit: `aegis budget` measures **artifacts**, not the final context. It does not
count the runner's system prompt, tool schemas, the diff, files read, or conversation
history. The budget constrains what the framework controls; it does not promise the model
will fit.

## What is guaranteed, checked, and merely likely

The distinction is the point. A regex scan catches the typical case and is evaded by a
variable; calling it a guarantee promises more than it can do.

**Guarantees — properties of artifacts, not requests.**
Exclusive write leases, with real glob intersection — a declaration `check trace` reads at the
merge boundary; nothing refuses a write mid-task.
A review that quotes the digest it was given, so an edit afterwards invalidates it — for the lenses the edited files' kinds select, and for every lens when the contract under `.aegis/` moves.
A status that is earned, not typed: `gated` requires a receipt written by a passing gate that
actually ran the project's commands, and `merged` requires that receipt to still match. The
receipt is a file; what stops it being forged is the hierarchy of trust — CI re-derives the
gate from the same inputs — not a signature.
Configuration as a pure function of `answers.json`, with hand edits blocked and detected.
A gate that fails when nothing ran.

**Checks — deterministic, but only as true as the artifacts they read.**
Requirement coverage per feature, file-to-task attribution, diagram freshness by source
digest, artifact token budgets, registry schemas, waivers with an owner and an expiry — and a
blocking review finding is deferred only by a `finding` waiver that names its id, and a person
writes that one.

**Heuristics — they catch the typical case and say so.**
Diff scans for unregistered environment variables, events, flags, integrations and routes;
the testing mandate; change-kind detection; evidence that a test command ran tests, read from
the summaries the common runners print — a runner nobody recognises makes the gate warn that
it cannot tell, and pass. They find `publish("order.created")` and not
`publish(topic)`. Every such finding says so in its own output, and the patterns are
extensible through `capabilities`.

**Known limits.** Nothing refuses a write mid-task: the lease is a declaration `check trace`
reads at the merge boundary, and two builders are kept apart by their worktrees. Pre-commit
checks drift and structure and nothing that reads the diff; pre-push and CI run the merge gate,
and `--no-verify` skips a hook and not CI. Every record under `.aegis/` is a file the agent can
write, and a lens report is checked for shape and digest, never for content — with no remote
the agent is trusted, with a remote CI is the barrier. Size budgets on lens reports, the handoff
and NOTES.md warn and never block; the round count is a signal, not a wall; an adopter's own
CLAUDE.md and AGENTS.md chain warn past their budgets too, and only the framework's own skills
and roles still fail, because those are ours. On an uncommitted repository, what was there at adoption is attributed to
adoption for as long as the repository still holds it.
`docs attest` proves the sources have not moved since someone signed for them, not that
anyone looked. Token figures are estimates — no tokenizer ships with Python; set
`AEGIS_TOKENIZER` for exactness.

## Commands

```
aegis init [--yes] [--profile S|M|L] [--mode interactive|hybrid|autonomous] [--force]
                                       detect, scaffold, compile, index, and add the gate
                                       workflow where the project already uses GitHub Actions
                                       (otherwise it is parked at .aegis/ci/). Then run
                                       `aegis gate --stage bootstrap` and
                                       `aegis git-hooks install` — neither happens on its own
aegis interview [--json] [--all]       what is left to ask, batched and ordered; --all
                                       includes the phase-2 questions
aegis answer <question> <value> [--source --rationale]
                                       record an answer and recompile
aegis next [--run]                     the next action; --run executes CLI steps
aegis detect                           what the repository says about itself; writes nothing
aegis migrate                          after a framework upgrade; records a missing adoption baseline
aegis compile | scaffold [--profile --doc-profile --force]
                                       recompile .aegis/generated from answers;
                                       re-materialise files
aegis git-hooks install [--force]      pre-commit (drift and structure, a checkpoint) and
                                       pre-push (the full merge gate): the early error every
                                       runner shares — CI is the barrier
aegis task new <ID> --feature --objective --owns [--requirements --kinds]
aegis task claim <ID> | status <ID> <value> | list
                                       manifests and the write lease — a declaration `check
                                       trace` reads at the merge boundary
aegis land                             runs the full merge gate at HEAD, moves the mainline to
                                       it, marks the gated tasks merged and commits that
aegis packet <TASK> [--json]           the task packet
aegis diff <TASK>                      the diff a reviewer reads — exactly what the digest covers
aegis lens plan <ID> [--closing] | record <ID> --lens [--reviewer --digest]
aegis lens disposition <ID> <F-id> fixed|false-positive|waived|deferred --reason --by
                                       review planning and evidence; `--closing` is the only way
                                       the design lens is planned at a feature close
aegis gate --stage bootstrap|task|merge [--task <ID>] [--no-run]
aegis check <name>|all                 structure setup registry env surfaces routes trace
                                       requirements testing docs budget drift banks reviews
                                       handoff protocols pointers commands
                                       (--task, --base, --feature scope the diff-bound ones;
                                       `docs --closing` and `requirements --planned` widen two)
aegis index | fmt | budget | metrics | status
aegis docs attest [<id>] --by <who> [--note]
aegis --root <dir> …                   run against another checkout
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how it works inside: the compiler, gate
  stages, leases, digests, the position on memory, and multi-agent runners.
- [docs/EVALUATION.md](docs/EVALUATION.md) — every review cycle, who reviewed and what they found,
  and what the measurements say about the method itself.
- [docs/spec-v0.3-original.md](docs/spec-v0.3-original.md) — the original specification,
  kept as the design record.

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Alex Derkach.
