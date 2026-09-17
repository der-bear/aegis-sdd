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
aegis interview
```

`init` reads manifests, lockfiles, the Makefile and CI, then scaffolds and compiles. It
establishes packages with their **real** test and lint commands, the project type,
environment variables, routes, migration and test paths.

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
    why:     This is the escalation boundary every builder is held to.
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

`aegis next --run` executes consecutive CLI steps and stops where a human or an agent is
needed.

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
| Agents edit the same files and collide | An exclusive **write lease** per task; overlapping leases are refused at creation, and a write outside one is refused by a hook |
| Every builder gets a differently worded brief | `aegis packet` **generates** the delegation contract from the spec and the manifest |
| "Which reviews should run" is a judgement call | `aegis lens plan` computes it from declared **and** detected change kinds |
| Review findings get lost between rounds | Stable finding ids, carried dispositions, and detection of a "fixed" finding that came back |
| A review stops describing the code | The report quotes the digest it was given; an edit afterwards invalidates it |
| Diagrams drift from the code | Content digest of the sources a diagram watches — a date can be edited, a digest cannot |
| Documentation accumulates | Anything outside the doc profile is a gate finding, not a bonus |
| Configuration drifts | `answers.json` → `generated/` by a pure function; hand edits are blocked and detected |
| The gate cannot run on a legacy repo | Three stages, and every check scoped to the diff rather than the repository |

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

Profiles scale the machinery: **S** is one builder, two registries and two lenses on task
work — the third, design, is dispatched when a feature closes; **L** is
three builders, every registry and a strict review matrix. A profile can shrink as readily
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
A status that cannot be asserted: `gated` requires a receipt written by a passing gate that
actually ran the project's commands, and `merged` requires that receipt to still match.
Configuration as a pure function of `answers.json`, with hand edits blocked and detected.
A gate that fails when nothing ran.

**Checks — deterministic, but only as true as the artifacts they read.**
Requirement coverage per feature, file-to-task attribution, diagram freshness by source
digest, artifact token budgets, registry schemas, waivers with an owner and an expiry — and a
blocking review finding is deferred only by a `finding` waiver that names its id.

**Heuristics — they catch the typical case and say so.**
Diff scans for unregistered environment variables, events, flags, integrations and routes;
the testing mandate; change-kind detection; evidence that a test command ran tests, read from
the summaries the common runners print — a runner nobody recognises produces "the gate cannot
tell", not a pass. They find `publish("order.created")` and not
`publish(topic)`. Every such finding says so in its own output, and the patterns are
extensible through `capabilities`.

**Known limits.** A `Bash` command can still write where an `Edit` would be refused; the
containment there is the builder's git worktree and the landing review, not the hook. Write
hooks exist only inside Claude Code; a Codex builder is contained by attribution at the gate.
The commit hook recognises the ordinary spellings of `git commit` and `git push`; a shell can
build one it does not, so the hook is an early error and the merge gate is the barrier.
On an uncommitted repository, what was there at adoption is attributed to adoption for as long
as the repository still holds it — committing that state as it is keeps it attributed and
retires the baseline, while a commit that records something else puts the path back in task
scope.
`docs attest` proves the sources have not moved since someone signed for them, not that
anyone looked. Token figures are estimates — no tokenizer ships with Python; set
`AEGIS_TOKENIZER` for exactness.

## Commands

```
aegis init [--yes] [--profile S|M|L]   detect, scaffold, compile, index, install CI
aegis interview [--json]               what is left to ask, batched and ordered
aegis answer <question> <value>        record an answer and recompile
aegis next [--run]                     the next action; --run executes CLI steps
aegis commit-scope                     (for the commit hook) none | exempt | gate for a shell command
aegis detect                           what the repository says about itself; writes nothing
aegis migrate                          after a framework upgrade; records a missing adoption baseline
aegis git-hooks install [--force]      pre-commit and pre-push: the gate for commits Claude Code
                                       never sees (a runner without hooks is covered by CI)
aegis task new|claim|status|list|focus manifests and the write lease
aegis packet <TASK>                    the delegation contract
aegis diff <TASK>                      the diff a reviewer reads — exactly what the digest covers
aegis lens plan|record|disposition     review planning and evidence (record: --lens --reviewer
                                       --digest; disposition: --by)
aegis gate --stage bootstrap|task|merge
aegis check <name>                     structure setup registry env surfaces routes trace
                                       requirements testing docs budget drift banks reviews
                                       handoff protocols pointers commands
aegis index | fmt | budget | metrics | status | docs attest --by <who>
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how it works inside: the compiler, gate
  stages, leases, digests, the position on memory, and multi-agent runners.
- [docs/EVALUATION.md](docs/EVALUATION.md) — six adversarial audit rounds, what they found,
  and what the measurements say about the method itself.
- [docs/spec-v0.3-original.md](docs/spec-v0.3-original.md) — the original specification,
  kept as the design record.
