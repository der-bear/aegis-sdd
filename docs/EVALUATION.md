# Evaluation: what independent review found

Authoritative for: the results of independent review and the status of each finding.
References only: the implementation (see [ARCHITECTURE](ARCHITECTURE.md)).

Every claim below was produced by a reviewer instructed to find defects and not to praise,
read-only, in a context that did not build the change — `gpt-5.6-sol` at high or extreme
reasoning effort for §1–§7, fresh Claude subagents for §8, Claude Fable 5.1 for §9 — or by an
adversarial agent driving the CLI. §9 says where the reviewer was the same model as the builder,
which is weaker evidence than a different vendor's, and says it rather than hiding it behind the
word "independent".

---

## 1. API verification

Checked because parts of the original specification came from third-party blog posts rather
than documentation.

**Confirmed.** Subagent frontmatter does support `skills`, `disallowedTools`, `maxTurns`,
`memory`, `isolation: worktree`, `permissionMode`, `effort`, `background`, `color`. The
`ConfigChange` hook event exists. `PreToolUse` exit code 2 blocks the call and returns
stderr to the model as the reason. Subagents do not inherit session skills — `skills:`
injects the **full body**, not a description. A plugin-root `CLAUDE.md` is not loaded as
project context.

**Two errors in the specification.**

*`tools:` syntax.* The spec wrote `tools: Read, Grep, Bash(make test*)`. The field accepts
exact tool names, `mcp__<server>` patterns and `Agent(<type>)` only; `Bash(...)` is
permission-rule syntax for `settings.json`. Every role was rewritten and command scoping
moved where it works.

*The orchestrator cannot be a subagent.* The first tool filter removes `AskUserQuestion`
from every subagent and `Agent` at the depth limit. An orchestrator spawned as a subagent can
neither ask a human nor delegate: it silently degrades into a builder. It runs as the session
agent, and its own prompt says so.

Incidentally, that filter makes "subagents do not spawn subagents" native rather than
declarative.

---

## 2. The rounds

| Round | Scope | BLOCKING |
|---|---|---|
| 1 | specification v0.3 | 8 |
| 2 | implementation, full | 9 |
| 3 | implementation, **nine agreed items** | 0 |
| 4 | implementation, fresh full | 22 |
| 5 | after fixing all of round 4 | 24 |
| 6 | after narrowing claims + fixes | 15 → 11 → 17 |

Round 3's zero was honest, and narrow: it measured a list agreed **before** the run. Rounds
4–6 showed the general shape — **a fresh adversarial audit finds roughly twenty substantiated
items every time**, and closing the previous set does not reduce the next count.

The cause is not the quality of the fixes; each was verified by execution and locked by a
test. It is the size of the claim surface. An auditor asks not "does it work" but "can it be
bypassed by ordinary use", and on a surface with fifteen advertised guarantees, half will
always yield.

**The practical conclusion: "zero BLOCKING from a fresh full audit" is not an acceptance
criterion, it is unbounded work.** Criteria that do converge: zero against a list agreed in
advance; a green cycle on one real project from init to merge; N days of team work with no
manual gate bypass.

---

## 3. What was actually broken

A sample, chosen because the class matters more than the count. Every one of these reported
success while being wrong.

| Defect | Why it was worse than it looks |
|---|---|
| `changed_files` returned only the committed diff when a base existed | Uncommitted work was invisible to lenses, trace and package selection. The reviewer passed a diff that was not the diff — **a green gate on unread code** |
| Installation did not work at all | `install.sh` symlinked the launcher, which resolved its package relative to the symlink. The documented installation could not run one command. No audit caught it because every run used the direct path |
| Lens reports were stamped with the current digest at record time | An old verdict could be replayed onto changed code by resubmitting the same JSON — a forged review requiring nothing but a repeat |
| Re-running a lens with an empty findings list closed open findings | The cheapest route to a green gate was to run the lens again |
| `planned → merged` was permitted | Every check skips terminal statuses, so the entire gate was bypassed by one status write |
| A builder could widen its own lease | `.aegis/runs/**` was writable; a lease its holder can edit is not a lease |
| `[!a]` in a glob | Translated without negation, so it **permitted** exactly what it was written to exclude |
| The gate counted lint as verification | A package with `"lint": "true"` passed without running a test |
| `correctness.json` copied to `security.json` | Satisfied a security review requirement; files were trusted by name |
| `AEGIS_ALLOW_PROTECTED=1` disabled both write hooks | An unauthenticated variable that anything can set is the absence of enforcement |
| A symlink smuggled writes past the lease | The check compared spelling, not the file |
| `os.getenv("KEY")` was not detected | The most ordinary Python spelling, missing from the environment scan; likewise Rust and Ruby |
| `.github` was invisible to detection | The walker excluded directories by the prefix `.git`, so CI configuration was never read |

Two defects were introduced by the attempt to tighten, and both are informative. The gate
receipt hashed the task manifest, and recording the pass changed that manifest — the gate
invalidated its own evidence. The pre-commit hook ran the merge gate on every commit,
blocking the manifest commit made by the framework's own workflow. Neither was findable by
reading; both required execution.

---

## 4. What was borrowed from a working project

Mechanisms proven on a large multi-agent build rather than derived from principles:

- **A hook on `git commit`, not on every edit.** The commit is the moment work claims to be
  finished — the right interception point.
- **Check selection keyed on touched paths.** Gates outside the routine path get skipped
  exactly when they matter.
- **A task packet with an exclusive path lease** — the origin of the manifest design.
- **The two-strike rule:** a defect class surviving two rounds demands simplifying the
  mechanism, not a third patch. Implemented as `reopened` failing the gate.
- **The builder is never the final reviewer**, down to a different engine on risky surfaces.
- **Grep-verify a finding before acting on it** — reviewers have a false-positive tail.
- **Spec-as-registry, code checked against it:** drift gates as a pure core plus a thin
  caller. The idiom of every check in `checks.py`.
- **And an anti-pattern from the same source:** a 337 KB append-only progress log — proof
  that such documentation grows without bound. Hence `NOTES.md` is rewritten, not appended,
  and has a budget the gate enforces.

---

## 5. Narrowing the claims

Round 6 produced the change that finally moved the count: the enforcement list was split
into three, and the tool's own output was made to say which is which.

**Guarantees** are properties of artifacts and cannot be bypassed by ordinary use.
**Checks** are deterministic but only as true as the artifacts they read.
**Heuristics** are diff scans that find literals and miss computed names — and each such
finding now says so in its own hint.

Fifteen advertised guarantees, half of them bypassable, is worse than five that hold. That
is "no over-engineering" applied to the guarantees themselves.

---

## 6. Not fixed, deliberately

- **`Bash` bypassed the write hook** — historical: the hook was deleted on 2026-09-19 (ADR-5),
  and the lease is a declaration `check trace` reads at the merge boundary. The containment is
  the builder's `isolation: worktree` and attribution at landing.
- **`autonomy_limits` and `nfr_priorities` remain context.** They change *how* an agent
  decides, which no script can check. They are delivered into the task packet — an answer
  that never reaches the agent changed nothing — but not verified.
- **`docs attest` does not prove someone looked**, only that the sources have not moved since
  they signed for it.
- **No migration engine.** Registry schemas have never changed incompatibly; building
  machinery to replay migrations that do not exist is the ceremony this project avoids. The
  real case — a compiler version bump — is handled by `aegis migrate`.
- **The merge invariant is not enforced in CI by default.** `templates/ci/aegis-gate.yml`
  ships; installing it into a project that has no CI is a decision, not a default.

---

## 7. What this does not prove

The audits verified internal coherence, API conformance and resistance to bypass. They did
**not** verify that the framework pays for itself; that needs months on a real project.
Thresholds — a 30% lens acceptance rate, three refinement rounds, the S/M/L boundaries — are
calibrated guesses. `aegis metrics` exists to replace them with measurements, not to confirm
them.
---

## 8. The first cycle on a real project (2026-09-17)

Six audit rounds preceded this; none of them ran the loop. One day of running it on this
repository produced a different kind of evidence.

| | TASK-UNBLOCK-01 | TASK-UNBLOCK-02 | TASK-UNBLOCK-03 |
|---|---|---|---|
| Lenses | correctness, security, design | the same three roles, fresh contexts | the same three roles, fresh again |
| Rounds | 3 (the cap) | 3 (the cap) | 3 (the cap) |
| Findings | 43 | 25 (15 + 4 + 6) | 27 (15 + 6 + 6), after three audits of the session |
| Blocking left | 7, in three mechanisms | 0 | 0 |
| Status in its manifest | abandoned | abandoned | the task this document ships with, written before its gate ran |

**The gate found what six audits had not.** Six classes surfaced the first time a real task was
scoped, reviewed and gated: an uncommitted tree made every file the first task's change;
documentation was scanned as source; the framework's own skills counted as unrequested
documentation; the packet and the lens plan disagreed about the same diff's risk tier; setup
never completed after its last answer; lens reports failed a size budget no protocol stated.
Each became a requirement with a test in R-10 to R-15 — the second and third share R-11, and
R-14 belongs to the class below.

**One class survived three rounds, and a fresh lens broke it on the first try.** The commit
hook's exemption was bypassed in every round — the index form, then a second line and
`GIT_INDEX_FILE`, then `$(…)` in a message and an abbreviated flag — and twice simplified by
deletion, down to a single exact command. The fresh review then found the comparison itself ran
on whitespace-flattened text, where a newline reads as a space. The conclusion is the one §2
already reached, now with a second kind of receipt: **"zero blocking from a fresh audit" is not
an acceptance criterion.** What converges is zero against a list agreed in advance, plus the loop
running end to end.

Those seven were the commit hook's exemption (five), the adoption baseline (one) and the
absence of write protection on `answers.json` (one).

**The framework's own escalation rule fired, and was obeyed.** At the round cap the loop stopped
rather than patching a fourth time. The task was abandoned, every open finding was mapped in its
handoff to the change that answers it, and the work was re-issued with the simplified mechanism
and a fresh budget — a new task for a new mechanism, not a reset counter on the old one.

**Two mechanisms earned their place; two did not.**

- Stable finding ids with carried dispositions: 31 of 43 findings in the first task were
  reconciled by id across rounds, with evidence, and none was reopened under its own id. That
  is a narrower claim than it looks: the hook class below recurred in every round under new
  ids, because an id is a hash of one claim about one path and a class is not. The two-strike
  rule catches a repeated *finding*, never a repeated *class* — a person still has to see that.
- The single rule for authority: a blocking finding is closed by a code change a re-review
  confirms, or by a person. It has one implementation, read by the gate and by `aegis next`.
- The review-state bookkeeping around that — last-seen digest, second strikes, provenance, lens
  identity — produced defects in every round. It is exactly what ADR-1 replaces with candidate
  commits, and this is the empirical case ADR-1 asked for.
- The adoption baseline produced findings in three consecutive tasks, and its stated remedy was
  wrong: under the rule as written, committing a baselined path returned it to the scope of every
  task based before that commit, so the gate refused the adoption commit its own documentation
  instructed. ADR-4 rebuilt it on content — a path belongs to adoption while the repository still
  holds what was recorded — which makes that commit possible. Deleting the mechanism outright,
  and requiring a commit before the first task, remains the owner's open question in
  `.aegis/memory/retros/0001.md`.

**How the second cycle ended, and why there was a third.** TASK-UNBLOCK-02's three lenses
finished their last round clean, and their final advisories were about this very section: it had
recorded the cycle as finished while the review was still open, miscounted the classes above, and
credited the two-strike rule with a property it does not have. Correcting a document moves the
digest, so those three clean records went stale and a fourth round was not allowed. It cost
nothing, because the task could not have been gated either way — `trace` blocked on the rename
the repository owner had staged before adoption, and no waiver covers `trace` by design.

The owner then asked for a review of everything before the first commit. Three fresh auditors
read the session: the code with permission to run it, the documents, and the framework against
the two research reports and the plan. Twenty-eight findings, on work that had already passed six
lens rounds. That produced TASK-UNBLOCK-03, which rebuilt adoption attribution on content
(ADR-4), put the gate in front of every commit in the checkout rather than only the ones Claude
Code runs, and made two false claims true — a guarantee about tests that could never fire, and
two interview questions whose detection keys the scanner never produced. Its own first review
round then found ten more blocking defects in that work, including a staged deletion the new rule
would have waved through.

Three tasks, two abandoned, nothing hidden: each abandonment is recorded in its own handoff with
the finding it stopped on, and the escalation rule is what produced the simplifications rather
than a fourth patch.

**What the third task's own review says about its size.** Twenty-eight requirements under one
lease, and a diff of the whole framework, because nothing has been committed since the initial
commit: a re-issue inherits every requirement its predecessor did not land, so each escalation
makes the next task larger. The design lens called the tier-A independent review nominal at that
size, and it is right — the lenses reviewed the files the packet named, not 650 KB of diff. The
fix is not a smaller list, it is a commit: once this lands, the next task's diff is its own
change. Recorded as this cycle's clearest structural cost, and as the reason the sequence now
puts the barrier and the commit before anything else.

**How the third cycle ended.** Round 3 was the first in which all three lenses returned zero
blocking, and the task gate went green — the first of the dogfood. The merge gate then stayed
red on one document: a verification pass found three claims in `docs/ARCHITECTURE.md` false
against the code, and correcting them would have moved the digest with no round left. The owner
chose to commit with the document stale under a waiver in his name, the branch landed, and the
next commit was refused by the installed hook, with forty-eight `belongs to no task` findings —
a merged task no longer owned its files until `main` moved. Both facts became requirements of the next task (retro 0002), and
the second became the merge receipt described then in ARCHITECTURE §6 (since deleted; see ADR-5).

**What this still does not prove.** Nothing here measures whether the framework pays for itself:
one task, one repository, one day. The lens acceptance rate (0.69–0.73 in the first task) and the
cost of a warm lens against a cold one are measured but not yet meaningful at this sample size.
The next honest test was a project of a different kind, which is why ADR-2 made it the second
half of §B; §9 is what it found.

## 9. Seven tasks and a second project (2026-09-18 → 2026-09-21)

Numbers in this section are counted from the review records under `.aegis/runs/`, not recalled.
A "finding" is one entry in a lens's record across all its rounds; "blocking" is severity 3 or
more when raised.

**The cycle that ended in a decision, not a merge.** TASK-STABLE-01 drew 61 findings from three
lenses, 15 of them blocking, and was abandoned at the round cap with design at three of three
rounds and a severity-3 finding open. The finding that mattered was design's: the attribution
machinery was growing faster than it consolidated. ADR-5 records the decision and, in its own
*Corrections*, that the framework did not escalate at the cap — the builder did.

**The deletion.** The owner's brief — work stably, need a person rarely, do not over-restrict the
agent, never make it rewrite a report for its size — became SPEC-3 and TASK-SIMPLE-01. The write
hooks, the merge receipt, the delegation machinery and the base-agreement rule were deleted: 44
files, 2,981 lines out and 215 in, in the main commit. The trust model was stated in one paragraph
of ARCHITECTURE §6 instead of being guarded by records the agent could write anyway. Six rounds,
the most of any task: 35 findings, 2 blocking.

**Publication and the second project.** TASK-PUBLISH-01 found on its own first gate that a licence
counted as code owing a test. Then domain-hunter — the owner's brownfield Python service, 128
commits, a `justfile`, migrations — ran init, spec, task, build and a passing review with no
engine change. Its first hour produced four frictions, which became TASK-FIRSTHOUR-01 (R-32..R-36):
21 findings, 5 blocking, three rounds, and 15 of the 21 on one requirement — drafting a purpose
from a README's first paragraph, which is a Markdown-parsing problem, not one condition. Re-run on
an archive of that project with the new code, the four frictions were gone. The task gate there
then met another agent's uncommitted work in the same tree and refused it as unowned: the
two-builders-one-tree collision the documents describe, shown, not solved. Nothing was committed
in that repository.

**What only a real landing could find.** The framework's own pre-push gate refused the push of the
first landing it met: `land` moves the local mainline before the push, and the gate diffed
against the remote (TASK-LAND-01, R-37: 1 finding, none blocking). The next day the merge gate
refused the five new lens files as documentation outside the profile. Both are one class — a kind
of file or state the checks had never seen — and it is the class to expect on the next new
artefact.

**The last three.** Per-lens staleness (TASK-STABLE-02): 13 findings, 4 blocking; the reviewer,
probing, found that a control deleted after a review is invisible in the text that survives, and
that the plan must owe what the gate demands. The leftovers of retro 0002 (TASK-STABLE-03): 7
findings, 3 blocking; Go prints coverage text before `[no tests to run]`, and git records the
exec bit from the owner's bit alone. Lenses as data (TASK-LENSES-01, ADR-3): 8 findings, none
blocking. Per-lens staleness ran two cap rounds with one lens instead of three on the day it
landed.

| Task | Rounds | Findings | Blocking |
|---|---|---|---|
| TASK-SIMPLE-01 | 6 | 35 | 2 |
| TASK-PUBLISH-01 | 2 | 1 | 0 |
| TASK-FIRSTHOUR-01 | 3 | 21 | 5 |
| TASK-LAND-01 | 2 | 1 | 0 |
| TASK-STABLE-02 | 3 | 13 | 4 |
| TASK-STABLE-03 | 3 | 7 | 3 |
| TASK-LENSES-01 | 3 | 8 | 0 |

**Who reviewed.** Every round in this section was Claude Fable 5.1, briefed as all the lenses the
plan named, in one fresh read-only context per round, and told to run nothing that writes into the
repository and to execute only against an archive copy. That one sentence is what kept every
digest still under a review, after three records in one day were refused because the digest had
moved under one — twice by the builder's own edit while a lens was reading, once by the
reviewer's test run writing into the tree. The builder was the same model in the orchestrating session. The
tier-A rule accepts that — a different context, ideally a different model — and it is weaker
evidence than §2's rounds by another vendor's model.

**Measured.** `aegis metrics` on 2026-09-21, over the eleven tasks then recorded: correctness had
74 of 92 findings fixed, design 79 of 100, security 32 of 50 — acceptance of 0.80, 0.79 and 0.64,
all above the 30% line. No finding marked fixed has come back. Of the 57 still open, 18 are
advisories on merged tasks, declined in writing in their handoffs; the other 39 — 12 of them
blocking — belong to the three abandoned tasks, whose work was re-issued rather than finished, and
stay open in those records as what they were.

**What this still does not prove.** Two projects, one of them the framework itself, and one cycle
on the other, stopped at its gate by a concurrent agent. No measurement of whether the framework
pays for itself over months. No cycle through a pull request with CI as the only barrier. The
version is 0.9.0 for those reasons: 1.0 after a third project and one full pull-request cycle.
