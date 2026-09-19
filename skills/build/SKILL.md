---
name: build
description: Run the full Aegis cycle for one task — packet, builder, lenses, refinement, documentation sync, gate. Use to implement a task that already has a manifest.
argument-hint: "<TASK-ID>"
allowed-tools: Read, Grep, Glob, Bash, Agent, Edit, Write, TodoWrite
---

# Build one task

```
packet → build → verify → review → refine → docs → gate → commit → land
```

Every step's inputs and outputs are files, so a crashed session resumes from them. If you
lose your place at any point — after compaction, after a restart, or picking up someone
else's work:

```bash
aegis next
```

It computes the next action from state on disk rather than from anything you remember.

## 1. Claim and packet

```bash
aegis task claim <TASK-ID>
aegis packet <TASK-ID>
```

`claim` starts the task: it fixes the base at the branch point, moves the task to `building`
under the parallel-builder limit, and records what the packet costs. The lease is a declaration
`check trace` reads at the merge boundary. `packet` is pure and safe to repeat.

Do not write the brief yourself. The command emits the objective, the requirement text, the
acceptance criteria, the lease, the verification commands, the boundaries and the handoff
shape — measured against the token budget. Hand-written briefs drift between tasks, which
is how two builders end up under different rules.

## 2. Build

Dispatch `aegis-builder` with the packet as its prompt. Nothing else. The builder writes
code and tests together and runs the verification commands itself before reporting.

If it returns a lease-expansion request, that is correct behaviour: decide, then either
widen `owns` and re-issue, or split the task. Never let a builder take the write and
explain afterwards.

## 3. Review

```bash
aegis lens plan <TASK-ID>
```

Hand each lens `aegis packet <TASK-ID>` and `aegis diff <TASK-ID>` — the diff over exactly
the files the digest covers.

This unions the task's declared change kinds with kinds detected from the actual diff, so a
security review still happens when authorisation moved through middleware rather than a new
route. Run exactly the lenses it names — dispatch them in parallel, each in a clean context.

**Do not touch the tree until the last of them has reported.** A report is bound to the digest
the lens was given, so an edit made while another lens is still reading refuses the report it is
about to write — and a refused report has no finding ids, so its findings cannot be reconciled in
any later round. Fix nothing, rename nothing, correct no document until every lens of the round
is in. For the same reason, verify each stale document *before* the last round the cap allows:
correcting one afterwards moves the digest with no round left to re-take.

Each lens returns JSON. Record it, attaching who reviewed and what they read — the lens
does not echo either:

```bash
echo '<json>' | aegis lens record <TASK-ID> --lens <name> --reviewer lens-<name> --digest <diff_digest>
```

The digest comes from `aegis lens plan`. Recording assigns stable finding ids, so the same
finding keeps its identity across rounds and its disposition is not lost when a lens reruns.

## 4. Refine

Severity 3+ blocks. Fix the code, then **re-review**: a finding is closed by the lens that
raised it, not by a declaration.

1. `aegis lens plan <TASK-ID>` again — the digest moved, and the set of lenses may have grown.
2. Re-dispatch each lens with the ids from **its own** record,
   `.aegis/runs/<TASK-ID>/reviews/<lens>.json`. It reviews the diff fresh first, then
   returns a top-level `reconciled` list — `resolved` or `unresolved` per prior id, with one
   line of evidence. A lens with no prior record reviews fresh and omits the list.
3. Record each report with `--reviewer` and the new `--digest`.

`aegis lens disposition` is for **dismissing** a finding, never for satisfying one:

```bash
aegis lens disposition <TASK-ID> F-1a2b3c4d false-positive --reason "the cited line is test scaffolding" --by <who>
```

A waiver is a record with a check, a scope, a reason, an owner and an expiry, written into
`.aegis/waivers.json`. It silences a check; it proves nothing, and the review of the candidate
that adds it is what judges it. The one waiver kind that is a person's decision and never yours is
`finding`.

Dismissing a blocking finding — `false-positive`, `waived` or `deferred` — is a person's
decision: `--by` names them, and the gate refuses the task's builder, the lens that raised it,
and the framework's own role names. `waived` and
`deferred` also need a waiver in `.aegis/waivers.json` with `"check": "finding"`, the finding
id in `scope`, that person as owner and an expiry. `fixed` is what a
re-review records when the code changed; a human records it by hand only after a reopened
finding's mechanism was simplified.

**Who a step needs — one rule, and `aegis next` derives every `who` in the task loop from it.** A person is
needed for an irreversible outward-facing act (a push, a pull request, a release); for a change
to what the framework measures work against that a person owns (the constitution, an answer the
interview marks never-auto, the owner of a `finding` waiver); for a question a `proposed` ADR
records with a `**Blocks:**` line; for a tool permission the runner refuses; and for an
escalation — a finding marked fixed that came back. Everything else the agent decides, records
and continues: merge and land are commands, not permissions. A blocked step does not block other
ready work, and a report is not an approval gate. Land between tasks — a gated task is committed
and landed before the next one starts — `git commit`, then `aegis land` — which keeps every base
at the mainline.

Three rules govern this loop:

- **The builder is not the final judge of its own work.** For risk tier A the reviewer must
  be a different context, and ideally a different model — and tier A needs the minimum
  number of review rounds `aegis lens plan` prints, even when the first is clean.
- **A finding that returns after being marked fixed stops the loop.** It stays flagged on
  the finding itself, the gate fails on it, and only a human disposition closes it. It means
  the mechanism is wrong; propose the simpler design instead of a third patch.
- **The round count is a signal, not a wall.** Past `policy.refinement_rounds` the gate warns
  and `next` says what the number means: a finding surviving that many rounds usually means the
  mechanism is wrong. Simplify before patching again; do not abandon the work over a number.

## 5. Documentation

The lease is a declaration: `check trace` reads it at the merge boundary, and nothing refuses a
write mid-task. The doc-manager writes under `.aegis/` and `docs/` as the orchestrator does.

Dispatch `aegis-doc-manager` with the handoff. It is the only writer of registries,
diagrams and central documents, and it runs alone, which is why parallel builders never
collide there.

## 6. Gate, commit, land

```bash
aegis gate --stage task --task <TASK-ID>
```

A green gate writes the receipt and sets `gated` itself. It runs only the checks and package
commands this diff affects, so it is cheap enough to run every time. Then:

```bash
git add -A && git commit           # a checkpoint; pre-commit checks drift and structure only
aegis land                         # the full merge gate at HEAD, the ref moved, merged written
```

`land` is the one place `merged` is written and the one place the full suite runs. It commits
its own bookkeeping. Then start the next task in a fresh context: carrying the previous task's
history costs tokens and imports its assumptions.
