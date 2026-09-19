# ADR-5. The attribution ceiling of v1

- **Status:** proposed — one binary question in it is the owner's
- **Date:** 2026-09-18, **revised 2026-09-19** after an independent review overturned part of the
  first version. What the first version claimed and why it was wrong is kept below, under
  *Corrections*, rather than quietly edited out.
- **Supersedes:** nothing. Amends ADR-1 with the empirical case it asked for, and narrows one of
  ADR-1's own claims.
- **Raised by:** the design lens of TASK-STABLE-01, round 3, severity 2: *"the attribution
  machinery is growing faster than it consolidates, and the answer is ADR-1's candidate commit, not
  a sixth record."* Its minimal fix was to write this file. A fresh reviewer then read the file and
  found the cheaper answer the fork had hidden.

## Context

Aegis v1 answers "who owns this changed file?" by consulting records. There are five, ordered by a
hand-written precedence rule:

1. the adoption baseline — a path belongs to adoption while the repository still holds what was
   recorded (ADR-4);
2. a frozen zone — refused to every agent, owned by nobody;
3. a merge receipt — a merged task keeps a file while the file holds what the merge gate saw;
4. a write lease by glob — a holding task owns what its own reviewed diff contains;
5. **base agreement** — a holding task's base must match what the branch inherited, unless a
   receipt accounts for the difference.

Record 5 was added in TASK-STABLE-01 to close security's F-a0db7907.

## What the evidence actually supports

**Record 5 is one repair old, and it failed in both directions at once.** Correctness: on a branch
that diverged from the mainline before Aegis was adopted, every file the first task edits that the
branch had already changed is refused as content no review covers, and neither remedy the hint
offers is reachable. Security: its trust root is `default_base`, which falls through to the local
`main` ref when no remote-tracking ref exists, so `git branch -f main <payload-commit>` — one Bash
command no installed hook sees — makes the base agree with itself. A rule that over-restricts and
under-protects simultaneously is measuring the wrong thing. That conclusion stands; what does not
is calling it a class that survived two repairs. It survived one.

**The cost of the growth is measured.** The CLI went from 7,074 to 7,613 lines in this task;
`docs/ARCHITECTURE.md` from 3,705 to 4,811 words, with §3 and §6 — the two sections that explain
attribution — now 41% of it. Three sites still hand-roll `merge_base(ctx, x) == x` beside a
`core.is_ancestor` added this round and used once.

**The forgeable-record finding is the framework's trust model, not a new hole.** Security's
F-66b7d183 — write `"status": "merged"` plus a four-key merge receipt and the merge gate passes on
unreviewed code — is true. It is also not the cheapest route and never was: `flow.lens_record`
validates the schema, the lens name and the digest, and nothing about the content, so
`{"verdict": "pass", "findings": []}` recorded once per required lens has always produced a green
merge gate with no file forged at all. ARCHITECTURE said so before this cycle: approval rests on git
history and code review, not on signatures. Security's own round-1 F-414d9b0b said the receipt was
"no harder than forging a gate receipt was before" and filed it as *not a finding*; round 2 rated the
same fact severity 4 because a code comment at `flow.py:1647-1650` had become false. The comment is
false and should go. The exposure did not change.

## Decision

**No sixth attribution record in v1.** A new answer to "who owns this file" is not built as another
record in a precedence order. The mechanism has grown three times in three tasks and its newest
member fails in both directions; that is enough.

**Delete record 5, and close F-a0db7907's window by inclusion instead of refusal.** Three moves,
all inside v1, all in tracked files:

1. Delete `_unreviewed_at_base` (`checks.py`), the `receipted` map it needs in `check_trace`,
   `core.files_between`, and `is_ancestor`'s only call site. Three of the five blocking findings of
   round 3 close with it — F-b575178f, F-b240674d, F-0113be9f.
2. At the `planned → building` move, set `base_sha` to `default_base(ctx)` when a mainline ref
   resolves, else HEAD. Anything committed on the branch before the claim is then inside
   `base..worktree`, inside the digest, and in front of every lens: the payload is **reviewed**
   rather than refused. So a later task does not re-read an earlier one's landed work,
   `task_diff` and `diff_digest` skip a file a valid merge receipt holds at its recorded content —
   `merge_receipt_files` and `_holds_recorded` already exist and already do that test.
3. State the trust model in one paragraph instead of guarding it: with no remote every record is
   self-attested and the agent is trusted; with a remote, `origin/main` is the root and CI is the
   barrier.

The brownfield cost flips sign. Where record 5 refused the first task of a pre-adoption branch, the
inclusive base puts that branch's diff in the packet, where size *warns* under R-1 and nothing
blocks. That is the owner's stated priority — do not over-restrict the agent — answered by deleting
code rather than adding it. Four records, not five, and not six.

**One part of ADR-1 can be taken today, and one part of ADR-1 is narrowed.** The status that rests
on nothing writable — *merged means reachable from the target branch* — needs no rewrite: a merged
task owns nothing, because its work is behind `default_base`. Worth taking. What ADR-1 does *not*
deliver is the end of forgeable records: it stores attestations in git notes, `git notes add` is one
command no hook sees, and ADR-1's own second opinion records that notes do not sync by default. A
forged `merged` becomes a forged attestation under `refs/notes/`. ADR-1 is still the better design
for other reasons; it is not the answer to this class, and the first version of this file said it was.

## The owner's question, and it is binary

**Does a checkout with no remote trust its agent?**

There is no third answer, and nothing in v1 or v2 can distinguish the agent moving `main` from the
owner moving it. If **yes**: the trust model gets its paragraph, the two `who: human` steps in
`aegis next` — "merge the branch" and "land" — become `cli`, and the framework stops asking a person
to confirm what it cannot check anyway. If **no**: a remote is a precondition for the guarantees,
`origin/main` is the root, CI is the barrier, and the documents say so instead of implying local
enforcement.

Everything else in the first version of this file was mine to decide and is decided above.

## Corrections to the first version, 2026-09-19

- **"Abandoned by the framework's own escalation rule, not by a judgement of mine" was false.**
  Reproduced: at `rounds == cap` with an unmoved digest and an open severity-3 finding,
  `next_action` returns `fix <finding> in the code [agent]`. The escalation branch sits inside
  `if record.diff_digest != plan.diff_digest`, and the second one tests `rounds > cap`, strictly.
  `lens_record` then accepts round cap + 1 without complaint; only `check_reviews` says the limit is
  exceeded. Rule 5's mechanical trigger — a finding marked fixed that came back — has fired zero
  times in four tasks. **The framework did not escalate. I did, and the decision was right for a
  narrower reason: design was at 3 of 3 rounds with an open severity-3 finding, so any edit forced a
  fourth round for design and the task could not reach green.** R-2's escalation is half
  implemented, and that is a requirement for the next task, not a claim to repeat.
- **The fork hid this file's own answer.** (a) revert R-4 was priced correctly and is against every
  stated priority. (b) keep-and-state was mispriced as "a severity-4 hole sits in the tree"; its real
  cost is a paragraph. (c) start ADR-1 was mispriced as "the class stops being expressible". The
  option that was missing — delete record 5, base at the branch point, state the model — is hours,
  and it is now this ADR's decision rather than one of four choices.
- **"No task is re-issued until the fork is answered" rested on a prediction**: that a fresh
  security lens would meet F-66b7d183 in round 1. Security's round-1 F-414d9b0b accepted exactly
  that stated model and filed it as not a finding. The consequence is withdrawn; the three moves
  above are the next task.
- **"Forty files belong to no task" was not measured.** It is 19, and forty was
  `git status --porcelain | wc -l` — every uncommitted file, not every orphan. In the retro that
  celebrates catching unmeasured numbers.

## Consequences

- **The next task is the three moves above**, in that order, plus the round-3 advisories mapped in
  TASK-STABLE-01's handoff under `findings_to_steps` — with one entry withdrawn there as a false
  positive (see the retro, item 5).
- **`is_ancestor` absorbs the three hand-rolled ancestry tests.** Consolidation, not a new record.
- **The escalation path and the commit path contradict each other.** Observed: with
  TASK-STABLE-01 abandoned, a commit carrying this file was refused by the installed pre-commit hook
  with 19 `trace` failures — the code the task reviewed belongs to no task — and
  `requirements: not covered by any task`, because R-1..R-8 and R-16 lost their only citing task.
  The designed way out of an abandonment is to re-issue, so an abandonment that defers re-issuing
  cannot be recorded. The round's own evidence did commit (`e8bbace`), because the hook exempts a
  commit wholly inside `.aegis/runs/`. The exemption should cover `.aegis/memory/**` and
  `.aegis/decisions/**`: neither is ever code, and the moment a retro is written is the moment
  `trace` is most likely red.
- **ADR-1 keeps its status.** This file is the empirical case it asked for, with one of its claims
  narrowed: candidate commits do not end forgeable records, they move them.
