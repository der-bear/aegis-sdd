---
name: plan
description: Compare architecture options for a specified feature and write architecture.md plus an ADR. Use after /aegis:spec and before /aegis:tasks, when the approach is not already obvious.
argument-hint: "<feature-name>"
allowed-tools: Read, Grep, Glob, Write, Edit, Agent, Bash
---

# Choose and record an architecture

## 1. Generate options in parallel

Two or three options, each explored by a separate read-only subagent in a clean context.
This is legitimate parallelism: the paths are genuinely independent, so nothing is
duplicated by exploring them at once.

Give each subagent the spec, the NFR priorities from `.aegis/generated/policy.json`, and
one angle to take — for example simplest-thing-that-works, lowest-operational-risk,
most-extensible. Each returns at most 400 words: approach, what it costs, what it forecloses.

**The comparison criteria come from the spec's NFR priorities.** Do not invent criteria at
comparison time; that is how the option someone already preferred wins.

## 2. Decide, and record what you rejected

Write `.aegis/decisions/ADR-<n>.md`:

```markdown
# ADR-<n>: <decision>
Status: accepted
## Context
## Decision
## Consequences
## Rejected alternatives
- <option> — <one line: why not>
```

The rejected alternatives are the valuable part. Six months from now the question will be
"why not the obvious thing?", and this is the only place that answers it.

## 3. Write `architecture.md`

```markdown
# Architecture: <scope>
## Components and responsibilities
## Contracts and interfaces      <!-- the precondition for parallel builders -->
## Diagrams                      <!-- only what doc-profile.json requires -->
## Non-functional constraints
## Decisions                     <!-- links to ADRs -->
```

**Contracts are the load-bearing section.** Two builders can work in parallel only where a
written interface separates them. Anything left implicit here becomes a merge conflict with
opinions attached.

## 4. Diagrams

Only those `.aegis/generated/doc-profile.json` requires. Mermaid by default: it diffs, it
renders in review, and an agent can write it.

Register each one in `.aegis/registry/diagrams.json` with the globs it `watches`, then
`aegis docs attest <id> --by <you>`. A diagram that watches nothing can never be detected as stale,
which means it will quietly stop being true.

Prefer generating over drawing: an ERD from migrations and an API reference from schemas
cannot drift. Draw only the intent no generator can express.

## Gate

`aegis check requirements --feature <name>` and a `lens-design` pass in `closing` mode over
spec versus architecture. Contradictions here are cheap; the same contradiction found during
implementation is not.
