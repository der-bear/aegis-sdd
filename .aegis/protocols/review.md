---
name: review
description: Run the Aegis review lenses over a task's diff and record their findings, without implementing anything. Use to review completed work, re-review after fixes, or review a task built elsewhere.
argument-hint: "<TASK-ID> [--closing]"
allowed-tools: Read, Grep, Glob, Bash, Agent
---

# Review a task

## 1. Which lenses

```bash
aegis lens plan <TASK-ID>          # add --closing when finishing a feature
```

Run exactly what it names. Not fewer because the change looks small — the plan already saw
the diff. Not more because it looks risky — an extra lens costs a full context and dilutes
the signal from the ones that mattered.

## 2. Dispatch

All lenses in parallel, each in a clean context, each read-only. Give each one the task id,
`aegis packet <TASK-ID>` and `aegis diff <TASK-ID>` — exactly the files the digest covers;
`git diff` misses new untracked files the digest includes. Do not summarise the diff for
them — a summary hides exactly the detail a reviewer is for.

Only `lens-correctness` has `Bash`. The other two cannot execute anything, which is what
makes their read-only status a property rather than an instruction.

## 3. Record

```bash
echo '<json>' | aegis lens record <TASK-ID> --lens <name> --reviewer lens-<name> --digest <diff_digest>
```

`--reviewer` and `--digest` are attached by you, the dispatcher — the digest is the one
`aegis lens plan` printed, and a lens that echoes either adds a failure mode, not proof.
On a re-review, hand each lens the ids from its own `.aegis/runs/<TASK-ID>/reviews/<lens>.json`;
it returns `reconciled` and the recorder refuses an id it never raised, or an open prior
finding it left out.

Never paraphrase a lens's output into the record. The JSON is the evidence, it is what the
gate reads, and it is what survives into the pull request.

## 4. Judge the findings before acting

Reviewers have a false-positive tail. Before sending a finding back to a builder, confirm it
against the code — read the line it cites. A finding that does not survive that check is
`false-positive`, recorded with a reason, and it counts against that lens in the metrics.

That accounting is the point: a lens whose findings are accepted less than about 30% of the
time is not protecting the project, it is taxing it. Fix its protocol or switch it off.

## Verdicts

- `pass` — nothing blocking. An empty findings list is a good result, not a lazy one.
- `pass-with-notes` — advisory findings only.
- `fail` — at least one severity 3+ finding.

The verdict does not decide anything by itself. `aegis gate` decides, from the recorded
findings and their dispositions. Lenses advise; the deterministic gate rules.
