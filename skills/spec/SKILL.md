---
name: spec
description: Elicit scope for a feature and write .aegis/specs/<feature>/spec.md with verifiable requirements. Use when starting a new feature or capability, before any architecture or implementation work.
argument-hint: "<feature-name>"
allowed-tools: Read, Grep, Glob, Write, Edit, AskUserQuestion
---

# Write a specification

A requirement that cannot fail a test is not a requirement. Everything here exists to make
requirements checkable.

## Interview

Ask about the goal, the boundary, and the failure modes — in that order:

1. What changes for a user when this ships? What would make it a failure?
2. What is explicitly **out of scope**? This section prevents more waste than any other.
3. What must not break — existing behaviour, contracts, performance floors?
4. Where is it allowed to be imperfect? Knowing this stops silent over-engineering.

## Write `.aegis/specs/<feature>/spec.md`

```markdown
# SPEC-<id>: <title>

## Problem and goal
## In scope / Out of scope
## User scenarios
## Requirements
R-1. <verifiable statement>
R-2. When <trigger>, the system shall <response>.
## Acceptance criteria      <!-- each maps to an R-* -->
## Edge cases               <!-- the builder's test list; lens-correctness runs them -->
## Contracts                <!-- inputs, outputs, events, invariants -->
## End-to-end check         <!-- the command or scenario that proves the feature -->
## Risks and open questions
```

Use EARS phrasing — *When \<trigger\>, the system shall \<response\>* — for behavioural
requirements. It is cheap and it removes the ambiguity that would otherwise be resolved by
an agent guessing at implementation time.

Requirement ids are permanent. `R-3` means the same thing in the tasks, in the review
findings and in the commit six months from now. Never renumber; supersede instead.

## Rules

- Every requirement is independently verifiable. "The system should be fast" becomes "p95
  under 200 ms at 100 rps" or it is not a requirement.
- No implementation in the spec. "Store in Redis" is a decision for the plan and an ADR.
- List open questions as questions. An assumption you resolved silently becomes a defect
  that only surfaces once the code exists.
- Out of scope is not optional. Write it even when it feels obvious.
- Edge cases, contracts and the end-to-end check are quoted into every task packet verbatim
  and run by the correctness lens. Write them to be executed, not read.

Finish by running `aegis check requirements --feature <name>`; it will report requirements
no task covers yet, which is expected until `/aegis:tasks` runs.
