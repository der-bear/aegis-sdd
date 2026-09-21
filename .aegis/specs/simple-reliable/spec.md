# SPEC-3 — Simple, reliable, convenient, understandable

> **Done 2026-09-19, in three commits, and further than written.** The owner then asked whether
> the whole thing was over-built; the review said yes, and the deletion went past R-17: the merge
> receipt, the write hooks, `task focus`, `aegis waive` and the delegation answer, and the
> person-name regex were all removed (`df28057`). R-17's receipt-skip became unnecessary — no
> receipt, nothing to skip. R-19's cap is a signal in both the gate and `next`. R-21's `docs_attest`
> clause was dropped on review; R-22's comment went with the block that held it. Task 3's
> ARCHITECTURE rewrite: 4,811 → 4,476 words, §3 and §6 each one rule in one place.

The owner's instruction, verbatim: *"доведи до нужного состояния и не переусложняй, он должен быть
простой, надёжный и удобный"*, then *"и понятный"*. Read against the definition of optimal already
recorded — stable, little human participation, the agent not over-restricted, no artefact rewritten
for a token count — that gives four tests every requirement below has to pass:

- **Simple**: it removes more than it adds, or it is one condition. A requirement that needs a new
  mechanism belongs in a different spec.
- **Reliable**: it is a check with a stated edge, or a guarantee. No requirement here claims
  enforcement the code cannot deliver.
- **Convenient**: an adopter does nothing to get it, and nothing it does refuses legitimate work.
- **Understandable**: one rule lives in one place, and someone who did not build this can predict
  what the gate will say before running it.

**Three tasks, in order, with a commit between each.** The previous cycle put sixteen requirements
under one lease and hit the round cap; its own evaluation named the fix — *"not a smaller list, a
commit"*. Task 1 is what a stranger hits in their first hour and is independent of the other two.
Task 2 is the attribution rule. Task 3 is the documents, which can only be verified once the code
they describe has stopped moving.

## Decisions taken, both reversible in one line

**D-1. A checkout with no remote trusts its agent.** Nothing in v1 or v2 distinguishes the agent
moving the mainline ref from the owner moving it, so the framework states the model instead of
guarding it: with no remote every record is self-attested and the agent is trusted; with a remote the
remote's mainline ref is the root and CI is the barrier. Answers ADR-5's binary question toward
convenience, and R-24 derives from it.

**D-2. Lenses as data (ADR-3) is a later task.** A real gap for public use — a project cannot add or
change a lens without editing Python — and a new mechanism, which the first test forbids here.

---

# Task 1 — the first hour

Every requirement here was reproduced by driving a throwaway repository through
`init → task → gate → merge → land`. Each is a condition or a string, and each one today stops a new
adopter cold.

R-30. **The mainline ref shall be resolved or named, never silently absent.** `core.default_base`
      tries `origin/HEAD`, `origin/main`, `main`, `master` and returns `None` when none resolves — and
      on `None` the merge stage's scope becomes the entire repository. Reproduced on a repository whose
      branch is `develop`: three changed source files produced "48 files in the candidate diff", and
      `trace` and the testing mandate failed on all of them. The installed pre-commit hook runs exactly
      that command, so **every commit is refused and the message names none of the cause.** Three
      parts: `origin/master` joins the tuple, because `git remote add` — unlike `git clone` — leaves no
      `origin/HEAD` symref and a master-default remote then roots at the *local* `master`; `None` on a
      born HEAD raises an error naming the refs it tried; and the interview asks for the mainline
      branch when none of them resolves, which no question does today.

R-31. **`aegis next` shall have a step for every state the loop can actually be in.** Three holes,
      each reproduced:

      - *No commit step at all.* After a green merge gate the loop said `plan the architecture for
        orders`, because `_land_pending` needs the default branch to differ from HEAD and nothing had
        been committed. The step that stands between a gated task and a landed branch is committing the
        merge gate's own bookkeeping — `who: agent`, when the tree is dirty only under `.aegis/runs/`
        and a valid receipt exists.
      - *No docs step.* On the first commit that carries code, the merge gate fails with `profile
        requires diagrams that do not exist: api-reference`; `next` never mentions documentation, so
        the hook refuses with a reason the loop cannot lead you to.
      - *Gated for ever.* Committing before `gate --stage merge` leaves the candidate empty: the gate
        passes on nothing, the status stays `gated`, and `next` says "merge the branch" on every run
        for ever. The loop shall detect a task `gated` whose files are not in the candidate and say
        what happened, rather than repeating a step that cannot change anything.

R-23. **The tier the packet declares and the tier the gate judges shall agree, and the change-kind
      scan shall read the change.** Corrected diagnosis — the first version of this requirement blamed
      `\bauthoriz` matching ARCHITECTURE's "Authority is data", and that is false twice over:
      `authoriz` does not match `Authority`, and a `.md` path is classified `docs` and skipped before
      any pattern runs. What actually raises this repository to tier A is `\bsession\b` in
      `.aegis/runs/TASK-STABLE-01/handoff.json`, whose `agent` field reads *"claude-fable-5.1 session
      (orchestrator and builder)"* — the framework's own bookkeeping, which `in_review_scope` says is
      not part of the change. Any adopter whose handoff mentions a session inherits tier A and a
      security lens on every task. Two parts, both one condition: the kind scan's scope is filtered by
      `in_review_scope`, and the packet reports the declared tier *and* that the gate judges the
      effective tier from the diff — `_risk_tier` is already one function; what differs is that
      `task_claim` builds the packet on an empty diff.

R-25. **The git hook's bookkeeping exemption shall cover `.aegis/memory/**` and `.aegis/decisions/**`,
      and the receipt carve-out shall go.** Neither memory nor decisions is ever code, and the moment a
      retro or an ADR is written is the moment `trace` is most likely red — so the framework could not
      commit the record of its own escalation, which is how this cycle ended. The carve-out that forces
      the gate to run on a commit carrying a receipt is a no-op against forgery, because the gate then
      reads the receipt and passes; what it does cost is a full gate run on exactly the bookkeeping
      commit R-31 adds. The task shall reinstall with `aegis git-hooks install --force`:
      `git_hook_installed` tests only for the marker, so an old hook reads as installed.

---

# Task 2 — attribution, and the record the gate trusts

R-17. **Delete the base-agreement rule and close its window by inclusion instead.**
      `checks._unreviewed_at_base`, the `receipted` map it needs, and `core.files_between` go. At the
      `planned → building` move a task's `base_sha` becomes `core.default_base(ctx)` when a mainline
      ref resolves and `head_sha(ctx)` otherwise, and `None` leaves the base alone — so a commit made
      on the branch before the claim is inside `base..worktree`, inside the digest, and in front of
      every lens. The payload is **reviewed** rather than refused, which is what makes the first task
      of a pre-adoption branch possible at all. Closes F-b575178f, F-b240674d and F-0113be9f.

      **The receipt skip lives in `changed_files`, beside the adoption-baseline subtraction, and in
      `staged_files` with it — not in `task_diff` or `diff_digest`.** Put in the two filters, the digest
      would forget an earlier task's merged files while `lens_plan`, `check_reviews`, the task-gate
      scope, the change-kind scan and `affected_packages` all still saw them: two copies of one rule,
      which is R-7's own lesson. In `changed_files` the `merged` loop in `check_trace` becomes dead
      code and goes with it.

      Stated rather than discovered: two *holding* tasks on one branch under `parallel_builders: 2` get
      a worse case than today. Task 2's base at the branch point puts task 1's pre-claim commits inside
      task 2's digest, so task 1's next fix stales task 2's reviews; today's base-at-claim excludes
      them. The builder's declared worktree isolation avoids it and the parallel limit makes it rare.
      It is named here because a check with a stated edge is the reliability test.

R-18. **The generated-path exclusion shall apply only to paths no task *holding its lease* names.** An
      explicit lease beats an inferred default: `**/build/**` in `generated_paths` excludes
      `skills/build/SKILL.md` — the file R-16 edits — from attribution entirely, and every adopter with
      a `build/` or `dist/` source directory inherits it. "Holding" means `checks.HOLDING`, not any
      task: a *planned* row naming `build/**` must not lift the exclusion, or a backlog entry turns
      build output into orphans at somebody else's merge gate.

R-19. **`aegis next` shall escalate at the cap whether or not the digest moved.** The escalation exists
      only inside the moved-digest branch, and the second test is `rounds > cap`, strictly — so at the
      cap with an unmoved digest and a blocking finding open the loop says `fix … in the code`, which
      is the dead end this cycle walked into. One condition, in the same-digest branch.

      Deliberately *not* also refusing an over-cap report in `lens record`: `check_reviews` already
      enforces the limit, a second implementation is the duplication R-7 exists to stop, and discarding
      a report someone paid for is the loss this cycle regrets. With `next` escalating first, a cap+1
      round is never dispatched.

R-20. **`_land_pending` and `land` shall ignore a merge receipt the default branch already contains.**
      Both test ancestry of HEAD only, so after `land --run` and one bookkeeping commit `next` says
      `land the branch` again and `land --run` re-lands. One condition each, on `core.is_ancestor`.

R-21. **One validator for a person's name.** `_NAMES_NOBODY` loses `an` and `na`, because `An Na` is a
      real name the table refuses and every gate stage then fails on an invalid waivers file; and `_`
      and `.` become word separators for the model-word test, which catches `claude_opus`. `ClaudeOpus`
      stays out of reach and the docstring shall say so — there is no separator to split on, and a
      pattern that catches it catches ordinary names too.

      Deliberately *not* making `docs_attest` call `is_person_name`: that function refuses every agent,
      R-10 is a planned requirement that attests with `--by aegis-doc-manager`, and three diagrams in
      this repository carry `verified_by: "Claude Opus 5"`. Attestation asks for a name, not for a
      person, and the docstring already says so. What changes is the duplicated length constant, which
      moves into one helper both call.

R-22. **The false comment goes, and the trust model gets one paragraph.** The comment claiming that
      typing `merged` into a manifest buys nothing has been false since the merge receipt existed.
      `docs/ARCHITECTURE.md` shall state, once: `lens_record` validates a report's schema, its lens and
      its digest and nothing about its content, so a green merge gate has always been one honest report
      per lens away and one dishonest one too; with no remote every record is self-attested and the
      agent is trusted; with a remote the remote's mainline ref is the root and CI is the barrier. The
      paragraph shall describe what `default_base` actually tries, not an idealised `origin/main`.
      Saying this is the requirement; guarding it is not possible and shall not be claimed.

R-24. **The autonomy boundary shall be one named rule, not ten judgements.** `next_action` marks a step
      `who: human` in ten places, each decided case by case, which is why it asks a person to confirm
      what the framework cannot check and then advises past a decision that is genuinely theirs. The
      rule, stated once in the build protocol and used to derive every `who`:

        A person is needed for — an irreversible outward-facing act (a push, a pull request, a
        release); a change to what the framework measures work against and a person owns (the
        constitution, an answer the interview marks never-auto, the owner of a waiver); a question
        recorded in a `proposed` ADR; a tool permission the runner refuses; and an escalation, meaning
        a class that survived its fix or the round cap reached with a blocking finding open.

        Everything else the agent decides, records and continues. A blocked step does not block other
        ready work, and a report is not an approval gate.

      Consequences: "merge the branch" becomes `cli` unreservedly — it is a check, and everything it
      writes is re-derivable. "land" becomes `cli` under D-1: it moves a local ref, the non-ceremonial
      guards are elsewhere (an ungated holding task in the candidate fails the merge gate; with a
      remote the push is a separate act behind the pre-push hook), and with no remote it moves a ref
      rather than deploying anything. Push and the pull request stay a person's. `aegis next` shall
      also name an open question from a `proposed` ADR instead of advising past it: after
      TASK-STABLE-01 was abandoned it said "build TASK-STABLE-02", which ADR-5 forbade.

      Taken from `leadmaster/.agents/commands/work-next.md` §5, which states the same boundary in one
      paragraph and is the clearest answer in either source to "little human participation".

R-26. **Small and true, each one line.** `task_diff` uses `os.path.lexists` and emits a link's target
      rather than inlining the target's bytes as a regular file. `merge_receipt_files` checks the
      receipt names the task it was read for. `core.is_ancestor` absorbs the four hand-rolled ancestry
      tests at `checks.py:621`, `flow.py:1746`, `flow.py:1756` and `flow.py:1894`. `head_sha(ctx)`
      replaces the three raw `git rev-parse HEAD` reads at `flow.py:1712`, `flow.py:1736` and
      `flow.py:1883`, which take the literal string `HEAD` at face value on an unborn branch — the
      exact bug `head_sha` exists to fix. `docs/EVALUATION.md` §8 says 27 findings for TASK-UNBLOCK-03,
      which is what its own review records and `metrics.jsonl` hold; the "forty-eight" sentence beside
      it stays and cites retro 0002 item 10, which records that number twice — the first version of
      this requirement called it unsupported and was wrong. `templates/ci/aegis-gate.yml` describes the
      hook the framework installs. Deleted: `.aegis/standards/`, which holds one 151-byte placeholder
      the packet's own text forbids editing, and `.aegis/changes/universal-01/` with its
      `universal-01.applied.d/` marker directory — patches verified against a 169-test tree where this
      one has 255, four files still naming code R-3 deleted, and nothing lost because the design of
      their unapplied steps lives in ADR-3.

---

# Task 3 — the documents

R-28. **One rule in one place.** A reader shall answer "who owns this changed file?" from one ordered
      list without reading two sections. After R-17 there are four records — the adoption baseline, a
      frozen zone, a merge receipt, a write lease. Their precedence is prose spread across
      `docs/ARCHITECTURE.md` §3 (965 words) and §6 (998), together 40.8% of a document that went from
      3,705 to 4,811 words in one task. The rules do not change; where they are said does. Each section
      states its own subject once and points at the other rather than restating it, and the same holds
      for the review-state rules in §5 and §6. Where ARCHITECTURE makes a behavioural claim it shall
      use the three words README's own "What is guaranteed, checked, and merely likely" section already
      defines, and point at it — the stratification exists there already, so the requirement is to use
      it, not to build it. All four documents are re-attested after the pass, by a verification pass
      and not by assertion.

---

# Task 4 — the second project's first hour

Reproduced on `domain-hunter` (a brownfield Python service, 128 commits, 13 uncommitted files) on
2026-09-19, within the first hour of `aegis init`. Each is one condition, and each stopped an adopter.

R-32. **An adopter's own `CLAUDE.md` and `AGENTS.md` chain shall warn past their budgets, never
      fail.** Their CLAUDE.md was 3,247 tokens before Aegis added four lines; the bootstrap gate
      failed on it. The framework's own skill and role budgets keep failing — those are ours.

R-33. **The loop shall never wait for a constitution.** `init` drafts its purpose from the README's
      first paragraph and says so in the file; the header says a person amends it at any time and an
      agent when a task's objective calls for it, recorded in the handoff (it is `.aegis/` state,
      outside any lease — `task new` refuses one, so the first wording, "only through a task that
      leases it", promised a path that did not exist); `next` has no constitution step, and a
      missing file is redrafted by `aegis scaffold`, which leaves the answers alone. The owner: a
      person should not be needed in that equation at all.

R-34. **A `justfile` (any of its three spellings, quiet `@recipe:` included) is a front door like a
      `Makefile`, and a front door that defines `test` replaces the inferred commands rather than adding
      to them.** Detection proposed `mypy .` from `pyproject`; the team's `just test` ran pytest alone,
      and `mypy .` had 338 errors they had never run against — the first task gate would have failed
      on nothing the task did. A front door of `build` and `clean` alone has said nothing about how the
      project is verified, so there the inferred `go test ./...` stays (round 1 of the review, sev 2).

R-35. **`init` shall not scaffold `.aegis/standards/`** — the placeholder R-26 deleted here was still
      being written into every new project.

R-36. **A no-suffix file that starts with `#!` is code for the testing mandate** — the security lens's
      severity-2 on TASK-PUBLISH-01, declined there to keep its digest and fixed here.

R-37. **The base is the local mainline when it is ahead of the remote one.** `aegis land` moves the
      local ref and the push comes after; between the two, what sits between `origin/main` and `main`
      is landed work with its task marked merged, not a candidate. Diffing against the remote there
      made the framework's own pre-push gate refuse the push of the first landing it ever met
      (2026-09-20, TASK-FIRSTHOUR-01: eight files "belong to no task"), and would have handed the
      next task the landed files as its own diff. One rule in `default_base`; no new state.

R-38. **Lenses, roles and engines are data (ADR-3).** A lens is a file — `lenses/<name>.md` shipped,
      `.aegis/lenses/<name>.md` in a project, which wins on a name clash — with a focus and the
      triggers that select it; the compiler derives `policy.lens_matrix` from the files, and the
      shipped files reproduce the former constant exactly. Two auditor profiles replace the three
      per-lens profiles; `aegis lens prompt` assembles what any engine needs; the second engine is an
      answer that may be empty, run through one script. Adding a lens is one file and no engine
      change — the last real gap for public use named in every retro since 0001.

R-39. **What a newcomer reads first says what is true.** The version is 0.9.0 — 1.0 after a third
      project and one full pull-request cycle; `docs/EVALUATION.md` covers every review cycle, with
      its reviewer and its numbers measured from the records; `init` writes no file nothing reads
      (the empty `product/mission.md` and `roadmap.md` stubs, the same class as R-35); no live message
      names a deleted profile or one vendor; `aegis metrics` warns about a small sample only when a
      lens has one; and the three one-liners declined in TASK-LENSES-01 are done.

R-40. **The digest hashes what git records.** Content, the file type, and the owner's exec bit — not
      the full permission bits. Hashing `st_mode & 0o777` made the same commit digest differently in
      two checkouts: this one holds dozens of tracked files at 0600 and 0711, a clone holds them at
      0644 and 0755, and it worked only because `lens plan` and `lens record` always ran in the same
      checkout. On a pull request, CI would have found every review stale. Found on 2026-09-22 when a
      `git checkout` of two files rewrote them at 0644 and a review could no longer be recorded.

R-27. **Every test added or changed in any of the three tasks shall be shown to fail on the behaviour
      it forbids before it counts.** Two of the previous cycle's document locks passed on the exact
      text they were written to correct; both were found by a lens, not by me. In particular: R-17
      needs the brownfield case the deleted rule refused to pass now, and the payload-before-claim case
      to appear *in the diff* rather than be refused; R-18 needs a task owning a path under a `build/`
      directory and a planned task that does not lift the exclusion; R-19 needs the cap reached with an
      unmoved digest; R-20 needs a second commit after a landing; R-24 needs a `who` for each boundary
      in the rule and one case outside it; R-25 needs a commit of a retro to pass the hook while
      `trace` is red; R-30 needs a repository whose branch is `develop`; R-31 needs all three of its
      states.
