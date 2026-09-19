# Working notes

Owner: orchestrator. Rewritten at each milestone, not appended to — this is a checkpoint,
not a log. Keep it under the `notes` token budget in `policy.json`.

## Current milestone

**The framework was over-built, and the owner said so.** The commits on `stable-01` since
`4c54474` delete more than they add (−2,981/+215 in the deletion alone) and are held by
**TASK-SIMPLE-01**, claimed after the work so the merge gate can attribute it and the branch can
land. The owner's brief, verbatim: *simple, reliable, convenient, understandable* — and *do
what is needed to 100%, do not spend tokens on ceremony*.

What went: the write hooks and everything behind them (`lease_violation`, `task focus`, `aegis
lease`); merge receipts and the merge gate's writes; the base-agreement rule; `aegis waive`,
`policy.delegation`, `q.core.delegate`; the person-name regex; `.aegis/standards/` and the
`universal-01` bundle. What replaced them: the lease is a **declaration** `check trace` reads
at the merge boundary; `merged` is written by `aegis land`, the one place it is true; a task's
base is where the branch left the mainline, so a pre-claim commit is **reviewed, not refused**;
a waiver is a record; pre-commit checks drift and structure only and pre-push runs the merge
gate; the round cap is a signal; ten `who: human` marks became one rule.

What was added, each one condition, each reproduced by a review that drove a throwaway repo
through the whole loop: `policy.mainline` and an error naming the refs when none resolves (a
`develop`-only repo refused every commit with no cause named); `next` gains a commit step and a
docs step and lands as `cli`; `land` on the mainline marks merged in place; the change-kind scan
ignores `.aegis/runs/` (a handoff saying "session" made a docs change tier A); a held lease beats
`**/build/**`.

228 tests on both invocation paths, lint clean, bootstrap gate green. A final review then
found two real losses — `land` on the mainline ran no gate, and `task status merged` was a second
writer of a one-place status — and nine circles in the loop; all closed in `fa30aba`, with the
`review`/`refine`/`docs` statuses, the dry-run `land` and the minimum review rounds cut on its list. ARCHITECTURE 4,811 →
4,476 words with §3 and §6 each one rule in one place.

## Decisions taken (with the ADR they became, if any)

- ADR-5, accepted: no sixth attribution record; the binary question — does a checkout with no
  remote trust its agent — answered **yes**, and the decision taken further by deletion.
- The trust model, stated once in ARCHITECTURE §6: every record under `.aegis/` is a file the
  agent can write; a lens report is checked for shape and digest, never content; with no remote
  the agent is trusted, with a remote CI is the barrier.
- The autonomy boundary, one rule in `skills/build/SKILL.md` §4: a person is needed for an
  irreversible outward act, an owner-owned answer, a `proposed` ADR with a `**Blocks:**` line, a
  refused tool permission, or a finding that came back. Everything else the agent decides.
- Land between tasks. A gated task is committed and landed before the next one starts.
- ADR-3 (lenses as data) is the next mechanism to build, and the last real gap for public use.

## What is still open

- **Project 2.** Until the framework runs on a project of a different kind, universality is a
  claim. This is the single most important thing left.
- ADR-3. TASK-STABLE-02 (R-9, R-10) and TASK-STABLE-03 (R-11..R-15) are planned and small.
- Push and pull request for `adopt-aegis` and `stable-01`: the owner's.
- Constitution signature: the owner's.
- The adoption baseline: 15 recorded paths, 4 still attributed. Retire by committing them as
  they are, or delete the mechanism (retro 0001's argument) — the owner's.

## How to verify the current state

    make check                          # 228 tests + bootstrap gate
    python3 tests/test_aegis.py         # the same 228
    scripts/aegis/aegis next
    scripts/aegis/aegis status
