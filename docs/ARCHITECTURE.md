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
        └─> .aegis/generated/rules.md
          + .aegis/generated/{policy,doc-profile,capabilities,standards,materialization}.json
```

A pure function: the same inputs always produce the same bytes. Three consequences.

**The constitution stopped contradicting itself.** It used to be both "only a human changes
it" and "materialised at init". Now `constitution.md` is written by hand and *references*
compiled policy; the compiler physically cannot write outside `generated/`.

**Drift became checkable.** `aegis check drift` recompiles and compares. A difference means
someone hand-edited generated configuration — after which every later review argues against
the wrong baseline. The `protect-paths` hook blocks that write; `aegis answer` is the way in.
That hook matches by path — `generated/`, `answers.json`, `constitution.md`, after resolving
`..` and folding case — in whatever checkout the path lies in. Both write hooks are otherwise
silent where there is no `.aegis/` at all: a hook that cannot check refuses, but only where
there is something to check.

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
- **Overwrites are detected and self-healing.** `check pointers` (task and merge gates; the
  bootstrap gate does not run it, so a pointer overwritten right after `init` is caught at the
  first task gate, not before) fails when the import line is gone; `aegis migrate` re-appends it
without touching
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

`owns` is an exclusive write lease, and **a plan is not a lease**: a task holds it from
`claim` to `merge`. Before that it is a row in a backlog — it owns no file, several planned
tasks may name the same globs, and a backlog neither blocks a merge nor claims a file twice.
Claiming a lease another task holds is what gets refused, at `aegis task claim` and at the
`planned → building` move that is the same act; code written under a planned task's globs
belongs to *no* task until it is claimed, which is stricter than attributing it to a task
nobody started. A focused task's *file-tool* writes outside the lease are refused by a hook;
a shell redirect is not, which is why `check trace` is the containment at landing. Frozen zones are
refused to every agent write, focused or not — the orchestrator and the doc-manager work
unfocused, and a zone open to them was not frozen.

The same structure solves traceability. A commit-message convention cannot say who owns a
file: a squashed branch carries two tasks and a shared helper belongs to neither. A glob
written in advance can, and `aegis check trace` requires every changed file to belong to
exactly one active task. A holding task is attributed only what its own reviewed diff
contains — `changed_files` from its `base_sha` — so a commit made before the lease started is
not silently adopted by it. A merged task is attributed only what its merge receipt recorded,
and only while the repository still holds that content. Where two records could both claim a
file, a content record beats a lease, and the earliest record wins.

Being in the diff is necessary and not sufficient. A task's `base_sha` must also agree, for
each file it claims, with what the branch inherited — unless a merge receipt on this branch
records that content, which is what an earlier task of the same branch leaves behind. Without
that rule a payload committed while the task was still a plan sits *at* the base, outside
`base..worktree`, so one later comment to the same file put the whole content inside the
lease and inside the receipt while every lens read a diff containing the comment. The
comparison is against the point where the branch left the mainline, so on the default branch —
which has no such point — it is vacuous: a check with a stated edge, not a guarantee.

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
staged for it, and HEAD holds it too — or, for a path untracked at adoption, HEAD has nothing;
HEAD and the index may also still hold what they held when the baseline was recorded, since
nothing has been recorded for the path since. Three consequences, and the
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
task manifest, and in a worktree the manifest does not exist until committed. The shipped
workflow therefore commits the task's run directory before dispatch — and the marker is never
committed, so the workflow also makes the builder's first instruction `aegis task focus
<TASK>`. With both, the hook works there exactly as it does in the main checkout.

Running a builder by hand without the commit, or without that first `focus`, leaves no
write-time protection in the worktree: with no marker, `lease_violation` returns nothing for
every path outside a frozen zone. The containment is then the worktree itself plus `check
trace` at landing. Worth knowing rather than discovering.

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
a person's decision. `false-positive`, `waived` and `deferred` are that decision, so `--by` must
name
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
  unrelated edit *before* the finding was last seen no longer turns a later `resolved` on
  unchanged code into a fix; an edit after it still counts as change, since the digest is
  whole-diff.
- **The second strike is a property of the finding.** A finding that came back keeps failing
  the gate — whatever later rounds say — until a human records a disposition. Kept on the
  round's record alone, a third patch followed by `resolved` erased it.

Which lens a report counts as comes from the transport, never from the report: `aegis lens
record --lens <name> --reviewer <who> --digest <digest>`. A report that names a different lens
is refused — taken from the payload, a correctness run could have become the security review and
closed security's findings. `--reviewer` and `--digest` are overrides: absent, the report's own
fields are used, and the digest is checked against the current change either way. A disposition
records `--by`: a claim shown in review, not an
authentication, but one the gate can refuse when it names the lens, the task's builder or a
framework agent as the person closing a finding that came back.

The review budget applies to what a lens submitted in its latest round (`report_tokens`),
not to the record, which accumulates every round by design. `aegis diff <TASK>` is the one
source of the diff a reviewer reads, over exactly the files the digest covers: one filter,
`core.in_review_scope`, answers for both, so the two cannot drift apart. `.aegis/answers.json`
and `.aegis/waivers.json` are inside it, because a change to either invalidates every review —
and because the review is the control on a waiver, which it cannot be if it never sees one.

## 6. Gates, the barrier, and authority

### Three stages

| Stage | When | What |
|---|---|---|
| `bootstrap` | empty project, after init | structure, protocols, commands, banks, drift, budgets, schemas. Requires no code and no tests |
| `task` | a task is finished | checks scoped to its diff, the affected packages' commands, handoff, reviews, setup completeness |
| `merge` | a branch lands | everything, plus the full command set, requirement coverage and blocking diagram freshness |

One universal gate cannot serve all three: it either fails on an empty project, runs a
fifty-minute suite on every commit, or checks nothing before a merge. The split is what makes
the gate something people actually run.

A green task gate — commands included — writes a **receipt** carrying the diff digest; with
`--no-run` it writes nothing and sets no status. `gated` means that receipt
exists and still matches; `merged` requires it too, and a green *full* merge gate — commands
included — writes a **merge receipt**: the commit it ran on and, for every file the task owns in
that candidate, the content it saw. A merged task keeps ownership of a file only while the file
still holds that content, which is what lets a branch take its next commit before it lands, and
what makes a later edit to the same file belong to no task. A receipt whose commit is not
behind HEAD is ignored. None of this is a signature: `.aegis/runs/` is a versioned file, below
CI and tests in the hierarchy of trust, and a receipt is the gate's record, not proof against
someone editing the record. A status anyone can type into a manifest is not a gate; a receipt
someone could type is a record the gate re-derives from, and says so.

### The barrier

**A git hook and CI, and nothing else.** `aegis git-hooks install`
writes a `pre-commit` that runs the merge gate without project commands, and a `pre-push` that
runs it with them, for every commit made in the checkout — another agent, another CLI, a person
at a terminal. The hook reads the index, which is authoritative for what a commit will contain,
so the one exemption is exact: a commit whose staged paths all lie under `.aegis/runs/` and
none of which is a receipt. Each hook bakes in the path of the CLI it was installed from, falls
back to an `aegis` on `PATH`, and refuses when neither exists — a gate that can be skipped by
absence is not a gate. Nothing parses shell commands any more: the Claude Code hook that tried
to decide what an arbitrary `git commit` would record was found a new way through in every
review round and then deleted, because two barriers running one check are two places to get
stuck. Where hooks are not installed, CI runs the same command. `git commit --no-verify` skips
a hook and not CI, which is why CI is the barrier and the hook is the early error.

**A backlog is allowed** (§3: a plan is not a lease), so at the merge stage a requirement an
open task cites is *pending*, not uncovered — one spec becoming several tasks is the ordinary
case, and only a requirement no live task cites is uncovered.

**A waiver is a record too.** `.aegis/waivers.json` is an ordinary tracked file: an entry
typed in by hand with a plausible owner loads like one `aegis waive` wrote. What the framework
does is put the file in the diff digest — so changing it re-takes every review of that
candidate — and say out loud at the gate that the candidate changed what may be waived. The
listed-checks rule binds the command, not the file; the file is bound by review and by CI.

### Also in the watched code

**Also in the watched code, briefly.** `hooks/post-edit.sh` runs the path-keyed checks after
every edit; `hooks/session-start.sh` prints `aegis status` on resume, which is the mechanism
behind "survives compaction". The adoption baseline is recorded only up to `BASELINE_CAP`
(5,000) files, and exempts nothing unless `legacy_baseline: ratchet-from-today`; above the cap
nothing is exempt either, and the answer says so. A green full merge gate clears the focused
task, and the pre-push hook runs that gate, so a push can write merge receipts as a side effect.
`task new` is serialised by a lock file; `AEGIS_COMMAND_TIMEOUT` bounds a project command.

### Authority is data

**Not the agent's to widen.** `aegis answer` is refused while a task is focused, because the
write hook refuses `.aegis/answers.json` under a lease and the command must not be a way around
its own rule. A person answers `q.core.delegate` once *and commits it* — their name and the
checks they delegate, read from `HEAD:.aegis/answers.json`, because an uncommitted answer is
writable by the agent it would authorise — and `aegis waive <check> --scope <paths> --reason
<why> --expires <date>` then records a waiver in that name, for those checks only. A `finding`
waiver is never delegated; a waiver owned by an agent makes the file invalid, and an invalid
file is a gate finding that applies nothing — reachable by a hand edit and not by the command,
which validates its candidate list first and restores the file if the result would be rejected.
Size budgets — lens reports, the handoff, `NOTES.md` — warn and never fail: a rewrite to fit a
number costs more tokens than the overage and loses what was cut. `aegis land` refuses to print
anything while the merge gate's checks — commands excluded — are red at HEAD; green, it prints
the command that moves the default branch to a HEAD a merge receipt stands behind, and moves it
only with `--run`, on a clean tree, as a fast-forward, after re-running the full gate — commands
included — at HEAD, since the receipt was earned on a working tree HEAD need not match. A
printed command is the path most people take, so it is checked before it is printed.


## 7. Diagram freshness by content

Each `diagrams.json` entry carries `watches` — globs of the code it describes. The gate
hashes the normalised content of those sources and compares against `verified_source_digest`.

A `verified_at` date can be set to anything. A digest cannot: it only converges if someone
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
