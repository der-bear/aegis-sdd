# SPEC-2: Stable autonomy — the gate blocks on correctness only

## Problem and goal

The first full cycle on this repository (retro 0002) showed that half of its friction was the
framework's own doing: size caps that made an agent rewrite a handoff five times and told a
lens to drop a finding; a `merged` status that blocked the next commit until a person moved
`main`; waivers that only a person could own, requested one at a time; two barriers running one
check; three false claims in a document that no mechanical check could see. The owner's
definition of optimal is the goal: **it works stably, needs little human participation, does
not over-restrict the agent, and never makes it rewrite an artefact because it came out over a
token count.**

## In scope / Out of scope

In scope: the friction items and the correctness findings of retro 0002, as three tasks on one
spec. Out of scope: candidate commits (ADR-1), lenses/roles/engines as data (ADR-3), bundle
step 5, deleting the adoption baseline, rule 4 of CLAUDE.md — each is the owner's decision or
comes after these.

## User scenarios

An agent finishes a task whose lens reports run long; the gate warns and passes. The merge gate
goes green; the agent commits again on the same branch without anyone touching `main`. A stale
document is verified and attested by the doc-manager. A check that a person has delegated is
waived in that person's name with an expiry, and the loop continues. A docs-only fix after a
code review re-runs one lens, not three.

## Requirements

### Task 1 — friction

R-1. Size budgets on lens reports, handoffs and NOTES shall be warnings at every gate stage,
     never failures; the thresholds stay as the warning line. No protocol, prompt or hint shall
     tell a lens to drop, shorten or reorder a finding for size.
R-2. When the next review round would exceed `policy.refinement_rounds`, `aegis next` shall
     emit a `human` step that says what was tried, never a step to re-run a lens.
R-3. The Claude Code commit hook shall be deleted — `hooks/pre-commit-gate.sh`, its entry in
     `hooks/hooks.json`, `commit_scope` and its tests, and the workflow's reference — so that
     the git pre-commit hook and CI are the one barrier every runner shares.
R-4. A green full merge gate shall record a merge receipt holding the commit it ran on and,
     for each file the task owns in that candidate, the content it saw. A merged task shall own
     a scope file only while the file still holds that content, so its own commits stay
     attributed to it before the branch lands and a new edit to the same file belongs to no
     task. `aegis land` shall print the command that moves the default branch, and run it only
     when asked to, only with a merge receipt at or before HEAD, and only on a clean tree.
R-5. Delegation shall be data: a core interview question shall write `policy.delegation` with
     the owner's name and the checks an agent may waive in that name. A waiver's owner shall
     pass the same person test as a finding disposition; an agent may record a waiver in the
     delegated owner's name only for a listed check, and only with an expiry and a reason.
     Every existing agent-owned waiver shall be re-owned under the delegation or deleted.
R-6. A task shall hold its write lease from `claim` to `merge`, and not before: several planned
     tasks may name overlapping globs, a planned task shall own no file and shall be asked for
     neither a handoff nor a review, and claiming a lease another task holds shall be refused.
     Code under a planned task's globs therefore belongs to no task until it is claimed. At the
     merge stage a requirement an open task cites shall be reported as pending, not uncovered;
     uncovered shall mean that no live task cites it.
R-7. `aegis diff` shall show every file the digest covers, `.aegis/answers.json` included; the
     installed git hooks' run-directory exemption shall not cover `gate-receipt.json` or
     `merge-receipt.json`; `--by` and a waiver's owner shall share one validator that refuses a
     name shorter than three characters or one the framework knows as an agent.
R-8. The documents shall say what the code does: the three claims in `docs/ARCHITECTURE.md`
     that retro 0002 records as false are corrected; `docs/EVALUATION.md` §8 records three
     rounds and how the third cycle ended; `README.md` lists `compile`, `scaffold`,
     `lease check --path`, `lease show`, `check all`, `--root`, `gate --task|--no-run` and
     `check --task|--base|--feature`; the CI workflow states its claim once. `architecture` is
     attested after a verification pass, and `W-architecture-stale-after-cap` is deleted.
     (`lease check --path` rather than the `lease check|show` this requirement first said: the
     verification pass found that the bare form raises "`aegis lease check` needs --path", so the
     spelling the requirement asked for was the misleading one. The requirement changed on
     evidence, and the evidence is this sentence.)
R-16. The build protocol shall state that the tree is not edited between dispatching a round of
     lenses and the last of them reporting, and shall say why in one sentence, because a lens
     report is bound to a digest and an edit made while a lens is reading refuses the report it
     is about to write. Receipt: in this task's second round, two complete reports — correctness
     and security — were refused by `aegis lens record` because the builder applied the third
     lens's fixes while the other two were still reading. Their findings have no ids and never
     will. The verification pass over each stale document shall happen *before* the last round
     the cap allows, for the same reason: correcting a document afterwards moves the digest with
     no round left to re-take.

### Task 2 — review scope

R-9. A lens's record shall be stale only when the change since its digest touches a file whose
     detected kinds include one that triggers that lens. Per-lens scope shall be derived from
     the diff at check time, never stored. The task-gate receipt shall still cover the whole
     diff. A file under `skills/`, `.agents/`, `agents/` or `hooks/` shall count as code
     whatever its suffix.
R-10. The doc-sync protocol shall include a verification pass over each stale document's
      watched sources, after which the doc-manager attests it with `--by aegis-doc-manager` and
      a note naming what was checked. No step shall require a person to attest routinely.

### Task 3 — correctness findings of retro 0002

R-11. `tests_ran` shall classify `ok <pkg> … [no tests to run]` as `none`, shall match a bare
      `PASS` only as `^--- PASS:`, and shall list `no tests to run` among the no-run phrases.
R-12. `_digest_in_index` shall query the path as a literal pathspec, and both sides of the
      symlink key shall decode the target with `os.fsdecode`.
R-13. `aegis status` shall report the adoption baseline by attribution: how many recorded paths
      are still attributed, how many changed under a task, and retired when none is pending.
R-14. An executable regular file shall be keyed `exec:<sha256>` on both sides of the adoption
      comparison; a bare hash already recorded shall still be accepted.
R-15. On a push to the default branch, the CI workflow shall diff against the push event's
      before-commit, or state which half of the gate the push job runs.

## Edge cases

- A report far over the warning line (say ten times) still warns: size is not correctness.
- A merge receipt whose commit is not an ancestor of HEAD (a rebase, or a file copied in by
  hand) is ignored, not trusted; the receipt is a record, not a signature.
- A backlog of planned tasks over the same globs neither blocks a merge nor claims a file twice.
- A waiver whose owner is the delegated person but whose check is not listed is rejected.
- Delegation absent: a waiver still needs a person's name; nothing changes for that project.
- A docs-only change touching `skills/*.md` re-stales every lens, because a skill is code.

## Acceptance criteria

Each requirement is locked by a named test class; the list is completed as the tasks build.

- R-1: `SizeBudgetsWarn`. R-2: `NextEscalatesAtTheCap`. R-3: `TheGitHookIsTheOnlyBarrier`.
- R-4: `AMergedTaskDoesNotBlockTheBranch` (including a receipt from another history and a
  second task under the same globs), `AMergedLeaseIsNotAPermanentExemption`.
- R-5: `DelegationIsData`. R-6: `AnOpenTaskCoversPending`, `APlannedTaskOwnsNothing`,
  `ALeaseIsExclusiveWhileHeld`. R-7: `TheDiffShowsWhatTheDigestCovers`,
  `TheReceiptIsNotExempt`, `ANameIsAPerson`, `TheFirstSecurityReviewOfStableAutonomy`.
- R-8: `TheDocumentsSayWhatTheCodeDoes` locks the greppable half — the README command list, the
  rounds row in EVALUATION, the CI header stating its claim once, and no document promising a
  refusal at `task new`. The prose half is locked by the read-only verification pass and
  `docs attest`, and by `W-architecture-stale-after-cap` leaving the waiver file.
- R-9: `LensStalenessIsScopedByKind`, `ASkillEditRestalesEveryLens`. R-10: `TheDocManagerAttests`.
- R-11 to R-15: `TheRound3CorrectnessFindings`.
