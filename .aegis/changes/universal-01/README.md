# Change bundle universal-01 — steps 1–3 applied, steps 4–5 prepared

Prepared on 2026-09-17 while TASK-UNBLOCK-01 waited for a decision (its review rounds were
exhausted). Verified then on a fresh copy of the tree: `apply_all.sh` followed by
`python3 -m unittest discover -s tests` — 169 tests, OK.

| Steps | Where they landed |
|---|---|
| 1–3 | Applied in **TASK-UNBLOCK-02** (the re-issue of TASK-UNBLOCK-01), then extended there: commit detection also covers quoted option values, backticks and `sh -c`/`bash -c`/`eval`; a `finding` waiver kind lets a person defer a blocking finding |
| 4 | Not applied. For its own task, TASK-UNIVERSAL-01 (ADR-3), after TASK-UNBLOCK-02 merges |
| 5 | Not applied. For its own task after step 4 (ADR-2 B2) |

The scripts require `AEGIS_PATCH_ROOT` (registered in `.aegis/registry/env.json`); `apply_all.sh`
exports it. Each step leaves a marker in `.aegis/changes/universal-01.applied.d/`; steps 1–3 are
marked, so the script skips them and applies 4–5. Checked on a fresh copy of the tree after
TASK-UNBLOCK-02's changes: steps 4 and 5 apply cleanly and the suite passes (174 tests, OK). Apply inside a task whose lease covers
the touched paths — steps 4 and 5 also write `interview/**` and `lenses/**` — and pass the last
step to apply only part:

    .aegis/changes/universal-01/apply_all.sh . 4

## What each step resolves

| Step | Script | Resolves |
|---|---|---|
| 1 | `patch_round3_advisory.py` | design round 3 (sev 1–2): `aegis diff` named in the review, build and orchestrator protocols; spec Contracts; R-21 defines which names are not a person; ADR-2 Consequences name the baseline |
| 2 | `patch_hook_simplify.py`, `tests_hook_simplify.py` | correctness F-57c5beb7, F-6d1d7e2e, F-c9ec7723 and the bare lens name: the commit-hook exemption is **deleted down to one exact command**, git detection moves to tested Python, a baselined file leaves the baseline once any commit touches it |
| 3 | `patch_round3_security.py`, `tests_round3_security.py` | security F-3c8485a5 (renames list both sides), F-4ad7cbdd (brace expansion — closed by step 2), F-7fc9bd6d (inline `-c alias.*`), F-310ded7e (`answers.json` refused to agent edits) |
| 4 | `patch_lenses.py`, `tests_lenses.py`, `patch_lenses_tests_existing.py`, `patch_lenses_docs.py`, `lenses_src/` | ADR-3: lenses are files (`lenses/*.md`, project `.aegis/lenses/`), two auditor profiles replace three per-lens profiles, the matrix is derived and proven equal to the former constant, `aegis lens prompt`, `scripts/aegis/external-lens.sh` for any engine, `codex-lens.sh` a wrapper, `q.core.second-engine` may be empty, accessibility (web-saas) and data-integrity (data-etl) lenses |
| 5 | `patch_task2.py`, `tests_task2.py`, `patch_task2_docs.py` | ADR-2 B2: honest detection keys and thresholds, "a test command that ran no tests" fails, `[NEEDS CLARIFICATION]` and duplicate requirement ids, `.agents/skills` as adapters, `aegis packet --delta-from` for warm builders (D9), a root-cause pass on the second rejection (D10), the packet's handoff template asks for `agent` |

## The gap this bundle did not close

Deferring a blocking review finding needed a waiver the disposition could cite, but the waiver
schema had no check kind for a review finding. Closed in TASK-UNBLOCK-02: `"check": "finding"`,
scope lists finding ids, never matched by `apply_waivers`, and both the disposition's `--by`
and the waiver's owner must be a person's name (R-25).
