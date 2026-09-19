---
name: tasks
description: Decompose a specified feature into Aegis task manifests with exclusive write leases, requirement links and acceptance criteria. Use after /aegis:plan and before any implementation.
argument-hint: "<feature-name>"
allowed-tools: Read, Grep, Glob, Write, Edit, Bash
---

# Decompose a feature into tasks

A task manifest is a **write lease**. It is created before the work, not described after
it, which is what makes ownership of a changed file computable instead of arguable.

## Sizing

One task fits in one builder's context and produces one independently reviewable outcome.
If you cannot state its acceptance criteria in two lines, it is two tasks.

Split by **vertical slice**, never by layer. "Add the endpoint, its handler and its tests"
is a task. "Write all the handlers" and "write all the tests" is the split that loses the
reason each piece is shaped the way it is.

## Create each task

```bash
aegis task new TASK-042-01 \
  --feature invoicing \
  --objective "Emit invoice.finalised exactly once on finalisation" \
  --owns "src/billing/**,test/billing/**" \
  --requirements R-1,R-3 \
  --kinds code,route \
  --acceptance "duplicate finalise emits one event; unsigned webhook returns 401" \
  --size M
```

- `--owns` — the exclusive lease, held from `aegis task claim` to merge. Planning overlapping
  leases is allowed; claiming one another task holds is refused, and that refusal is the system
  telling you the decomposition is wrong. A planned task owns no file: until it is claimed,
  code under its globs belongs to no task.
- `--requirements` — which `R-*` this closes. A task closing nothing fails the gate.
- `--kinds` — from `code, test, docs, route, auth, contract, cross-module, dependency,
  data-migration, money, concurrency`. This selects the review lenses and the risk tier, so
  understating it buys speed by removing the check that would have caught the problem.
- `--acceptance` — observable criteria, semicolon separated.

## Order and parallelism

Tasks whose leases do not overlap and whose shared interface is already written in
`architecture.md` may run in parallel, up to `policy.parallel_builders`.

Fix the contract first. A task that must invent an interface another task also needs is
sequential, whatever the leases say.

## Check the decomposition

```bash
aegis task list
aegis check requirements --feature <name> --planned
```

`--planned` counts tasks that merely exist, which is what you want here: at decomposition
time nothing is built yet. At the merge gate a requirement an open task cites is *pending*;
only one that no live task cites is uncovered. Anything under-specified goes
back to the human as a question — not forward as an assumption.
