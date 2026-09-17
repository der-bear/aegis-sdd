---
name: audit
description: System health audit for an Aegis project — configuration drift, budget overruns, stale diagrams, expired waivers, orphaned protocols, and whether the profile still fits. Use on a schedule or before a release, not during a task.
allowed-tools: Read, Grep, Glob, Bash, Write
---

# Audit the framework itself

Everything else checks the product. This checks whether the framework is still earning its
cost.

## 1. Deterministic sweep

```bash
aegis gate --stage bootstrap --no-run
aegis check drift
aegis check budget
aegis check registry
aegis check docs --closing
aegis index
```

Anything red here is a fact, not an opinion. Fix it before continuing.

## 2. Hygiene

- **Waivers.** Expired ones surface as warnings. A waiver renewed twice is not a waiver, it
  is a decision nobody wants to make — take it.
- **Registries.** Entries `proposed` for a long time, `deprecated` with no `superseded_by`,
  entries still `verified: "observed"` on surfaces the project now depends on.
- **Protocols.** Skills that never fired across the last milestone are paying metadata rent
  on every turn for nothing. Skills that always fire together should be one.
- **CLAUDE.md.** Inside budget, and still only rules that are always true. Anything
  conditional belongs in a skill.
- **NOTES.md.** A checkpoint, not a log. If it grew, it is being appended to rather than
  rewritten.

## 3. Does the profile still fit?

Upgrade S → M when tasks routinely need more than one refinement round, or two people are
working at once. Upgrade M → L when three or more independent work streams are real.

**Downgrade too.** If L machinery is not paying for itself — parallel builders idle, lenses
passing without findings, doc-manager touching nothing — drop to M. A framework that cannot
shrink becomes the bloat it was built to prevent, and the team routes around it instead of
saying so.

## 4. Report

Write `.aegis/memory/audit-<date>.md`: what is red, what is drifting, what to change, and
explicitly what was checked and found healthy. Propose changes as pull requests.

State plainly what this audit could not verify. A health report that only lists what it
looked at reads as a clean bill of health for everything, including what it never opened.
