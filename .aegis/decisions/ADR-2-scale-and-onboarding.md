# ADR-2: Scaling Aegis to large, heterogeneous projects — root causes, sequence, and onboarding

Status: accepted — scope A + B; C–E are hypotheses gated on the first dogfood retro

## Context

Six adversarial audit rounds verified internal coherence (EVALUATION §2), and ADR-1 accepted a
v2 reorganisation around candidate commits with the verdict "dogfood before refactor". What
neither examined is whether Aegis scales to the projects it is for: a brownfield SaaS with a
455-row work queue and a 612k-word spec corpus (leadmaster), a greenfield service, a library,
a data pipeline — driven by Claude Code and Codex alike.

Sources for this decision: the Graph-Orchestrated SDD report (Sept 2026), the Claude Code /
Codex memory and context-engineering report (Sept 2026), seven months of agentic development
on leadmaster (`.agents/`, `foundation/22 §16`, playbooks with dated incidents), GitHub
spec-kit, cc-sdd v3, kiro-style-sdd, the v0.3 specification and the research that produced it.
The full analysis, in Russian, is the plan this ADR condenses.

## Root causes (not symptoms)

| # | Cause | Evidence |
|---|---|---|
| RC1 | **Work has no graph.** A task is a lease plus requirement ids: no `deps`, no computed ready frontier, no STALE, no reconciliation after merge | leadmaster `ledger:next`; report-7 late-dependency discovery |
| RC2 | **The only entry point is a feature spec.** Bugs, refactors, spikes, doc-only work, "extend an existing spec" have no protocol | cc-sdd `/kiro-discovery`, spec-kit bug/assess |
| RC3 | **Enforcement exists in one runner**, and the structural containment (`isolation: worktree`) contradicts experience | hooks live in `hooks/hooks.json`; leadmaster banned worktrees after two data-loss incidents |
| RC4 | **Onboarding is half-honest.** `detect:`/`auto-if-detected` are decorative; `init` is not idempotent (1 vs 5 ledger rows); the brownfield path of spec §7.4 was never built | `scaffold.initialise`, `config.interview` |
| RC5 | **No convergence.** Nothing is recomputed after a merge; spec and code drift silently | spec-kit `converge`/`analyze` |
| RC6 | **Growth without deletion.** Protocol triplication, vestigial statuses, two round budgets, `AEGIS_SKIP_GATE`, side effects in `packet` | ADR-1: "4,000 of 5,500 lines go" |

Cross-cutting: the handoff and NOTES.md are reports, not inputs to the next computation.

## Decision

Sequence everything after ADR-1's verdict. **Approval covers A and B.** Each item in C–E names
the evidence from B that justifies building it.

### A — unblock one real cycle (v1 patches)

1. Lens reports carry explicit reconciliation: the runner passes prior finding ids, the lens
   returns `reconciled: [{id, followup: resolved|unresolved, evidence}]` as a top-level field;
   findings keep `additionalProperties: false`. Two ordered phases: fresh scan, then reconcile.
2. One round budget: `policy.refinement_rounds` is the only cap; the risk tier sets
   `independent_reviewer` and a minimum, never a maximum.
3. `feature.md` is removed as an artifact; `Edge cases`, `Contracts`, `End-to-end check` live
   in `spec.md` and the packet reads them there.
4. ADRs live in `.aegis/decisions/` only (this file is the first consequence).
5. `aegis packet` is pure; `aegis task claim` focuses, starts, and records the packet metric.
6. `aegis next` emits structured steps (`command` + `note`, `who ∈ cli|agent|human`);
   `--run` executes only self-contained CLI steps — no comment parsing.
7. `AEGIS_SKIP_GATE` is deleted, with a test lock, for the reason `AEGIS_ALLOW_PROTECTED` was.
8. The orchestrator no longer runs `task status gated` after a green gate.
9. The framework's own `answers.json` is completed and its constitution drafted for human
   signature — the first dogfood finding, not preparation for it.

### B — dogfood (no new mechanisms)

Project 1: Aegis on itself. Success: one green cycle `init → spec → plan → tasks → build →
review → gate → merge` (EVALUATION §2). Project 2: a project of a different nature on profile S
(a library or CLI), verifying that a new project type is one JSON file and that S loads none of
the M/L machinery. Measure: tokens per task by kind, rounds, lens acceptance (≥30%), manual
gate bypasses, and — by hand until C2 — blocked-after-start, late hard-dependency discovery,
reopen rate. Output: `.aegis/memory/retros/0001.md`.

Known blocker for B: the baseline tree is untracked, so every task gate fails `trace`.
Committing the baseline is a human decision.

### C — v2 kernel (ADR-1) plus the minimal graph primitive

- **C1** Candidate commits, derived status. *Amends ADR-1 §Decision 2:* attestations are
  git-tracked files under `.aegis/runs/<TASK>/attest/<sha>.json`, not git notes — notes do not
  sync by default and silently break "recoverable from a clone" (ADR-1 second opinion).
- **C2** `deps:` in the manifest (task ids and/or contract ids from registries). `aegis next
  --queue [--count N]` computes the ready frontier — deps merged ∧ no lease overlap with
  in-flight work ∧ contracts stable ∧ acceptance present — ranked, parsed outside the model
  context (leadmaster `ledger:next`). *Evidence: ≥1 task blocked after start in B, or a queue
  >10 that became unmanageable by hand.*
- **C3** STALE is derived, never stored: a task is stale when a dependency's merged commit is
  not an ancestor of its `base_sha`, or a contract it depends on changed after `base_sha`.
  `task claim` becomes the preflight. Action: rebase or re-plan, never a silent build.
- **C4** `SPEC_CAPTURED` as a derived state in `check requirements`: requirement specified,
  no task yet.
- **C5** Discovery items: `kind: discovery`, no lease on source, output is `deps` edges, an ADR
  or `[NEEDS CLARIFICATION]`; run by `aegis-explorer` under a `discover-deps` protocol —
  **not a new role.**
- **C6** Impact reconciliation inside `gate --stage merge`: which tasks became ready, stale or
  superseded, computed from `deps` and `owns ∩ changed`. A script, not an agent.
- **C7** Handoff v2 keeps only inputs to the next computation: `new_deps` (→ frontier),
  `open_questions` (→ ledger / spec markers), `invalidated_assumptions` (→ ADR status or spec),
  `next_safe_action` (→ NOTES.md). Machine-known facts are never echoed (ADR-1).
- **C8** Worktree conflict resolved: worktrees stay as the container, with (a) a BASE-GATE as
  the packet's first line — `pwd` and `git rev-parse HEAD` must equal `manifest.base_sha`, STOP
  otherwise; (b) zero git-mutation authority for builders (`reset/rebase/clean/gc/prune/force`);
  (c) a vendor-neutral barrier: in v1 a git `pre-commit` hook (`aegis git-hooks install`) with
  the runs-only exemption; **in v2 `pre-commit` cannot be the barrier** because candidates are
  made with `git commit-tree` — the barrier is the *land* step validating `(candidate,
  attestations)` before anything is reachable from the target branch, with `pre-push` and CI as
  the second line. This also closes Codex parity: never skip a gate because a vendor wrapper is
  unavailable.
- **C9** Deletions: protocol triplication → one body in `skills/`, adapters ≤70 words in
  `.aegis/protocols/` and `.agents/skills/`, `check adapters`; vestigial `review/refine/docs`
  statuses (or the whole transition table, per ADR-1); decorative `detect:` fields — either
  `detect.py` emits every key the banks name, or the fields go; the second round budget;
  `AEGIS_SKIP_GATE`; `packet` side effects.

**Deliberately not built from report-7:** edge entities with confidence/evidence/status, six
new agent roles, a control-plane database, semantic candidate retrieval. Reasons: the two
reasons to create an agent (ARCHITECTURE §0), the role-fragmentation finding in the research
that produced Aegis, a ceiling of three builders. Revisited only under E2.

### D — optional modules, outside the kernel, with their own budgets

- **D1 Onboarding** (see below).
- **D2 Intake router** `/aegis:intake`: `feature | bug | refactor | spike | doc | ops |
  extend-spec` → which artifacts are mandatory, from a deterministic table in `policy.json`;
  classification by a model with human confirmation. A bug needs a failing reproduction before
  the fix and no spec; a spike is a discovery item; doc-only leases only docs; extend-spec runs
  `validate-gap` first.
- **D3 Convergence and analyze-lite** `aegis check converge --feature F`: script passes —
  requirements without tasks, tasks without requirements, changed files outside any task,
  remaining `[NEEDS CLARIFICATION]`/`TBD` markers (fail before tasks), duplicate ids,
  requirements without acceptance; model pass — `lens-design closing` classifies `missing |
  partial | contradicts | unrequested`; output is an append-only block of tasks
  `derived-from: converge`. `--before-extend` is the brownfield `validate-gap`.
- **D4 Path-scoped context**: `.aegis/standards/<area>.md` with `applies: [globs]`; the packet
  includes standards whose globs intersect `owns`, plus recent commits touching `owns`;
  `check budget` enforces Tier-1 = packet + standards + cited protocols ≤ 6,000 tokens
  ("pointers route, never chain"). Vendor-neutral steering; `.claude/rules/` stays the team's.
- **D5 NOTES.md with a schema** (`state_of_world` in plain prose, `active_task`, `last_gate`,
  `blocked_by`, `open_questions`, `next_action`), validated by `check notes`; plus a
  `PreCompact` / `SessionStart(compact|resume)` hook that re-injects the NOTES pointer, the
  active task and the open-findings count.
- **D6 Executable truth and ratchets**: assert-tests-ran (the gate needs evidence tests
  executed — a runner-reported count, not an exit code; `"test": "true"` passes today);
  `check commands` (every command a protocol cites exists); coverage and token ratchets with a
  named measurement epoch; `check invariants` for `INV-*` declared in the constitution.
- **D7 Retro as a graduation pipeline**: metrics + findings + handoff open questions → a draft
  PR to a protocol or standard; a lesson that changed the process leaves only a pointer in
  memory, and the rule cites the dated incident.
- **D8 Codex parity**: `check budget` counts the `AGENTS.md` chain (32 KiB); adapters; the git
  hook of C8 as the one barrier all runners share.
- **D9 Warm profiled builders by context boundary** (owner's observation; leadmaster
  `PROFILE.md` "Persistent profiled team"): manifests get `cluster` (default: `feature`); the
  orchestrator keeps one named builder per cluster and continues it for the cluster's next
  tasks instead of spawning fresh; `aegis packet <ID> --delta-from <PREV>` sends only what is
  new. Rules: warmth only inside a cluster sharing a lease family (rule 6 — fresh context
  between *unrelated* tasks — already allows this); lenses are always fresh; a handoff is
  written per task so warmth is an optimisation, never a dependency; context above 70–80% →
  checkpoint and respawn. Profile by context boundary (api / frontend / data), not by SDLC
  role. Metrics: tokens per task cold vs warm, context rediscovery rate.
- **D10 Root-cause pass in a clean context on the second rejection** (cc-sdd `kiro-debug`):
  the second refine round runs the builder fresh under a cause-first protocol, not the same
  context patching a third time; `reopened` still escalates to a human.

### E — deferred, with triggers

| Item | Build when |
|---|---|
| Eval harness (`.aegis/evals/`, headless runs, "merge only if evals ≥ baseline") | ≥3 protocol edits with a triggering regression, or profile L |
| Edge entities with confidence/evidence | late-dependency discovery stays high after C2 |
| `audit --upgrade-check` (S→M→L and back) | the first project that outgrows S by B's metrics |
| Control-plane DB / merge queue | never at a ceiling of three builders (ARCHITECTURE §10) |
| Dedicated Dependency / Convergence / Verification roles | refused; protocols on existing roles |

## Onboarding

Agent-led onboarding is needed, and it already exists — detection, interview-as-data and the
pure compiler are among the strongest parts of v1. The optimisation is not more questions:

1. **Honest detection → answer.** Either `detect.py` emits every key the banks reference and
   `interview()` resolves `auto-if-detected:0.N` at the declared threshold, or the fields are
   removed. `bank-lint` fails on a `detect:` key `detect.py` does not emit.
2. **Idempotent `init`.** Re-running refreshes `detected`, keeps human answers, recomputes the
   ledger deterministically; test: init twice → identical `answers.json`.
3. **Lazy configuration by area.** Init asks only `core` + project type + brownfield context.
   Questions marked `deferrable:<area>` surface at the first task whose `owns` touches the
   area: `task new` emits ledger rows that block `packet` (the existing "unreviewed ledger
   blocks phase 3" mechanism); the orchestrator runs `aegis interview --area <x>`; standards
   with `applies:` are created then. A library never sees route or event registries.
4. **The brownfield path of spec §7.4:** `architecture.md` from code with `observed |
   inferred` labels; registries back-filled as candidates for batch confirmation; frozen zones
   into the constitution and `protect-paths`; `changes/<id>/` delta mode; `validate-gap` before
   extending a spec; for a large spec corpus, an ownership table (`docs.json` with
   `owns_topic`) that `/aegis:spec <topic>` consults first — a double definition is drift.
5. **The profile decides which modules load.** S: kernel + onboarding-lite + one lens; M:
   + registries + doc profile + retro; L: + convergence + ratchets + audit.

Onboarding never writes to `.claude/rules/`, `~/.claude/` or `.codex/`; never generates
placeholder documents to fill a template; never auto-resolves `never-auto` questions.

## Acceptance (converging criteria, from EVALUATION §2)

- Zero BLOCKING against the pre-agreed list A1–A9 — not zero from a fresh audit.
- One green `init → merge` cycle on Project 1; a second on Project 2 without engine changes.
- N days of team work with no manual gate bypass; A7 removes only the env switch — Bash
  bypass and non-Claude runners remain until C8 and are counted separately.
- After C2: blocked-after-start, late-hard-dependency discovery and reopen rates trend down
  between Project 1 and Project 2.
- Lens acceptance ≥ 30%; Tier-0 ≤ 3,000 tokens per runner, Tier-1 ≤ 6,000, measured by
  `check budget`.

## Open decision

Where the graph primitive (C2–C6) is built: in the v2 rewrite (recommended — STALE and status
are both derived from git and fit candidate commits) or patched into v1 if B shows the queue
becomes unmanageable before v2 exists. ADR-1's second opinion bet on finding reconciliation as
the first v2 piece; the evidence gathered here puts A1–A3 before it, and those are v1 patches.

## Amendments from the first dogfood cycle (2026-09-17)

- **B built one mechanism.** B could not run at all on an uncommitted tree: every file counted
  as the first task's change. The adoption baseline (`core.changed_files`, recorded by `init`
  and `migrate`) was built to run B. It is configuration the kernel reads — onboarding produces
  it, the kernel consumes it like the package commands, and without it the scope is the plain
  git diff. Recording one while tasks are open changes their digests once.
- **RC4 overstated `init`.** Three runs in a scratch repository produce byte-identical
  `answers.json` from the second run on; the "1 versus 5 ledger rows" came from this repository's
  own stale answers file. The idempotency test is kept as a lock.
- **RC3 and D8 named a vendor.** "Codex parity" means any runner that is not Claude Code; the
  second reviewing engine is configuration and may be absent (ADR-3).
- **D9 on lenses.** A lens stays independent of the builder and fresh per task, but may be
  continued across the rounds of one task: the second round ran that way, reconciled all
  sixteen first-round findings with evidence and found fifteen new, real defects.
- **Two classes survived two review rounds**: bypasses of the commit hook's exemption, and the
  bookkeeping of review state (last-seen digest, second strikes, provenance, lens identity). The
  first was simplified by deletion. The second is the bookkeeping ADR-1 removes with candidate
  commits — the empirical evidence ADR-1 asked for before choosing its first piece.

## Amendments from the re-issued cycle (TASK-UNBLOCK-02, same day)

- **The round cap did its job, and the abandon-and-re-issue path is how a simplification lands.**
  TASK-UNBLOCK-01 stopped at three rounds with seven blocking findings in one class. The
  mechanism was simplified by deletion, and the change was re-issued as a new task with a fresh
  budget and fresh lenses — not as a fourth round on the old one. Its handoff maps every open
  finding to the change that answers it. The rule this adds: **a changed mechanism is a new
  change; a reset counter on the old one is a bypass.**
- **Fresh lenses are worth what independence costs.** On code that had just passed three rounds,
  three fresh lenses found fifteen findings, six blocking, including a fourth way through the
  hook's exemption (the exact match compared whitespace-flattened text, and a newline ends a
  command). D9's rule stands: warm across the rounds of one task, fresh per task.
- **New requirement, R-25: authority over a blocking finding.** It is closed by a code change a
  re-review confirms, or by a person who is neither the builder nor the lens — `false-positive`,
  `waived` and `deferred` all require that name, and the latter two also a `finding` waiver
  naming the id. One implementation, read by the gate and by `aegis next`. This closes the gap
  the first cycle found: the gate's own hint told a task to write a waiver the schema could not
  hold.
- **The adoption baseline is the weakest mechanism in the framework, and a candidate for
  deletion.** It produced findings in both tasks, its remedy text was wrong (committing a
  baselined path returns it to the scope of every task based before that commit), and it cannot
  cover a deletion at all. The alternative is smaller: require a commit before the first task
  and let the git diff be the scope, which is ADR-1's direction. Deferred to the owner because it
  changes what adopting on a dirty tree means. Evidence: `.aegis/memory/retros/0001.md`.
- **A report-size cap of 1,000 tokens is not calibrated per lens.** Nine of the eighteen rounds
  across the two tasks exceeded it while saying nothing redundant, and in the re-issue it was the
  design lens in all three of its rounds — a design finding has to quote the document it
  contradicts, while a correctness finding names a line. The measurement stays; one number for
  every lens is the part to reconsider.

## Amendments from the review of the whole session (TASK-UNBLOCK-03, same day)

Three fresh auditors read the session's code, its documents, and its fidelity to the two research
reports and the plan. Twenty-eight findings; what they change about this document:

- **The adoption baseline is rebuilt, not deleted — see ADR-4.** Attribution is by content, so
  committing the adoption state keeps it attributed to adoption. The old rule made the remedy this
  ADR itself recommended impossible, because `trace` is unwaivable and refused the adoption commit.
  Deleting the mechanism outright stays the owner's open question; the argument for it is in
  retro 0001.
- **RC3 is closed in its v1 form, and only now.** `aegis git-hooks install` writes a `pre-commit`
  and a `pre-push` hook, and the framework's own CI runs the merge gate. Before this, every claim
  of runner parity rested on a Claude Code hook, which sees only what Claude Code runs. C8's v2
  barrier — the land step over a candidate commit — is still not built.
- **RC4 is closed.** Two shipped questions declared detection keys the scanner never produced, so
  `auto-if-detected` on them could never fire. Detection now publishes one table, the bank lint
  holds every `detect:` key to it, and the interview reads the threshold each question declares.
- **One guarantee was not one.** "The gate fails when a package declaring tests did not run them"
  compared two values derived from the same field and could never fire. Evidence now comes from the
  runner's own output, and it is labelled a heuristic, because a runner nobody recognises produces
  `unknown` rather than a pass.
- **A document's commands are now checked.** `aegis check commands` holds every `aegis …` quoted in
  a protocol, a profile or the README to what the parser accepts. It found four cases, in two
  shipped protocols, that could not run as written.
- **The sequence changes.** The graph (C2–C6) was first; the evidence says the barrier is. Every
  defect class in both dogfood cycles comes from reviewing a moving working tree or from
  enforcement living in one runner — and C2's own trigger cannot fire, because one task is not a
  queue. Order: the barrier (done in v1 form), then ADR-3, then B2, then ADR-1's land step, then
  the graph when there is a queue to measure it on.

## Consequences

Approving A + B adds one piece of configuration the kernel reads — the adoption baseline, built
during B (see the amendments) — and removes an environment override, a second round budget, a
phantom artifact, a side effect and the index form of the commit hook's exemption. C–E are recorded so that B's retro has something
concrete to confirm or refute; none of them is built on the strength of this document alone.
