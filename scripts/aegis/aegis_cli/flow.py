"""Run-level mechanics: task manifests, task packets, lens records, staged gates.

The artifacts here are the ones that make a crashed session recoverable. A builder's
handoff and a lens's report are files with schemas, not messages in a transcript, because
a transcript does not survive compaction and cannot be diffed in a pull request.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
from typing import Any

from . import checks
from .core import (
    content_key, file_mode_tracked, ABSENT, git,
    AegisError,
    Ctx,
    EMPTY_TREE,
    Report,
    append_jsonl,
    canonical,
    changed_files,
    diff_digest,
    emit,
    estimate_tokens,
    git,
    git_available,
    globs_overlap,
    head_sha,
    default_base,
    require_base,
    human_tokens,
    in_review_scope,
    matches_any,
    normalise_glob,
    read_json,
    read_jsonl,
    read_text,
    staged_files,
    working_tree_files,
    untracked_files,
    validate,
    write_json,
    write_text,
)

CHANGE_KINDS = [
    "code", "test", "docs", "route", "auth", "contract",
    "cross-module", "dependency", "data-migration", "money", "concurrency",
]

# The id becomes a directory under .aegis/runs/, so it is validated rather than trusted.
TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def now() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def run_dir(ctx: Ctx, task_id: str) -> str:
    """Every path built from a task id goes through here, and every id is validated here.

    Validating only at creation left `aegis task status ../.. building` rewriting whatever
    `manifest.json` happened to sit two directories up.
    """
    if not TASK_ID.match(task_id):
        raise AegisError(
            f"invalid task id {task_id!r}: letters, digits, dot, dash and underscore only. "
            "The id becomes a directory name under .aegis/runs/."
        )
    return ctx.path("runs", task_id)


# ---------------------------------------------------------------------- task setup


def task_new(ctx: Ctx, task_id: str, *, feature: str, objective: str, owns: list[str],
             requirements: list[str], kinds: list[str], acceptance: list[str],
             reads: list[str] | None = None, size: str = "M") -> dict:
    """Create the task manifest. This is the write lease: `owns` is exclusive.

    Written before any code, because a lease decided afterwards is not a lease — it is a
    description of whatever the agent happened to touch.
    """
    if not TASK_ID.match(task_id):
        raise AegisError(
            f"invalid task id {task_id!r}: use letters, digits, dot, dash and underscore only. "
            "The id becomes a directory name, so anything else would write outside .aegis/runs/."
        )
    # Serialise creation. Two agents calling `task new` at once both saw "no conflict" and
    # both wrote overlapping manifests — the check was correct and the sequence was not.
    os.makedirs(ctx.path("runs"), exist_ok=True)
    lock = ctx.path("runs", ".lock")
    try:
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        age = _dt.datetime.now().timestamp() - os.path.getmtime(lock)
        if age < 60:
            raise AegisError("another `aegis task new` is running; retry in a moment") from None
        os.remove(lock)  # a crashed process left it behind
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        return _task_new_locked(ctx, task_id, feature=feature, objective=objective, owns=owns,
                                requirements=requirements, kinds=kinds, acceptance=acceptance,
                                reads=reads, size=size)
    finally:
        os.close(handle)
        if os.path.exists(lock):
            os.remove(lock)


def _task_new_locked(ctx: Ctx, task_id: str, *, feature: str, objective: str, owns: list[str],
                     requirements: list[str], kinds: list[str], acceptance: list[str],
                     reads: list[str] | None, size: str) -> dict:
    policy = checks.policy(ctx)
    limit = policy.get("parallel_builders", 1)
    in_flight = [t for t in checks.active_tasks(ctx)
                 if t.get("status") == "building"]
    if len(in_flight) >= limit:
        raise AegisError(
            f"profile {policy.get('profile')} allows {limit} task(s) in flight and "
            f"{len(in_flight)} already are ({', '.join(t['id'] for t in in_flight)}). "
            "Finish one, or raise the limit deliberately by changing the profile — "
            "parallelism is bounded by review capacity, not by how many agents are available."
        )

    if os.path.exists(os.path.join(run_dir(ctx, task_id), "manifest.json")):
        # Silently rewriting the manifest kept the old handoff and reviews, so the run
        # directory would describe two different pieces of work at once.
        raise AegisError(
            f"{task_id} already exists. Pick a new id, or delete .aegis/runs/{task_id}/ "
            "if that run is genuinely being abandoned."
        )
    unknown = [k for k in kinds if k not in CHANGE_KINDS]
    if unknown:
        raise AegisError(f"unknown change kinds {unknown}; expected any of {', '.join(CHANGE_KINDS)}")
    framework = [g for g in owns if normalise_glob(g).startswith(".aegis/")]
    if framework:
        raise AegisError(
            f"a task cannot lease framework state: {framework}. `.aegis/` is written by the "
            "framework and by humans, never by a task — `trace` exempts it, so the lease would "
            "attribute nothing."
        )
    if not owns:
        raise AegisError(
            "a task needs at least one --owns glob. Without a write lease nothing constrains "
            "where it writes, and `aegis check trace` cannot attribute its changes."
        )

    # A frozen zone that only lives in a configuration file is a wish. Refusing the lease is
    # where it becomes a boundary, because it happens before any code is written.
    frozen = read_json(ctx.gen("standards.json"), default={}).get("frozen_zones") or []
    trespass = [g for g in owns if any(globs_overlap(g, f) for f in frozen)]
    if trespass:
        raise AegisError(
            f"lease {trespass} enters a frozen zone ({', '.join(frozen)}). "
            "Frozen zones are changed by a human, not leased to an agent — "
            "narrow the lease, or have the human unfreeze the path in answers.json first."
        )


    manifest = {
        "id": task_id,
        "feature": feature,
        "risk_tier": _risk_tier(checks.policy(ctx), sorted(set(kinds)))["id"],
        "objective": objective,
        "status": "planned",
        "size": size,
        "base_sha": head_sha(ctx) if git_available(ctx) else None,
        "owns": sorted(owns),
        "reads": sorted(reads or []),
        "requirements": sorted(requirements),
        "change_kinds": sorted(set(kinds)),
        "acceptance": acceptance,
        "created": now(),
    }
    write_json(os.path.join(run_dir(ctx, task_id), "manifest.json"), manifest)
    return manifest


def gate_receipt_valid(ctx: Ctx, task_id: str) -> bool:
    """Did a passing gate write a receipt for the code as it stands now?

    Status lives in a manifest anyone can edit. Editing `planned` to `gated` made `aegis
    next` recommend a merge for work no gate had ever seen; the receipt is what the status
    now has to agree with.
    """
    path = os.path.join(run_dir(ctx, task_id), "gate-receipt.json")
    if not os.path.exists(path):
        return False
    receipt = read_json(path)
    if receipt.get("task") != task_id:
        return False  # a receipt copied from another run is not this task's evidence
    manifest = checks.load_task(ctx, task_id)
    return receipt.get("diff_digest") == diff_digest(ctx, manifest.get("base_sha"), task_id)




def task_status(ctx: Ctx, task_id: str, status: str) -> dict:
    allowed = ["planned", "building", "gated", "merged", "abandoned"]
    if status not in allowed:
        raise AegisError(f"unknown status {status!r}; expected one of {', '.join(allowed)}")

    current_status = read_json(os.path.join(run_dir(ctx, task_id), "manifest.json")).get("status", "planned")
    allowed_from = {
        "planned": {"building", "abandoned"},
        "building": {"abandoned", "building"},
        "gated": {"building", "abandoned"},
        "merged": set(),
        "abandoned": set(),
    }
    if status in ("gated", "merged"):
        # Written by the thing that makes them true — a green task gate, and `aegis land` —
        # and by nothing else, or "one place" is a sentence rather than a property.
        raise AegisError(f"{task_id} cannot become {status!r} by hand: `aegis gate --stage task` "
                         f"writes gated, `aegis land` writes merged")
    if status != current_status and status not in allowed_from.get(current_status, set()):
        # The disk state is what a resumed session reads to decide what to do next; letting
        # it move backwards or sideways makes that decision meaningless.
        raise AegisError(
            f"{task_id} is {current_status!r} and cannot become {status!r}. "
            f"From {current_status!r} the valid moves are: "
            f"{', '.join(sorted(allowed_from.get(current_status, set())) or ['none — it is terminal'])}."
        )

    if status == "building" and current_status != "building":
        manifest = checks.load_task(ctx, task_id)
        # Where the lease is actually taken. Checking only in `task_claim` left
        # `aegis task status <id> building` as a way past it whenever the profile allows a
        # second builder, and a later claim then passed because the task was no longer planned.
        _refuse_lease_clash(ctx, task_id, manifest.get("owns") or [])
        if current_status == "planned":
            # Only here, from `planned`. The base is where this branch left the mainline, so
            # anything committed on the branch before the claim is inside `base..worktree`:
            # in the digest, in `aegis diff`, in front of every lens. Reviewed, not refused —
            # a rule that refused it instead failed in both directions at once (ADR-5). With
            # no mainline ref the base is HEAD; on an unborn branch `head_sha` is None and the
            # base is left alone rather than set to the literal string `HEAD`.
            base = require_base(ctx) or head_sha(ctx)
            if base and manifest.get("base_sha") != base:
                manifest["base_sha"] = base
                write_json(os.path.join(run_dir(ctx, task_id), "manifest.json"), manifest)
        policy = checks.policy(ctx)
        limit = policy.get("parallel_builders", 1)
        in_flight = [t for t in checks.active_tasks(ctx)
                     if t["id"] != task_id and t.get("status") == "building"]
        if len(in_flight) >= limit:
            # Checked at creation only, the limit was bypassed by creating several tasks
            # first and starting them afterwards.
            raise AegisError(
                f"profile {policy.get('profile')} allows {limit} task(s) in flight and "
                f"{len(in_flight)} already are ({', '.join(t['id'] for t in in_flight)})."
            )

    return _set_status(ctx, task_id, status)


def _set_status(ctx: Ctx, task_id: str, status: str) -> dict:
    path = os.path.join(run_dir(ctx, task_id), "manifest.json")
    manifest = read_json(path)
    manifest["status"] = status
    manifest["updated"] = now()
    write_json(path, manifest)
    append_jsonl(os.path.join(run_dir(ctx, task_id), "metrics.jsonl"),
                 {"at": now(), "event": "status", "task": task_id, "value": status})
    return manifest


# ------------------------------------------------------------------ context packet


SECTION = re.compile(r"^##+\s*(.+?)\s*$", re.MULTILINE)


def _extract_requirements(spec_text: str, ids: list[str]) -> list[str]:
    out = []
    for req_id in ids:
        match = re.search(rf"^\s*{re.escape(req_id)}\.\s*(.+?)(?=^\s*R-\d+\.|^##|\Z)",
                          spec_text, re.MULTILINE | re.DOTALL)
        if match:
            body = " ".join(line.strip() for line in match.group(1).splitlines() if line.strip())
            out.append(f"{req_id}. {body}")
    return out


def _section(text: str, *names: str) -> str | None:
    for name in names:
        match = re.search(rf"^##+\s*{re.escape(name)}\s*$(.*?)(?=^##|\Z)",
                          text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
        if match and match.group(1).strip():
            return match.group(1).strip()
    return None


def build_packet(ctx: Ctx, task_id: str) -> tuple[str, dict]:
    """Assemble the task packet deterministically.

    The orchestrator does not improvise this. A script emits it, so the packet is
    reproducible, measurable, and identical across restarts — and its token cost is a
    number the gate can enforce rather than a hope.
    """
    manifest = checks.load_task(ctx, task_id)
    feature = manifest.get("feature")
    spec_dir = ctx.path("specs", feature) if feature else None
    policy = checks.policy(ctx)
    caps = checks.capabilities(ctx)

    parts: list[str] = []
    parts.append(f"# Task packet {task_id}\n")
    parts.append(f"**Objective.** {manifest.get('objective', '(none recorded)')}\n")

    if spec_dir and os.path.exists(os.path.join(spec_dir, "spec.md")):
        spec_text = read_text(os.path.join(spec_dir, "spec.md"))
        reqs = _extract_requirements(spec_text, manifest.get("requirements", []))
        if reqs:
            parts.append("**Requirements this task closes.**")
            parts.extend(f"- {r}" for r in reqs)
            parts.append("")

    if manifest.get("acceptance"):
        parts.append("**Acceptance criteria.**")
        parts.extend(f"- {a}" for a in manifest["acceptance"])
        parts.append("")

    # Edge cases, contracts and the end-to-end check live in the spec. They used to be read
    # from a `feature.md` that no protocol ever wrote — the packet consumed an artifact with
    # no producer, so builders never saw the test list the spec author had written.
    if spec_dir and os.path.exists(os.path.join(spec_dir, "spec.md")):
        for heading in ("Edge cases", "Contracts", "End-to-end check"):
            body = _section(spec_text, heading)
            if body:
                parts.append(f"**{heading}.**\n{body}\n")

    parts.append("**Write lease — exclusive, and the only paths you may modify.**")
    parts.extend(f"- {g}" for g in manifest.get("owns", []))
    if manifest.get("reads"):
        parts.append("\n**Read-only context.**")
        parts.extend(f"- {g}" for g in manifest["reads"])
    parts.append("")

    verification = _verification_commands(ctx, manifest, caps)
    parts.append("**Verification — run these yourself before reporting done.**")
    parts.extend(f"- `{c}`" for c in verification)
    parts.append("")

    protocols = _protocol_paths(ctx, manifest)
    if protocols:
        parts.append("**Protocols that apply. Read them; they are not preloaded.**")
        parts.extend(f"- {p}" for p in protocols)
        parts.append("")

    # Effective kinds, as `aegis lens plan` computes them: the packet told the builder
    # "tier C, mechanical" while the plan derived tier A from the same diff, because the
    # packet read only the declared kinds. A brief and its review must agree on the stakes.
    base = manifest.get("base_sha")
    detected = detect_change_kinds(ctx, changed_files(ctx, base), base)
    tier = _risk_tier(policy, sorted(set(manifest.get("change_kinds") or []) | set(detected)))

    # Answers that never reach an agent are answers that changed nothing. These two are
    # judgement inputs — no script can check "did you weigh security over speed" — so the
    # least dishonest thing is to make sure they arrive where the judgement happens.
    priorities = policy.get("nfr_priorities") or []
    if priorities:
        parts.append(f"**Decide close calls by these priorities, in order:** {', '.join(priorities)}.\n")
    limits = policy.get("autonomy_limits") or []
    granted = ", ".join(limits) if limits else "nothing"
    parts.append(
        f"**You may decide alone:** {granted}. Anything else — a dependency, a schema change, "
        f"a public contract, a security trade-off — stops and returns the question.\n"
    )

    parts.append(
        "**Boundaries.**\n"
        "- Do not write outside the lease. A needed change elsewhere stops the task and returns a lease-expansion request.\n"
        "- Do not edit `.aegis/generated/`, registries, or any skill; `.aegis/constitution.md` only when this task's objective calls for it, and say so in the handoff.\n"
        "- Do not weaken, skip or delete a test to reach green.\n"
        "- Do not improve code outside this task's scope.\n"
        f"- Risk tier {tier['id']} as declared: {tier['description']}. The gate judges the "
        f"effective tier from the diff, so a route or an authorisation change raises it.\n"
    )
    parts.append(
        f"**Handoff.** Before returning, write `.aegis/runs/{task_id}/handoff.json`:\n"
        f'`{{"task": "{task_id}", "summary": "...", "changed_files": [...], '
        f'"verification": [{{"command": "...", "result": "pass|fail|skipped"}}], '
        f'"deviations": [...], "registry_drafts": [...], "lease_expansion_request": [...], '
        f'"agent": "<your agent type or model id>", "open_questions": [...], '
        f'"new_dependencies": [...], "invalidated_assumptions": [...], "next_safe_action": "..."}}`\n'
        f"The last four are what the next session cannot recompute: a question nobody answered, "
        f"a dependency this work uncovered, an assumption it disproved, and the one action that "
        f"is safe to take next. Leave them out when there are none.\n"
        f"Then return at most 300 words: what changed, how it was verified, deviations and why. "
        f"Never restate the code — the diff is already readable."
    )

    # The packet is a pure function of the manifest and the spec. It used to focus the task,
    # advance its status and append a metrics row as side effects — and the shipped workflow
    # regenerates it on every review round, so `aegis metrics` counted rounds as packets.
    # Starting a task is `aegis task claim`.
    text = "\n".join(parts)
    tokens = estimate_tokens(text)
    meta = {
        "task": task_id,
        "tokens": tokens,
        "budget": (policy.get("budgets") or {}).get("packet", 6000),
        "risk_tier": tier["id"],
        "verification": verification,
        "protocols": protocols,
    }
    return text, meta


def lens_prompt(ctx: Ctx, task_id: str, lens: str, with_contract: bool = False,
                with_diff: bool = True, closing: bool = False) -> str:
    """Everything one lens needs, for any engine: its focus, its own prior findings with the
    two-phase reconciliation, the packet and the diff — and the review contract itself when
    the engine does not preload it. Deterministic, so every runner briefs a lens the same way.
    """
    from .config import load_lenses
    lenses = load_lenses(ctx)
    if lens not in lenses:
        raise AegisError(f"no lens {lens!r}; known: {', '.join(sorted(lenses)) or 'none'}. "
                         "A lens is a file in lenses/ or .aegis/lenses/.")
    parts = [f"# Review task {task_id} as the {lens} lens" + (" — mode `closing`" if closing else " — mode `task`")]
    if with_contract:
        contract = ctx.path("protocols", "review-lens.md")
        if not os.path.exists(contract):
            contract = next((p for p in checks.skill_files(ctx) if p.endswith(os.path.join("review-lens", "SKILL.md"))), "")
        if contract:
            parts.append(checks.parse_frontmatter(read_text(contract))[1].strip())
    parts.append("## Your focus\n\n" + lenses[lens]["body"])
    record_path = os.path.join(run_dir(ctx, task_id), "reviews", f"{lens}.json")
    prior = read_json(record_path, default={}).get("findings", []) if os.path.exists(record_path) else []
    if prior:
        listed = "\n".join(f"- {f['id']} [{f.get('disposition', 'open')}] {f['message'][:160]}" for f in prior)
        parts.append(
            "## Two phases, in this order\n\n"
            "PHASE 1 — review the diff fresh, as if for the first time, and write `findings`.\n"
            "PHASE 2 — only then reconcile this lens's previous findings in a top-level `reconciled` "
            "list, one entry per open id: `{\"id\": \"<id>\", \"followup\": \"resolved\" or \"unresolved\", "
            "\"evidence\": \"<one line>\"}`. Never copy a prior id into `findings`. Reading this list "
            "first would anchor the fresh scan.\n\n" + listed)
    if with_diff:
        packet, _meta = build_packet(ctx, task_id)
        parts.append("## Task packet\n\n" + packet)
        parts.append("## Diff under review\n\n" + task_diff(ctx, task_id))
    parts.append("## Output\n\nReturn only the JSON object the review contract specifies — about "
                 "1,000 tokens at most. Do not include `lens`, `reviewer` or `diff_digest`: the recorder "
                 "attaches them.")
    return "\n\n".join(parts)


def task_diff(ctx: Ctx, task_id: str) -> str:
    """The diff a reviewer reads, over exactly the files the digest covers.

    The workflow and the Codex runner each rebuilt it in shell from `git ls-files --others`,
    so pre-adoption files the digest excludes were handed to every lens — three copies of
    "the change" that disagreed. One function now, built on `changed_files` and sharing
    `in_review_scope` with the digest, so the diff cannot go blind to a file the digest covers.
    """
    manifest = checks.load_task(ctx, task_id)
    base = manifest.get("base_sha")
    files = changed_files(ctx, base)
    untracked = untracked_files(ctx)
    parts: list[str] = []
    for rel in files:
        if not in_review_scope(rel, task_id):
            continue
        if rel in untracked:
            full = os.path.join(ctx.root, rel)
            if os.path.islink(full):
                # The digest hashes the link's target; the diff shows the same, rather than
                # inlining the target's bytes as if the path were a regular file.
                parts.append(f"--- /dev/null\n+++ b/{rel}\n@@ -0,0 +1 @@\n+symlink -> {os.readlink(full)}\n")
                continue
            if not os.path.isfile(full):
                continue
            if checks._is_binary(full):
                parts.append(f"--- /dev/null\n+++ b/{rel}\nBinary file\n")
                continue
            body = read_text(full, default="")
            lines = body.splitlines()
            parts.append(f"--- /dev/null\n+++ b/{rel}\n@@ -0,0 +1,{len(lines)} @@\n"
                         + "".join(f"+{line}\n" for line in lines))
        else:
            parts.append(git(ctx, "diff", base or EMPTY_TREE, "--", rel))
    return "\n".join(p for p in parts if p)


def _refuse_lease_clash(ctx: Ctx, task_id: str, owns: list[str]) -> None:
    """A lease is exclusive while it is held — from claim to merge — not from the moment a
    task is planned.

    Refusing overlap at `task new` made one spec split into several tasks impossible: the
    later tasks could not be written down while the first was building, so their requirements
    read as uncovered at its merge gate and the gate failed for work that was planned. A plan
    is not a lease. Planning several overlapping tasks is allowed; claiming the second while
    the first holds it is refused, which is the moment a builder would actually collide.
    """
    for other in checks.active_tasks(ctx):
        if other["id"] == task_id or other.get("status") not in checks.HOLDING:
            continue
        clash = [(mine, theirs) for mine in owns for theirs in (other.get("owns") or [])
                 if globs_overlap(mine, theirs)]
        if clash:
            pairs = "; ".join(f"{m} ∩ {t}" for m, t in clash[:3])
            raise AegisError(
                f"write lease overlaps {other['id']} ({pairs}), which holds it. Narrow the "
                f"globs, or finish that task first — overlapping leases are how two builders "
                f"silently overwrite each other."
            )


def task_claim(ctx: Ctx, task_id: str) -> dict:
    """Start a task: move it to `building` under the parallel-builder limit, fix its base at
    the branch point, and record what its packet costs.

    One command, because the three used to be scattered: focus was a separate step nobody
    remembered, the status moved as a side effect of printing the packet, and the metric
    was appended every time the packet was regenerated. Safe to repeat.
    """
    manifest = checks.load_task(ctx, task_id)
    if manifest.get("status") == "planned":
        task_status(ctx, task_id, "building")  # refused on a lease clash or the builder limit
    status = checks.load_task(ctx, task_id).get("status", "building")
    _text, meta = build_packet(ctx, task_id)
    metrics_path = os.path.join(run_dir(ctx, task_id), "metrics.jsonl")
    if not any(row.get("event") == "packet" for row in read_jsonl(metrics_path)):
        # Once per task, however often the claim is repeated: the metric measures what a
        # task costs to brief, and a resumed session is not a second task.
        append_jsonl(metrics_path,
                     {"at": now(), "event": "packet", "task": task_id, "tokens": meta["tokens"],
                      "risk_tier": meta["risk_tier"]})
    return {"task": task_id, "status": status, "packet_tokens": meta["tokens"],
            "budget": meta["budget"], "over_budget": meta["tokens"] > meta["budget"]}


def _verification_commands(ctx: Ctx, manifest: dict, caps: dict) -> list[str]:
    packages = caps.get("packages") or {}
    owns = manifest.get("owns") or []
    selected = []
    for name, spec in sorted(packages.items()):
        if any(matches_any(_glob_head(g), spec.get("paths") or []) for g in owns):
            selected.append((name, spec))
    if not selected and caps.get("default_package") in packages:
        selected = [(caps["default_package"], packages[caps["default_package"]])]
    commands = []
    for _name, spec in selected:
        for key in ("lint", "typecheck", "test"):
            if spec.get(key):
                commands.append(spec[key])
    return commands or ["(no verification commands configured — set capabilities.packages)"]


def _glob_head(glob: str) -> str:
    return glob.split("*")[0].rstrip("/") or glob


def _protocol_paths(ctx: Ctx, manifest: dict) -> list[str]:
    """Point at protocols instead of injecting them.

    Preloaded skills cost their full body at startup whether or not the task needs them.
    A path costs a few tokens and the agent reads it only when it actually applies.
    """
    index = ctx.gen("index", "skills.json")
    if not os.path.exists(index):
        return []
    kinds = set(manifest.get("change_kinds") or [])
    out = []
    for entry in read_json(index):
        applies = set(entry.get("change_kinds") or [])
        if applies and applies & kinds:
            out.append(entry["path"])
    return sorted(out)


def _risk_tier(policy: dict, kinds: list[str]) -> dict:
    tiers = policy.get("risk_tiers") or {}
    for tier_id in ("A", "B", "C"):
        spec = tiers.get(tier_id)
        if spec and set(spec.get("match_change_kinds") or []) & set(kinds):
            return {"id": tier_id, **spec}
    return {"id": "C", "description": "mechanical", "independent_reviewer": False}


# ------------------------------------------------------------------------- lenses


ROUTE_HINTS = [r"@(?:Get|Post|Put|Patch|Delete)Mapping", r"app\.(?:get|post|put|patch|delete)\(",
               r"router\.(?:get|post|put|patch|delete)\(", r"@(?:app|router)\.(?:get|post|put|delete)",
               r"http\.HandleFunc\("]
AUTH_HINTS = [r"(?i)\bauthoriz", r"(?i)\bauthenticat", r"(?i)\bpermission", r"(?i)\brole[_-]?check",
              r"(?i)\bjwt\b", r"(?i)\bsession\b"]
DEP_FILES = ["package.json", "requirements.txt", "pyproject.toml", "go.mod", "Cargo.toml",
             "Gemfile", "pom.xml", "build.gradle"]


def diff_text(ctx: Ctx, base: str | None) -> str:
    """Added and removed lines for the whole candidate change."""
    from .core import git, git_available
    if not git_available(ctx):
        return ""
    parts = []
    if base:
        parts.append(git(ctx, "diff", "--unified=0", f"{base}...HEAD"))
    parts.append(git(ctx, "diff", "--unified=0"))
    parts.append(git(ctx, "diff", "--unified=0", "--cached"))
    return "\n".join(parts)


PROTOCOL_DIRS = ("skills/", ".agents/", "agents/", "hooks/")


def _file_kinds(ctx: Ctx, rel: str, caps: dict, base: str | None = None) -> set[str]:
    """The change kinds one file carries, from its path, its text, and — given a base — the
    lines removed from it since that base.

    One function for the plan and for staleness: which lenses a file selects is the same
    question as which lens records a change to it invalidates. The removed lines matter to
    both: an authorisation call deleted after the security review is invisible in the text
    that survived, and reading only that text left the record fresh.
    """
    kinds: set[str] = set()
    if rel.startswith(".aegis/"):
        # Contract state, never hint-scanned: a task objective containing "session" is not
        # an authorisation change. Its staleness is total (`lens_staleness`), not by kind.
        kinds.add("docs" if rel.endswith(".md") else "code")
        return kinds
    migration_globs = caps.get("migration_paths") or ["**/migrations/**", "**/migrate/**", "db/**"]
    test_globs = caps.get("test_paths") or ["**/test/**", "**/tests/**", "**/*_test.*", "**/*.test.*", "**/*.spec.*"]
    name = os.path.basename(rel)
    if name in DEP_FILES or name.endswith(".lock"):
        kinds.add("dependency")
    if matches_any(rel, migration_globs):
        kinds.update({"data-migration", "contract"})
    if matches_any(rel, test_globs):
        kinds.add("test")
        return kinds
    # A protocol, a role or a hook is behaviour whatever its suffix: a `.md` under `skills/`
    # changes what every agent does, and reading it as documentation lost it its review. Its
    # prose is not scanned for hints, though: "session" in a protocol's sentences raised every
    # adopter's first task to tier A through the framework's own materialised copies.
    if rel.startswith(PROTOCOL_DIRS) and rel.endswith(".md"):
        kinds.add("code")
        return kinds
    if rel.startswith("docs/") or rel.endswith(".md"):
        kinds.add("docs")
        return kinds
    if base:
        removed = "\n".join(line for line in git(ctx, "diff", "--unified=0", base, "--", rel).splitlines()
                            if line.startswith("-") and not line.startswith("---"))
        if any(re.search(p, removed) for p in AUTH_HINTS):
            kinds.update({"auth", "code"})
        if any(re.search(p, removed) for p in ROUTE_HINTS):
            kinds.update({"route", "code"})
    full = os.path.join(ctx.root, rel)
    if not os.path.isfile(full):
        # The file is gone. Deleting a middleware or an authorisation helper is exactly
        # the change a security lens exists for, and reading the file cannot reveal it.
        kinds.add("code")
        low = rel.lower()
        if any(word in low for word in ("auth", "permission", "role", "session", "token", "guard")):
            kinds.add("auth")
        if any(word in low for word in ("route", "handler", "controller", "endpoint", "api")):
            kinds.add("route")
        return kinds
    if checks._is_binary(full):
        return kinds
    try:
        text = read_text(full)
    except (AegisError, UnicodeDecodeError):
        return kinds
    kinds.add("code")
    if any(re.search(p, text) for p in ROUTE_HINTS):
        kinds.add("route")
    if any(re.search(p, text) for p in AUTH_HINTS):
        kinds.add("auth")
    return kinds


def review_snapshot(ctx: Ctx, base: str | None, task_id: str) -> dict[str, str]:
    """What a lens read, file by file: the review-scope files and their content keys.

    Stored with the record so that a later check can say *which* files moved after the
    review, and from their kinds whether this lens cares. The digest alone says only that
    something moved, which re-ran every lens for a docstring."""
    out = {}
    for rel in changed_files(ctx, base):
        if not in_review_scope(rel, task_id):
            continue
        if rel == f".aegis/runs/{task_id}/manifest.json":
            # The contract half only, as `diff_digest` keys it: a status the gate writes is
            # not a move, and keying the whole file re-ran every lens after every gate.
            try:
                data = json.loads(read_text(os.path.join(ctx.root, rel)))
                out[rel] = "contract:" + hashlib.sha256(canonical({k: data.get(k) for k in
                    ("requirements", "acceptance", "owns", "feature", "objective")}).encode("utf-8")).hexdigest()
                continue
            except Exception:
                pass
        out[rel] = content_key(os.path.join(ctx.root, rel), file_mode_tracked(ctx)) or ABSENT
    return out


def lens_staleness(ctx: Ctx, task_id: str, lens: str, record: dict, plan: dict) -> str | None:
    """Why this lens must run again, or None while its record still describes the change.

    A lens is stale only when a file whose kinds trigger it moved since the record (R-9).
    The always-on lens is stale on any move. A record with no snapshot cannot say what it
    read, so it is stale the moment the digest differs — no grandfathering.
    """
    if record.get("diff_digest") == plan["diff_digest"]:
        return None
    snapshot = record.get("files")
    if not isinstance(snapshot, dict):
        return "the code moved after that review, and the record cannot say what it read"
    manifest = checks.load_task(ctx, task_id)
    current = review_snapshot(ctx, manifest.get("base_sha"), task_id)
    moved = sorted(rel for rel in set(snapshot) | set(current) if snapshot.get(rel) != current.get(rel))
    if not moved:
        # A mode change: the digest hashes it, the snapshot does not. Conservative — every lens.
        return "the digest moved after that review (a mode change; no content did)"
    contract = [rel for rel in moved if rel.startswith(".aegis/")]
    if contract:
        # The review is the control on a waiver, an answer and the spec (ARCHITECTURE §6): a
        # change there re-takes every review, whatever kinds the files carry.
        return f"the contract moved after that review: {', '.join(contract[:3])}"
    matrix = checks.policy(ctx).get("lens_matrix") or {}
    if lens in (matrix.get("always") or ["correctness"]):
        return f"{len(moved)} file(s) moved after that review: {', '.join(moved[:3])}"
    triggers = {kind for kind, lenses in matrix.items() if kind != "always" and lens in (lenses or [])}
    caps = checks.capabilities(ctx)
    base = manifest.get("base_sha")
    then = record.get("kinds") or {}
    hits = sorted({kind for rel in moved
                   for kind in set(then.get(rel) or []) | _file_kinds(ctx, rel, caps, base) if kind in triggers})
    if hits:
        return f"a file whose change kind ({', '.join(hits)}) selects lens-{lens} moved after that review"
    return None


def detect_change_kinds(ctx: Ctx, scope: list[str], base: str | None = None) -> list[str]:
    """Conservative detectors over the diff, unioned with the task's declared kinds.

    Declared kinds alone are a self-report; detectors alone miss intent. Their union is what
    keeps a security lens from being skipped because authorisation moved through middleware
    rather than a visibly new route.
    """
    # The change, as the review-scope filter defines it. `.aegis/runs/**` is bookkeeping, and
    # a handoff whose `agent` field said "session" raised a documentation change to tier A.
    scope = [rel for rel in scope if in_review_scope(rel)]
    kinds: set[str] = set()
    caps = checks.capabilities(ctx)
    test_globs = caps.get("test_paths") or ["**/test/**", "**/tests/**", "**/*_test.*", "**/*.test.*", "**/*.spec.*"]
    for rel in scope:
        kinds |= _file_kinds(ctx, rel, caps, base)

    # Removed lines carry the strongest signal there is: a control that used to be here.
    # Reading only what survived the change made deleting an authorisation call invisible
    # to the lens that exists to notice exactly that.
    removed = "\n".join(line for line in diff_text(ctx, base).splitlines()
                        if line.startswith("-") and not line.startswith("---"))
    if removed:
        if any(re.search(p, removed) for p in AUTH_HINTS):
            kinds.update({"auth", "code"})
        if any(re.search(p, removed) for p in ROUTE_HINTS):
            kinds.update({"route", "code"})
        if re.search(r"(?i)\b(assert|expect|it\(|test\(|def test_)", removed):
            kinds.add("test")

    # Cross-module means several *source* modules, not merely several top-level directories.
    # Counting `src` and `test` as two modules made every ordinary task cross-module and
    # dragged the design lens into work it had nothing to say about.
    framework = (".aegis", ".claude", ".agents", "docs", ".github")
    source_dirs = {
        rel.split("/")[0] for rel in scope
        if "/" in rel
        and not matches_any(rel, test_globs)
        and rel.split("/")[0] not in framework
    }
    if len(source_dirs) == 1:
        # Within one source root, modules are its immediate children.
        root = next(iter(source_dirs))
        source_dirs = {rel.split("/")[1] for rel in scope
                       if rel.startswith(root + "/") and rel.count("/") > 1
                       and not matches_any(rel, test_globs)}
    if len(source_dirs) > 1:
        kinds.add("cross-module")
    return sorted(kinds)


def lens_plan(ctx: Ctx, task_id: str, closing_feature: bool = False) -> dict:
    manifest = checks.load_task(ctx, task_id)
    policy = checks.policy(ctx)
    matrix = policy.get("lens_matrix") or {}
    scope = changed_files(ctx, manifest.get("base_sha"))
    detected = detect_change_kinds(ctx, scope, manifest.get("base_sha"))
    kinds = sorted(set(manifest.get("change_kinds") or []) | set(detected))
    if closing_feature:
        kinds.append("feature-close")

    selected: list[str] = list(matrix.get("always") or ["correctness"])
    reasons: dict[str, list[str]] = {lens: ["always"] for lens in selected}
    for kind in kinds:
        for lens in matrix.get(kind) or []:
            if lens not in selected:
                selected.append(lens)
            reasons.setdefault(lens, []).append(kind)

    # Paths select lenses as well as change kinds: an accessibility lens follows the files a
    # web project's interface lives in, whatever the task declared.
    for lens, globs in sorted((policy.get("lens_paths") or {}).items()):
        hits = [rel for rel in scope if matches_any(rel, globs)]
        if hits:
            if lens not in selected:
                selected.append(lens)
            reasons.setdefault(lens, []).append(f"paths: {hits[0]}" + (f" +{len(hits) - 1}" if len(hits) > 1 else ""))

    tier = _risk_tier(policy, kinds)
    profiles = policy.get("lens_profiles") or {}
    plan = {
        "task": task_id,
        # The reviewer quotes this back in its report; that is what proves what it read.
        "diff_digest": diff_digest(ctx, manifest.get("base_sha"), task_id),
        "declared_kinds": manifest.get("change_kinds") or [],
        "detected_kinds": detected,
        "effective_kinds": kinds,
        "risk_tier": tier["id"],
        # One round budget, the policy's. The tier decides the independent reviewer, nothing
        # about counts: a second round "for the count" is ceremony.
        "refinement_rounds": policy.get("refinement_rounds", 3),
        "independent_reviewer": tier.get("independent_reviewer", False),
        "lenses": selected,
        # Which tool profile each lens needs; the focus comes from `aegis lens prompt`.
        "profiles": {lens: profiles.get(lens, "lens-auditor") for lens in selected},
        "external_reviewer": checks.capabilities(ctx).get("external_reviewer") or None,
        "why": {lens: sorted(set(why)) for lens, why in reasons.items()},
        "scope_files": len(scope),
    }
    # Which of them must actually run now: the ones with no record, and the ones whose
    # record a moved file of a triggering kind invalidated. A fresh lens is not dispatched.
    reviews = os.path.join(run_dir(ctx, task_id), "reviews")
    # The same name rule as the write path: a hand-placed file in reviews/ is not a lens.
    recorded = sorted(n[:-5] for n in os.listdir(reviews)
                      if n.endswith(".json") and LENS_NAME.match(n[:-5])) if os.path.isdir(reviews) else []
    stale: dict[str, str] = {}
    for lens in selected + [lens for lens in recorded if lens not in selected]:
        path = os.path.join(reviews, f"{lens}.json")
        if not os.path.exists(path):
            stale[lens] = "no record yet"
            continue
        why_stale = lens_staleness(ctx, task_id, lens, read_json(path, default={}), plan)
        if why_stale:
            stale[lens] = why_stale
            if lens not in selected:
                # A recorded lens the diff no longer selects — the control it read was deleted
                # and committed — is still owed a re-run: the gate fails on it, so the plan says so.
                selected.append(lens)
                reasons.setdefault(lens, []).append("stale-record")
    plan["lenses"] = selected
    plan["why"] = {lens: sorted(set(why)) for lens, why in reasons.items()}
    plan["stale"] = stale
    plan["run"] = [lens for lens in selected if lens in stale]
    return plan


# The lens name becomes a filename. Untrusted review output is piped into `aegis lens
# record` by design — including output from a different vendor's model — so the name is
# validated rather than trusted. Without this, `"lens": "../../../../etc/x"` is an
# arbitrary file write that reports success.
LENS_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")

LENS_REPORT_SCHEMA = {
    "type": "object",
    "required": ["lens", "verdict", "findings"],
    "properties": {
        "lens": {"type": "string", "pattern": r"^[a-z][a-z0-9-]{0,31}$"},
        "diff_digest": {"type": "string", "minLength": 8,
                        "description": "the digest the reviewer was given; proves what it read"},
        "reviewer": {"type": "string", "minLength": 2,
                     "description": "who produced this report — agent type or model id"},
        "verdict": {"enum": ["pass", "fail", "pass-with-notes"]},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["severity", "message"],
                "properties": {
                    "severity": {"type": "integer", "minimum": 0, "maximum": 5},
                    "message": {"type": "string", "minLength": 8},
                    "path": {"type": "string"},
                    "line": {"type": "integer"},
                    "requirement": {"type": "string"},
                    "minimal_fix": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        # A re-review reconciles the prior findings it was handed, by id. Hashing prose
        # assumed two runs of a model word the same concern identically, and they do not;
        # the ids travel in the prompt and come back here — as a separate top-level field,
        # so the fresh scan in `findings` stays fresh and the findings schema stays closed.
        "reconciled": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "followup"],
                "properties": {
                    "id": {"type": "string", "pattern": r"^F-[0-9a-f]{8}$"},
                    "followup": {"enum": ["resolved", "unresolved"]},
                    "evidence": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}


def finding_id(lens: str, finding: dict) -> str:
    """Stable across reruns: same lens, same place, same claim -> same id.

    Without this, a rerun invents new findings, dispositions cannot be carried forward,
    and acceptance-rate metrics measure noise rather than lens quality.
    """
    # The full normalised claim, not a prefix: two different findings sharing an opening
    # sentence inherited each other's disposition, so a severity 5 could arrive already
    # dismissed.
    normalised = re.sub(r"\s+", " ", finding.get("message", "")).strip().lower()
    key = f"{lens}|{finding.get('path', '')}|{normalised}"
    return f"F-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:8]}"


def lens_record(ctx: Ctx, task_id: str, payload: dict, lens: str | None = None) -> dict:
    if lens is not None:
        # Which lens a report belongs to is a transport fact, like the digest. Taken from the
        # payload, `"lens": "security"` piped from the correctness run became the security
        # review and could reconcile — close — security's findings.
        if payload.get("lens") not in (None, lens):
            raise AegisError(f"the report says it is lens {payload.get('lens')!r} but was recorded "
                             f"as lens-{lens}; a report cannot choose which review it counts as")
        payload = {**payload, "lens": lens}
    errors = validate(payload, LENS_REPORT_SCHEMA)
    if errors:
        raise AegisError("lens report rejected:\n  " + "\n  ".join(errors))
    lens = payload["lens"]
    if not payload.get("diff_digest"):
        raise AegisError(
            "no diff_digest on the report and none attached by the caller. "
            "Pass --digest to `aegis lens record` (preferred), or include the field."
        )
    if not LENS_NAME.match(lens):
        raise AegisError(
            f"invalid lens name {lens!r}: lowercase letters, digits and dashes only. "
            "The name becomes a filename, and review output is not trusted input."
        )
    directory = os.path.join(run_dir(ctx, task_id), "reviews")
    path = os.path.join(directory, f"{lens}.json")
    previous = read_json(path, default={}) if os.path.exists(path) else {}
    prior_findings = {f["id"]: f for f in previous.get("findings", [])}

    manifest = checks.load_task(ctx, task_id)
    current = diff_digest(ctx, manifest.get("base_sha"), task_id)
    if payload["diff_digest"] != current:
        # The reviewer quotes the digest it was handed. Stamping whatever the digest happens
        # to be at record time let an old report be replayed against changed code and pass as
        # if that code had been reviewed.
        raise AegisError(
            f"this report was produced against {payload['diff_digest']} but the change is now "
            f"{current}. The code moved after the review; re-run lens-{lens} against the "
            "current diff. `aegis lens plan` prints the digest to quote."
        )
    round_no = previous.get("round", 0) + 1
    reopened, findings = [], []
    for raw in payload["findings"]:
        fid = finding_id(lens, raw)
        prior = prior_findings.get(fid, {})
        reopened_in = list(prior.get("reopened_in") or [])
        kept: dict = {}
        if prior.get("disposition") == "fixed":
            # Marked fixed, raised again: the two-strike rule. It is remembered on the
            # finding, not only on this round's record, so a later `resolved` cannot make
            # it pass on the third patch — only a person's disposition closes it.
            reopened.append(fid)
            reopened_in.append(round_no)
            kept = {"disposition_by": "lens",
                    "disposition_reason": f"raised again by lens-{lens} round {round_no}",
                    "disposition_at": now()}
        elif prior.get("disposition") not in (None, "open"):
            # A kept disposition keeps who made it and why. Dropping them made a person's
            # false-positive fail "without a reason" the next time the lens repeated itself.
            kept = {k: prior[k] for k in ("disposition_by", "disposition_reason", "disposition_at")
                    if k in prior}
        findings.append({
            "id": fid,
            "severity": raw["severity"],
            "message": raw["message"],
            "path": raw.get("path"),
            "line": raw.get("line"),
            "requirement": raw.get("requirement"),
            "minimal_fix": raw.get("minimal_fix"),
            "disposition": prior.get("disposition", "open") if prior.get("disposition") != "fixed" else "open",
            # The digest at which the finding was *last confirmed present*, not first raised.
            # Kept at the first digest, an unrelated edit in between let a later `resolved`
            # on an unchanged tree count as "the code changed since it was raised".
            "raised_digest": payload["diff_digest"],
            "first_seen_round": prior.get("first_seen_round", round_no),
            "rounds": sorted(set(prior.get("rounds", []) + [round_no])),
            **({"reopened_in": reopened_in} if reopened_in else {}),
            **kept,
        })
    # Explicit reconciliation, when the caller asked for it: every prior finding the lens
    # was handed comes back by id as resolved or unresolved. Ids the lens never raised, and
    # open findings it left out, are rejected rather than guessed at — a partial
    # reconciliation is indistinguishable from one nobody did.
    reconciled = payload.get("reconciled")
    recon: dict[str, dict] = {}
    open_prior_ids = sorted(fid for fid, f in prior_findings.items()
                            if f.get("disposition") in (None, "open"))
    if reconciled is None and open_prior_ids and not all(
            any(f["id"] == fid for f in findings) for fid in open_prior_ids):
        # Absence used to mean "fixed" once the code had changed. That made the producer of
        # an untrusted report choose which control applied: drop the `reconciled` key and
        # every open finding closed on the next edit, with no per-id accounting. A re-review
        # with open prior findings reconciles them by id, or it is not a re-review.
        raise AegisError(
            f"lens-{lens} has open findings on {task_id} ({', '.join(open_prior_ids)}) and this "
            "report does not reconcile them. A re-review returns `reconciled`: one entry per "
            "prior id, `resolved` or `unresolved`, with one line of evidence."
        )
    if reconciled is not None:
        unknown = sorted({r["id"] for r in reconciled} - set(prior_findings))
        if unknown:
            raise AegisError(
                f"reconciled names findings lens-{lens} never raised on {task_id}: "
                f"{', '.join(unknown)}. Reconcile only the ids you were given; a new concern "
                "belongs in `findings`."
            )
        open_prior = {fid for fid, f in prior_findings.items()
                      if f.get("disposition") in (None, "open")}
        re_raised = {f["id"] for f in findings}
        missing = sorted(open_prior - {r["id"] for r in reconciled} - re_raised)
        if missing:
            raise AegisError(
                f"reconciliation is incomplete: open findings {', '.join(missing)} were neither "
                "reconciled nor raised again. Every prior open finding needs `resolved` or "
                "`unresolved` with one line of evidence."
            )
        recon = {r["id"]: r for r in reconciled}

    # A finding absent from this round keeps whatever disposition it already had — an open
    # one stays open. Treating absence as resolution let a rerun with an empty findings list
    # silently clear an unfixed severity 5, which is the most dangerous possible default:
    # the cheapest way to a green gate would have been to run the lens again.
    for fid, prior in prior_findings.items():
        if any(f["id"] == fid for f in findings):
            # Raised again by content: the fresh scan outranks the reconciliation, because
            # the finding is demonstrably still there.
            continue
        entry = recon.get(fid)
        if entry is not None:
            changed = prior.get("raised_digest") != payload["diff_digest"]
            if entry["followup"] == "resolved" and prior.get("disposition") in (None, "open"):
                if changed:
                    prior["disposition"] = "fixed"
                    prior["disposition_by"] = f"lens-{lens}"
                    prior["disposition_reason"] = (
                        f"lens-{lens} round {round_no}: "
                        f"{entry.get('evidence') or 'resolved on re-review'}")
                    prior["disposition_at"] = now()
                else:
                    # Nothing changed since it was raised. A lens cannot resolve a finding the
                    # code did not answer — the rule `aegis lens disposition` already enforces.
                    prior["reconciliation_rejected"] = {
                        "round": round_no, "followup": "resolved",
                        "why": "no code change since the finding was raised",
                    }
            elif entry["followup"] == "unresolved":
                if prior.get("disposition") == "fixed":
                    # Marked fixed, still there by the reviewer's own account: the two-strike
                    # rule by id, not by wording.
                    reopened.append(fid)
                    prior["reopened_in"] = sorted(set(prior.get("reopened_in") or []) | {round_no})
                    prior["disposition"] = "open"
                    # Whoever closed it before, the reopen is the lens's: a stale person's
                    # name here made the second strike invisible to the gate.
                    prior["disposition_by"] = f"lens-{lens}"
                    prior["disposition_reason"] = f"reopened by lens-{lens} round {round_no}"
                    prior["disposition_at"] = now()
                # Confirmed present at this digest: a later `resolved` must follow a change
                # made after *this* round, not after the round that first raised it.
                prior["raised_digest"] = payload["diff_digest"]
                prior["rounds"] = sorted(set(prior.get("rounds", []) + [round_no]))
            findings.append(prior)
            continue
        # Neither raised again nor reconciled: only reachable for a finding that is not open
        # (fixed, waived, deferred, false-positive) or when no reconciliation was required.
        # It keeps its disposition. Absence is never evidence.
        findings.append(prior)

    record = {
        "task": task_id,
        "lens": lens,
        "reviewer": payload.get("reviewer"),
        "verdict": payload["verdict"],
        "round": round_no,
        "recorded": now(),
        # What this round's report costs a reader; the budget is checked against this, not
        # against the record, which grows with every round by design.
        "report_tokens": estimate_tokens(canonical({"findings": payload["findings"],
                                                    "reconciled": payload.get("reconciled") or []})),
        # Binds this report to the code it actually read. An edit afterwards invalidates it —
        # for the lenses the moved files' kinds select (R-9); `files` is what makes that
        # question answerable.
        "diff_digest": payload["diff_digest"],
        "files": review_snapshot(ctx, manifest.get("base_sha"), task_id),
        # The kinds each file carried when the lens read it. A control deleted afterwards is
        # invisible in the text that survives, so staleness asks what the file *was* as well.
        "kinds": {rel: sorted(_file_kinds(ctx, rel, checks.capabilities(ctx), manifest.get("base_sha")))
                  for rel in review_snapshot(ctx, manifest.get("base_sha"), task_id)},
        "findings": sorted(findings, key=lambda f: (-f["severity"], f["id"])),
        "reopened": reopened,
    }
    write_json(path, record)
    append_jsonl(os.path.join(run_dir(ctx, task_id), "metrics.jsonl"), {
        "at": now(), "event": "lens", "task": task_id, "lens": lens, "round": round_no,
        "verdict": payload["verdict"], "findings": len(payload["findings"]),
        "blocking": sum(1 for f in payload["findings"] if f["severity"] >= 3),
    })
    return record


# Names that are recognisably not a person: the framework's agents, common engine and model
# families, and any `engine:model` reviewer label. A person's name rarely contains a colon.

def _closed_by_a_person(finding: dict, builder: str, lens: str = "") -> bool:
    """A second strike is closed by a person, never by the lens or the builder.

    `disposition_by` is a claim written by whoever ran the command — it is recorded and shown
    in the pull request, not authenticated. What the check can refuse is the claims it can
    recognise as not a person: the lens, the task's own builder, and the framework's agents.
    """
    return _names_a_person(finding.get("disposition_by"), builder, lens)


def _names_a_person(name: str | None, builder: str, lens: str = "") -> bool:
    return checks.is_person_name(name, builder, lens)


def _waivers_or_problem(ctx: Ctx, problems: list, label: str) -> list[dict]:
    try:
        return checks.load_waivers(ctx)
    except AegisError as err:
        problems.append((f"{label}: waivers.json is invalid ({' '.join(str(err).split())})",
                         "no waiver applies until the file validates"))
        return []


def _dismissal_problems(ctx: Ctx, finding: dict, builder: str, lens: str) -> list[tuple[str, str]]:
    """Why a dismissed blocking finding still blocks, as (message, hint); empty when it may go.

    A blocking finding leaves the gate in one of two ways: a code change a re-review confirms,
    or a person's decision. `false-positive`, `waived` and `deferred` are that decision, so
    `--by` must name neither the task's builder, nor the lens that raised it, nor anything the
    gate recognises as an agent; a waiver or deferral also needs a `finding` waiver naming the
    id, owned by such a name. Both names are recorded claims, and `waivers.json` is an ordinary
    file — what the check can refuse is a name it recognises as not an independent person.
    """
    disposition = finding.get("disposition")
    if finding.get("severity", 0) < 3 or disposition not in ("false-positive", "waived", "deferred"):
        return []
    label = f"{lens} {finding['id']} (sev {finding['severity']}) is {disposition}"
    problems = []
    by = (finding.get("disposition_by") or "").strip()
    if not _names_a_person(by, builder, lens):
        if not by:
            reason = "with nobody named"
        elif by.lower() == (builder or "").strip().lower():
            reason = "by the builder of this task, not by an independent person"
        elif by.lower() == (lens or "").strip().lower():
            reason = "by the lens that raised it"
        else:
            reason = f"by {by!r}, which the gate recognises as an agent"
        problems.append((f"{label} {reason}",
                         "a person who did not build this task dismisses a blocking finding: "
                         f"`aegis lens disposition <TASK> {finding['id']} {disposition} "
                         "--reason … --by <their name>`"))
    if disposition in ("waived", "deferred"):
        # Only a `finding` waiver naming this id counts. Citing a waiver written for another
        # check borrowed its owner and expiry for a decision nobody recorded.
        waivers = [w for w in _waivers_or_problem(ctx, problems, label)
                   if w.get("check") == "finding" and not checks.expired(w)
                   and finding["id"] in (w.get("scope") or [])]
        if not waivers:
            problems.append((f"{label} without a waiver record",
                             'add to .aegis/waivers.json {"id": …, "check": "finding", '
                             f'"scope": ["{finding["id"]}"], "reason": …, "owner": <a person>, '
                             '"expires": "YYYY-MM-DD"}'))
        elif not any(_names_a_person(w.get("owner"), builder, lens) for w in waivers):
            owners = ", ".join(repr(w.get("owner")) for w in waivers)
            problems.append((f"{label} under a waiver owned by {owners}, which is not a person",
                             "the person who decided owns the waiver"))
    return problems


def disposition(ctx: Ctx, task_id: str, fid: str, value: str, reason: str = "", by: str = "") -> dict:
    if not by.strip():
        raise AegisError("--by is required: a disposition records who stands behind it")
    allowed = ["fixed", "false-positive", "waived", "deferred"]
    if value not in allowed:
        raise AegisError(f"unknown disposition {value!r}; expected {', '.join(allowed)}")
    if value != "fixed" and not reason.strip():
        # Dismissing a finding is a judgement someone has to stand behind. `fixed` is the one
        # case the code itself evidences, and even that is re-checked by the next review.
        raise AegisError(
            f"--reason is required to record {value!r}: a dismissed finding without a stated "
            "reason is indistinguishable from one nobody looked at."
        )
    directory = os.path.join(run_dir(ctx, task_id), "reviews")
    if not os.path.isdir(directory):
        raise AegisError(f"no lens reports recorded for {task_id}")
    manifest = checks.load_task(ctx, task_id)
    current = diff_digest(ctx, manifest.get("base_sha"), task_id)
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        record = read_json(path)
        for finding in record.get("findings", []):
            if finding["id"] == fid:
                if value == "fixed" and finding.get("raised_digest") == current:
                    raise AegisError(
                        f"{fid} cannot be marked fixed: nothing has changed since it was "
                        "raised. Change the code, then re-run the lens — a disposition is "
                        "for dismissing a finding, not for satisfying one."
                    )
                finding["disposition"] = value
                finding["disposition_by"] = by.strip()
                finding["disposition_reason"] = reason
                finding["disposition_at"] = now()
                write_json(path, record)
                append_jsonl(os.path.join(run_dir(ctx, task_id), "metrics.jsonl"), {
                    "at": now(), "event": "disposition", "task": task_id,
                    "lens": record["lens"], "finding": fid, "value": value,
                })
                return finding
    raise AegisError(f"no finding {fid} under {task_id}")


def check_reviews(ctx: Ctx, task_id: str) -> Report:
    """Every blocking finding must be resolved, and oscillation must stop the loop
    rather than burn the iteration budget silently."""
    report = Report()
    policy = checks.policy(ctx)
    plan = lens_plan(ctx, task_id)
    directory = os.path.join(run_dir(ctx, task_id), "reviews")
    recorded = set()
    if os.path.isdir(directory):
        recorded = {n[:-5] for n in os.listdir(directory) if n.endswith(".json")}
    missing = [lens for lens in plan["lenses"] if lens not in recorded]
    if missing:
        report.fail("reviews", f"required lenses have not run: {', '.join(missing)}", None,
                    hint=f"`/aegis:review {task_id}` runs exactly the required set")

    max_rounds = policy.get("refinement_rounds", 3)
    manifest = checks.load_task(ctx, task_id)
    # Effective kinds, not declared ones: declaring `code` while adding an authorisation
    # route would otherwise duck the independent-review requirement the change earns.
    scope = changed_files(ctx, manifest.get("base_sha"))
    effective_kinds = sorted(set(manifest.get("change_kinds") or [])
                             | set(detect_change_kinds(ctx, scope, manifest.get("base_sha"))))
    tier = _risk_tier(policy, effective_kinds)
    handoff = read_json(os.path.join(run_dir(ctx, task_id), "handoff.json"), default={})
    builder = (handoff.get("agent") or "").strip().lower()
    for lens in sorted(recorded):
        record = read_json(os.path.join(directory, f"{lens}.json"))
        if record.get("lens") != lens or record.get("task") != task_id:
            # Required reviews are recognised by filename; copying correctness.json to
            # security.json otherwise satisfied a security requirement with a correctness
            # review.
            report.fail("reviews",
                        f"{lens}.json contains a {record.get('lens')!r} report for "
                        f"{record.get('task')!r}", None,
                        hint=f"re-run lens-{lens} and record it; a renamed file is not a review")
            continue
        why_stale = lens_staleness(ctx, task_id, lens, record, plan)
        if why_stale:
            # Per lens, by the kinds of the files that moved: a docstring after a security
            # review does not re-run security. No grandfathering for a record that cannot
            # say what it read.
            report.fail("reviews", f"{lens} did not review this version of the change: {why_stale}", None,
                        hint=f"re-run lens-{lens} against the current diff and record it again")
        came_back = [f["id"] for f in record.get("findings", [])
                     if f.get("reopened_in") and not _closed_by_a_person(f, builder, lens)]
        if came_back:
            # Read from the findings, not from this round's `reopened` list: a third patch
            # followed by `resolved` emptied the list and let the gate pass on exactly the
            # pattern the two-strike rule exists to stop. Only a human closes a reopened one.
            report.fail("reviews", f"{lens}: findings marked fixed came back: {', '.join(came_back)}",
                        hint="the mechanism is wrong, not the patch; simplify it, then a person records "
                             "`aegis lens disposition <TASK> <id> <value> --reason … --by <name>`")
        if tier.get("independent_reviewer"):
            # Whoever built it does not get to certify it. On an irreversible surface that
            # is the whole point of reviewing at all, so it is checked rather than requested.
            reviewer = (record.get("reviewer") or "").strip().lower()
            if not reviewer:
                report.fail("reviews", f"{lens}: risk tier {tier['id']} needs a named reviewer", None,
                            hint='add "reviewer": "<agent type or model id>" to the lens report')
            elif not builder:
                report.fail("reviews", "the handoff does not say who built this task", None,
                            hint='set "agent" in handoff.json; independence cannot be checked against an anonymous builder')
            elif reviewer == builder:
                report.fail("reviews", f"{lens}: reviewed by {reviewer}, which also built this task", None,
                            hint="tier A requires a different context, ideally a different model")
        if record.get("round", 0) > max_rounds:
            # A signal, not a wall. Abandoning and re-issuing at the cap made every successor
            # larger than the task it replaced, three times in four cycles; the number is
            # worth knowing and worth stepping back on, not worth losing the work over.
            report.warn("reviews", f"{lens}: {record['round']} rounds, past the {max_rounds} the "
                        f"policy expects — a finding surviving this many rounds usually means the "
                        f"mechanism is wrong; simplify before patching again",
                        hint="escalate to a human with what was tried; do not start another round")
        for finding in record.get("findings", []):
            if finding.get("severity", 0) >= 3 and finding.get("disposition") in ("open", None):
                report.fail("reviews", f"{lens} {finding['id']} (sev {finding['severity']}) is unresolved: {finding['message'][:90]}",
                            finding.get("path"), hint=finding.get("minimal_fix") or "fix it or record a disposition")
            if finding.get("disposition") in ("waived", "deferred", "false-positive") \
                    and not finding.get("disposition_reason"):
                report.fail("reviews", f"{lens} {finding['id']} was {finding['disposition']} without a reason")
            # A free-text note is not a waiver, and an agent's say-so is not a decision:
            # blocking findings set aside without a person and an expiry stay set aside forever.
            for message, hint in _dismissal_problems(ctx, finding, builder, lens):
                report.fail("reviews", message, None, hint=hint)
    return report


def check_handoff(ctx: Ctx, task_id: str) -> Report:
    report = Report()
    path = os.path.join(run_dir(ctx, task_id), "handoff.json")
    if not os.path.exists(path):
        report.fail("handoff", "no handoff.json", ctx.rel(path),
                    hint="the builder writes it before returning; it is what survives a crashed session")
        return report
    schema = {
        "type": "object",
        "required": ["task", "agent", "changed_files", "verification", "summary"],
        "properties": {
            "task": {"type": "string"},
            "agent": {"type": "string", "minLength": 2,
                      "description": "who implemented this — agent type or model id"},
            "summary": {"type": "string", "minLength": 10},
            "changed_files": {"type": "array", "items": {"type": "string"}},
            "verification": {"type": "array", "items": {
                "type": "object", "required": ["command", "result"],
                "properties": {"command": {"type": "string"}, "result": {"enum": ["pass", "fail", "skipped"]},
                               "note": {"type": "string"}},
                "additionalProperties": False}},
            "deviations": {"type": "array", "items": {"type": "string"}},
            "registry_drafts": {"type": "array", "items": {"type": "object"}},
            "lease_expansion_request": {"type": "array", "items": {"type": "string"}},
            # What the next session needs and cannot recompute: a question nobody answered, a
            # dependency the work uncovered, an assumption it disproved, and the one action that
            # is safe to take next. Everything the runner knows by itself stays out.
            "open_questions": {"type": "array", "items": {"type": "string"}},
            "new_dependencies": {"type": "array", "items": {"type": "string"}},
            "invalidated_assumptions": {"type": "array", "items": {"type": "string"}},
            "next_safe_action": {"type": "string"},
        },
        "additionalProperties": False,
    }
    data = read_json(path)
    for error in validate(data, schema):
        report.fail("handoff", error, ctx.rel(path))
    if data.get("task") and data["task"] != task_id:
        report.fail("handoff", f"this handoff claims task {data['task']}, not {task_id}",
                    ctx.rel(path), hint="a copied handoff describes work that did not happen here")
    if not data.get("verification"):
        report.fail("handoff", "no verification was recorded", ctx.rel(path),
                    hint="run the packet's commands and record their results; "
                         "an empty list is not the same as a green run")
    tokens = estimate_tokens(canonical(data))
    cap = (checks.policy(ctx).get("budgets") or {}).get("handoff", 1500)
    if tokens > cap:
        report.warn("handoff", f"≈{tokens} tokens, past the {cap} warning line", ctx.rel(path),
                    hint="report outcomes and paths, never restate the code")
    verifications = [v for v in data.get("verification", []) if isinstance(v, dict)]
    failed = [v.get("command", "?") for v in verifications if v.get("result") == "fail"]
    if verifications and all(v.get("result") == "skipped" for v in verifications):
        report.fail("handoff", "every verification was skipped, so nothing was proven", ctx.rel(path),
                    hint="run the packet's commands; a task with no executed check is not done")
    if failed:
        report.fail("handoff", f"verification reported failures: {', '.join(failed)}", ctx.rel(path))
    manifest = checks.load_task(ctx, task_id)
    # The same exemption `check trace` applies: every `.aegis/` file is framework state outside any
    # lease (a task retires a requirement in its own spec), not only its run directory.
    outside = [f for f in data.get("changed_files", [])
               if not matches_any(f, manifest.get("owns") or []) and not f.startswith(".aegis/")]
    if outside:
        report.fail("handoff", f"wrote outside the lease: {', '.join(outside[:5])}", ctx.rel(path),
                    hint="revert those paths and request a lease expansion")
    return report


# ------------------------------------------------------------------------- indexes


def build_indexes(ctx: Ctx) -> list[str]:
    """Derive every index that can be derived.

    A hand-maintained index of things that already exist is a second source of truth and
    will drift. Skills, decisions and diagrams are therefore generated from their own
    files; only facts that live nowhere else stay hand-owned.
    """
    written = []
    skills = []
    for path in checks.skill_files(ctx):
        front, body = checks.parse_frontmatter(read_text(path))
        meta = front.get("metadata") if isinstance(front.get("metadata"), dict) else {}
        kinds = meta.get("change_kinds") or []
        if isinstance(kinds, str):
            kinds = [k.strip() for k in kinds.split(",") if k.strip()]
        name = front.get("name") or os.path.basename(os.path.dirname(path))
        # Prefer the copy inside the project: a packet must cite a path that resolves on
        # every machine, not one pointing into whoever installed the plugin.
        vendored = ctx.path("protocols", f"{name}.md")
        skills.append({
            "name": name,
            "path": ctx.rel(vendored if os.path.exists(vendored) else path),
            "description": front.get("description", ""),
            "change_kinds": kinds,
            "body_tokens": estimate_tokens(body),
        })
    skills.sort(key=lambda s: s["name"])
    if write_json(ctx.gen("index", "skills.json"), skills):
        written.append("generated/index/skills.json")

    decisions = []
    decisions_dir = ctx.path("decisions")
    if os.path.isdir(decisions_dir):
        for name in sorted(os.listdir(decisions_dir)):
            if not name.endswith(".md"):
                continue
            text = read_text(os.path.join(decisions_dir, name))
            title = (re.search(r"^#\s*(.+)$", text, re.MULTILINE) or [None, name])[1]
            status = (re.search(r"^Status:\s*(.+)$", text, re.MULTILINE) or [None, "unknown"])[1]
            decisions.append({"id": name[:-3], "title": title.strip(), "status": status.strip(),
                              "path": ctx.rel(os.path.join(decisions_dir, name))})
    if write_json(ctx.gen("index", "decisions.json"), decisions):
        written.append("generated/index/decisions.json")

    lines = ["# Project index", "", "_Generated by `aegis index`. Do not edit._", "",
             "## Protocols", ""]
    for skill in skills:
        lines.append(f"- `{skill['name']}` — {skill['description'][:110]} → {skill['path']}")
    lines += ["", "## Registries", ""]
    for name in checks.REGISTRY_FILES:
        path = ctx.path("registry", f"{name}.json")
        if os.path.exists(path):
            entries = read_json(path)
            active = sum(1 for e in entries if isinstance(e, dict) and e.get("status") == "active")
            noun = "entry" if len(entries) == 1 else "entries"
            lines.append(f"- `{name}` — {len(entries)} {noun} ({active} active) → .aegis/registry/{name}.json")
    if decisions:
        lines += ["", "## Decisions", ""]
        lines += [f"- {d['id']} — {d['title']} [{d['status']}]" for d in decisions]
    tasks = checks.active_tasks(ctx)
    if tasks:
        lines += ["", "## Open tasks", ""]
        for task in tasks:
            if task.get("status") not in ("merged", "abandoned"):
                lines.append(f"- {task['id']} [{task.get('status')}] {task.get('objective', '')[:80]}"
                             f" — R: {', '.join(task.get('requirements') or []) or '—'}")
    if write_text(ctx.gen("index", "INDEX.md"), "\n".join(lines) + "\n"):
        written.append("generated/index/INDEX.md")
    return written


def docs_attest(ctx: Ctx, diagram_id: str | None, by: str = "", note: str = "") -> list[str]:
    """Record that a diagram matches its sources now.

    A digest proves the sources have not moved since someone attested; it cannot prove they
    looked. Requiring a name and a sentence does not prove it either — but it puts a
    signature on the claim, which is the difference between an unowned green check and one
    somebody can be asked about.
    """
    if not by:
        raise AegisError(
            "`aegis docs attest` needs --by <who>: attesting is a claim that you brought the "
            "diagram up to date, and an unsigned claim is not evidence."
        )
    if len(by.strip()) < 3:
        raise AegisError(f"`--by {by!r}` names nobody; give the name of who checked the document")
    return _docs_attest(ctx, diagram_id, by, note)


def _docs_attest(ctx: Ctx, diagram_id: str | None, by: str, note: str) -> list[str]:
    path = ctx.path("registry", "diagrams.json")
    entries = read_json(path)
    known = {e.get("id") for e in entries if isinstance(e, dict)}
    if diagram_id and diagram_id not in known:
        raise AegisError(
            f"no diagram {diagram_id!r} in the registry"
            + (f"; known ids: {', '.join(sorted(i for i in known if i))}" if known
               else "; the registry is empty")
        )
    touched = []
    for entry in entries:
        if diagram_id and entry.get("id") != diagram_id:
            continue
        digest = checks.source_digest(ctx, entry.get("watches") or [])
        if entry.get("verified_source_digest") != digest:
            entry["verified_source_digest"] = digest
            entry["verified_at"] = _dt.date.today().isoformat()
            entry["verified_by"] = by
            if note:
                entry["verified_note"] = note
            touched.append(entry["id"])
    write_json(path, entries)
    return touched


def fmt(ctx: Ctx) -> list[str]:
    changed = []
    for name in checks.REGISTRY_FILES:
        path = ctx.path("registry", f"{name}.json")
        if not os.path.exists(path):
            continue
        entries = read_json(path)
        if isinstance(entries, list):
            entries = sorted(entries, key=lambda e: e.get("id", "") if isinstance(e, dict) else "")
        if write_json(path, entries):
            changed.append(ctx.rel(path))
    return changed


# --------------------------------------------------------------------------- gates


def _task_touched_scope(ctx: Ctx, task: dict, scope: list[str]) -> bool:
    return any(matches_any(rel, task.get("owns") or []) for rel in scope)


COMMAND_TIMEOUT = int(os.environ.get("AEGIS_COMMAND_TIMEOUT", "900"))


def _run(command: str, cwd: str) -> tuple[int, str]:
    """A suite that needs a service nobody started hangs forever, and a gate that hangs is a
    gate that gets bypassed. Fail loudly with the remedy instead."""
    try:
        proc = subprocess.run(command, shell=True, cwd=cwd, capture_output=True,
                              text=True, timeout=COMMAND_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 124, (f"timed out after {COMMAND_TIMEOUT}s. If this command needs a database, "
                     "queue or other service, start it first or wrap the command so it does. "
                     "Raise the ceiling with AEGIS_COMMAND_TIMEOUT if the suite is simply slow.")
    return proc.returncode, (proc.stdout + proc.stderr)


def affected_packages(ctx: Ctx, scope: list[str]) -> list[tuple[str, dict]]:
    caps = checks.capabilities(ctx)
    packages = caps.get("packages") or {}
    hits = []
    for name, spec in sorted(packages.items()):
        if any(matches_any(rel, spec.get("paths") or []) for rel in scope):
            hits.append((name, spec))
    if not hits and caps.get("default_package") in packages:
        hits = [(caps["default_package"], packages[caps["default_package"]])]
    return hits


def _record_gate(ctx: Ctx, stage: str, task_id: str | None, report: Report, started: float) -> None:
    """Gate outcomes are the dogfooding signal: which checks fail, how often, how long."""
    import time
    if not task_id:
        return
    failing = sorted({f.check for f in report.findings if f.severity == "fail"})
    append_jsonl(os.path.join(run_dir(ctx, task_id), "metrics.jsonl"),
                 {"at": now(), "event": "gate", "task": task_id, "stage": stage,
                  "passed": not report.failed, "failing_checks": failing,
                  "seconds": round(time.monotonic() - started, 1)})


def _test_evidence(package: str, key: str, command: str, output: str) -> Report:
    """What a passing test command actually showed. Silent for anything but a test command."""
    report = Report()
    if key != "test":
        return report
    verdict = checks.tests_ran(output)
    if verdict == "none":
        report.fail("verify", f"{package}: `{command}` exited 0 and ran no tests", None,
                    hint="a filter that matches nothing, a runner that found no test files, or a "
                         "placeholder command: an exit code is not evidence. Read from recognised "
                         "runner summaries only, so a runner this does not know produces "
                         "`unknown` rather than this finding")
    elif verdict == "unknown":
        report.warn("verify", f"{package}: `{command}` passed, and its output does not say how "
                              "many tests ran", None,
                    hint="the gate recognises the common runners' summaries; a command like "
                         "`true` lands here, which is why this is a heuristic and not a guarantee")
    return report


def gate(ctx: Ctx, stage: str, task_id: str | None = None, run_commands: bool = True) -> Report:
    """Three stages, because one universal gate cannot serve all three moments.

    bootstrap — the framework itself is coherent. Runs on an empty project, so it must not
                require code, tests, or registries that do not exist yet.
    task      — this task is finished. Scoped to its diff and its affected packages only,
                so it stays fast enough to run every time.
    merge     — this branch may land. The full suite, blocking documentation, requirement
                coverage: the expensive checks, paid once, on the candidate commit.
    """
    from .config import check_drift, lint_banks

    report = Report()
    report.note(f"stage: {stage}" + (f" · task: {task_id}" if task_id else ""))

    if stage == "bootstrap":
        report.extend(checks.check_structure(ctx))
        report.extend(checks.check_protocol_copies(ctx))
        report.extend(checks.check_commands(ctx))
        report.extend(lint_banks(ctx))
        report.extend(check_drift(ctx))
        report.extend(checks.check_budget(ctx))
        report.extend(checks.check_registry(ctx))
        return checks.apply_waivers(ctx, report)

    if stage == "task":
        if not task_id:
            raise AegisError("`aegis gate --stage task` needs --task <TASK-ID>")
        manifest = checks.load_task(ctx, task_id)
        scope = changed_files(ctx, manifest.get("base_sha"))
        report.note(f"{len(scope)} changed files since {(manifest.get('base_sha') or 'unknown')[:8]}")
        report.extend(checks.check_structure(ctx))
        report.extend(checks.check_pointers(ctx))
        report.extend(checks.check_setup(ctx))
        report.extend(check_drift(ctx))
        report.extend(checks.check_registry(ctx))
        report.extend(checks.check_env(ctx, scope))
        report.extend(checks.check_surfaces(ctx, scope))
        report.extend(checks.check_routes(ctx, scope))
        report.extend(checks.check_testing_mandate(ctx, scope))
        report.extend(checks.check_trace(ctx, scope, task_id))
        report.extend(checks.check_docs(ctx, scope, closing_feature=False))
        report.extend(check_handoff(ctx, task_id))
        report.extend(check_reviews(ctx, task_id))
        if run_commands:
            executed = 0
            for name, spec in affected_packages(ctx, scope):
                for key in ("lint", "typecheck", "test", "build"):
                    command = spec.get(key)
                    if not command:
                        continue
                    executed += 1
                    code, output = _run(command, ctx.root)
                    if code != 0:
                        tail = "\n".join(output.strip().splitlines()[-12:])
                        report.fail("verify", f"{name}: `{command}` failed", None, hint=tail)
                    else:
                        report.info("verify", f"{name}: `{command}` passed")
                        report.extend(_test_evidence(name, key, command, output))
            test_globs = checks.capabilities(ctx).get("test_paths") or []
            # The former floor here compared two values derived from the same field, so it could
            # never fire. Evidence from the runner's own output is what tells a run from a
            # command that exits 0.
            if any(matches_any(rel, test_globs) for rel in scope) and \
                    not any(spec.get("test") for _n, spec in affected_packages(ctx, scope)):
                report.fail("verify", "tests changed but no package declares a test command", None,
                            hint="set it with `aegis answer q.core.commands`; otherwise the gate "
                                 "cannot tell whether the tests it just accepted pass")
            if not executed:
                # A gate that runs nothing passes everything. Silence here read as success
                # on a project whose commands were never configured.
                report.fail("verify", "no command ran, so nothing was verified", None,
                            hint="set the project's commands: "
                                 "aegis answer q.core.commands '{\"app\": {\"paths\": [\"src/**\"], \"test\": \"...\"}}'")
        report = checks.apply_waivers(ctx, report)
        if not report.failed and run_commands:
            # Advance the state machine here rather than expecting the caller to remember a
            # second command. Forgetting it made `aegis next` repeat "gate TASK" forever.
            manifest_now = checks.load_task(ctx, task_id)
            write_json(os.path.join(run_dir(ctx, task_id), "gate-receipt.json"), {
                "task": task_id, "at": now(),
                "diff_digest": diff_digest(ctx, manifest_now.get("base_sha"), task_id),
                "note": "written by a passing task gate; `gated` without this is not gated",
            })
            _set_status(ctx, task_id, "gated")
            report.note(f"{task_id} -> gated")
        return report

    if stage == "merge":
        # Union, not preference: staging one file made every other candidate change
        # invisible to trace, requirements, documentation and review checks.
        # The branch's diff, plus every holding task's own diff: on the mainline the branch
        # point is HEAD, so a task committed before this gate ran had a candidate of 0 files
        # and passed on nothing.
        scope = set(staged_files(ctx)) | set(changed_files(ctx, require_base(ctx)))
        for task in checks.active_tasks(ctx):
            if task.get("status") in checks.HOLDING and task.get("base_sha"):
                scope |= set(changed_files(ctx, task["base_sha"]))
        scope = sorted(scope)
        report.note(f"{len(scope)} files in the candidate diff")
        report.extend(checks.check_structure(ctx))
        report.extend(checks.check_pointers(ctx))
        report.extend(checks.check_setup(ctx))
        report.extend(checks.check_protocol_copies(ctx))
        report.extend(checks.check_commands(ctx))
        report.extend(lint_banks(ctx))
        report.extend(check_drift(ctx))
        report.extend(checks.check_registry(ctx))
        report.extend(checks.check_env(ctx, scope))
        report.extend(checks.check_surfaces(ctx, scope))
        report.extend(checks.check_routes(ctx, scope))
        report.extend(checks.check_testing_mandate(ctx, scope))
        report.extend(checks.check_trace(ctx, scope))
        report.extend(checks.check_requirements(ctx))
        report.extend(checks.check_docs(ctx, scope, closing_feature=True))
        report.extend(checks.check_budget(ctx))
        # Every task holding its lease over part of this candidate must have been reviewed
        # and handed off; skipping `building` once let a task land by never advancing its
        # status. A `planned` task is not skipped for leniency: it owns nothing, so code
        # written under its globs fails `trace` as belonging to no task until someone claims
        # it — one rule instead of two, and the strict side of it.
        for task in checks.active_tasks(ctx):
            # Only tasks holding their lease. A merged task holds none, so its files are
            # orphans and `trace` says so — and `task status` refuses to write `merged` by
            # hand anyway. A planned task owns nothing either, for the same reason.
            if task.get("status") not in checks.HOLDING:
                continue
            if not _task_touched_scope(ctx, task, scope):
                continue
            if task.get("status") != "gated" or not gate_receipt_valid(ctx, task["id"]):
                # Valid artefacts are not the same as a passed gate, and neither is a status
                # someone typed into the manifest.
                report.fail("trace",
                            f"{task['id']} has no passing gate receipt for this change", None,
                            hint=f"run `aegis gate --stage task --task {task['id']}` before merging")
            report.extend(check_handoff(ctx, task["id"]))
            report.extend(check_reviews(ctx, task["id"]))
        if run_commands:
            caps = checks.capabilities(ctx)
            executed = 0
            for name, spec in sorted((caps.get("packages") or {}).items()):
                for key in ("lint", "typecheck", "test", "build"):
                    command = spec.get(key)
                    if not command:
                        continue
                    executed += 1
                    code, output = _run(command, ctx.root)
                    if code != 0:
                        tail = "\n".join(output.strip().splitlines()[-12:])
                        report.fail("verify", f"{name}: `{command}` failed", None, hint=tail)
                    else:
                        report.info("verify", f"{name}: `{command}` passed")
                        report.extend(_test_evidence(name, key, command, output))
            if not executed:
                # The task gate had this floor and the merge gate did not, so a project with
                # no configured commands could land a branch on a gate that ran nothing.
                report.fail("verify", "no command ran, so nothing was verified", None,
                            hint="set the project's commands through `aegis answer q.core.commands`")
        report = checks.apply_waivers(ctx, report)
        if not report.failed and run_commands:
            # The gate judges; it writes nothing. `merged` is what `aegis land` records when
            # the default branch actually moves — a status the gate wrote here was a file the
            # agent could write too, and a gated task kept owning nothing after it, which is
            # what refused the next commit 48 times in the second cycle.
            report.note("merge gate passed; `aegis land` moves the default branch and marks "
                        "gated tasks merged")
        return report

    raise AegisError(f"unknown gate stage {stage!r}; expected bootstrap, task or merge")




def _default_branch(ctx: Ctx) -> str:
    """The mainline's name: `policy.mainline` if the project named it, else origin/HEAD, main, master."""
    named = checks.policy(ctx).get("mainline")
    if named and git(ctx, "rev-parse", "--verify", "-q", f"refs/heads/{named}").strip():
        return str(named)
    head = git(ctx, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD").strip()
    if head.startswith("origin/"):
        return head[len("origin/"):]
    for name in ("main", "master"):
        if git(ctx, "rev-parse", "--verify", "-q", f"refs/heads/{name}").strip():
            return name
    raise AegisError("no mainline branch found: tried policy.mainline, origin/HEAD, main, master — "
                     "`aegis answer q.core.mainline '\"<branch>\"'` names it")


def land(ctx: Ctx) -> list[str]:
    """Run the full merge gate at HEAD, move the mainline to it, mark the gated tasks merged,
    and commit that bookkeeping.

    The one place `merged` is written, because it is the one place it is true. On the mainline
    itself nothing moves; the gate still runs, over every gated task's own diff, and the tasks
    are marked merged in place. With no remote this moves a local ref, not a deployment.
    """
    from .core import is_ancestor
    head = head_sha(ctx)
    if not head:
        raise AegisError("nothing to land: no commit yet")
    gated = [t["id"] for t in checks.active_tasks(ctx)
             if t.get("status") == "gated" and gate_receipt_valid(ctx, t["id"])]
    if not gated:
        raise AegisError("nothing to land: no task is gated with a receipt for the current code; "
                         "`aegis gate --stage task --task <ID>` first")
    if git(ctx, "status", "--porcelain").strip():
        raise AegisError("the working tree is not clean; commit before landing")
    default = _default_branch(ctx)
    current = git(ctx, "branch", "--show-current").strip()
    tip = git(ctx, "rev-parse", "--verify", "-q", f"refs/heads/{default}").strip()
    if current != default and tip and not is_ancestor(ctx, tip, head):
        raise AegisError(f"{default} has commits HEAD does not; rebase or merge them first")
    if current != default:
        # Every refusal before anything is recorded. git refuses to move a branch that is
        # checked out in another worktree; discovering that after `merged` was written and
        # committed left a record the mainline did not carry and nothing to recover it with.
        worktrees = git(ctx, "worktree", "list", "--porcelain")
        if f"branch refs/heads/{default}\n" in worktrees + "\n":
            raise AegisError(f"{default} is checked out in another worktree, so git will refuse "
                             f"to move it; land from that checkout, or detach it first")
    report = gate(ctx, "merge", run_commands=True)
    if report.failed:
        failing = [f.render() for f in report.findings if f.severity == "fail"]
        raise AegisError("the full merge gate is red at HEAD:\n" + "\n".join(failing[:12]))
    lines = [f"gated: {', '.join(gated)}"]
    # Record first, move second: the mainline must carry the commit that says what landed,
    # or `next` on the mainline lands it again and the branch diverges from its own record.
    for task_id in gated:
        _set_status(ctx, task_id, "merged")
    git(ctx, "add", "--", ".aegis/runs", check=True)
    git(ctx, "commit", "-q", "-m", f"chore: land {', '.join(gated)}", check=True)
    landed = head_sha(ctx) or head
    if current != default:
        git(ctx, "branch", "-f", default, landed, check=True)
        lines.append(f"landed: {default} -> {landed[:12]}")
    else:
        lines.append(f"on {default} already; nothing to move")
    lines.append(f"merged: {', '.join(gated)} — recorded in {landed[:12]}")
    return lines



def _land_pending(ctx: Ctx) -> bool:
    """A gated task exists, and either the mainline is behind HEAD or HEAD is the mainline."""
    try:
        head = head_sha(ctx)
        if not head:
            return False
        default = _default_branch(ctx)
        tip = git(ctx, "rev-parse", "--verify", "-q", f"refs/heads/{default}").strip()
        current = git(ctx, "branch", "--show-current").strip()
        if not tip or (tip == head and current != default):
            return False
        return any(t.get("status") == "gated" for t in checks.active_tasks(ctx))
    except AegisError:
        return False



def next_action(ctx: Ctx) -> dict:
    """What to do right now, computed from the state on disk.

    The loop is guaranteed by being derivable, not by being remembered. An agent that
    resumes after compaction, a different runner, or a human returning on Monday all ask
    the same question and get the same answer.
    """
    # `who` says what the step needs: `cli` — a self-contained `aegis …` command that
    # `aegis next --run` may execute; `agent` — a command followed by a dispatch or a
    # judgement; `human` — a decision. The instruction that used to ride along as a shell
    # comment lives in `note`, so `command` is always exactly what to run.
    def step(what: str, why: str, command: str | None = None, who: str = "agent",
             note: str | None = None) -> dict:
        return {"do": what, "why": why, "command": command, "who": who, "note": note}

    if not os.path.isdir(ctx.aegis):
        return step("initialise Aegis", "no .aegis/ directory in this project",
                    "aegis init", "human")

    if not os.path.exists(ctx.path("constitution.md")):
        # Nobody authors it. `scaffold`, not `init`: a re-run of init rebuilds the ledger and
        # flips a complete project back to provisional, which is the human step R-33 removed,
        # one step later. `scaffold` writes only what is missing and leaves answers.json alone.
        profile = read_json(ctx.path("answers.json"), default={}).get("resolved", {}).get("q.core.profile", {})
        profile = profile.get("value") if isinstance(profile, dict) else None
        return step("draft the constitution", "constitution.md is missing",
                    f"aegis scaffold --profile {profile}" if profile in ("S", "M", "L") else "aegis scaffold",
                    "cli", note="scaffold writes only the missing files and never touches answers.json")

    answers = read_json(ctx.path("answers.json"), default={})
    if answers.get("status") == "provisional" and answers.get("ledger"):
        n = len(answers["ledger"])
        return step("review the assumption ledger",
                    f"{n} answer{'' if n == 1 else 's'} auto-resolved without you; phase 3 is blocked until reviewed",
                    "cat .aegis/answers.json", "human",
                    note="`aegis answer <qid> <value>` for each row")

    # Who a step needs is derived from one rule, stated in the build protocol: a person is
    # needed for an irreversible outward-facing act, for a change to what the framework
    # measures work against that a person owns, for a question a proposed ADR records, for a
    # tool permission the runner refuses, and for an escalation. Everything else the agent
    # decides, records and continues. Ten case-by-case `human` marks used to live here.
    question = _open_adr_question(ctx)
    if question:
        return step("answer the question the ADR records", question[1], f"$EDITOR {question[0]}",
                    "human", note="an ADR with `**Status:** proposed` and a `**Blocks:**` line "
                                  "stops the loop until a person edits one of the two")

    tasks = checks.active_tasks(ctx)
    open_tasks = [t for t in tasks if t.get("status") not in ("merged", "abandoned")]
    gated = [t for t in tasks if t.get("status") == "gated" and gate_receipt_valid(ctx, t["id"])]
    building = [t for t in open_tasks if t.get("status") == "building"]
    try:
        require_base(ctx)
    except AegisError as exc:
        return step("name the mainline branch", str(exc).split(":")[0],
                    "aegis answer q.core.mainline '\"<branch>\"'",
                    note="a fact about the repository, not a policy; answer it and continue")

    # Land between tasks: a gated task is committed and landed before the next one starts,
    # and only when nothing is mid-build — a building task's uncommitted work is not a
    # candidate, and the merge gate would refuse it for having no receipt anyway.
    if gated and not building and git(ctx, "status", "--porcelain").strip():
        # The step that stands between a gated task and a landed branch. Without it the loop
        # went from a green merge gate straight to "plan the next feature", because landing
        # needs a commit and nothing had said so.
        return step("commit the candidate", f"{', '.join(t['id'] for t in gated)} gated and the "
                    "tree is dirty; landing needs a commit",
                    "git add -A && git commit", note="the message is yours; the pre-commit hook "
                                                     "checks drift and structure and nothing else")

    if gated and not building:
        # What the profile still owes, said here — the merge gate at `land` would refuse on it
        # and only its stderr would name the cause.
        for t in gated:
            judged = checks.apply_waivers(ctx, checks.check_docs(
                ctx, changed_files(ctx, t.get("base_sha")), closing_feature=True))
            docs = [f for f in judged.findings if f.severity == "fail"]
            if docs:
                return step("write the documentation the profile requires", docs[0].message, None,
                            note=docs[0].hint or "the doc-manager verifies it against its sources, "
                                                 "then `aegis docs attest <id> --by aegis-doc-manager --note <what was checked>`")
    if gated and not building:
        # The merge gate refuses a landing over an uncovered requirement; say it here rather
        # than advising a land the gate will refuse — the loop and the gate must not disagree.
        uncovered = [f for f in checks.check_requirements(ctx).findings if f.severity == "fail"]
        if uncovered:
            return step("cover or retire the requirement", uncovered[0].message, None,
                        note=uncovered[0].hint)
    if gated and not building and _land_pending(ctx):
        on_mainline = git(ctx, "branch", "--show-current").strip() == _default_branch(ctx)
        return step("land the branch", "a gated task is committed on the mainline; the gate "
                    "runs and it is marked merged in place" if on_mainline else
                    "a gated task is committed and the default branch is behind it",
                    "aegis land", "cli",
                    note="runs the full merge gate at HEAD, moves the ref as a fast-forward, marks "
                         "the gated tasks merged and commits that")

    if not open_tasks:
        specs = ctx.path("specs")
        features = sorted(os.listdir(specs)) if os.path.isdir(specs) else []
        if not features:
            return step("specify the first feature", "no specs exist yet", "/aegis:spec <feature>")
        for feature in features:
            if not os.path.exists(os.path.join(specs, feature, "architecture.md")):
                return step(f"plan the architecture for {feature}", "spec exists, architecture does not",
                            f"/aegis:plan {feature}")
        # A feature with every requirement covered is finished; advising its decomposition
        # again sent completed work back to the start of the loop.
        coverage = checks.check_requirements(ctx)
        uncovered = [f for f in coverage.findings if f.severity == "fail"]
        if uncovered:
            feature = uncovered[0].message.split(":")[0]
            return step(f"decompose {feature} into tasks", uncovered[0].message,
                        f"/aegis:tasks {feature}")
        return step("start the next feature", "every requirement of every spec is covered by a merged task",
                    "/aegis:spec <feature>", "human")

    # Unfinished work outranks finished work: a gated task is waiting on a human to merge,
    # while a planned one is waiting on the agent. Sorting gated first stalled the pipeline.
    # Gated with a receipt that still matches ranks last — it is waiting on land, not on the
    # agent — and so does `gated` with no receipt at all, which is a typed status and must not
    # stall an unbuilt task. Gated with a receipt the code has moved past is unfinished: it
    # needs a re-review and a re-gate, and ranking it as finished sent the loop to claim a
    # planned task the lease clash then refused.
    def finished(t: dict) -> bool:
        if t.get("status") != "gated":
            return False
        has_receipt = os.path.exists(os.path.join(run_dir(ctx, t["id"]), "gate-receipt.json"))
        return not has_receipt or gate_receipt_valid(ctx, t["id"])
    task = sorted(open_tasks, key=lambda t: (finished(t), t["id"]))[0]
    task_id = task["id"]
    if not task.get("requirements"):
        # The gate rejects this unconditionally, so advising anything else here would send
        # the agent down a path that cannot end in a green gate.
        return step(f"give {task_id} a requirement", "the gate rejects a task that closes nothing",
                    None, note=f"edit .aegis/runs/{task_id}/manifest.json and set "
                               f"\"requirements\": [\"R-1\"]")

    directory = run_dir(ctx, task_id)
    has_handoff = os.path.exists(os.path.join(directory, "handoff.json"))
    reviews = os.path.join(directory, "reviews")
    recorded = ({n[:-5] for n in os.listdir(reviews) if n.endswith(".json")}
                if os.path.isdir(reviews) else set())

    if not has_handoff:
        claimed = task.get("status") == "building"
        return step(f"build {task_id}", "no handoff recorded yet",
                    f"aegis packet {task_id}" if claimed else f"aegis task claim {task_id}",
                    note="dispatch aegis-builder with that text" if claimed else
                         f"then `aegis packet {task_id}`, and dispatch aegis-builder with that text")

    handoff_report = check_handoff(ctx, task_id)
    if handoff_report.failed:
        first = next(f for f in handoff_report.findings if f.severity == "fail")
        return step(f"fix the handoff for {task_id}", first.message,
                    None, note=f"edit .aegis/runs/{task_id}/handoff.json")

    plan = lens_plan(ctx, task_id)
    missing = [lens for lens in plan["lenses"] if lens not in recorded]
    if missing:
        return step(f"review {task_id}", f"required lenses have not run: {', '.join(missing)}",
                    f"aegis lens plan {task_id}", note=f"dispatch the {missing[0]} lens to its plan profile, briefed by `aegis lens prompt {task_id} {missing[0]}`")

    cap = checks.policy(ctx).get("refinement_rounds") or 3
    for lens in sorted(recorded):
        record = read_json(os.path.join(reviews, f"{lens}.json"))
        rounds = record.get("round", 0)
        why_stale = lens_staleness(ctx, task_id, lens, record, plan)
        if why_stale:
            return step(f"re-run lens-{lens}", why_stale,
                        f"aegis lens plan {task_id}", note=f"dispatch the {lens} lens again, to its plan profile"
                        + (f" — round {rounds + 1}, past the {cap} the policy expects: a finding "
                           f"surviving this many rounds usually means the mechanism is wrong, so "
                           f"simplify before patching again" if rounds >= cap else ""))
        builder = (read_json(os.path.join(directory, "handoff.json"), default={}).get("agent") or "")
        came_back = [f["id"] for f in record.get("findings", [])
                     if f.get("reopened_in") and not _closed_by_a_person(f, builder, lens)]
        if came_back:
            return step(f"simplify the mechanism behind {', '.join(came_back)}",
                        f"{lens}: a finding marked fixed came back — patching it again will not hold",
                        None, "human",
                        note=f"when it is simplified and re-reviewed, a person records `aegis lens "
                             f"disposition {task_id} {came_back[0]} fixed --reason … --by <name>`")
        for finding in record.get("findings", []):
            if finding.get("severity", 0) >= 3 and finding.get("disposition") in (None, "open"):
                # Fix the code, then re-review. Advising the disposition command first taught
                # the loop that the cheapest route to green was to declare the finding fixed.
                # At the cap the advice is the same and the note says what the number means.
                return step(f"fix {finding['id']} in the code", f"{lens}: {finding['message'][:80]}",
                            None,
                            note=f"{finding.get('minimal_fix') or 'apply the fix'}, then re-run "
                                 f"lens-{lens} and record it; dismissing it instead — false-positive, "
                                 f"waived or deferred — is a person's decision, not the loop's"
                                 + (f". This is round {rounds} of the {cap} the policy expects: a "
                                    f"finding that survives this many rounds usually means the "
                                    f"mechanism is wrong — simplify before patching again"
                                    if rounds >= cap else ""))
        for finding in record.get("findings", []):
            problems = _dismissal_problems(ctx, finding, builder, lens)
            if problems:
                return step(f"a person decides {finding['id']}", problems[0][0], None, "human",
                            note=f"{problems[0][1]}; or fix the code and re-run lens-{lens}")

    if task.get("status") != "gated" or not gate_receipt_valid(ctx, task_id):
        return step(f"gate {task_id}",
                    "work and review are complete"
                    if task.get("status") != "gated" else
                    "the manifest says gated but no passing gate wrote a receipt for this code",
                    f"aegis gate --stage task --task {task_id}", "cli")

    return step("land the branch", f"{task_id} is gated", "aegis land", "cli",
                note="the full merge gate at HEAD, the ref moved, merged written and committed")


def _open_adr_question(ctx: Ctx) -> tuple[str, str] | None:
    """A `proposed` ADR that says what it blocks stops the loop until a person edits it.

    Convention, not schema: `- **Status:** proposed` and a line beginning `- **Blocks:**`.
    After TASK-STABLE-01 was abandoned the loop said "build the next task" past a decision
    that forbade exactly that; an ADR with no `Blocks:` line blocks nothing.
    """
    directory = ctx.path("decisions")
    if not os.path.isdir(directory):
        return None
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".md"):
            continue
        text = read_text(os.path.join(directory, name), default="")
        if not re.search(r"^\s*-\s*\*\*Status:\*\*\s*proposed", text, re.M):
            continue
        blocks = re.search(r"^\s*-\s*\*\*Blocks:\*\*\s*(.+)$", text, re.M)
        if blocks:
            return (os.path.join(".aegis", "decisions", name), blocks.group(1).strip())
    return None


def metrics(ctx: Ctx) -> dict:
    """Aggregate what the run artefacts already record.

    Computed from dispositions rather than from verdicts: a lens that files ten findings
    nobody acts on is not thorough, it is expensive. Acceptance rate is the number that
    tells the two apart, and it only means anything once the sample is large enough — so
    the sample size is reported next to it rather than buried.
    """
    per_lens: dict[str, dict[str, int]] = {}
    tasks = checks.active_tasks(ctx)
    reopened_total = 0
    rounds: list[int] = []
    packet_tokens: list[int] = []
    gate_runs = {"passed": 0, "failed": 0}
    gate_fail_checks: dict[str, int] = {}
    for task in tasks:
        for row in read_jsonl(os.path.join(run_dir(ctx, task["id"]), "metrics.jsonl")):
            if row.get("event") == "packet":
                packet_tokens.append(row.get("tokens", 0))
            elif row.get("event") == "gate":
                gate_runs["passed" if row.get("passed") else "failed"] += 1
                for name in row.get("failing_checks") or []:
                    gate_fail_checks[name] = gate_fail_checks.get(name, 0) + 1

    for task in tasks:
        directory = os.path.join(run_dir(ctx, task["id"]), "reviews")
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".json"):
                continue
            record = read_json(os.path.join(directory, name))
            lens = record.get("lens", name[:-5])
            bucket = per_lens.setdefault(lens, {"findings": 0, "fixed": 0, "false_positive": 0,
                                                "waived": 0, "deferred": 0, "open": 0, "runs": 0})
            bucket["runs"] += 1
            rounds.append(record.get("round", 1))
            reopened_total += len(record.get("reopened") or [])
            for finding in record.get("findings", []):
                bucket["findings"] += 1
                key = {"fixed": "fixed", "false-positive": "false_positive", "waived": "waived",
                       "deferred": "deferred"}.get(finding.get("disposition"), "open")
                bucket[key] += 1

    for lens, bucket in per_lens.items():
        judged = bucket["findings"]
        bucket["acceptance_rate"] = round(bucket["fixed"] / judged, 2) if judged else None
        bucket["sample"] = judged
        bucket["note"] = "fixed over all findings raised, matching the retro protocol"

    status_counts: dict[str, int] = {}
    for task in tasks:
        status_counts[task.get("status", "unknown")] = status_counts.get(task.get("status", "unknown"), 0) + 1

    return {
        "tasks": {"total": len(tasks), "by_status": status_counts},
        "packet_tokens": {"mean": round(sum(packet_tokens) / len(packet_tokens)) if packet_tokens else 0,
                          "max": max(packet_tokens, default=0), "n": len(packet_tokens)},
        "gates": {**gate_runs, "failures_by_check": dict(sorted(
            gate_fail_checks.items(), key=lambda kv: -kv[1]))},
        "review_rounds": {"max": max(rounds) if rounds else 0,
                          "mean": round(sum(rounds) / len(rounds), 2) if rounds else 0},
        "reopened_findings": reopened_total,
        "lenses": per_lens,
        "caveat": ("fewer than 10 judged findings for a lens: treat its acceptance rate as an "
                   "observation, not evidence to change a protocol"),
    }


def status(ctx: Ctx) -> str:
    policy = checks.policy(ctx)
    lines = [f"Aegis · profile {policy.get('profile', '?')} · mode {policy.get('mode', '?')}"]
    answers_path = ctx.path("answers.json")
    if os.path.exists(answers_path):
        answers = read_json(answers_path)
        ledger = answers.get("ledger") or []
        lines.append(f"  init: {answers.get('status', 'unknown')}"
                     + (f" · {len(ledger)} assumptions awaiting review" if ledger else ""))
    baseline = (checks.capabilities(ctx).get("baseline") or {})
    baselined = baseline.get("files")
    if baselined:
        from .core import _pre_adoption_files
        attributed = _pre_adoption_files(ctx, set(baselined))
        uncommitted = attributed & set(working_tree_files(ctx))
        changed = len(baselined) - len(attributed)
        if uncommitted or changed:
            lines.append(f"  baseline: {len(baselined)} path(s) recorded at adoption — "
                         f"{len(attributed)} still attributed, {len(uncommitted)} of them uncommitted, "
                         f"{changed} changed under a task since "
                         f"(recorded {baseline.get('recorded', '?')}; committing the attributed ones "
                         "as they are keeps them attributed and retires the baseline)")
        else:
            lines.append(f"  baseline: retired — the {len(baselined)} path(s) recorded at adoption "
                         f"on {baseline.get('recorded', '?')} are committed as they were")
    elif baseline.get("skipped"):
        lines.append(f"  baseline: {baseline['skipped']} uncommitted files — too many to baseline; "
                     "commit them before the first task")
    tasks = checks.active_tasks(ctx)
    open_tasks = [t for t in tasks if t.get("status") not in ("merged", "abandoned")]
    lines.append(f"  tasks: {len(open_tasks)} open / {len(tasks)} total")
    for task in open_tasks[:10]:
        lines.append(f"    {task['id']} [{task.get('status')}] {task.get('objective', '')[:70]}")
        handoff = read_json(os.path.join(run_dir(ctx, task["id"]), "handoff.json"), default={})
        questions = handoff.get("open_questions") or []
        if questions:
            lines.append(f"      {len(questions)} open question(s) from its handoff: {questions[0][:80]}")
        if handoff.get("next_safe_action"):
            lines.append(f"      next safe action: {handoff['next_safe_action'][:80]}")
    for name in checks.REGISTRY_FILES:
        path = ctx.path("registry", f"{name}.json")
        if os.path.exists(path):
            lines.append(f"  registry/{name}: {len(read_json(path))} entries")
    budget_report = checks.check_budget(ctx)
    over = [f for f in budget_report.findings if f.severity in ("fail", "warn")]
    lines.append(f"  budgets: {'OK' if not over else str(len(over)) + ' past a warning line'}")
    return "\n".join(lines)
