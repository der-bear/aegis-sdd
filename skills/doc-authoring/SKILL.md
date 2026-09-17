---
name: doc-authoring
description: How Aegis documentation is written and kept true — ownership headers, one fact one home, generate-over-draw, diagram staleness. Use when writing or updating any document or diagram in an Aegis project. Not for writing protocols — use protocol-authoring.
metadata: {change_kinds: [docs, contract]}
---

# Writing documentation that stays true

Documentation is read mostly by agents. Optimise for retrieval and for not being wrong,
not for narrative.

## One fact, one home

Every document opens with two lines:

```markdown
Authoritative for: <what this document defines; nothing else may redefine these>
References only: <what it uses but does not own, each pointing at its owner>
```

Then the rule that follows from it: **if a fact has a home, link to it — never copy it.** A
copied paragraph is a second source of truth with a delayed fuse. The copy is updated, or
the original is, and after that both are quoted with equal confidence.

Feature detail lives in `.aegis/specs/<feature>/`. Central documents link there.

## Nothing outside the profile

`.aegis/generated/doc-profile.json` lists what this project requires. Documents outside that
list are not created — not a per-folder README, not a design essay, not a second
architecture overview. "It might be useful" is how a repository acquires documentation
nobody trusts and nobody deletes.

If the profile genuinely lacks something, change the profile through `answers.json` and
recompile. That is a decision with a record, not an unreviewed file appearing in a diff.

## Generate rather than draw

An ERD generated from migrations cannot drift. An API reference generated from the schema
cannot drift. Hand-write only what no generator can produce: the intent, the trade-off, the
reason this design and not the obvious one.

Register generated artefacts with `"generated": true` and a `generator` command; the gate
requires regenerating them to be diff-clean.

## Diagrams

Mermaid by default — it diffs, it renders in review, and an agent can write it. Structurizr
only when C4 levels must stay consistent by construction, and accept that it is one more
tool in the pipeline.

Every diagram is registered in `.aegis/registry/diagrams.json` with the globs it `watches`.
The gate hashes those sources and compares the digest, so staleness is detected by content
rather than by a date anyone could edit.

When watched sources move: update the diagram, then `aegis docs attest <id> --by <you>`. Attesting
without looking is worse than a stale diagram — it converts a working check into a green
light that means nothing.

## Style

Short declarative sentences. Tables over prose for anything enumerable. No narrative of how
the code came to be — that belongs in ADRs and commit messages.

Code comments carry a machine-greppable anchor and the constraint the code cannot show —
one line, with its requirement id. Never a description of what the next line does.
