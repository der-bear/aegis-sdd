"""Project skeleton. Called by /aegis:init once the interview has answers.

Scaffolding writes two kinds of file and never confuses them: human-owned documents that
are created once and then belong to the team, and generated configuration that is
rewritten from answers.json on every compile. Nothing here writes into generated/.
"""
from __future__ import annotations

import datetime as _dt
import os

from . import checks
from .core import Ctx, read_json, read_text, write_json, write_text

CLAUDE_MD = """# {name}

@.aegis/generated/rules.md

<!-- aegis:pointer — the line above imports the compiled agent rules. If you are an agent
     and this import is missing, run `aegis migrate`. Rules live in .aegis/generated/,
     which is write-protected; edit .aegis/answers.json to change them. -->
"""

# AGENTS.md is the Linux Foundation standard read by Codex and twenty other tools. It has
# no import mechanism, so it carries a read instruction instead of an @import.
AGENTS_MD = """# {name}

Before doing anything here, read `.aegis/generated/rules.md` — the project's compiled
agent rules. Then run `aegis next` for the current step. The `aegis` command comes from
the Aegis checkout; run its `install.sh` once if it is missing.

<!-- aegis:pointer -->
"""

CONSTITUTION = """# Constitution

Authoritative for: the principles below, and nothing else.
References only: everything in `.aegis/generated/` (compiled — see `answers.json`).

**This file is written and changed by a human. Agents may open a pull request against it;
they may not edit it.** Generated configuration lives in `.aegis/generated/policy.json`
and is referenced from here rather than copied, so the two can never disagree.

## Purpose

<one paragraph: what this project is for, and what would make it a failure>

## Non-negotiable

1. <e.g. no user data leaves the primary region>
2. <e.g. money movement is append-only and double-entry>
3. <e.g. public API contracts change only through a versioned deprecation>

## Autonomy limits

Agents decide alone: see `policy.autonomy_limits` in `.aegis/generated/policy.json`.
Agents always escalate: data migrations, public contract changes, security policy,
licence or paid-service choices, and anything that cannot be undone by a revert.

## Frozen zones

Paths no agent modifies without explicit human instruction:

- <path or glob>

## Amendment

Change this file in its own pull request, reviewed by a human, never bundled with feature
work. If a change here also implies configuration, edit `answers.json` and run
`aegis compile` in the same pull request.
"""

NOTES = """# Working notes

Owner: orchestrator. Rewritten at each milestone, not appended to — this is a checkpoint,
not a log. Keep it under the `notes` token budget in `policy.json`.

## Current milestone

## Decisions taken (with the ADR they became, if any)

## Open questions for the human

## How to verify the current state
"""

MISSION = """# Mission

Authoritative for: why this product exists and who it is for.

## Problem

## Who it serves

## What success looks like (measurable)

## Explicitly not doing
"""

ROADMAP = """# Roadmap

Authoritative for: milestones and their measurable outcomes.

| Milestone | Outcome (measurable) | Status |
|---|---|---|
| M1 | | planned |
"""

STANDARDS_INDEX = """# Standards index

One line per standard. Agents read the line, then the file only if it applies.

| File | Applies to | One-line rule |
|---|---|---|
"""

REGISTRY_SEEDS = {
    "integrations": [],
    "events": [],
    "env": [],
    "flags": [],
    "diagrams": [],
}


BASELINE_CAP = 5000


def _adoption_baseline(ctx: Ctx) -> dict:
    """Uncommitted files present when Aegis was adopted, with their content hashes.

    See `core._pre_adoption_files` for why. Capped: a tree with thousands of untracked
    files is not a baseline, it is a repository that needs a commit first, and the ledger
    says so instead of recording a hash for every file.
    """
    from .core import git_available, head_sha, working_tree_files, file_sha256, matches_any
    if not git_available(ctx):
        return {}
    # Paths leased to an open task are that task's work in progress, not the state of the
    # repository at adoption. Baselining them would exempt the task's own edits from its gate.
    leased = [glob for task in checks.active_tasks(ctx)
              if task.get("status") not in ("merged", "abandoned")
              for glob in (task.get("owns") or [])]
    # `.agents/` holds copies the framework derives from its own protocols: exempt from
    # attribution already, and refreshed by `aegis migrate`, so a hash of one is only noise.
    # Every uncommitted change, not only untracked files: a staged rename or an edited tracked
    # file present at adoption is the repository's starting state just the same.
    pending = sorted(f for f in working_tree_files(ctx)
                     if not f.startswith((".aegis/", ".agents/"))
                     and not (leased and matches_any(f, leased)))
    recorded = _dt.date.today().isoformat()
    if len(pending) > BASELINE_CAP:
        return {"head": head_sha(ctx), "recorded": recorded, "files": {}, "skipped": len(pending),
                "note": "too many uncommitted files to baseline; commit them first"}
    from .core import ABSENT, content_key
    hashes = {}
    for rel in pending:
        full = os.path.join(ctx.root, rel)
        key = content_key(full)
        if key is not None:
            hashes[rel] = key
        elif not os.path.lexists(full):
            # A deletion pending at adoption, including the source side of a staged rename, is
            # the repository's starting state just as much as an edited file is. Skipping it
            # left a path that no lease could own — a frozen destination cannot be leased — and
            # therefore a `trace` failure nothing could clear.
            hashes[rel] = ABSENT
    # Recorded even when empty: a clean tree at adoption is a baseline of nothing, and must
    # not read later as "never recorded". `absent_recorded` says this baseline already knows
    # about missing paths, so the one-time rename backfill has nothing to complete.
    return {"head": head_sha(ctx), "recorded": recorded, "files": hashes, "absent_recorded": True}


def record_baseline_if_missing(ctx: Ctx) -> int | None:
    """For a project adopted before baselines existed: record one, once. None when there
    was nothing to do — no answers file, a baseline already present, or no untracked files."""
    path = ctx.path("answers.json")
    if not os.path.exists(path):
        return None
    answers = read_json(path)
    detected = answers.setdefault("detected", {})
    if "baseline" in detected:
        # Presence, not truthiness: a clean tree records an empty baseline at adoption, and
        # treating that as "never recorded" let a later migrate baseline newer files.
        return None
    baseline = _adoption_baseline(ctx)
    if not baseline:
        return None
    detected["baseline"] = baseline
    write_json(path, answers)
    return len(baseline.get("files") or {})


def complete_baseline_renames(ctx: Ctx) -> list[str]:
    """Add the source side of a pending rename to a baseline recorded without it.

    A baseline recorded before ADR-4 hashed files, so a deletion had nothing to record, and
    git's rename detection hid the source of a staged rename entirely. The pairing is the proof:
    a deletion git pairs with a destination that the baseline holds, whose content still matches
    what was recorded, was part of the repository's state at adoption. Nothing else is added —
    a bare deletion is a change, and it belongs to a task.
    """
    from .core import ABSENT, file_sha256, git, git_available

    path = ctx.path("answers.json")
    if not (os.path.exists(path) and git_available(ctx)):
        return []
    answers = read_json(path)
    baseline = ((answers.get("detected") or {}).get("baseline") or {})
    files = baseline.get("files")
    if not isinstance(files, dict) or not files:
        return []
    if baseline.get("absent_recorded"):
        # Once, for a baseline written before absence was a record. Left running, it would read
        # every later `migrate` against the current index, and a rename staged after adoption
        # would record its source as adoption — which the pairing does not prove.
        return []
    added = []
    records = [r for r in git(ctx, "status", "--porcelain", "--untracked-files=all", "-z").split("\0") if r]
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if len(record) <= 3 or "R" not in record[:2] or index >= len(records):
            continue
        destination, source = record[3:], records[index]
        index += 1
        recorded = files.get(destination)
        if not recorded or recorded == ABSENT or source in files:
            continue
        full = os.path.join(ctx.root, destination)
        if not os.path.isfile(full) or file_sha256(full) != recorded:
            continue  # the destination has moved on, so it proves nothing about the source
        files[source] = ABSENT
        added.append(source)
    baseline["absent_recorded"] = True
    write_json(path, answers)
    return sorted(added)


GIT_HOOK_MARK = "# installed by `aegis git-hooks install`"

_PRE_COMMIT = GIT_HOOK_MARK + """
# Fast, and about the commit itself: compiled configuration must match its answers, and the
# framework's own files must be where the framework expects them. Both take a fraction of a
# second and neither reads the diff. Everything that judges the *change* — attribution, reviews,
# tests, documentation — runs at the merge boundary: `pre-push` and CI. A commit is a checkpoint,
# and a checkpoint that a gate can refuse is a checkpoint nobody makes.
set -eu
root=$(git rev-parse --show-toplevel)
[ -d "$root/.aegis" ] || exit 0
aegis="__AEGIS__"
[ -x "$aegis" ] || aegis=$(command -v aegis 2>/dev/null || true)
if [ -z "${aegis:-}" ] || [ ! -x "$aegis" ]; then
  {
    echo "Aegis cannot run: the CLI is not at __AEGIS__ and not on PATH."
    echo "Run the framework's install.sh, or \\`aegis git-hooks install\\` from the checkout you use."
  } >&2
  exit 1
fi
if output=$("$aegis" --root "$root" check drift 2>&1) && output2=$("$aegis" --root "$root" check structure 2>&1); then
  exit 0
fi
{
  echo "Aegis: this commit would leave compiled configuration out of step with its answers."
  printf '%s\\n%s\\n' "${output:-}" "${output2:-}" | grep -E '^\\s*\\[FAIL\\]' | head -12
  echo "\\`aegis compile\\` regenerates it; \\`aegis answer <q> <v>\\` is how configuration changes."
} >&2
exit 1
"""


_PRE_PUSH = GIT_HOOK_MARK + """
# What is about to become other people's problem runs the full gate, commands included.
set -eu
root=$(git rev-parse --show-toplevel)
[ -d "$root/.aegis" ] || exit 0
aegis="__AEGIS__"
[ -x "$aegis" ] || aegis=$(command -v aegis 2>/dev/null || true)
if [ -z "${aegis:-}" ] || [ ! -x "$aegis" ]; then
  {
    echo "Aegis gate cannot run: the CLI is not at __AEGIS__ and not on PATH."
    echo "Run the framework's install.sh, or \\`aegis git-hooks install\\` from the checkout you use."
    echo "A hook that cannot check is not a gate, so this refuses rather than passing quietly."
  } >&2
  exit 1
fi
if output=$("$aegis" --root "$root" gate --stage merge 2>&1); then
  exit 0
fi
{
  echo "Aegis merge gate failed — this push would break the branch."
  printf '%s\\n' "$output" | tail -40
} >&2
exit 1
"""


def install_git_hooks(ctx: Ctx, force: bool = False) -> dict[str, str]:
    """Install the git-level gate, and say what happened to each hook.

    The Claude Code hooks are an early error inside one runner. A git hook covers every commit
    in this checkout whatever produced it — a Codex session, a script, a person — which is the
    parity the framework claims and did not have. `--no-verify` still skips it: the barrier
    nothing skips is CI, and the hook's own message says so.
    """
    from .core import git, git_available

    if not git_available(ctx):
        return {}
    from .core import plugin_root

    executable = os.path.join(plugin_root(), "scripts", "aegis", "aegis")
    hooks_dir = (git(ctx, "rev-parse", "--git-path", "hooks").strip()
                 or os.path.join(".git", "hooks"))
    if not os.path.isabs(hooks_dir):
        hooks_dir = os.path.join(ctx.root, hooks_dir)
    os.makedirs(hooks_dir, exist_ok=True)
    out: dict[str, str] = {}
    for name, body in (("pre-commit", _PRE_COMMIT), ("pre-push", _PRE_PUSH)):
        path = os.path.join(hooks_dir, name)
        # The path is baked at install time: a hook that shrugs when it cannot find the tool
        # is a gate that can be skipped by absence.
        content = ("#!/usr/bin/env sh\n" + body.lstrip("\n")).replace("__AEGIS__", executable)
        if os.path.exists(path):
            existing = read_text(path, default="")
            if existing == content:
                out[name] = "unchanged"
                continue
            if GIT_HOOK_MARK not in existing and not force:
                # Someone else's hook is someone else's decision.
                out[name] = "kept — not ours; re-run with --force to replace it"
                continue
        write_text(path, content)
        os.chmod(path, 0o755)
        out[name] = "installed"
    return out


def initialise(ctx: Ctx, mode: str = "hybrid", profile: str | None = None,
               force: bool = False, accept_all: bool = False) -> dict:
    """One command from an unknown repository to a working project: detect, scaffold,
    compile, index.

    Detection runs first and fills `answers.json` so the interview that follows asks about
    intent only. Everything auto-resolved lands in the ledger with its evidence, so the
    human reviews a short list of decisions instead of answering a long questionnaire.
    """
    from . import config, detect as detect_mod, flow

    facts = detect_mod.detect(ctx)
    facts["baseline"] = _adoption_baseline(ctx)
    resolved: dict[str, dict] = {}
    ledger: list[dict] = []

    def record(qid: str, value, source: str, confidence: float, why: str,
               threshold: float = 0.8) -> None:
        resolved[qid] = {"value": value, "source": source, "confidence": confidence, "rationale": why}
        if source != "human" and confidence < threshold:
            ledger.append({"question": qid, "value": value, "confidence": confidence, "note": why})

    chosen_profile = profile or facts["repo_size"]
    record("q.core.profile", chosen_profile, "human" if profile else "heuristic",
           1.0 if profile else 0.7, f"{'chosen' if profile else 'repository size'}")
    record("q.core.project-type", facts["project_type"], "detected",
           facts["project_type_confidence"], facts["project_type_evidence"])
    record("q.core.mode", mode, "human", 1.0, "init flag")
    if facts["packages"]:
        record("q.core.commands", facts["packages"], "detected", 0.9,
               f"{len(facts['packages'])} package(s) found in manifests")
    else:
        ledger.append({"question": "q.core.commands", "value": {}, "confidence": 0.0,
                       "note": "no build manifest found — the gate cannot run project commands until this is set"})
    if facts["frozen_candidates"]:
        ledger.append({"question": "q.core.frozen", "value": facts["frozen_candidates"],
                       "confidence": 0.5, "note": "candidates only; confirm before they become a hard boundary"})

    # Every other question that declares `detect:` resolves the same way: through the one table
    # detection publishes, against the threshold the question itself declares. The four hand
    # written records above are the ones whose value is not a detected fact (the profile, the
    # mode) or which the packet cannot run without (the commands).
    known = detect_mod.answerable(facts)
    for bank in config.load_banks(ctx).values():
        for question in bank.get("questions", []):
            qid, key = question.get("id"), question.get("detect")
            if not qid or not key or qid in resolved:
                continue
            threshold = config.auto_threshold(question)
            if threshold is None or key not in known:
                continue
            value, confidence, why = known[key]
            record(qid, value, "detected", confidence, why, threshold)

    answers = {
        "mode": mode,
        "status": "provisional" if ledger else "complete",
        "detected": {k: v for k, v in facts.items() if k not in ("evidence", "surfaces")},
        "resolved": resolved,
        "ledger": ledger,
        "evidence": facts["evidence"],
    }

    # Read before scaffolding: `--force` rewrites answers.json, and reading it afterwards lost
    # the adoption baseline — the one thing `--force` must not reset.
    answers_path = ctx.path("answers.json")
    existing = read_json(answers_path, default=None) if os.path.exists(answers_path) else None
    created = scaffold(ctx, chosen_profile, facts["project_type"], force)

    # Re-running init is normal — a package was added, the stack changed. It must refresh
    # what was *detected* and leave what a human *decided* alone; overwriting the file
    # wholesale silently discarded reviewed answers and reopened the ledger.
    if existing and "baseline" in (existing.get("detected") or {}):
        # The adoption baseline is recorded once — `--force` included. Refreshing it on a
        # re-run would launder edits into "pre-existing" files, the opposite of a ratchet.
        answers["detected"]["baseline"] = existing["detected"]["baseline"]
    if existing and not force:
        kept = {qid: entry for qid, entry in (existing.get("resolved") or {}).items()
                if isinstance(entry, dict) and entry.get("source") == "human"}
        answers["resolved"].update(kept)
        answers["ledger"] = [row for row in answers["ledger"] if row["question"] not in kept]
        answers["status"] = "provisional" if answers["ledger"] else existing.get("status", "complete")
        answers["preserved_human_answers"] = sorted(kept)
    banks = config.load_banks(ctx)
    for question in config.resolve_questions(banks, config.select_banks(answers)) if banks else []:
        if question.get("autonomy") != "always-ask" or question["id"] in resolved:
            continue
        ledger.append({"question": question["id"], "value": question.get("default"),
                       "confidence": 0.0,
                       "note": f"only a human can answer this: {question.get('ask', '')}"})
    if ledger:
        answers["ledger"] = ledger
        answers["status"] = "provisional"

    if facts.get("truncated"):
        # Recorded before the file is written: appended afterwards, the fact lived only in
        # this run's console output and the next session could not learn detection had been
        # partial — which is precisely when it matters.
        answers["ledger"].append({
            "question": "detection completeness", "value": "partial", "confidence": 0.4,
            "note": "the repository is large enough that ordinary files were not all listed; "
                    "build manifests were, but observed conventions may be incomplete — "
                    "raise AEGIS_WALK_LIMIT or run init per sub-tree"})
        answers["status"] = "provisional"

    write_json(answers_path, answers)

    if accept_all and answers["ledger"]:
        # Accepting the assumptions is a decision, so it is recorded as one rather than
        # making the ledger disappear. The list stays readable; what changes is that a
        # person took responsibility for it and phase 3 is no longer blocked.
        answers["accepted_assumptions"] = {
            "at": _dt.datetime.now().replace(microsecond=0).isoformat(),
            "count": len(answers["ledger"]),
            "note": "accepted wholesale via `aegis init --yes`; each entry is still listed in ledger",
        }
        answers["status"] = "complete"
        write_json(answers_path, answers)
        accepted, ledger = list(answers["ledger"]), []

    config.materialize(ctx)
    copied = vendor_protocols(ctx)
    created.extend(copied)
    created.extend(install_ci(ctx))
    flow.build_indexes(ctx)
    return {
        "accepted": bool(accept_all and answers.get("accepted_assumptions")),
        "created": created,
        "profile": chosen_profile,
        "project_type": facts["project_type"],
        "packages": facts["packages"],
        "brownfield": facts["brownfield"],
        "ledger": ledger,
        "surfaces": {k: len(v) for k, v in facts["surfaces"].items()},
    }


def install_ci(ctx: Ctx) -> list[str]:
    """Put the merge gate where it becomes a property of the repository.

    The commit hook is per-machine and per-agent; CI runs on the candidate commit whoever
    produced it. Installed automatically only into a project that already uses GitHub
    Actions — adding a CI system to a project that has none is a decision, not a default.
    """
    from .core import plugin_root

    template = os.path.join(plugin_root(), "templates", "ci", "aegis-gate.yml")
    if not os.path.exists(template):
        return []
    workflows = os.path.join(ctx.root, ".github", "workflows")
    target = (os.path.join(workflows, "aegis-gate.yml") if os.path.isdir(workflows)
              else ctx.path("ci", "aegis-gate.yml"))
    if os.path.exists(target):
        return []
    write_text(target, read_text(template))
    return [ctx.rel(target)]


def vendor_protocols(ctx: Ctx) -> list[str]:
    """Copy the protocols into the project as `.aegis/protocols/<name>.md`.

    Three reasons this is worth the duplication. A task packet cites protocol paths, and an
    absolute path into whoever ran `init` first does not resolve on a colleague's machine or
    in CI. Codex and a human need the same file the Claude subagent was given, without
    knowing where the plugin lives. And a protocol that changed under a project should show
    up as a reviewable diff rather than as different behaviour on different machines.
    """
    written: list[str] = []
    for source in checks.skill_files(ctx):
        if os.path.abspath(source).startswith(os.path.abspath(ctx.path("protocols"))):
            continue
        if "/.agents/" in os.path.abspath(source).replace(os.sep, "/"):
            continue
        content = read_text(source)
        front, _body = checks.parse_frontmatter(content)
        name = front.get("name") or os.path.basename(os.path.dirname(source))
        if write_text(ctx.path("protocols", f"{name}.md"), content):
            written.append(f".aegis/protocols/{name}.md")
        # Codex discovers repository skills under `.agents/skills/`. Exporting the runner
        # neutral procedures there is what makes "the same protocol, either runner" true
        # rather than aspirational — a Codex session finds them without being told where.
        if name in RUNNER_NEUTRAL:
            target = os.path.join(ctx.root, ".agents", "skills", name, "SKILL.md")
            if write_text(target, content):
                written.append(f".agents/skills/{name}/SKILL.md")
    return written


RUNNER_NEUTRAL = {"build-task", "review-lens", "doc-sync",
                  "registry-authoring", "doc-authoring", "protocol-authoring"}


def scaffold(ctx: Ctx, profile: str, doc_profile: str, force: bool = False) -> list[str]:
    created: list[str] = []

    def put_text(rel: str, content: str, pointer: str | None = None) -> None:
        path = os.path.join(ctx.root, rel) if not rel.startswith(".aegis/") else ctx.path(rel[len(".aegis/"):])
        if os.path.exists(path) and not force:
            # An existing CLAUDE.md or AGENTS.md belongs to the project. Leaving it entirely
            # alone was worse than overwriting it, though: the agents that read it then had
            # no idea Aegis was installed. Append a pointer, keep their content.
            if pointer:
                current = read_text(path, default="")
                if "Aegis" not in current:
                    write_text(path, current.rstrip("\n") + "\n\n" + pointer)
                    created.append(f"{rel} (pointer appended)")
            return
        if write_text(path, content):
            created.append(rel)

    def put_json(rel: str, data) -> None:
        path = ctx.path(rel[len(".aegis/"):])
        if os.path.exists(path) and not force:
            return
        if write_json(path, data):
            created.append(rel)

    name = os.path.basename(ctx.root)
    claude_pointer = ("\n@.aegis/generated/rules.md\n"
                      "<!-- aegis:pointer -->\n")
    agents_pointer = ("\n## Aegis\n\nBefore working here, read `.aegis/generated/rules.md` "
                      "— the compiled agent rules.\n<!-- aegis:pointer -->\n")
    put_text("CLAUDE.md", CLAUDE_MD.format(name=name), claude_pointer)
    put_text("AGENTS.md", AGENTS_MD.format(name=name), agents_pointer)
    put_text(".aegis/constitution.md", CONSTITUTION)
    put_text(".aegis/memory/NOTES.md", NOTES)
    put_text(".aegis/product/mission.md", MISSION)
    put_text(".aegis/product/roadmap.md", ROADMAP)
    put_text(".aegis/standards/index.md", STANDARDS_INDEX)

    put_json(".aegis/answers.json", {
        "mode": "hybrid",
        "status": "provisional",
        "detected": {},
        "resolved": {
            "q.core.profile": {"value": profile, "source": "cli", "confidence": 1.0},
            "q.core.project-type": {"value": doc_profile, "source": "cli", "confidence": 1.0},
        },
        "ledger": [],
    })
    put_json(".aegis/waivers.json", [])
    for registry, seed in REGISTRY_SEEDS.items():
        put_json(f".aegis/registry/{registry}.json", seed)

    runs = ctx.path("runs")
    os.makedirs(runs, exist_ok=True)
    keep = os.path.join(runs, ".gitkeep")
    if not os.path.exists(keep):
        write_text(keep, "")
        created.append(".aegis/runs/.gitkeep")
    return created
