---
name: init
description: Initialise Aegis SDD in this repository — detect what the code already says, ask only what it cannot, then compile the configuration. Use when setting up Aegis in a new or existing project, or when re-running setup after answers change.
argument-hint: "[--mode interactive|hybrid|autonomous] [--profile S|M|L]"
allowed-tools: Read, Grep, Glob, Bash, Write, Edit, AskUserQuestion, Agent
---

# Initialise an Aegis project

**Detect → Confirm → Ask → Materialize.** Setup that asks first wastes the human's
attention on facts already sitting in the repository.

## 1. Detect and scaffold

```bash
aegis init
```

One command reads manifests, lockfiles, CI configuration and the Makefile, then scaffolds,
compiles and indexes. It establishes packages with their real test and lint commands,
project type, environment variables, routes, migration and test paths.

Read what it printed, then get the conversation:

```bash
aegis interview
```

This is the whole interview, already decided: which questions the detector could not
answer, in batches of three, irreversible decisions first, each with its default and the
reason it is being asked. Do not invent questions and do not reorder — that is how two
projects end up configured by different conversations.

## 2. Confirm what was read

`aegis interview` prints a `confirm` block: everything detection established with high
confidence. Show it as **one screen**, not as questions. The human corrects what is wrong.

## 3. Ask the rest

One batch at a time with `AskUserQuestion`. Show each question's `why` — a question whose
purpose is invisible gets answered carelessly. "I don't know" is a valid answer: take the
default, and it stays in the ledger for later.

Record every answer through the CLI, never by editing files:

```bash
aegis answer q.core.autonomy-limits '["code-style","internal-refactors"]'
```

The values are validated against the question, so a typo is refused rather than compiled
into configuration that silently means nothing.

Mode changes only how much you ask. `hybrid` (default) leaves the batches above.
`autonomous` asks nothing: everything auto-resolves into the ledger, questions marked
irreversible take their conservative default and set `status: provisional`, which blocks
phase 3 until a human clears them. `aegis init --yes` accepts the ledger wholesale and
records that a person did so.

## 4. Adapt to the project's shape

The question set is not fixed. It composes: `core` always, plus the pack for the detected
project type, plus `context/brownfield` when there is existing code. A web SaaS is asked
about tenancy and the frontend model; a data pipeline about personal data and schema
evolution; a library about its compatibility promise. Nothing else is asked.

A new kind of project is one JSON file in `interview/project-type/`, usually with
`extends`. Neither the agents nor the engine change — that is what makes the framework
adapt rather than accumulate special cases.

## 5. Finish

```bash
$EDITOR .aegis/constitution.md   # a human writes this; agents never touch it
aegis gate --stage bootstrap
aegis next
```

`aegis next` tells you the next action at any point from then on — computed from state on
disk, so it survives compaction, a different runner, and Monday morning.

## Brownfield

On an existing codebase, dispatch `aegis-explorer` **after** `aegis init`. It does not
repeat detection; it reports what a scanner cannot decide — actual conventions with
evidence, contradictions between them, freeze candidates, and which detected surfaces are
load-bearing enough to register now.

If most of the repository is untracked, `init` records an adoption baseline: those files are
outside task scope while they stay unchanged, so the first task is judged on its own work.
It is an adoption aid, not history — recommend committing the tree before the first task.

Do not backfill registries wholesale. Static scanning cannot tell a live route from a dead
one, and a registry of guesses is worse than an empty one because the guesses now carry
authority. Register what matters, mark the rest `verified: "observed"` with its evidence
path, and let coverage ratchet forward as tasks touch the code.

## Definition of done

- `aegis gate --stage bootstrap` is green on the fresh project.
- `aegis interview` reports nothing left to ask, or the ledger is explicitly accepted.
- The constitution is written by a human — `aegis check setup` fails while it is the
  template.
- A hook demonstrably fires: try to edit `.aegis/generated/` and confirm it is refused.
  An untested hook is a hook that does not exist.
