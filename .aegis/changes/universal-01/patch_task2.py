import os, sys, io, json
ROOT = os.environ["AEGIS_PATCH_ROOT"]
def patch(rel, old, new, count=1):
    p=f"{ROOT}/{rel}"; t=io.open(p,encoding="utf-8").read()
    if new and new in t:
        print("already",rel); return
    n=t.count(old)
    if n!=count: sys.exit(f"{rel}: expected {count}, found {n}:\n{old[:220]!r}")
    io.open(p,"w",encoding="utf-8").write(t.replace(old,new)); print("patched",rel)
CFG="scripts/aegis/aegis_cli/config.py"; SCF="scripts/aegis/aegis_cli/scaffold.py"
FLOW="scripts/aegis/aegis_cli/flow.py"; CHK="scripts/aegis/aegis_cli/checks.py"; MAIN="scripts/aegis/aegis_cli/__main__.py"

# =============================================================== T2-1 honest detection
patch(CFG, '''AUTONOMY_RE = re.compile(r"^(always-ask|auto-default|detect-only|auto-if-detected:0\\.\\d+)$")
''', '''AUTONOMY_RE = re.compile(r"^(always-ask|auto-default|detect-only|auto-if-detected:0\\.\\d+)$")

# What detection actually produces, and how sure it is of each fact. A question's `detect:`
# must name a key here. Two shipped questions named keys nothing emitted, so their
# `auto-if-detected` could never fire — a declaration the interview could not keep.
DETECT_KEYS: dict[str, str] = {
    "repo_size": "S | M | L, from the number of files",
    "project_type": "the kind of system, with project_type_confidence and evidence",
    "packages": "package name -> commands, from manifests, lockfiles, Makefile and CI",
}


def detected_answer(key: str, facts: dict) -> tuple[Any, str, float, str] | None:
    """(value, source, confidence, rationale) for a detect key, or None when detection found
    nothing. The confidences live here, next to the keys, instead of in scattered calls."""
    if key == "repo_size" and facts.get("repo_size"):
        return facts["repo_size"], "heuristic", 0.7, "repository size"
    if key == "project_type" and facts.get("project_type"):
        return (facts["project_type"], "detected", float(facts.get("project_type_confidence") or 0),
                facts.get("project_type_evidence") or "detected")
    if key == "packages" and facts.get("packages"):
        return (facts["packages"], "detected", 0.9,
                f"{len(facts['packages'])} package(s) found in manifests")
    return None


def autonomy_threshold(question: dict, fallback: float = 0.8) -> float:
    """The confidence at which a detected answer is taken without asking — the number the
    bank declares, not a constant the engine picked."""
    match = re.match(r"^auto-if-detected:(0\\.\\d+)$", question.get("autonomy", ""))
    return float(match.group(1)) if match else fallback
''')
patch(CFG, '''            elif autonomy != "always-ask":
                has_default = "default" in question
                has_detect = bool(question.get("detect"))
''', '''            elif autonomy != "always-ask":
                has_default = "default" in question
                has_detect = bool(question.get("detect"))
                if autonomy.startswith("auto-if-detected") and not has_detect:
                    report.fail("bank-lint", f"{qid} is auto-if-detected but names no detect key", where,
                                hint="add `detect` from the detection keys, or make it auto-default")
                if has_detect and question["detect"] not in DETECT_KEYS:
                    report.fail("bank-lint",
                                f"{qid} detects {question['detect']!r}, which detection never produces",
                                where, hint=f"detection produces: {', '.join(sorted(DETECT_KEYS))}")
''')
patch(CFG, '''        if source in ("detected", "heuristic") and confidence >= 0.8:
''', '''        if source in ("detected", "heuristic") and confidence >= autonomy_threshold(question):
''')
patch(SCF, '''    chosen_profile = profile or facts["repo_size"]
    record("q.core.profile", chosen_profile, "human" if profile else "heuristic",
           1.0 if profile else 0.7, f"{'chosen' if profile else 'repository size'}")
    record("q.core.project-type", facts["project_type"], "detected",
           facts["project_type_confidence"], facts["project_type_evidence"])
    record("q.core.mode", mode, "human", 1.0, "init flag")
    if facts["packages"]:
        record("q.core.commands", facts["packages"], "detected", 0.9,
               f"{len(facts['packages'])} package(s) found in manifests")
    else:
''', '''    chosen_profile = profile or facts["repo_size"]
    record("q.core.mode", mode, "human", 1.0, "init flag")
    if profile:
        record("q.core.profile", profile, "human", 1.0, "chosen")
    # Every other detected answer comes from the banks' own `detect:` declarations, at the
    # threshold each question declares — four hard-coded calls and a constant 0.8 used to
    # decide this while the declarations were read only by the linter.
    banks_for_detection = config.load_banks(ctx)
    probe = {"detected": {k: v for k, v in facts.items() if k not in ("evidence", "surfaces")}}
    for question in (config.resolve_questions(banks_for_detection, config.select_banks(probe))
                     if banks_for_detection else []):
        key = question.get("detect")
        if not key or question["id"] in resolved:
            continue
        found = config.detected_answer(key, facts)
        if found is None:
            continue
        value, source, confidence, why = found
        resolved[question["id"]] = {"value": value, "source": source, "confidence": confidence,
                                    "rationale": why}
        if confidence < config.autonomy_threshold(question):
            ledger.append({"question": question["id"], "value": value, "confidence": confidence,
                           "note": why})
    if not facts["packages"]:
''')
patch(SCF, '''    def record(qid: str, value, source: str, confidence: float, why: str) -> None:
        resolved[qid] = {"value": value, "source": source, "confidence": confidence, "rationale": why}
        if source != "human" and confidence < 0.8:
            ledger.append({"question": qid, "value": value, "confidence": confidence, "note": why})
''', '''    def record(qid: str, value, source: str, confidence: float, why: str) -> None:
        resolved[qid] = {"value": value, "source": source, "confidence": confidence, "rationale": why}
''')
for rel, qid in (("interview/project-type/api-service.json", "q.api.errors"),
                 ("interview/project-type/web-saas.json", "q.web.frontend")):
    p=f"{ROOT}/{rel}"; bank=json.load(open(p))
    for q in bank["questions"]:
        if q["id"]==qid:
            q.pop("detect",None); q["autonomy"]="auto-default"
    json.dump(bank,open(p,"w"),indent=2,ensure_ascii=False); open(p,"a").write("\n"); print("bank",rel)
p=f"{ROOT}/interview/core.json"; bank=json.load(open(p))
for q in bank["questions"]:
    if q["id"]=="q.core.profile": q["autonomy"]="auto-if-detected:0.8"
json.dump(bank,open(p,"w"),indent=2,ensure_ascii=False); open(p,"a").write("\n"); print("bank core: profile threshold 0.8")

# =============================================================== T2-3 tests actually ran
patch(FLOW, '''def affected_packages(ctx: Ctx, scope: list[str]) -> list[tuple[str, dict]]:
''', '''# Evidence that a test command executed tests, by runner. A heuristic, and labelled as one:
# a recognised count of zero fails; output with no recognisable count only warns.
_TESTS_RAN = [
    r"\\bRan (\\d+) tests?\\b",                    # unittest
    r"\\b(\\d+) passed\\b",                         # pytest, vitest, deno, cargo
    r"\\bTests:\\s+(?:.*?,\\s*)?(\\d+) passed",       # jest
    r"\\b(\\d+) passing\\b",                        # mocha
    r"\\b(\\d+) examples?, 0 failures\\b",           # rspec
    r"\\bOK \\((\\d+) tests?",                       # phpunit
    r"\\bTests run: (\\d+)",                         # junit / maven / gradle
    r"^# pass\\s+(\\d+)",                           # tap
    r"^(?:ok|PASS)\\s+\\S+",                          # go test
]
_NO_TESTS = [
    r"\\bRan 0 tests\\b", r"\\bno tests ran\\b", r"\\bcollected 0 items\\b", r"\\bNo tests found\\b",
    r"\\b0 passing\\b", r"\\brunning 0 tests\\b", r"\\bno test files\\b", r"\\bno tests to run\\b",
    r"\\b0 examples\\b", r"\\bTests:\\s+0 total\\b",
]


def tests_ran(output: str) -> str:
    """`ran` when the output shows at least one executed test, `none` when it shows zero,
    `unknown` when it shows neither. Exit code 0 from a runner that found nothing to run is
    the false green this exists for: "not executed" must never read as "passed"."""
    counted = False
    for pattern in _TESTS_RAN:
        for match in re.finditer(pattern, output, re.MULTILINE):
            counted = True
            if not match.groups() or int(match.group(1)) > 0:
                return "ran"
    if counted or any(re.search(p, output, re.MULTILINE | re.IGNORECASE) for p in _NO_TESTS):
        return "none"
    return "unknown"


def _verify_test_output(report: Report, name: str, command: str, output: str) -> None:
    verdict = tests_ran(output)
    if verdict == "none":
        report.fail("verify", f"{name}: `{command}` exited 0 but ran no tests", None,
                    hint="a filter that matches nothing, or a runner that found no test files, "
                         "is not a passing suite")
    elif verdict == "unknown":
        report.warn("verify", f"{name}: `{command}` passed, but its output shows no recognisable test count",
                    hint="a heuristic: counts from unittest, pytest, jest, vitest, mocha, rspec, "
                         "phpunit, JUnit, TAP and go test are recognised")


def affected_packages(ctx: Ctx, scope: list[str]) -> list[tuple[str, dict]]:
''')
patch(FLOW, '''                    code, output = _run(command, ctx.root)
                    if code != 0:
                        tail = "\\n".join(output.strip().splitlines()[-12:])
                        report.fail("verify", f"{name}: `{command}` failed", None, hint=tail)
                    else:
                        report.info("verify", f"{name}: `{command}` passed")
''', '''                    code, output = _run(command, ctx.root)
                    if code != 0:
                        tail = "\\n".join(output.strip().splitlines()[-12:])
                        report.fail("verify", f"{name}: `{command}` failed", None, hint=tail)
                    else:
                        report.info("verify", f"{name}: `{command}` passed")
                        if key == "test":
                            _verify_test_output(report, name, command, output)
''', count=2)

# =============================================================== T2-4 spec clarity
patch(CHK, '''        declared = set(re.findall(r"^\\s*(R-\\d+)\\.", read_text(spec_file), re.MULTILINE))
        if not declared:
''', '''        spec_text = read_text(spec_file)
        ids = re.findall(r"^\\s*(R-\\d+)\\.", spec_text, re.MULTILINE)
        declared = set(ids)
        twice = sorted({i for i in ids if ids.count(i) > 1})
        if twice:
            report.fail("requirements", f"{name}: declared more than once: {', '.join(twice)}",
                        ctx.rel(spec_file), hint="an id is permanent and names one requirement; supersede, never reuse")
        unclear = len(re.findall(r"\\[NEEDS CLARIFICATION", spec_text))
        if unclear:
            has_tasks = any(t.get("feature") == name and t.get("status") != "abandoned" for t in tasks)
            (report.fail if has_tasks else report.warn)(
                "requirements", f"{name}: {unclear} unresolved [NEEDS CLARIFICATION] marker(s)",
                ctx.rel(spec_file),
                hint="tasks cut from an ambiguous spec encode a guess; answer the questions first"
                     if has_tasks else "answer them before `/aegis:tasks`")
        if not declared:
''')

# =============================================================== T2-5 Codex adapters
patch(CHK, '''def check_protocol_copies(ctx: Ctx) -> Report:
''', '''def codex_adapter(name: str, description: str) -> str:
    """The `.agents/skills/<name>/SKILL.md` Codex discovers: its trigger metadata and a
    pointer to the one vendored body. A third byte-identical copy only added churn on every
    protocol edit and a second place for the two to disagree."""
    return (f"---\\nname: {name}\\ndescription: {json.dumps(description, ensure_ascii=False)}\\n---\\n\\n"
            f"# {name}\\n\\nThe maintained body of this procedure is `.aegis/protocols/{name}.md`. "
            "Read it and follow it exactly — this file adds nothing, so the two cannot disagree.\\n")


def check_protocol_copies(ctx: Ctx) -> Report:
''')
patch(CHK, '''        elif os.path.exists(codex_copy) and read_text(codex_copy) != read_text(source):
            report.fail("protocols", f"{name} differs in .agents/skills/ (the copy Codex reads)",
                        ctx.rel(codex_copy), hint="run `aegis migrate`")
''', '''        elif os.path.exists(codex_copy) and name in RUNNER_NEUTRAL and \\
                read_text(codex_copy) != codex_adapter(name, front.get("description", "")):
            report.fail("protocols", f"{name}: the Codex adapter in .agents/skills/ is not the generated one",
                        ctx.rel(codex_copy), hint="run `aegis migrate`")
''')
patch(SCF, '''        if name in RUNNER_NEUTRAL:
            target = os.path.join(ctx.root, ".agents", "skills", name, "SKILL.md")
            if write_text(target, content):
                written.append(f".agents/skills/{name}/SKILL.md")
''', '''        if name in RUNNER_NEUTRAL:
            target = os.path.join(ctx.root, ".agents", "skills", name, "SKILL.md")
            if write_text(target, checks.codex_adapter(name, front.get("description", ""))):
                written.append(f".agents/skills/{name}/SKILL.md")
''')

# =============================================================== T2-6 delta packet + handoff agent field
patch(FLOW, '''def build_packet(ctx: Ctx, task_id: str) -> tuple[str, dict]:
    """Assemble the delegation contract deterministically.

    The orchestrator does not improvise this. A script emits it, so the packet is
    reproducible, measurable, and identical across restarts — and its token cost is a
    number the gate can enforce rather than a hope.
    """
    manifest = checks.load_task(ctx, task_id)
''', '''def build_packet(ctx: Ctx, task_id: str, delta_from: str | None = None) -> tuple[str, dict]:
    """Assemble the delegation contract deterministically.

    The orchestrator does not improvise this. A script emits it, so the packet is
    reproducible, measurable, and identical across restarts — and its token cost is a
    number the gate can enforce rather than a hope.

    `delta_from` is for a builder that is kept warm across tasks of one cluster: it already
    holds the previous packet, so what did not change — protocols, priorities, boundaries,
    the handoff format, and the spec's edge cases when the feature is the same — is replaced
    by one line instead of being re-read.
    """
    manifest = checks.load_task(ctx, task_id)
    previous = checks.load_task(ctx, delta_from) if delta_from else None
    same_feature = bool(previous) and previous.get("feature") == manifest.get("feature")
''')
patch(FLOW, '''    if spec_dir and os.path.exists(os.path.join(spec_dir, "spec.md")):
        for heading in ("Edge cases", "Contracts", "End-to-end check"):
''', '''    if spec_dir and os.path.exists(os.path.join(spec_dir, "spec.md")) and not same_feature:
        for heading in ("Edge cases", "Contracts", "End-to-end check"):
''')
patch(FLOW, '''    protocols = _protocol_paths(ctx, manifest)
    if protocols:
        parts.append("**Protocols that apply. Read them; they are not preloaded.**")
''', '''    protocols = _protocol_paths(ctx, manifest)
    if protocols and not (previous and protocols == _protocol_paths(ctx, previous)):
        parts.append("**Protocols that apply. Read them; they are not preloaded.**")
''')
patch(FLOW, '''    priorities = policy.get("nfr_priorities") or []
    if priorities:
        parts.append(f"**Decide close calls by these priorities, in order:** {', '.join(priorities)}.\\n")
    limits = policy.get("autonomy_limits") or []
    granted = ", ".join(limits) if limits else "nothing"
    parts.append(
        f"**You may decide alone:** {granted}. Anything else — a dependency, a schema change, "
        f"a public contract, a security trade-off — stops and returns the question.\\n"
    )

    parts.append(
''', '''    priorities = policy.get("nfr_priorities") or []
    limits = policy.get("autonomy_limits") or []
    granted = ", ".join(limits) if limits else "nothing"
    if previous:
        parts.append(
            f"**Unchanged from {delta_from}.** Decision priorities, autonomy limits, boundaries"
            + (", the spec's edge cases and contracts" if same_feature else "")
            + " and the handoff format are the same as in that packet — only the handoff path is "
            f"new: `.aegis/runs/{task_id}/handoff.json`, with `\\"task\\": \\"{task_id}\\"`.\\n"
            f"- Risk tier {tier['id']}: {tier['description']}.\\n"
        )
    if priorities and not previous:
        parts.append(f"**Decide close calls by these priorities, in order:** {', '.join(priorities)}.\\n")
    if not previous:
        parts.append(
            f"**You may decide alone:** {granted}. Anything else — a dependency, a schema change, "
            f"a public contract, a security trade-off — stops and returns the question.\\n"
        )

    if not previous:
        parts.append(
''')
patch(FLOW, '''        f"- Risk tier {tier['id']}: {tier['description']}.\\n"
    )
    parts.append(
        f"**Handoff.** Before returning, write `.aegis/runs/{task_id}/handoff.json`:\\n"
        f'`{{"task": "{task_id}", "summary": "...", "changed_files": [...], '
        f'"verification": [{{"command": "...", "result": "pass|fail|skipped"}}], '
        f'"deviations": [...], "registry_drafts": [...], "lease_expansion_request": [...]}}`\\n'
        f"Then return at most 300 words: what changed, how it was verified, deviations and why. "
        f"Never restate the code — the diff is already readable."
    )
''', '''        f"- Risk tier {tier['id']}: {tier['description']}.\\n"
        )
        # `agent` is required by the handoff schema — it is how the gate proves the reviewer
        # was someone else. The template omitted it, so a builder following the packet
        # literally wrote a handoff the gate rejects.
        parts.append(
            f"**Handoff.** Before returning, write `.aegis/runs/{task_id}/handoff.json`:\\n"
            f'`{{"task": "{task_id}", "agent": "<your agent type or model id>", "summary": "...", '
            f'"changed_files": [...], '
            f'"verification": [{{"command": "...", "result": "pass|fail|skipped"}}], '
            f'"deviations": [...], "registry_drafts": [...], "lease_expansion_request": [...]}}`\\n'
            f"Then return at most 300 words: what changed, how it was verified, deviations and why. "
            f"Never restate the code — the diff is already readable."
        )
''')
patch(FLOW, '''        "verification": verification,
        "protocols": protocols,
    }
    return text, meta
''', '''        "verification": verification,
        "protocols": protocols,
        "delta_from": delta_from,
    }
    return text, meta
''')
patch(MAIN, '''    p.add_argument("--json", action="store_true", help="emit metadata instead of the packet text")

''', '''    p.add_argument("--json", action="store_true", help="emit metadata instead of the packet text")
    p.add_argument("--delta-from", metavar="TASK",
                   help="for a builder kept warm: omit what is unchanged since that task's packet")

''')
patch(MAIN, '''        text, meta = flow.build_packet(ctx, args.id)
''', '''        text, meta = flow.build_packet(ctx, args.id, args.delta_from)
''')
print("task2 code patches applied")

# checks.codex_adapter serialises the description; checks.py had no json import.
patch(CHK, '''import datetime as _dt
import hashlib
import os
import re
''', '''import datetime as _dt
import hashlib
import json
import os
import re
''')
print("task2 json import applied")
