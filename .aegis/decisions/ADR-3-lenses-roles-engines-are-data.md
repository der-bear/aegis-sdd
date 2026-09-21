# ADR-3: Lenses, roles and engines are data; code only computes the plan

Status: accepted — implemented in TASK-LENSES-01 (2026-09-21)

## Context

The owner asked, during the first dogfood cycle (2026-09-17): are the lenses the same for every
project? Can there be two builders, or other roles? Should this be code at all, or skills with
agent profiles? And: "I will not always have Codex — why is a Codex lens its own setting?"

What v1 does today:

- `LENS_MATRIX` is a constant in `config.py`: three strictness tables mapping change kinds to three
  lens names. A project cannot add a lens without editing the framework.
- Each of the three lenses is its own agent profile (`agents/lens-{correctness,security,design}.md`),
  although two of them differ only in focus text.
- `scripts/aegis/codex-lens.sh` hard-wires one vendor, and the README has a "Claude and Codex"
  section, as if a second engine were a fixed part of the design.

What the sources say:

- The Graph-Orchestrated SDD report: a role "does not necessarily mean a different model; it is
  first of all different permissions, protocol and output schema". Its Agent Registry holds role,
  model class, allowed tools, permissions and protocol version — data, not code.
- The memory and context report: procedures belong in Skills, a portable open format with
  progressive disclosure; subagents are context firewalls, not new kinds of thing.
- Leadmaster: one parameterised `contract-reviewer` profile with remits; "no new profile per
  edit/lens"; "a lens is not a spawned agent".
- ARCHITECTURE §0: an agent exists for a tool set and a model; everything else is a protocol.

## Decision

1. **A lens is a data file.** `lenses/<name>.md` ships with the framework; `.aegis/lenses/<name>.md`
   belongs to a project and wins on a name clash. Frontmatter: `name`, `description`, `executes`
   (whether it must run commands), `applies` (`always`, `kinds`, `paths`), `from_strictness`
   (`minimal | standard | strict`) and optional `project_types`. The body is the focus: what this
   lens looks for, in the terms of the review-lens contract.
2. **Two auditor profiles replace the per-lens profiles**: `lens-auditor` (read-only) and
   `lens-runner` (may execute the test suite). A lens uses the one its `executes` names. The focus
   reaches the auditor through `aegis lens prompt <TASK> <lens>`, which assembles the contract, the
   focus, the lens's own prior findings, the packet and `aegis diff` — deterministically, for any
   engine.
3. **The fan-out stays a script.** The compiler turns lens files, the strictness and answers such
   as `pii` into `policy.lens_matrix`, drift-checked like every other compiled field; `aegis lens
   plan` unions the lenses whose `kinds` or `paths` match. Adding a lens is one file and no engine
   change — the same acceptance test as a new project type (ADR-2 §6.2).
4. **Project-type packs contribute lenses**: web-saas → accessibility, data-etl → data-integrity,
   money and concurrency kinds → money-integrity, library → public-API compatibility. A project like
   leadmaster adds its own: tenancy, consent.
5. **Roles are instances, not profiles.** Two builders are two instances of `aegis-builder` within
   `parallel_builders` and non-overlapping leases; a cluster keeps one warm instance (ADR-2 D9). A
   new profile is justified only by a different tool set or permission boundary.
6. **Engines are data.** The second reviewing engine is an answer (`q.core.second-engine` →
   `capabilities.external_reviewer`), and it may be empty. `scripts/aegis/external-lens.sh <TASK>
   <lens> <engine-label> -- <command …>` runs any CLI that takes a prompt and prints JSON — Codex,
   Gemini CLI, Claude, OpenCode, a local model — and records the report with `--lens` and
   `--reviewer <engine-label>`. `codex-lens.sh` stays as a thin wrapper with Codex defaults. Risk
   tier A needs a reviewer that is not the builder; a second engine strengthens that, and is never
   required.
7. **What stays code** is what has one right answer: matching triggers to a plan, the report
   schema, finding identity and reconciliation, the gates.

## Consequences

- Deleted: the `LENS_MATRIX` constant (it becomes derived data), the three per-lens profiles (replaced
  by two auditor profiles and three lens files carrying the same focus text), vendor names in the
  shipped documentation.
- Existing review records stay valid: lens names do not change.
- A project lens with a vague focus produces noise; the lens acceptance rate (≥ 30%) and the retro
  decide whether to sharpen or remove it, exactly as for a shipped lens.
- Warm lenses: a lens may be continued across the rounds of one task — it keeps its own reading
  of the diff and reconciles its own findings — but never reviews work it helped build, and starts
  fresh on the next task. The first dogfood cycle's second round ran this way (EVALUATION §8).

## Rejected alternatives

- Let projects add a profile per lens — a profile per remit is what leadmaster banned, and it
  duplicates tool configuration that should live in one place.
- Let the orchestrator model choose the lenses — the fan-out would vary between runs; the plan must
  be computable.
