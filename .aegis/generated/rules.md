# Agent rules (compiled — edit answers.json, never this file)

Project truth lives in `.aegis/`. Read `.aegis/generated/index/INDEX.md` before
searching the tree, and run `aegis next` to get the current step.

Rules always in force:

1. Every change belongs to a TASK with an exclusive write lease. No task, no code.
2. Code and its tests are written together, by the same agent. Done means the
   verification commands ran green, not that they should.
3. An event, environment variable or feature flag exists only once it is in
   `.aegis/registry/`; a route exists only once it is in the API contract.
4. Never edit `.aegis/generated/` (compiled) or `.aegis/constitution.md`
   (human-owned). Change configuration with `aegis answer <question> <value>`.
5. Review findings are resolved or explicitly dispositioned; a finding that
   returns after being marked fixed means the mechanism is wrong — simplify it.
6. Between unrelated tasks, start a fresh context.

Profile: M · parallel builders: 2 · testing mandate: tests-with-code

Agents decide alone: code-style, internal-refactors. Everything else escalates.

Frozen zones (never modify): docs/spec-v0.3-original.md

Verification commands the gate runs:

- aegis-sdd — lint: `make lint` · test: `make test`
