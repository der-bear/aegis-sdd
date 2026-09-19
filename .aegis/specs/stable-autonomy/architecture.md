# Architecture: stable-autonomy

## Components and responsibilities

- `scripts/aegis/aegis_cli/checks.py` — budget severities (R-1), waiver validation and the
  person test (R-5, R-7), requirement coverage with `pending` (R-6), per-lens staleness by
  kind (R-9), `tests_ran` (R-11).
- `scripts/aegis/aegis_cli/flow.py` — `next_action` at the cap (R-2), merge receipt and
  `_default_base` (R-4), `aegis land` and `aegis waive` (R-4, R-5), `task_diff` (R-7),
  `status` baseline line (R-13).
- `scripts/aegis/aegis_cli/core.py` — `commit_scope` deleted (R-3), `_git_key`/`_digest_in_index`
  (R-12, R-14).
- `scripts/aegis/aegis_cli/scaffold.py` — installed hook bodies (R-7).
- `scripts/aegis/aegis_cli/config.py`, `interview/core.json` — `policy.delegation` (R-5).
- `hooks/` — `pre-commit-gate.sh` and its `hooks.json` entry deleted (R-3).
- `skills/`, `.agents/skills/`, `.aegis/protocols/` — review-lens (R-1), doc-sync (R-10),
  build (order of verification and review).
- `docs/`, `README.md`, `.github/workflows/` — R-8, R-15.

## Contracts and interfaces

- Merge receipt: `.aegis/runs/<TASK>/merge-receipt.json` = `{"task", "sha", "at", "files":
  {path: content key}}`. Written only by a green full merge gate. Read by `check_trace`: a
  merged task owns a scope file only while `content_key(path)` equals the record. The merge
  base does not change; landing is bookkeeping.
- `policy.delegation` = `{"owner": "<person>", "may_waive": ["docs", "env", …]}`. Compiled
  from `answers.json`; absent means no delegation.
- `aegis waive <check> --scope <glob,…> --reason <text> --expires <date>` records a waiver
  owned by `policy.delegation.owner`, refusing a check outside `may_waive`.
- Per-lens staleness (R-9): `stale(lens) = any(kinds(f) ∩ triggers(lens) for f in changed
  since record.digest)`, computed at check time from `detect_change_kinds`.
- `checks.HOLDING` = the statuses in which a task holds its lease (`building` … `gated`). Read
  by `check_trace` (who owns a file), the merge gate (who owes a handoff and reviews) and
  `_refuse_lease_clash` (who may claim). One tuple, three readers.

## Boundaries

Nothing here stores new mutable state except the merge receipt, which is an attestation over
a commit — the shape ADR-1 moves everything to. No new agent role. No vendor dependency.
