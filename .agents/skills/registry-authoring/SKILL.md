---
name: registry-authoring
description: Conventions for Aegis registries — what belongs in one, entry shape, lifecycle, and how brownfield entries are backfilled honestly. Use when adding an integration, event, environment variable, flag or diagram entry, or when adding a new registry type. Not for product documentation.
metadata: {change_kinds: [route, contract, dependency, data-migration]}
---

# Working with registries

A registry answers a question that would otherwise cost a repository-wide search with an
uncertain result: *which integrations exist, where does event X go, what reads this
variable.* Thirty lines of JSON instead of thousands of tokens of grep.

## What belongs in a registry

Only facts that live nowhere else. Before adding anything, ask where the fact already is:

| Fact | Where it belongs |
|---|---|
| Internal HTTP routes | the API schema (OpenAPI or equivalent), not a registry |
| Skills, ADRs, doc index | derived — `aegis index` generates these |
| External integration ownership, retry policy, auth mechanism | `integrations.json` |
| Cross-module event contracts | `events.json` |
| Environment variables | `env.json` |
| Feature flags and their sunset date | `flags.json` |
| Which diagram describes which code | `diagrams.json` |

A registry duplicating a canonical source is a second source of truth, and the second one
always loses.

## Entry rules

- `id` follows the registry's pattern; `status` is `proposed | active | deprecated`;
  `origin` names the task, ADR or retro that introduced it.
- **Secrets are never values.** `"secret_ref": "env:STRIPE_KEY"` — never the key itself.
- **The entry lands with the artefact, not after it.** A route without its entry fails the
  gate, which is checked mechanically against the diff.
- Sorted by `id`, one entry per block. `aegis fmt` enforces this so git merges cleanly.
- Deprecating requires `superseded_by`. Deleting an entry deletes the history of why it
  existed.

## Who writes

Builders never write registries. They put drafts in `registry_drafts` in the handoff; the
doc-manager applies them serially at the gate. That is the whole reason parallel builders do
not conflict here, and it costs nothing as long as builders respect it.

## Brownfield backfill

Scanning an existing codebase produces plausible-looking entries that are frequently wrong:
dead routes, test fixtures, generated clients, dynamically registered handlers it cannot
see, and ownership it cannot possibly know.

So backfill lands quarantined:

- `verified: "observed"` plus the path and line it came from.
- A human promotes an entry to `"confirmed"` — usually only for the surfaces that matter.
- Everything else is picked up as tasks touch it. Coverage ratchets forward.

Marking a scanned guess `active` and `confirmed` converts a guess into authority. Every
later decision then rests on it, and nobody remembers it was a guess.

## Adding a registry type

Three steps, one pull request: JSON Schema in `schemas/`, an entry in `policy.registries`,
and a row in the table above. A registry with no schema cannot be linted, and an unlinted
registry decays within weeks.
