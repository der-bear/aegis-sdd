# SPEC-3 — where the parts live, and what is deliberately not built

> Written before the work; the deletion went further than planned (see spec.md's preamble), so
> two rows below name symbols that no longer exist — `merge_receipt_files`, `_holds_recorded`,
> `FRAMEWORK_AGENT`, `_NAMES_NOBODY` — and R-26's receipt clause was moot. Kept as the plan it was.

## What already exists and must not be rebuilt

| It exists | Where | Used by R- |
|---|---|---|
| `core.default_base(ctx)` — where the branch left the mainline | `core.py` | R-17 |
| `core.is_ancestor(ctx, older, newer)` | `core.py` | R-20, R-26 |
| `checks.merge_receipt_files` + `_holds_recorded` — a receipt's content test | `checks.py` | R-17, R-26 |
| `core.in_review_scope(rel)` — the one filter for digest and diff | `core.py` | R-17 |
| `checks.is_person_name` + `FRAMEWORK_AGENT` + `_NAMES_NOBODY` | `checks.py` | R-21 |
| `flow._risk_tier(policy, kinds)` | `flow.py` | R-23 |
| `scaffold._PRE_COMMIT` — the installed hook's template | `scaffold.py` | R-25 |
| `checks.HOLDING` — claim to merge | `checks.py` | unchanged |

## Where the changes go

- `checks.py` — `_unreviewed_at_base` and the `receipted` map deleted (R-17); the generated-path
  exclusion reordered behind explicit leases (R-18); `is_person_name` separators and table (R-21);
  `merge_receipt_files` checks the task name (R-26).
- `core.py` — `files_between` deleted (R-17).
- `flow.py` — `base_sha` at the `planned → building` move (R-17); the cap escalation and
  `lens_record`'s refusal (R-19); `_land_pending` and `land` ancestry (R-20); `docs_attest` calls the
  one validator (R-21); the false comment deleted (R-22); one tier computation (R-23); `who` derived
  from the boundary rule (R-24); `task_diff` symlinks and the receipt skip (R-17, R-26); the four
  hand-rolled ancestry tests replaced by `is_ancestor` (R-26).
- `scaffold.py` — the hook's bookkeeping exemption (R-25).
- `skills/build/SKILL.md` and its vendored copy — the autonomy boundary, stated once (R-24).
- `docs/ARCHITECTURE.md` — the trust model paragraph (R-22); one place per rule (R-28); each claim
  saying which of the three kinds it is (R-29).
- `README.md` — the same claim discipline (R-29).
- `docs/EVALUATION.md` — the corrected count (R-26).
- Deleted outright: `.aegis/standards/`, `.aegis/changes/universal-01/` (R-26).

**Nothing stores new state.** No new file, no new registry, no new field in the manifest. The only
schema change is the hook template's exemption, which is a shell condition.

## Deliberately not built, with the reason

The two research reports and `leadmaster/.agents` were re-read against this spec. Most of what they
recommend and this framework lacks is declined here, not overlooked. A reader who wonders "why is
there no graph?" should find the answer in this section and nowhere else.

**The work graph — `deps`, ready frontier, `STALE`, impact reconciliation after merge.** Report-7's
central recommendation, and the plan's own trigger for building it was "a queue over ten items, or a
task blocked after start". Four tasks have run in this repository and there has never been a queue.
The trigger cannot fire, so the graph has no evidence and no way to get any: it is declined until a
project with a real backlog exists, which is the same condition as the second project. Building it
now would be the largest single mechanism in the framework, justified by a report rather than by a
measurement — the opposite of what this cycle just learned.

**Semantic edges with `confidence`, `status` and `evidence`; the six agent roles; a control-plane
database.** Report-7 itself says a 400-item project does not need Neo4j, and it names the pattern
"two reasons to create an agent". Declined for the same reason as the graph, and the framework's own
research on role fragmentation is against the roles.

**Path-scoped standards** — `.aegis/standards/<area>.md` with `applies:` globs, the pattern both
reports name (`.claude/rules` with `paths:`, Kiro's conditional steering) and the plan's D4. This is
the strongest of the declined items: routing context by the path being touched is how a monorepo
keeps a frontend task from carrying settlement rules. It is declined *now* because the packet already
routes by change kind, the framework has exactly one project, and the mechanism's whole value is
visible only when two areas have genuinely different rules. R-26 deletes the empty
`.aegis/standards/` placeholder rather than leaving a directory that reads as a delivered feature —
an empty promise is worse than an honest absence. It is the first thing to build for the second
project.

**Documentation as a projection of canonical state.** Report-7 argues docs should be generated from
the graph, not maintained by hand; this framework does the opposite deliberately and has never
written down why. The reason: a projection can only express what the schema holds, and the things
worth saying about this framework are arguments — why the barrier is CI and not the hook, why a
receipt is a record and not a signature — which no registry field carries. So documents stay
hand-written, and freshness is enforced by content digest instead of by generation (§7). R-29 makes
each claim say which kind it is, which is the honest version of the same goal: not generated, but
checkable. Recorded here because "why is ARCHITECTURE not generated?" should have an answer.

**An intake router for non-feature work, and a convergence check.** RC2 and RC5 of the plan. Both are
new mechanisms; neither has a failure behind it in four cycles. Declined.

**The eval harness.** The plan's E1, with an explicit trigger: three protocol edits with a triggering
regression, or profile L. Not met.

**ADR-1's candidate commits.** ADR-5 records why this is not the answer to the attribution class it
was proposed for, and it remains the better design for other reasons. Not this task.

## What the re-read did change

- **R-24 exists because of `leadmaster/.agents/commands/work-next.md` §5.** That file states the
  autonomy boundary in one paragraph — "resolve ordinary scope/design/lease questions autonomously
  from authority; stop only at real owner-only, external, production, irreversible or tool-permission
  boundaries" — where this framework had ten `who: human` decisions taken case by case. One rule
  replacing ten judgements is a deletion, so it passes this spec's first test, and it is the single
  clearest answer in either source to "little human participation". The same file adds two lines this
  spec adopts: a blocked step does not block other ready work, and a report is not an approval gate.
- **The declarative/procedural split is worth naming even though nothing changes here.** The memory
  report separates declarative knowledge (CLAUDE.md, ADRs, docs) from procedural (Skills);
  `leadmaster/.agents` goes further and splits the durable engine-neutral contract (`CONVENTIONS.md`)
  from the volatile runtime and vendor bindings (`PROFILE.md`), with the rule "point here; never
  inline". This framework compiles the volatile half into `.aegis/generated/` from answers, which is
  the same separation reached by a different route, and it is stronger, because the volatile half
  cannot be hand-edited. Nothing to do; worth saying in ARCHITECTURE once, under R-28.
- **Two claims the reports make that this framework already satisfies**, checked rather than assumed:
  always-on context small (CLAUDE.md ≈ 628 tokens, the AGENTS chain 5,496 bytes against a 32 KiB
  limit) and subagents as context firewalls (a lens spends its own budget and returns a report).

## Verification

Every requirement has a test, and R-27 governs all of them: a test is shown to fail on the behaviour
it forbids before it counts. In particular — R-17 needs the brownfield case that the deleted rule
refused to pass now, and the payload-before-claim case to be *in the diff* rather than refused;
R-18 needs a task owning a path under a `build/` directory; R-19 needs the cap reached with an
unmoved digest; R-20 needs a second commit after a landing; R-24 needs a `who` for each boundary in
the rule and for one case outside it; R-25 needs a commit of a retro to pass the hook while `trace` is
red; R-28 and R-29 need the document locks to fail on the text they forbid, which is where the
previous cycle's two fake locks came from.
