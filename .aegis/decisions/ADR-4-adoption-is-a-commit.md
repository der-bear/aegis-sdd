# ADR-4: adoption is a commit, not a permanent exemption

Status: draft (TASK-UNBLOCK-03)
Date: 2026-09-17
Supersedes: nothing. Amends the adoption baseline introduced during ADR-2 §B.

## Context

Adopting Aegis on a repository with uncommitted work needs the first task's scope to be the
task's change, not the repository's starting state. ADR-2 §B added the **adoption baseline**:
`init` and `migrate` record the uncommitted files and their content hashes once, and a recorded
path is outside every task's scope while it is unchanged.

Two dogfood cycles produced four findings in that one mechanism, and the last of them showed the
mechanism cannot reach its own stated remedy:

1. A baselined file that a task committed and then reverted in the working tree was hidden from
   scope. Fixed by putting any path touched by a commit since the baseline head back in scope.
2. That fix made the documented remedy impossible. "Commit the adoption state" now returns every
   baselined path to the scope of every task based before that commit, so the adoption commit
   cannot pass `trace`, and `trace` is unwaivable by design. On this repository the gate
   therefore blocks the one action its own hint recommends.
3. A deletion pending at adoption is never baselined: `_adoption_baseline` hashes files, and a
   deletion has no content. The source side of a staged rename is such a deletion. It is
   unownable as well, because a lease into a frozen zone is refused and the rename's destination
   is frozen here.
4. The exemption is applied by `changed_files`, but the merge stage's scope is
   `staged_files ∪ changed_files`, and `staged_files` does not apply it. A baselined path that is
   merely staged is unowned at the merge gate. Reproduced on a fresh repository.

The class has now produced a finding in every task that touched it. Rule 5 of this project says a
class that survives its fix means the mechanism is wrong.

## Decision

The baseline records **what the repository looked like at adoption**, and attribution asks
whether a path still looks like that — in the working tree, in the index, and at HEAD. The
question "has a commit touched it" is replaced by "does what the repository holds still equal
what was recorded".

1. **Content, not history.** A baselined path is attributed to adoption while every version the
   repository holds matches its record: the working tree, the index if it is there, and HEAD if
   it is tracked. A commit that records exactly the adoption content therefore keeps the path
   attributed to adoption — that is the adoption commit. A commit that records anything else
   puts the path in scope, which is finding 1 closed on content rather than on history.
2. **Absence is a recorded state.** A path missing at adoption — a pending deletion, including
   the source side of a rename — is recorded as absent instead of being skipped. It is
   attributed to adoption while it stays absent from the working tree and the index, and while
   HEAD either does not have it or a commit removed exactly it.
3. **One scope function.** The union the merge stage builds is subtracted once, in one place, so
   staged and unstaged halves of the candidate diff obey the same exemption.
4. **A rename inherits.** A deletion that git pairs as a rename of a baselined path whose content
   still matches its record is part of the adoption state. This is the only backfill: a baseline
   recorded by a version that could not see rename sources is completed by `migrate` from that
   pairing alone, never from a bare deletion, and never for a path the pairing does not prove.
5. **The baseline expires by being committed, not by a date.** Once the adoption state is
   committed, every recorded path matches HEAD, nothing is exempt from anything a task does next,
   and `status` says the baseline is retired rather than listing files.

## Consequences

The adoption commit becomes possible, which is what unblocks this repository and any brownfield
adopter who staged work before running `init`. The attack of finding 1 stays closed, because a
committed change has content that differs from the record. The mechanism loses a rule rather than
gaining one: "any commit since the baseline head" disappears.

What this deliberately does not do: it does not let a person or an agent add paths to the
baseline after the fact. The only addition is the rename pairing of decision 4, which the
repository itself proves. If a deletion cannot be proven that way, the answer stays "commit it
and attribute it to a task", not "record it as adoption".

The alternative considered and rejected: delete the baseline and refuse the first task on a dirty
tree. It is smaller, and it is what a mature project should probably do, but it makes adoption
harder exactly where the framework claims to be easy, and the retro records it as the owner's
open question rather than a decision an agent takes alone.
