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

Then write `.aegis/constitution.md` yourself. The write hook refuses an `Edit` or `Write` to
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
  then: dispatch lens-security
```

`aegis next --run` executes the step when it is a self-contained `aegis` command — today that
is the task gate, and nothing else — and stops where a human or an agent is needed.

The full cycle, as slash commands in Claude Code:

```
/aegis:spec checkout        # spec.md with verifiable R-* requirements
/aegis:plan checkout        # architecture options → ADR → architecture.md
/aegis:tasks checkout       # decomposition into manifests with write leases
/aegis:build TASK-042-01    # packet → builder → lenses → refinement → docs → gate
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
| Agents edit the same files and collide | An exclusive **write lease** per task, held from `claim` to `merge`; claiming a lease another task holds is refused, and a write outside one is refused by a hook |
| Every builder gets a differently worded brief | `aegis packet` **generates** the delegation contract from the spec and the manifest |
| "Which reviews should run" is a judgement call | `aegis lens plan` computes it from declared **and** detected change kinds |
| Review findings get lost between rounds | Stable finding ids, carried dispositions, and detection of a "fixed" finding that came back |
| A review stops describing the code | The report quotes the digest it was given; an edit afterwards invalidates it |
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
| `lens-correctness` | sonnet | read-only + **Bash** | `review-lens` |
| `lens-security` | sonnet | read-only, no Bash | `review-lens` |
| `lens-design` | sonnet | read-only, no Bash | `review-lens` |

Three lenses, not five. Documentation obligations are checked deterministically and more
cheaply by `aegis check docs`; architecture and chain-consistency were one question asked at
two moments. `lens-correctness` is separate precisely because it is **the only one with
`Bash`** — the others cannot execute anything, and that is a property, not an instruction.

## Mixed ecosystem: Claude and Codex

`aegis init` writes both `CLAUDE.md` and `AGENTS.md`, and exports the runner-neutral
protocols to `.agents/skills/`, where Codex discovers them itself.

"The builder is never the final reviewer" holds literally, with a different engine, in one
command:

```bash
scripts/aegis/codex-lens.sh TASK-042-01 security
```

It hands Codex the same `review-lens` protocol a Claude lens gets, together with the diff
and the spec, and records the result through `aegis lens record` — with provenance attached
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
Exclusive write leases, with real glob intersection and a hook that refuses the write.
A review that quotes the digest it was given, so an edit afterwards invalidates it.
A status that is earned, not typed: `gated` requires a receipt written by a passing gate that
actually ran the project's commands, and `merged` requires that receipt to still match. The
receipt is a file; what stops it being forged is the hierarchy of trust — CI re-derives the
gate from the same inputs — not a signature.
Configuration as a pure function of `answers.json`, with hand edits blocked and detected.
A gate that fails when nothing ran.

**Checks — deterministic, but only as true as the artifacts they read.**
Requirement coverage per feature, file-to-task attribution, diagram freshness by source
digest, artifact token budgets, registry schemas, waivers with an owner and an expiry — and a
blocking review finding is deferred only by a `finding` waiver that names its id — and that one
is never delegated: a person writes it into `.aegis/waivers.json`, which is what the gate's own
hint says to do.

**Heuristics — they catch the typical case and say so.**
Diff scans for unregistered environment variables, events, flags, integrations and routes;
the testing mandate; change-kind detection; evidence that a test command ran tests, read from
the summaries the common runners print — a runner nobody recognises makes the gate warn that
it cannot tell, and pass. They find `publish("order.created")` and not
`publish(topic)`. Every such finding says so in its own output, and the patterns are
extensible through `capabilities`.

**Known limits.** A `Bash` command can still write where an `Edit` would be refused; the
containment there is the builder's git worktree and the landing review, not the hook. Write
hooks exist only inside Claude Code; any other builder is contained by attribution at the gate.
The git pre-commit hook runs the merge gate's *checks* — not the project's commands, and not at
all for a commit carrying only run bookkeeping; pre-push and CI run the full gate, and
`--no-verify` skips a hook and not CI, which is why CI is the barrier and the hook the early
error. Both write hooks are silent in a checkout with no `.aegis/` at all. Size budgets on lens reports, the handoff and NOTES.md
warn and never block; the bootstrap budgets — CLAUDE.md, the AGENTS.md chain, skills, roles —
still fail, because those are loaded into every session.
On an uncommitted repository, what was there at adoption is attributed to adoption for as long
as the repository still holds it — committing that state as it is keeps it attributed and
retires the baseline, while a commit that records something else puts the path back in task
scope.
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
                                       record an answer and recompile. `q.core.delegate`
                                       takes {"owner": "<name>", "may_waive": ["docs"]} and
                                       must be committed before `aegis waive` will use it
aegis next [--run]                     the next action; --run executes CLI steps
aegis detect                           what the repository says about itself; writes nothing
aegis migrate                          after a framework upgrade; records a missing adoption baseline
aegis compile | scaffold [--profile --doc-profile --force]
                                       recompile .aegis/generated from answers;
                                       re-materialise files
aegis git-hooks install [--force]      pre-commit (the merge gate's checks, no project
                                       commands) and pre-push (the full gate): the early error
                                       every runner shares — CI is the barrier
aegis task new <ID> --feature --objective --owns [--requirements --kinds]
aegis task claim <ID> | status <ID> <value> | list | focus [<ID>]
                                       manifests and the write lease; `focus` with no id
                                       releases it, which is how you answer the interview
                                       again — `aegis answer` is refused under a lease
aegis lease check --path <p>           may this path be written (the write hook calls this;
                                       without --path it refuses)
aegis lease show                       the focused task's globs
aegis land [--run]                     prints the move once the merge gate's checks are green
                                       at HEAD; --run re-runs the full gate, commands
                                       included, and moves the ref
aegis waive <check> --scope --reason --expires [--ticket]
                                       a waiver for one of the checks the *committed*
                                       q.core.delegate delegates, in that owner's name; an
                                       uncommitted delegation authorises nothing, and
                                       `finding` is never delegated
aegis packet <TASK> [--json]           the delegation contract
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
- [docs/EVALUATION.md](docs/EVALUATION.md) — six adversarial audit rounds, what they found,
  and what the measurements say about the method itself.
- [docs/spec-v0.3-original.md](docs/spec-v0.3-original.md) — the original specification,
  kept as the design record.
