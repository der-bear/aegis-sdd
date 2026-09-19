# Working notes

Owner: orchestrator. Rewritten at each milestone, not appended to — this is a checkpoint,
not a log. Keep it under the `notes` token budget in `policy.json`.

## Current milestone

**TASK-STABLE-01 is abandoned, and the framework's own rule is what abandoned it.** Branch
`stable-01`, off `adopt-aegis` at `458eb78`. One commit, `e8bbace`, carries the round's evidence;
the 21 code and document files are uncommitted because the gate refuses them. Seven of its sixteen
requirements converged with every finding closed — R-1, R-2, R-3, R-5, R-7, R-8, R-16. R-4 and R-6,
the attribution half, did not: the class produced a blocking finding in every round of this task and
of the two before it, and in round 3 correctness and security found *opposite* failures of one rule
in one round — it refuses legitimate work on a brownfield branch that diverged before adoption, and
its trust root is a local ref an agent can move with one command. Rule 5 says the mechanism is
wrong, and rule 5 is what the task obeyed.

**ADR-5 decides what to do, and leaves the owner one binary question.** Revised 2026-09-19 after an
independent review: the next task deletes the base-agreement rule, sets a task's base at the branch
point so a pre-claim commit is *reviewed* instead of refused, and states the trust model in a
paragraph. Hours, four records instead of five, and it answers the brownfield refusal by inclusion —
the owner's "do not over-restrict the agent", paid for by deleting code. The question that is not
mine: **does a checkout with no remote trust its agent?** Nothing in v1 or v2 can tell the agent
moving `main` from the owner moving it, so the answer decides whether the two `who: human` steps
become `cli` or whether a remote becomes a precondition for the guarantees.

**The tree stays as round 3 read it** because the next task starts by deleting that rule, not because
moving it would destroy evidence.

255 tests, `make lint` clean, the bootstrap gate green, all four documents attested,
`W-architecture-stale-after-cap` deleted. After the abandonment `trace` correctly reports forty
files as belonging to no task. Retro: `.aegis/memory/retros/0003.md`.

## Decisions taken (with the ADR they became, if any)

- ADR-2, with amendments from all four cycles: root causes, sequence, and what the dogfood changed.
- ADR-3: lenses, roles and engines are data; no vendor is required. Not yet built.
- ADR-4: adoption is attributed by content, not by history — a recorded path belongs to adoption
  while the repository still holds what was recorded, absence is itself a record, and committing
  the adoption state as it stands keeps it attributed and retires the baseline.
- A changed mechanism is a new change: it gets a new task with a fresh round budget, never a
  reset counter on the old one.
- A plan is not a lease. A task holds `owns` from `claim` to `merge`; several planned tasks may
  name the same globs, and code under a planned task's globs belongs to no task.
- A merged task keeps a file only while the file still holds what its merge receipt recorded.
  That is what lets a branch take its next commit before it lands.
- Authority is data, and the data must be older than the decision it authorises: `aegis waive`
  reads the delegation from `HEAD:.aegis/answers.json`, never from the working tree.
- Size budgets warn and never block. A rewrite to fit a number costs more tokens than the overage
  and loses what was cut — the owner's two reasons. This file and the handoff are both over.
- A document is attested only when someone has checked it, and an agent that checked one may sign
  for that.

## The lesson of this cycle

**Do not touch the tree between dispatching a round and the last lens reporting.** A report is
bound to the digest the lens was given; an edit while another lens reads refuses the report it is
about to write, and a refused report has no ids, so its findings can never be reconciled. Two
reports, lost in one afternoon. Now R-16, in the protocol, with its receipt.

Second: a test written to lock a document claim counts only once it has been shown to fail on the
bad text. Both of this cycle's first attempts passed on the very text they were written to
correct — one harvested words from descriptions, the other looked for a number anywhere in a
table row. Both were verified red-then-green this time, and the same discipline caught a real
regression an hour later, when restructuring the README broke the command list.

Third: the residual of a check belongs in the document, not in the reviewer's head. The
base-agreement rule in `check trace` is vacuous on the default branch, and ARCHITECTURE §3 says so.

## Next actions, in order

1. **Owner:** answer ADR-5's fork. Everything else waits on it.
2. Then the converging task: delete `_unreviewed_at_base` and the three `default_base` findings with
   it, fix the one false number in EVALUATION §8 (27, not 43 — its own records and metrics say so),
   take R-16's script half (record the dispatched digest at `lens plan`; let `lens record` store a
   stale-marked report instead of discarding it), and the nine advisory findings mapped in
   TASK-STABLE-01's handoff under `findings_to_steps`.
3. Then TASK-STABLE-02 (R-9, R-10) and TASK-STABLE-03 (R-11..R-15, plus `templates/**` and the CI
   template's divergent claim, recorded in TASK-STABLE-01's `lease_expansion_request`).

## Open questions for the human

- Constitution: confirm or rewrite `.aegis/constitution.md#Signature`. An agent must not sign it.
- Project 2: which project of a different kind.
- Keep the adoption baseline at all? ADR-4 makes it correct; retro 0001 argues for deleting it and
  requiring a commit before the first task.
- Push and pull request for `adopt-aegis` and `stable-01`: not done, and not to be done without
  the owner. Both changed `skills/`, the protocols and the drafted constitution.

## How to verify the current state

    make check                          # 255 tests + bootstrap gate
    python3 tests/test_aegis.py         # the same 255, which is what R-16's neighbour locks
    scripts/aegis/aegis gate --stage task --task TASK-STABLE-01 --no-run
    scripts/aegis/aegis gate --stage merge --no-run
    scripts/aegis/aegis next
    scripts/aegis/aegis status
