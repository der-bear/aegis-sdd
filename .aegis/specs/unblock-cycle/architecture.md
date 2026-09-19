# Architecture: unblock-cycle

## Components and responsibilities

- `scripts/aegis/aegis_cli/flow.py` — lens schema and recording, packet, claim, next.
- `scripts/aegis/aegis_cli/__main__.py` — CLI surface (`task claim`, `next --run`).
- `workflows/aegis-task.js` — the runner loop; reads `refinement_rounds`.
- hooks/pre-commit-gate.sh — deleted by SPEC-2 R-3; the git hook is the barrier.
- `skills/{build,spec,review-lens}/SKILL.md`, `agents/{aegis-orchestrator,lens-correctness}.md` — protocol text.

## Contracts and interfaces

See `spec.md#Contracts`. No public API of the framework changes shape except the additive
`reconciled` field and the additive `note` field.

## Diagrams

None required by the `library` doc profile.

## Non-functional constraints

Python 3.9+, no dependencies; every change locked by a test in `tests/test_aegis.py`.

## Decisions

- `.aegis/decisions/ADR-2-scale-and-onboarding.md` §A.
