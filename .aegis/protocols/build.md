---
name: build
description: Run the full Aegis cycle for one task — packet, builder, lenses, refinement, documentation sync, gate. Use to implement a task that already has a manifest.
argument-hint: "<TASK-ID>"
allowed-tools: Read, Grep, Glob, Bash, Agent, Edit, Write, TodoWrite
---

# Build one task

```
packet → build → verify → review → refine → docs → gate
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

`claim` starts the task: it focuses it, so the write hook refuses any edit outside its
`owns` globs; moves it to `building` under the parallel-builder limit; and records what the
packet costs. Without focus the lease is a sentence in a prompt, and a prompt is not an
invariant. `packet` is pure and safe to repeat.

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

Dismissing a blocking finding — `false-positive`, `waived` or `deferred` — is a person's
decision: `--by` names them, and the gate refuses the task's builder, the lens that raised it,
and any name it recognises as an agent. `waived` and
`deferred` also need a waiver in `.aegis/waivers.json` with `"check": "finding"`, the finding
id in `scope`, that person as owner and an expiry. `fixed` is what a
re-review records when the code changed; a human records it by hand only after a reopened
finding's mechanism was simplified.

Three rules govern this loop:

- **The builder is not the final judge of its own work.** For risk tier A the reviewer must
  be a different context, and ideally a different model — and tier A needs the minimum
  number of review rounds `aegis lens plan` prints, even when the first is clean.
- **A finding that returns after being marked fixed stops the loop.** It stays flagged on
  the finding itself, the gate fails on it, and only a human disposition closes it. It means
  the mechanism is wrong; propose the simpler design instead of a third patch.
- **Rounds are capped** by `policy.refinement_rounds`. Exhausting them escalates to a human
  with what was tried — it does not start another round.

## 5. Documentation

```bash
aegis task focus          # release the lease first
```

The lease forbids writes under `.aegis/`, which is precisely what the doc-manager must do.
Dispatch it only after the focus is cleared.

Dispatch `aegis-doc-manager` with the handoff. It is the only writer of registries,
diagrams and central documents, and it runs alone, which is why parallel builders never
collide there.

## 6. Gate

```bash
aegis gate --stage task --task <TASK-ID>
```

A green gate sets the task to `gated` itself — running the status command afterwards would
re-run every check for nothing.

The gate runs only the checks and package commands this diff affects, so it is cheap enough
to run every time. The full suite runs once, at merge:

```bash
aegis gate --stage merge
```

Then commit with the task id in the message and start the next task in a fresh context.
Carrying the previous task's history costs tokens and imports its assumptions.
