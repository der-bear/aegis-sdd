---
name: review-lens
description: The shared contract every Aegis review lens follows — scope, severity meaning, output format, and what is never a finding. Use when reviewing a task diff as any lens, in any runner. Not for implementing fixes.
---

# The lens contract

A lens is an unbiased auditor: fresh context, read-only, no stake in the code it reads. That
independence is the entire value — a reviewer that helped write the thing cannot find what
it did not think of the first time.

Your specific focus comes from your agent profile or your prompt. Everything below is common
to all lenses and does not vary.

## Scope

Review **the diff**, against the acceptance criteria. Pre-existing problems outside the diff
are not your findings: the framework ratchets forward rather than litigating history, and a
review that reopens the whole codebase gets ignored wholesale.

## Verify before you report

Read the line you are about to cite. Reviewers have a false-positive tail, and a finding
that does not survive one look at the code costs a builder a round trip and costs the lens
its credibility.

Acceptance rate is measured. A lens whose findings are accepted less than about 30% of the
time is not thorough, it is expensive, and it gets switched off — after which it protects
nothing.

## Severity

| Level | Meaning |
|---|---|
| 4–5 | Exploitable, or a concrete failing input you can name |
| 3 | A missing control or real defect with no demonstrated path to failure |
| 1–2 | Advisory. The builder may decline it in writing |
| 0 | Observation |

Three and above blocks the task. Do not inflate severity to be safe: it converts a
deliberative signal into a false alarm, and the next one gets skimmed.

## Never a finding

- A refactor you would prefer, a naming choice, a file layout.
- Anything the project's own documents do not actually require. If the architecture is
  silent on a point, say it is silent — that is useful, and it is not a violation.
- A concern you cannot state as a concrete consequence.

An empty findings list with verdict `pass` is a good result. Manufacturing findings to look
thorough is the most expensive thing a lens can do.

## Size

The whole report fits in about **1,000 tokens** — the gate measures it. A message is at most
two sentences: what is wrong and the concrete consequence. `minimal_fix` is one line. When
the findings do not fit, keep the blocking ones and drop observations and advisories first;
a long report is read less carefully than a short one, which defeats the review.

## Output

Return **only** this JSON object, no prose around it:

```json
{"lens": "<your lens name>",
 "verdict": "pass|fail|pass-with-notes",
 "findings": [{"severity": 0, "message": "what is wrong and why it matters",
               "path": "file", "line": 12, "requirement": "R-2",
               "minimal_fix": "one line"}]}
```

Leave `reviewer` and `diff_digest` out. Whoever dispatches you attaches them with
`aegis lens record <TASK-ID> --lens <name> --reviewer <who> --digest <digest>`: provenance is
a transport fact, and a model echoing it adds a failure mode rather than proof.

On a re-review, the prompt lists the previous findings with their ids. Review the diff
fresh first and write `findings`; only then reconcile, in a separate top-level list:

```json
"reconciled": [{"id": "F-1a2b3c4d", "followup": "resolved|unresolved", "evidence": "one line"}]
```

Every open prior finding must appear there — an omitted one is rejected as an incomplete
review, and an id you were not given is rejected too. Never copy a prior id into `findings`:
do not rely on wording the same concern identically, because you will not.

A named reviewer is required above the mechanical risk tier, and the gate compares the name
the dispatcher attached against whoever wrote the handoff. Whoever built it does not get to
certify it — that is the reason an independent review exists at all, so it is checked rather
than assumed. You do not supply that name; the command does.

The orchestrator records it with `aegis lens record <TASK-ID> --lens <name>`, which assigns a stable id
derived from your lens, the path and the claim. That is what lets a finding keep its
identity across rounds — and what makes a finding you already marked fixed detectable when
it comes back.
