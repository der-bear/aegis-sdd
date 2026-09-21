# Working notes

Owner: orchestrator. Rewritten at each milestone, not appended to — this is a checkpoint,
not a log. Keep it under the `notes` token budget in `policy.json`.

## Current milestone

**The framework was over-built, and the owner said so. It is simpler now, and landed.** The
commits on `stable-01` since `4c54474` delete more than they add (−2,981/+215 in the deletion
alone); **TASK-SIMPLE-01** holds them, passed six review rounds at frozen digests, and `aegis land`
moved `main` to `a9d4097` and marked it merged. The owner's brief, verbatim: *simple, reliable, convenient, understandable* — and *do
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

At that point, 232 tests on both invocation paths, lint clean, bootstrap gate green. A final review then
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

- **Project 2 ran** — `domain-hunter`, a brownfield Python service, on branch `aegis-adopt`, 2026-09-19:
  init → detect → constitution → spec → task → claim → build → handoff → review (pass), with no
  engine change; four first-hour frictions became R-32..R-36. The task gate then met another
  agent's concurrent uncommitted work in the same tree and reported it as unowned, with that
  agent's tests red — the two-builders-one-tree collision, shown rather than absorbed. Nothing was
  committed or landed there.
- TASK-FIRSTHOUR-01 (R-32..R-36): three review rounds by Fable at frozen digests — round 1 four
  blocking (a non-UTF-8 README aborted init, the old template still stopped the task gate, a quiet
  `@test:` recipe was missed, the shebang probe read whole files in text mode), round 2 one
  (re-running `init` for a missing constitution rebuilt the ledger and brought the human step
  back), round 3 the cap. Re-run read-only on an archive of domain-hunter with the new code: the
  adopter's CLAUDE.md warns, the constitution carries the README's first paragraph, the gate runs
  `just test`/`just lint` and no `mypy`, no standards stub, and the first `next` is "specify the
  first feature [agent]".
- TASK-LAND-01 (R-37): the push of TASK-FIRSTHOUR-01's landing was refused by the framework's own
  pre-push gate — after `land` the task is merged and `origin/main` is behind until the push, so
  the landed files belonged to no task. `default_base` now prefers the local mainline when it is
  ahead of the remote one; two review rounds; landed 9f9787f and pushed; CI green (35477214032).
- Declined in writing (TASK-FIRSTHOUR-01, round 3, sev 1/0, all in scaffold.py, one line each):
  `***`/`___` thematic breaks in the rule regex; the CLAUDE.md pointer test should be the marker
  (`@.aegis/generated/rules.md`) as `migrate` uses, not the word "aegis"; the constitution
  template's `## Amendment` section still asks for a human-reviewed PR; drop `islink` and keep the
  realpath test. No task carries them yet; TASK-STABLE-03 (the correctness leftovers of retro 0002) is the natural carrier.
- 2026-09-21, three tasks landed and pushed, CI green on each: TASK-STABLE-02 (R-9 per-lens
  staleness by the kinds that moved, with the record remembering what each file was; R-10 the
  doc-manager verifies and attests under its own name — three rounds), TASK-STABLE-03 (R-11..R-15
  and the declined lines: the go no-run suffix behind coverage text, the owner's exec bit as git
  reads it, the pointer marker, the literal pathspec — three rounds), TASK-LENSES-01 (ADR-3: lenses,
  roles and engines are data; `lenses/<name>.md`, two auditor profiles, `aegis lens prompt`,
  `external-lens.sh` for any engine; the historical package from 1277dbe applied with two anchors
  redone — three rounds). Per-lens staleness paid for itself the same day: two cap rounds ran one
  lens instead of three.
- Declined in writing, one line each, for the next task that touches the lens tooling:
  flow.LENS_NAME duplicates config.LENS_FILE_NAME (import the twin); external-lens.sh's 100 KB
  stdin threshold counts characters, not bytes (`wc -c`); the workflow's `grep -c FAIL` over
  `check docs` reads an exit-2 error as zero doc work (the task gate still refuses).
- Published: https://github.com/der-bear/aegis-sdd (public, MIT); `main` pushed through the
  pre-push gate on 2026-09-19, and the first CI run of the merge gate was green in 1m12s.
- Constitution signature: the owner's.
- The adoption baseline: 15 recorded paths, 4 still attributed. Retire by committing them as
  they are, or delete the mechanism (retro 0001's argument) — the owner's.

## How to verify the current state

    make check                          # 279 tests + bootstrap gate
    python3 tests/test_aegis.py         # the same 279
    scripts/aegis/aegis next
    scripts/aegis/aegis status
