# How Aegis works

Authoritative for: the configuration compiler, gate stages, leases, digests; the position on
memory and on multi-agent runners.
References only: roles and commands (see [README](../README.md)), why decisions were made
(see [EVALUATION](EVALUATION.md)).

---

## 0. The protocol is primary; an agent is a profile

Procedures live in `skills/*/SKILL.md` and contain nothing vendor-specific. Claude Code loads
one through a role's `skills:` frontmatter, Codex reads it by path from `AGENTS.md`, a person
reads it with their eyes. An agent supplies only what a prompt cannot: **a tool set and a
model**.

That gives exactly two reasons to create an agent:

1. **A narrow task that should not flood the session's context** — the builder, doc-sync,
   the explorer. Their work would fill the main conversation with reads nobody needs again.
2. **An auditor that must be unbiased** — the lenses. A fresh context and no authorship is
   their entire value; a reviewer who helped write the thing cannot find what it did not
   think of the first time.

Everything else is a protocol. The practical consequence: `lens-correctness` exists
separately not because correctness is important, but because it is **the only lens with
`Bash`**. The others cannot execute anything, and that cannot be overridden at dispatch.
Tooling is what a profile is for.

## 1. The line between script and model

| Script | Model |
|---|---|
| What changed and who owns it | Whether it is right |
| Whether a requirement has a task | Whether the task actually satisfies it |
| Whether a diagram is stale | What in it is now wrong |
| Whether a registry entry exists | Whether its fields are true |
| Whether a budget was exceeded | What to drop to fit |

The rule: **if a check reduces to comparing paths, schemas or digests, it is a script.**
Everything moved left became free in tokens and stopped varying between runs.

## 2. The configuration compiler

```
.aegis/answers.json  +  interview/*.json  +  COMPILER_VERSION
        └─> .aegis/generated/{policy,doc-profile,capabilities,standards,materialization}.json
```

A pure function: the same inputs always produce the same bytes. Three consequences.

**The constitution stopped contradicting itself.** It used to be both "only a human changes
it" and "materialised at init". Now `constitution.md` is written by hand and *references*
compiled policy; the compiler physically cannot write outside `generated/`.

**Drift became checkable.** `aegis check drift` recompiles and compares. A difference means
someone hand-edited generated configuration — after which every later review argues against
the wrong baseline. The `protect-paths` hook blocks that write; `aegis answer` is the way in.

**A question with no consequence is forbidden.** Every question declares a `writes` target
from a closed table; an unknown target fails bank-lint rather than doing nothing quietly.

The `when` grammar is closed and parsed by recursive descent: `==`, `!=`, `in`, `not`, `and`,
`or`, `detected(x)`. No `eval`.

## 2.5. Detection: the interview is short only if the scanner is good

`aegis detect` reads manifests, lockfiles, CI and the Makefile: packages and their **real**
commands, project type, environment variables, routes, migration, test, generated and shared
paths. Every fact carries a confidence and the file it came from.

This is not a nicety. `capabilities.packages` decides what the gate runs at all; a model's
plausible guess at a test command turns the gate into noise on the first run, and it gets
switched off in week two.

Three decisions, each found on a real repository:

- **The package manager comes from the lockfile.** `npm run test` in a pnpm workspace
  resolves different dependencies than the team's own command — the gate would test
  something nobody ships.
- **Nested checkouts are skipped.** A git worktree inside a repository is a complete second
  copy; on a live repo the walker produced six copies of two packages, one per branch.
- **Mixed signals lower confidence instead of picking a winner.** A repository with both
  `prefect` and `react` gets 0.5 and lands in the ledger. A confident single answer would
  have installed the wrong documentation profile with nobody noticing.

Observed surfaces are **not written to registries**. A static scan cannot tell a live route
from a dead one or infer who owns an integration; those are candidates a human confirms.

## 2.6. The interview is data, not improvisation

`aegis interview` turns the question banks into a conversation: what detection could not
answer, in batches of three, irreversible decisions first, each with its default and the
reason it is asked. Anything established confidently is listed separately for a single
batch confirmation rather than asked.

Ordering is deliberate. Tenancy and personal data shape every table and cannot be undone by
a revert, so they get the attention a human still has at the start; diagram tooling does not.

The set composes rather than branches: `core`, plus the pack for the detected project type
(with `extends`), plus `context/brownfield` when there is existing code. A new kind of
project is one JSON file — neither the agents nor the engine change. That is what makes the
framework adapt instead of accumulating special cases.

## 2.7. `aegis next` — the loop is guaranteed by being computable

One command answers "what now" from state on disk: no `.aegis/` → initialise; an unreviewed
ledger → it blocks phase 3; no handoff → the builder; a lens from the plan missing → review;
an open severity-3 finding → fix the code and re-review; all clear → the gate.

Hence the property this exists for: the loop survives context compaction, a change of
runner, and a human returning on Monday. An agent that "forgot" the protocol and a Codex
session that never read it ask the same question and get the same answer.

## 2.8. Pointer files, not prefilled files

Any agent can overwrite `CLAUDE.md` or `AGENTS.md` — they are ordinary project files, and a
rewritten file used to mean the rules silently vanished. The design accepts that the
pointer files are expendable and makes the rules themselves untouchable:

```
CLAUDE.md   →  @.aegis/generated/rules.md     (Claude Code expands imports at launch)
AGENTS.md   →  "read .aegis/generated/rules.md first"  (the LF standard has no imports)
                        │
                        └─ compiled by `aegis compile` from answers.json:
                           pure function → drift-checked → write-hook-protected
```

Three properties fall out:

- **The rules carry real facts, not placeholders.** Compiled from answers, they state this
  project's actual commands, profile, autonomy limits and frozen zones — and recompile when
  an answer changes, instead of rotting the way a scaffolded-once file does.
- **Overwrites are detected and self-healing.** `check pointers` (bootstrap and task gates)
  fails when the import line is gone; `aegis migrate` re-appends it without touching
  whatever else the file now contains.
- **Tampering with the rules is tampering with `generated/`** — refused by the write hook,
  caught by `check drift`, restored by `aegis compile`.

Considered and rejected:

- **Prefilled full files** (the previous design): unprotectable, and they drift the moment
  the project's commands change.
- **`.claude/rules/`**: loads at launch like CLAUDE.md and supports path scoping, but Codex
  and the other AGENTS.md readers never see it, and it is the team's own space — the
  framework does not colonise it. Path-scoped rules remain attractive for *project-owned*
  conventions; nothing stops a team using them alongside Aegis.
- **A symlink `CLAUDE.md → AGENTS.md`**: loses the ability to give Claude the full rules at
  launch while giving Codex a read instruction, and breaks on Windows without developer
  mode.

The same reasoning fixes the `.claude/` question: Aegis writes nothing there. The plugin
supplies agents, skills and hooks from its own directory; project state lives in `.aegis/`;
`.claude/` belongs to the team.

## 3. The lease as the unit of ownership

The task manifest is created **before** the work:

```json
{"id": "TASK-042-01", "base_sha": "4b82…", "owns": ["src/billing/**"],
 "requirements": ["R-1"], "change_kinds": ["code", "route"], "acceptance": ["…"]}
```

`owns` is an exclusive write lease. `aegis task new` refuses an overlap at creation, not
afterwards, and a focused task's writes outside it are refused by a hook. Frozen zones are
refused to every agent write, focused or not — the orchestrator and the doc-manager work
unfocused, and a zone open to them was not frozen.

The same structure solves traceability. A commit-message convention cannot say who owns a
file: a squashed branch carries two tasks and a shared helper belongs to neither. A glob
written in advance can, and `aegis check trace` requires every changed file to belong to
exactly one active task.

### Adopting on an uncommitted tree

On a committed repository the diff against `base_sha` scopes every check to the task. On a
tree with untracked work — the usual state of a repository someone is trying a tool on —
every untracked file counted as changed by the first task, so trace, the environment scan and
the lenses all judged code the task never touched.

`aegis init` (or `aegis migrate`, for a project adopted earlier) records the uncommitted files
once: their content hashes, and `absent` for a path that is missing — a pending deletion, or the
source side of a staged rename.

Attribution is by content, not by history (ADR-4). A recorded path belongs to adoption while
the repository still holds what was recorded: the working tree matches it, nothing different is
staged for it, and no commit has recorded anything else for it. Three consequences, and the
first is the one the earlier rule got wrong:

- **Committing the adoption state keeps it attributed to adoption.** That is how a repository
  retires its baseline, and it is what the documentation tells a project to do first. The
  earlier rule — any commit touching a recorded path returns it to scope — made that impossible,
  and `trace` is unwaivable, so the gate refused the one action it recommended.
- **A commit that records different content puts the path in scope**, even if the working tree is
  put back afterwards. That is the case the earlier rule existed for, and content decides it.
- **A deletion is a state, not an absence of one.** Recorded as `absent`, it stays attributed
  while it stays gone; `migrate` completes a baseline written before that, but only where git
  pairs the deletion with a recorded destination whose content still matches.

Paths leased to an open task are never recorded — that is the task's work, not the repository's
starting state. The baseline is recorded even when it is empty and survives `init --force`, so a
later run can never record newer files as if they predated adoption.

The baseline is configuration the kernel reads, like the package commands; onboarding produces
it. Recording one while tasks are open changes their digests once, and their reviews re-run.

### Worktrees and the lease hook

The builder is declared `isolation: worktree`. The hook reads `.aegis/runs/ACTIVE` and the
task manifest, and in a worktree neither exists until committed. The shipped workflow
therefore **commits the run directory before dispatch**, and the hook works there exactly as
it does in the main checkout.

Running a builder by hand without that commit leaves no write-time protection in the
worktree — the containment is then the worktree itself plus `check trace` at landing. Worth
knowing rather than discovering.

## 4. Lens selection: declared ∪ detected

```
lenses = matrix[always] ∪ ⋃ matrix[kind]   for kind ∈ (declared ∪ detected)
```

Declared kinds are a self-report: understate them and you buy speed by removing the check
that would have caught the problem. Detectors read the diff — including **removed lines**,
because deleting an authorisation call is exactly what a security lens is for and reading
only the surviving file cannot see it.

The risk tier (A/B/C) derives from the same kinds and decides the **minimum** number of
review rounds and whether an independent reviewer is required; `policy.refinement_rounds`
is the cap. Both are printed by `aegis lens plan`, and `check_reviews` enforces both.

## 5. Findings live across rounds

`finding_id = sha256(lens | path | normalised claim)[:8]` — the same claim in the same place
gets the same id on every rerun.

That makes possible what otherwise is not: dispositions (`fixed | false-positive | waived |
deferred`) carry between rounds, and a finding marked `fixed` that reappears is caught as
`reopened` and **fails the gate**. That is the two-strike rule: a defect class that survived
its fix means the mechanism is wrong — simplify it rather than patching a third time.

`fixed` requires the code to have changed. Declaring it on an unchanged tree was the
cheapest possible route to a green gate.

A blocking finding leaves the gate in one of two ways: a code change a re-review confirms, or
a person's decision. `false-positive`, `waived` and `deferred` are that decision, so `--by` must name
neither the task's builder, nor the lens that raised the finding, nor anything the gate
recognises as an agent — the rule a second strike already follows.
`waived` and `deferred` also need a waiver of check `finding` whose scope lists the finding's
id, owned by a person, with an expiry. It never mutes a check; it is the record the deferral
points at. Citing a waiver written for another check does not count: it borrowed an owner and a
date for a decision nobody recorded. `aegis next` hands such a finding to a person rather than
advising a gate that would fail.

Across rounds the ids travel explicitly. A re-review is handed the prior findings **of that
lens** by id and returns a separate `reconciled` list — `resolved` or `unresolved`, one line
of evidence — after its fresh scan, so the scan is not anchored by the prior list. Content
hashing alone assumed two runs word the same concern identically; they do not.

Three rules close the cheap routes the first dogfood review found:

- **Reconciliation is required, not offered.** A lens with open findings either reconciles
  each by id or raises it again; a report that does neither is rejected. Absence used to
  count as "fixed" after an edit, which let whoever produced the report choose the control.
- **`resolved` is measured from the last time the finding was seen**, not the first. An
  unrelated edit between rounds no longer turns a later `resolved` on unchanged code into
  a fix.
- **The second strike is a property of the finding.** A finding that came back keeps failing
  the gate — whatever later rounds say — until a human records a disposition. Kept on the
  round's record alone, a third patch followed by `resolved` erased it.

Provenance comes from the transport, never from the report: `aegis lens record --lens
<name> --reviewer <who> --digest <digest>`. A report that names a different lens is refused —
taken from the payload, a correctness run could have become the security review and closed
security's findings. A disposition records `--by`: a claim shown in review, not an
authentication, but one the gate can refuse when it names the lens, the task's builder or a
framework agent as the person closing a finding that came back.

The review budget applies to what a lens submitted in its latest round (`report_tokens`),
not to the record, which accumulates every round by design. `aegis diff <TASK>` is the one
source of the diff a reviewer reads, over exactly the files the digest covers.

## 6. Three gate stages

| Stage | When | What |
|---|---|---|
| `bootstrap` | empty project, after init | structure, banks, drift, budgets, schemas. Requires no code and no tests |
| `task` | a task is finished | checks scoped to its diff, the affected packages' commands, handoff, reviews, setup completeness |
| `merge` | a branch lands | everything, plus the full command set, requirement coverage and blocking diagram freshness |

One universal gate cannot serve all three: it either fails on an empty project, runs a
fifty-minute suite on every commit, or checks nothing before a merge. The split is what makes
the gate something people actually run.

A green task gate writes a **receipt** carrying the diff digest. `gated` means that receipt
exists and still matches; `merged` requires it too. A status anyone can type into a manifest
is not a gate.

The commit hook runs the merge gate without project commands before any git commit or push,
with one exemption: the exact command the workflow uses for its bookkeeping,

    git [add -f .aegis/runs/<TASK> && ]commit -q -m "chore(<TASK>): task manifest" -- .aegis/runs/<TASK>[ || true]

The bracketed parts are optional, `|| true` included: the workflow emits it so that a second
run of the same step is not a failure.

**The hook is not the barrier.** `aegis git-hooks install` writes a `pre-commit` and a
`pre-push` that run the same merge gate for every commit in the checkout, whoever makes it —
another agent, another CLI, a person at a terminal. Each hook bakes in the path of the CLI it
was installed from and **refuses** when that path is gone, because a gate that can be skipped
by absence is not a gate. Where hooks are not installed, CI runs the same command.

`aegis commit-scope` answers `none`, `exempt` or `gate` from the command text. Three review
rounds each found a new way through a parser that tried to decide what an arbitrary commit
would record — reading the index, a second line, `bash -c`, `GIT_INDEX_FILE`, a staged
rename, `$(…)` inside a message, git's abbreviated `--inc`, brace expansion. The parser was
deleted; an exact match has nothing to get around. Detection of a commit recognises the
ordinary spellings (`\git`, `/usr/bin/git`, a quoted `"git"`, `command git`, `-C "a path"`,
backticks, `bash -c "…"` and `eval "…"`, an inline `-c alias.x=commit`) and leaves a quoted
phrase handed to any other program alone, so `grep "git commit"` is not a commit. It is an early error, not a barrier: a shell can always build a command
no pattern recognises, which is why a merge needs a passing gate and a receipt. There is no
environment switch.

## 7. Diagram freshness by content

Each `diagrams.json` entry carries `watches` — globs of the code it describes. The gate
hashes the normalised content of those sources and compares against `verified_source_digest`.

A `last_verified` date can be set to anything. A digest cannot: it only converges if someone
actually brought the diagram up to date and ran `aegis docs attest --by <who>`. A glob that
matches no file is a finding — its digest could never change, so staleness could never be
detected.

---

## 8. Aegis has no memory system, deliberately

Claude Code offers subagents `memory: user|project|local`. **Aegis uses it in no role.**

The reason follows from "artifacts over agents". Memory outside git is not reviewable in a
pull request, not reproducible between two developers on the same codebase, not recoverable
after a crashed session, and drifts from the code with nothing in the loop able to notice.

Version-controlled artifacts do the job instead:

| Usually put in agent memory | Where it lives here |
|---|---|
| "Where I left off" | `.aegis/memory/NOTES.md` — a checkpoint, rewritten, not appended |
| "What the builder did" | `.aegis/runs/<TASK>/handoff.json`, schema-validated |
| "What review found and how it ended" | `.aegis/runs/<TASK>/reviews/*.json` with dispositions |
| "Why we decided that" | `.aegis/decisions/ADR-*.md` |
| "What exists in this project" | registries plus `generated/index/` |
| "What we learned" | a protocol, through a pull request — that is, in git, reviewed |

The result: any role can restart from nothing, and the truth is recoverable from files.

**With Claude Code's own memory.** The generated `CLAUDE.md` is thin — an index pointing at
`.aegis/`, with a hard budget. Personal memory under `~/.claude/` stays personal; Aegis does
not write there.

**With Codex and other runners.** `aegis init` also writes `AGENTS.md` and exports the
runner-neutral protocols to `.agents/skills/`, where Codex discovers them. The runner
changes; `.aegis/` and the CLI do not. Codex as a reviewer fits naturally: it returns the
same JSON shape as a lens and is recorded by the same `aegis lens record`, which makes
"the builder is never the final reviewer" literal — a different engine.

## 9. Multi-agent runners

Aegis does not compete with a runner's orchestration; it supplies the plan.

```
aegis lens plan <TASK>   →  what to fan out, and why
aegis packet <TASK>      →  each agent's prompt, deterministically
aegis lens record        →  collection, with stable ids
aegis gate --stage task  →  the barrier
```

The key property: **the plan comes from a script, not from a model's judgement.** The same
cycle therefore runs identically whether an orchestrator agent drives it, the shipped
`workflows/aegis-task.js` does, or a person types the commands. The executor changes; the
decision does not.

What more agents does **not** change: leases stay exclusive, `parallel_builders` stays a
ceiling, the barrier stays deterministic. Every one of those is checked by a script rather
than agreed to.

The converse matters more: **more agents does not improve the result by itself.** Coding
parallelises worse than research because code shares state. The ceiling comes from the
profile, not from the available budget, and `aegis metrics` shows whether the rounds paid.

### Does the orchestrator interpret correctly without a rule for every case?

Yes, and the design counts on it. The orchestrator is a capable model; it does not need
prose for every decision, it needs **unambiguous state and a next step**. Hence `aegis next`
and `aegis packet`.

The split: a script answers questions with one right answer; a model answers questions whose
answer is a judgement. Trying to mechanise the second produces regexes that cannot be
complete and break on ordinary code — that happened once with shell-command parsing, and the
right outcome was to delete the mechanism, not extend it.

## 10. Deliberately not built

- **An eval runner for protocols.** The format is described; execution is manual. Treating
  recorded expectations as automated coverage would be worse than not having them.
- **A merge queue with locking.** At a ceiling of three builders, serialisation is handled by
  a human and by leases. Building a transactional queue in advance pays for a need that does
  not exist yet.
- **Stack adapters as a plugin contract.** Detectors are configured by regexes in
  `capabilities.json`. When regexes stop being enough, false positives will say so — and
  that is when an adapter contract earns its place.
- **Cryptographic approval provenance.** "A human approved" rests on git history and code
  review, not signatures.
