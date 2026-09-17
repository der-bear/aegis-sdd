# Working notes

Owner: orchestrator. Rewritten at each milestone, not appended to — this is a checkpoint,
not a log. Keep it under the `notes` token budget in `policy.json`.

## Current milestone

**TASK-UNBLOCK-03 is merged, on branch `adopt-aegis` — not landed on `main`, not pushed.** The first full green cycle
of this dogfood — init → spec → plan → tasks → build → review → gate → merge — which is the
acceptance criterion EVALUATION §2 set. Three commits: `5dfb9e0` records the adoption state
(13 paths by name plus the staged rename), `1277dbe` is the task, and `b430e32` its merge bookkeeping. The review digest
`7942d66a9fd82cf9` did not move across the adoption commit, which is ADR-4's central claim,
now verified on the real repository rather than in a fixture.

Three lens rounds, 43 findings, all three lenses ending with zero blocking open. 213 tests.

**One thing is committed knowingly wrong, under a person-owned waiver.** `docs/ARCHITECTURE.md`
holds three claims a verification pass found false against the code. It sits inside the
digest, and the round budget was spent, so correcting it before the commit would have invalidated
the receipt and all three reviews. The owner chose to commit with it stale and owned:
`W-architecture-stale-after-cap`, Alex Derkach, expires 2026-10-02. The next task retires the
waiver by correcting the three claims on the small post-commit diff and attesting the document.

`aegis status` currently prints "2 still uncommitted and attributed to adoption". Both halves are
false: `CLAUDE.md` and `AGENTS.md` are committed, under the task. The baseline is retired — 13
paths as recorded, 2 changed under a task. That is requirement 4 of the next task.

**Landing is the owner's step, and the framework currently forces it.** Once the task was
`merged`, the pre-commit hook refused the next commit: the merge gate diffs the whole branch
against `main`, and a merged task no longer owns its 48 files. The agent's attempt to move `main`
was refused by the permission layer as a merge without review — correctly. So this file is
uncommitted until the branch lands (requirement 10 in retro 0002 records the finding).

## Decisions taken (with the ADR they became, if any)

- ADR-2, with amendments from all three cycles: root causes, sequence, and what the dogfood changed.
- ADR-3: lenses, roles and engines are data; no vendor is required. Not yet built.
- ADR-4: adoption is attributed by content, not by history — a recorded path belongs to adoption
  while the repository still holds what was recorded, absence is itself a record, and committing
  the adoption state as it stands keeps it attributed and retires the baseline.
- A changed mechanism is a new change: it gets a new task with a fresh round budget, never a
  reset counter on the old one.
- The commit hook is an early error, not a barrier. The barrier outside Claude Code is
  `aegis git-hooks install` plus CI, and a hook that cannot find its CLI refuses rather than
  passing quietly.
- A blocking review finding is closed by a code change a re-review confirms, or by a person who
  is neither the builder nor the lens (R-25). One implementation, read by the gate and by
  `aegis next`.
- A document is attested only when someone has checked it. `cli-reference` and `usage` carry an
  agent's signature and say so; `architecture` carries none, because signing a claim there is
  evidence against is worse than an unowned stale marker.

## The lesson of this cycle

**A green task gate does not imply a committable state.** Document freshness and review freshness
are independent checks over the same files, and once the round budget is spent only one of them
can be satisfied: correcting a document invalidates the reviews, leaving it uncorrected blocks
the merge. Two consecutive cycles ended in that vice, which makes it a class, and rule 5 says the
mechanism is wrong. The mechanism is **review bound to a moving working tree** — ADR-1's case,
now with a second receipt. The cheap fix available today: verify the documents *before* the last
lens round, not after.

Second: mechanical checks passing is not the documents being true. `check commands`,
`check protocols` and `check pointers` were all green while three prose claims were false.

## Next actions, in order

1. **Owner:** land the branch — `git branch -f main adopt-aegis` moves `main` to the gated
   commit without a checkout (the working tree holds this uncommitted file, so `git switch main`
   would refuse). Then `git add .aegis/memory && git commit` lands this checkpoint and retro 0002,
   and `main` moves once more. Push and review as a pull request when ready. It changed `skills/`, the protocols and the
   drafted constitution, which rule 4 says a human approves.
2. Next task: the nine requirements in `retros/0002.md`, found after the round budget was spent.
   The first is a regression this cycle introduced in the tests-ran evidence; the sixth retires
   the waiver.
3. Then TASK-UNIVERSAL-01 (bundle step 4, ADR-3). Step 5 must be rewritten as the remainder: it
   was prepared against the pre-03 tree and now overlaps what this task implemented differently.

## Open questions for the human

- Constitution: confirm or rewrite `.aegis/constitution.md#Signature`. An agent must not sign it.
- Project 2: which project of a different kind.
- Keep the adoption baseline at all? ADR-4 makes it correct; retro 0001 argues for deleting it and
  requiring a commit before the first task.
- The lens report cap of 1,000 tokens: exceeded in several rounds with nothing redundant in them.

## How to verify the current state

    make check                          # 213 tests + bootstrap gate
    scripts/aegis/aegis gate --stage task --task TASK-UNBLOCK-03 --no-run
    scripts/aegis/aegis gate --stage merge --no-run     # green; architecture waived
    scripts/aegis/aegis next
    scripts/aegis/aegis status
