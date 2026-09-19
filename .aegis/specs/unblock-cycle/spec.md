# SPEC-1: Unblock one real Aegis cycle (ADR-2 group A)

## Problem and goal

No task has ever completed the shipped loop on a real project: refinement rounds are rejected
by the lens schema, the refine loop has zero iterations for tiers B and C, the packet reads a
file nothing writes, and the framework's own configuration is provisional. The goal is a loop
that can run end to end on this repository, so that dogfood (ADR-2 §B) measures the framework
rather than its defects.

## In scope / Out of scope

In scope: the nine v1 patches of ADR-2 §A, their tests, and the protocol and documentation
lines that describe the changed commands. Out of scope: candidate commits (ADR-1), the graph
primitive, onboarding rework, any new agent role.

## User scenarios

An orchestrator runs `aegis next` after a first review found a blocking issue, dispatches the
builder, re-runs the lens with the prior finding ids, records the report, and reaches a green
task gate without hand-editing any run file.

## Requirements

R-1. When a lens report contains a top-level `reconciled` list, `aegis lens record` shall
     accept it, mark each `resolved` prior finding fixed only if the code changed since it was
     raised, keep `unresolved` ones open, and flag `unresolved` on a finding already marked
     fixed as reopened.
R-2. `aegis lens plan` shall expose `refinement_rounds` from policy as the only round cap, and
     the shipped workflow shall read that field.
R-3. When `spec.md` has `Edge cases`, `Contracts` or `End-to-end check` sections, the packet
     shall include them; `feature.md` is no longer read.
R-4. ADRs shall live in `.aegis/decisions/` and appear in the generated index.
R-5. `aegis packet` shall have no side effects; `aegis task claim` shall focus the task, move
     it to `building`, and record the packet metric.
R-6. `aegis next` shall emit a bare executable `command` and a separate `note`, and `--run`
     shall execute only self-contained CLI steps.
R-7. The pre-commit gate hook shall have no environment override.
R-8. The orchestrator profile shall not instruct `aegis task status <ID> gated`.
R-9. The framework's own `answers.json` shall have no unresolved ledger rows and its
     constitution shall not be the scaffolded template.

Added by the first dogfood gate and the first lens round (ADR-2 §B):

R-10. When `aegis init` or `aegis migrate` runs and `legacy_baseline` is `ratchet-from-today`,
      it shall record what the repository holds at each uncommitted path once — excluding paths
      leased to open tasks and framework-derived copies, recorded even when empty, and kept by
      `init --force`. (Amended by TASK-UNBLOCK-03: attribution is by content, and R-27 states
      it. The clause this requirement used to carry — exempt only while no commit since the
      baseline head has touched it — is deleted, because it made the adoption commit impossible.)
R-11. Documentation files shall not be scanned for environment reads, surfaces or routes,
      and protocol, agent-profile, frozen and shared files shall not be reported as
      unrequested documentation.
R-12. The packet and `aegis lens plan` shall report the same risk tier for the same diff.
R-13. When the last ledger row is answered, `answers.json` status shall become `complete`.
R-14. The commit hook shall exempt exactly one command, the workflow's bookkeeping commit
      `git [add -f .aegis/runs/<T> && ]commit -q -m "chore(<T>): task manifest" --
      .aegis/runs/<T> [|| true]`; every other command it recognises as a git commit or push —
      including `\git`, a path to git, a quoted "git", `command git`, an option with a quoted
      value, `$(…)` or backticks, the quoted command of `sh -c`/`bash -c`/`eval`, and an inline
      alias — shall
      run the gate. (Amended by TASK-UNBLOCK-02: the parser that decided what an arbitrary
      commit would record was deleted after three review rounds.)
R-15. The lens-report budget shall be measured on the report a lens submitted in its latest
      round, and the review-lens protocol shall state the limit.
R-16. When a lens has open findings on a task, a new report from it shall reconcile each by
      id or raise it again; `resolved` shall close a finding only if the code changed since
      the finding was last confirmed present; a kept disposition shall keep who made it and
      why; a finding that came back shall keep failing the gate until a person records a
      disposition (R-21).
R-17. A refused `aegis task claim` shall leave the focus and every status unchanged, and a
      claim shall report the status the task is actually in.
R-18. A task shall not pass review with fewer rounds per lens than its risk tier's minimum.
R-19. The shipped workflow shall hand each lens only the prior findings from its own record,
      and every documented `aegis lens record` command shall attach `--lens`, `--reviewer` and
      `--digest`.

Added by the second lens round:

R-20. `aegis lens record` shall take the lens from `--lens` and reject a report that names a
      different lens.
R-21. `aegis lens disposition` shall require `--by`; a finding that came back shall stay blocking
      until a disposition whose `--by` is not the task's builder and not a name the framework
      recognises as an agent or engine: `lens`, `lens-*`, `aegis-*`, `claude*`, `codex*`,
      `gemini*`, `gpt-*`, `opus*`, `sonnet*`, `haiku*`, or any `engine:model` label containing a
      colon. The name is a recorded claim, not an authentication.
R-22. `aegis diff <TASK>` shall emit the diff over exactly the files the digest covers, and the
      workflow and the Codex runner shall use it instead of rebuilding it.
R-23. A frozen zone shall be refused to every agent write, focused or not, and trace shall not
      exempt a change inside one.
R-24. The workflow shall dispatch a builder only for a `fix` step; a `record` document shall
      never be reported stale; the Codex runner shall reconcile its own prior findings.

Added when TASK-UNBLOCK-01 reached its round cap and was re-issued as TASK-UNBLOCK-02:

R-25. A blocking review finding shall be dismissed — `false-positive`, `waived` or `deferred` —
      only under a `--by` name that is neither the task's builder, nor the lens that raised it,
      nor one R-21 recognises as an agent; `waived` and `deferred` shall
      also need an unexpired waiver of check `finding` whose scope names the finding's id and
      whose owner is such a name. A waiver of any other check shall not defer a finding, a
      `finding` waiver shall list only finding ids, and `aegis next` shall hand an undecided
      dismissal to a person.
R-26. Task scope shall include both sides of a staged or committed rename, and agent edits to
      `.aegis/answers.json` shall be refused; it changes through `aegis answer`.

Added by the review of the whole session, before the first commit (ADR-4):

R-27. The adoption baseline shall attribute a path to adoption by content, not by history: a
      recorded path shall be outside every task's scope while what the repository holds for it
      now — in the working tree, in the index and at HEAD — is either what was recorded or what
      the baseline head held. Intermediate history shall not be consulted: a path whose current
      state equals adoption has nothing left to attribute, and the commits that took it there
      are in the log. Absence in the index while a removal is staged shall not count as
      adoption. A path absent at adoption,
      including the source side of a pending rename, shall be recorded as absent and stay
      attributed to adoption while it is absent. The exemption shall apply to every scope the
      gate builds, including the staged half of the merge candidate. `aegis migrate` shall
      complete a baseline that predates the absent record only where git pairs the deletion with
      a baselined destination whose content still matches, and `aegis status` shall report a
      baseline retired once every recorded path matches HEAD.
R-28. Every protocol, pointer file and measured number shall say what the code does: the
      project's own `CLAUDE.md` shall be the pointer template rather than a second copy of the
      rules, `AGENTS.md` shall point at the compiled rules, every `aegis …` command quoted in a
      document shall run as written, a lens profile shall not ask the model for provenance the
      transport attaches, the figures in `README.md` shall be the ones `aegis budget` prints, and
      the counts in `docs/EVALUATION.md` shall be the ones the run artefacts hold.

## Acceptance criteria

- R-1: a second-round report with `reconciled` is recorded (exit 0); a `resolved` entry whose
  code did not change stays open; `unresolved` on a fixed finding appears in `reopened`.
- R-2: `aegis lens plan` JSON has no `review_rounds` key; `workflows/aegis-task.js` does not
  match `review_rounds`.
- R-3: a packet for a spec with `## Edge cases` contains that section.
- R-4: `generated/index/decisions.json` lists ADR-1 and ADR-2.
- R-5: after `aegis packet`, the manifest is still `planned` and no `ACTIVE` marker exists;
  after `aegis task claim`, both are set.
- R-6: no `next` command contains `#`; `--run` executes a `gate` step.
- R-7: superseded by SPEC-2 R-3 — the Claude Code commit hook was deleted, and the git hook
  it left behind has no environment switch (`TheGitHookIsTheOnlyBarrier`).
- R-8: `agents/aegis-orchestrator.md` contains no `task status` line.
- R-9: `aegis check setup` passes except for the constitution signature note.
- R-10: `AdoptionRatchetsFromToday`, `MigrateBaselinesOutsideOpenLeases`.
- R-11: `test_documentation_examples_are_not_environment_reads`,
  `test_procedure_and_frozen_files_are_not_unrequested_documentation`.
- R-12: `test_the_packet_and_the_lens_plan_agree_on_the_risk_tier`.
- R-13: `SetupStatusIsDerivedFromTheLedger`.
- R-14: `TheCommitHookExemptsOnlyBookkeeping` — the command table and the hook run for real;
  `test_an_inline_alias_for_commit_is_a_commit`,
  `test_brace_expansion_cannot_ride_the_bookkeeping_exemption`.
- R-10 as amended, and R-27: `AdoptionIsAttributedByContent`, `TheRenameBackfillNeedsItsProof`,
  `TheAdoptionCommitIsPossible`, `ABaselinedFileLeavesTheBaselineOnceCommitted`.
- R-15: `TheReviewBudgetMeasuresTheReport`.
- R-16: `ReviewFindingsCannotBeClosedCheaply` (reconcile required, last-seen digest, second strike).
- R-17: `test_a_refused_claim_leaves_the_running_task_focused`,
  `test_claim_reports_the_status_the_task_is_actually_in`.
- R-18: `test_a_tier_a_change_needs_its_minimum_review_rounds`.
- R-19: `ProtocolsSayWhatTheCodeDoes`.
- R-20: `test_a_report_cannot_choose_which_lens_it_counts_as`.
- R-21: `test_a_finding_that_came_back_blocks_until_a_human_closes_it`,
  `ALensCannotCloseItsOwnSecondStrike`.
- R-22: `test_the_task_diff_covers_exactly_what_the_digest_covers`,
  `test_the_workflow_and_codex_take_the_diff_from_aegis`.
- R-23: `test_a_frozen_zone_is_refused_to_an_unfocused_agent_and_trace_sees_it`.
- R-24: `test_the_workflow_dispatches_a_builder_only_for_a_finding`,
  `test_a_record_document_is_never_stale`, `test_codex_reconciles_its_own_prior_findings`.
- R-25: `ABlockingFindingIsDeferredOnlyByAFindingWaiver`.
- R-28: `ProtocolsSayWhatTheCodeDoes`, `TheMeasuredNumbersAreMeasured`.
- Round-1 review of TASK-UNBLOCK-02: `TheFirstReviewOfTheReissue`,
  `ANonAsciiBaselinedFileLeavesTheBaselineOnceCommitted`.
- R-26: `test_a_staged_rename_keeps_its_source_in_scope`,
  `test_answers_json_is_not_edited_by_an_agent`.

## Edge cases

- A `reconciled` entry naming an id the lens never raised is rejected, not ignored.
- A report with `reconciled` that omits an open prior finding is rejected as incomplete.
- `aegis task claim` on an already-building task is idempotent, and records the packet
  metric once.
- A pre-adoption file edited after the baseline is back in scope; a second `init` or
  `migrate` does not re-record it.
- `git add src/x && git commit -m y` is not bookkeeping, even when the index at hook time
  holds only `.aegis/runs/`.
- `git commit -m x -- .aegis/runs/T` runs the gate: it names only run paths but is not the
  bookkeeping command, and a pathspec can hide brace expansion or `$(…)`.
- `grep -rn "git commit" docs/` is not a commit.
- A file baselined at adoption, committed with other content, then reverted in the working
  tree, is in scope. Committed with its adoption content, it is not.
- A deletion or rename source pending at adoption is recorded as `absent` and stays attributed
  to adoption while it stays gone, so the adoption commit that records it changes nothing about
  attribution (R-27). On this repository that is the owner's staged
  `aegis-sdd-framework-full.md -> docs/spec-v0.3-original.md`, which `migrate` backfilled from
  the rename pairing because the baseline predates the `absent` record.
- A baselined path committed with content the baseline never recorded is in scope, and putting
  the working tree back does not change that.
- A lens newly added by a re-plan has no prior record and reviews fresh, without `reconciled`.
- A finding re-raised by content after an unrelated edit is measured from that edit.

## Contracts

- Lens report: `{lens, verdict, findings[], reconciled?: [{id, followup, evidence?}]}`.
- `aegis next` step: `{do, why, command, note, who: cli|agent|human}`.
- aegis commit-scope (removed by SPEC-2 R-3; the git hook reads the index instead)
- Finding waiver: `{id, check: "finding", scope: ["F-xxxxxxxx", …], reason, owner, expires}`.
- `aegis diff <TASK>`: unified diff over the digest's file set.
- `aegis lens record <TASK> --lens <name> [--reviewer <who>] [--digest <d>]`; `aegis lens
  disposition <TASK> <id> <value> --reason <why> --by <who>`.
- Stored lens record: adds `report_tokens`; findings may carry `reopened_in`, `disposition_by`
  (`lens`, or the `--by` name) and `reconciliation_rejected`.

## End-to-end check

    make check && scripts/aegis/aegis gate --stage bootstrap --no-run

## Risks and open questions

- The adoption baseline is configuration the kernel reads (like `capabilities.packages`);
  recording one while tasks are open changes their digests once, so their reviews re-run.
  ADR-2 records this as a deviation from "no new mechanisms" during B.
- Without a commit between tasks, the next task's scope includes this task's changes;
  committing is the repository owner's decision.
