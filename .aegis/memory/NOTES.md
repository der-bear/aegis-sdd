# Working notes

Owner: orchestrator. Rewritten at each milestone, not appended to — this is a checkpoint,
not a log. Keep it under the `notes` token budget in `policy.json`.

## Current milestone

**TASK-UNBLOCK-03 is gated. The merge gate is red on exactly one thing, and clearing it needs a
person.** Three lens rounds, 43 findings, all three lenses ending with zero blocking open — as in
TASK-UNBLOCK-02; what is new is that the task gate is green, which neither earlier task reached. 213 tests pass; `make lint` is clean; the task gate receipt
is bound to digest `7942d66a9fd82cf9`.

The one blocker: **`docs/ARCHITECTURE.md` cannot be honestly attested.** A read-only verification
pass against the code it watches found three claims in it that are false. Correcting them moves
the digest, and the round budget is spent, so there is no honest move left inside this task —
which is the round cap doing what it exists to do. `cli-reference` and `usage` were verified and
attested; the same pass found nothing false in them.

`ARCHITECTURE.md` is itself inside the digest — measured: adding one blank line moved
`7942d66a9fd82cf9` to `6b7a4d99a84af1c7`. So correcting the document and attesting it is **not** a
path to a green merge gate: it trades the `docs` failure for a failed `reviews` check and an
invalid receipt. Two real paths, and both need a person:

1. **Record a person-owned `docs` waiver with an expiry.** The digest is untouched, the reviews and
   the receipt stay valid, and the merge gate goes green now; the three claims are corrected in the
   next task, where they are already requirement 6.
2. **Apply the corrections and authorise a fresh review round** — only a person may spend past the
   cap — then re-gate the task and attest the document.

An agent cannot take either: a waiver owned by an agent mutes a check with nobody accountable,
which is this project's own open finding F-45e2dc3f, and re-issuing a spent round budget is the
counter-reset the cap exists to prevent. The claims, with `file:line` and fixes, are in
`retros/0002.md`.

Nothing is committed. The commits are written out and ready in the handoff's `next_safe_action`.

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

1. **Owner:** clear the `architecture` blocker (three ways above), then make the two commits from
   the handoff — adoption first, by name, never `git add -A`; then the task.
2. **Owner:** review this session as a pull request. It changed `skills/`, the protocols and the
   drafted constitution, which rule 4 says a human approves.
3. Next task: the nine requirements in `retros/0002.md`, found after the round budget was spent.
   The first is a regression this cycle introduced in the tests-ran evidence.
4. Then TASK-UNIVERSAL-01 (bundle step 4, ADR-3). Step 5 must be rewritten as the remainder: it
   was prepared against the pre-03 tree and now overlaps what this task implemented differently.

## Open questions for the human

- Constitution: confirm or rewrite `.aegis/constitution.md#Signature`. An agent must not sign it.
- Project 2: which project of a different kind.
- Keep the adoption baseline at all? ADR-4 makes it correct; retro 0001 argues for deleting it and
  requiring a commit before the first task.
- The lens report cap of 1,000 tokens: exceeded in several rounds with nothing redundant in them.
- This cycle's new one: how `architecture` gets cleared, since the cap leaves an agent no honest move.

## How to verify the current state

    make check                          # 213 tests + bootstrap gate
    scripts/aegis/aegis gate --stage task --task TASK-UNBLOCK-03 --no-run
    scripts/aegis/aegis gate --stage merge --no-run     # red on architecture only
    scripts/aegis/aegis next
    scripts/aegis/aegis status
