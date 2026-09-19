"""aegis — deterministic half of the Aegis SDD framework.

Everything that must happen *every* time lives here rather than in a prompt: it costs no
tokens, cannot be talked out of firing, and produces the same answer twice.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aegis_cli import checks, config, detect, flow, scaffold  # noqa: E402
from aegis_cli.core import AegisError, Ctx, Report, emit, find_root, read_json  # noqa: E402


CHECKS = {
    "structure": lambda ctx, args: checks.check_structure(ctx),
    "setup": lambda ctx, args: checks.check_setup(ctx),
    "pointers": lambda ctx, args: checks.check_pointers(ctx),
    "protocols": lambda ctx, args: checks.check_protocol_copies(ctx),
    "commands": lambda ctx, args: checks.check_commands(ctx),
    "registry": lambda ctx, args: checks.check_registry(ctx),
    "env": lambda ctx, args: checks.check_env(ctx, _scope(ctx, args)),
    "trace": lambda ctx, args: checks.check_trace(ctx, _scope(ctx, args), args.task),
    "requirements": lambda ctx, args: checks.check_requirements(ctx, args.feature, getattr(args, "planned", False)),
    "docs": lambda ctx, args: checks.check_docs(ctx, _scope(ctx, args), args.closing),
    "budget": lambda ctx, args: checks.check_budget(ctx),
    "drift": lambda ctx, args: config.check_drift(ctx),
    "banks": lambda ctx, args: config.lint_banks(ctx),
    "reviews": lambda ctx, args: flow.check_reviews(ctx, _require_task(args)),
    "handoff": lambda ctx, args: flow.check_handoff(ctx, _require_task(args)),
    "surfaces": lambda ctx, args: checks.check_surfaces(ctx, _scope(ctx, args)),
    "routes": lambda ctx, args: checks.check_routes(ctx, _scope(ctx, args)),
    "testing": lambda ctx, args: checks.check_testing_mandate(ctx, _scope(ctx, args)),
}


def _require_task(args) -> str:
    if not args.task:
        raise AegisError("this check needs --task <TASK-ID>")
    return args.task


def _scope(ctx: Ctx, args) -> list[str]:
    from aegis_cli.core import changed_files
    if args.task:
        manifest = checks.load_task(ctx, args.task)
        return changed_files(ctx, manifest.get("base_sha"))
    return changed_files(ctx, args.base)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis", description=__doc__.splitlines()[0])
    parser.add_argument("--root", help="project root (default: nearest .aegis/ or git root)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="detect, scaffold, compile and index in one step")
    p.add_argument("--mode", default="hybrid", choices=["interactive", "hybrid", "autonomous"])
    p.add_argument("--profile", choices=["S", "M", "L"], help="override the detected profile")
    p.add_argument("--force", action="store_true", help="overwrite existing files")
    p.add_argument("--yes", action="store_true",
                   help="accept every detected assumption, recording that you did")

    sub.add_parser("detect", help="report what this repository says about itself, and change nothing")

    p = sub.add_parser("interview", help="the questions still worth asking, batched and ordered")
    p.add_argument("--json", action="store_true", help="machine-readable, for an agent to drive")
    p.add_argument("--all", action="store_true", help="include questions deferred to phase 2")
    p = sub.add_parser("next", help="the single next action, computed from state on disk")
    p.add_argument("--run", action="store_true",
                   help="execute it when it is a CLI action, so the loop needs no memory")

    p = sub.add_parser("scaffold", help="create the .aegis/ skeleton without detection")
    p.add_argument("--profile", default="S", choices=["S", "M", "L"])
    p.add_argument("--doc-profile", default="api-service", choices=sorted(config.DOC_PROFILES))
    p.add_argument("--force", action="store_true", help="overwrite existing files")

    sub.add_parser("compile", help="answers.json -> .aegis/generated/* (idempotent)")

    p = sub.add_parser("answer", help="record an interview answer and recompile")
    p.add_argument("qid")
    p.add_argument("value", help="JSON value; bare strings are accepted")
    p.add_argument("--source", default="human", choices=["human", "detected", "default", "heuristic"])
    p.add_argument("--rationale", default="")
    sub.add_parser("index", help="regenerate derived indexes")
    sub.add_parser("migrate", help="bring a project up to this version of the framework")
    p = sub.add_parser("land", help="run the full merge gate at HEAD, move the mainline to it, mark gated tasks merged")
    p = sub.add_parser("git-hooks", help="install the git-level gate: every commit in this "
                                        "checkout, not only the ones Claude Code runs")
    p.add_argument("action", choices=["install"])
    p.add_argument("--force", action="store_true",
                   help="replace a pre-commit or pre-push hook this command did not write")
    p = sub.add_parser("diff", help="the task's diff, over exactly the files its digest covers")
    p.add_argument("id")
    sub.add_parser("fmt", help="canonicalise and sort the registries")
    sub.add_parser("status", help="one-screen project state")
    sub.add_parser("budget", help="measured token load per role and protocol")
    sub.add_parser("metrics", help="aggregate run artefacts: lens acceptance, rounds, reopened findings")

    p = sub.add_parser("check", help="run one deterministic check")
    p.add_argument("name", choices=sorted(CHECKS) + ["all"])
    p.add_argument("--task")
    p.add_argument("--base", help="git ref to diff against")
    p.add_argument("--feature")
    p.add_argument("--closing", action="store_true", help="treat documentation gaps as blocking")
    p.add_argument("--planned", action="store_true",
                   help="count planned tasks as coverage; for decomposition, not for the gate")

    p = sub.add_parser("gate", help="staged gate: bootstrap | task | merge")
    p.add_argument("--stage", default="task", choices=["bootstrap", "task", "merge"])
    p.add_argument("--task")
    p.add_argument("--no-run", action="store_true", help="skip project commands; run checks only")

    p = sub.add_parser("task", help="task manifests (the write lease)")
    tsub = p.add_subparsers(dest="task_command", required=True)
    n = tsub.add_parser("new")
    n.add_argument("id")
    n.add_argument("--feature", required=True)
    n.add_argument("--objective", required=True)
    n.add_argument("--owns", required=True, help="comma-separated globs; exclusive write lease")
    n.add_argument("--requirements", default="", help="comma-separated R-* ids")
    n.add_argument("--kinds", default="code", help=f"comma-separated: {', '.join(flow.CHANGE_KINDS)}")
    n.add_argument("--acceptance", default="", help="semicolon-separated criteria")
    n.add_argument("--reads", default="")
    n.add_argument("--size", default="M", choices=["S", "M", "L"])
    s = tsub.add_parser("status")
    s.add_argument("id")
    s.add_argument("value")
    tsub.add_parser("list")
    c = tsub.add_parser("claim", help="start a task: mark it building, fix its base, record the packet cost")
    c.add_argument("id")

    p = sub.add_parser("packet", help="emit the task packet")
    p.add_argument("id")
    p.add_argument("--json", action="store_true", help="emit metadata instead of the packet text")

    p = sub.add_parser("lens", help="lens planning and reports")
    lsub = p.add_subparsers(dest="lens_command", required=True)
    lp = lsub.add_parser("plan")
    lp.add_argument("id")
    lp.add_argument("--closing", action="store_true")
    lr = lsub.add_parser("record", help="read a lens report as JSON on stdin")
    lr.add_argument("id")
    lr.add_argument("--lens", required=True, help="which lens produced the report; attached by the caller")
    lr.add_argument("--reviewer", help="who produced the report; the caller knows, the model need not echo it")
    lr.add_argument("--digest", help="the digest the reviewer was given; attached by the caller")
    ld = lsub.add_parser("disposition")
    ld.add_argument("id")
    ld.add_argument("finding")
    ld.add_argument("value", choices=["fixed", "false-positive", "waived", "deferred"])
    ld.add_argument("--reason", default="")
    ld.add_argument("--by", required=True, help="who stands behind this disposition — a person, for a finding that came back")

    p = sub.add_parser("docs", help="documentation bookkeeping")
    dsub = p.add_subparsers(dest="docs_command", required=True)
    da = dsub.add_parser("attest", help="record that a diagram matches its sources now")
    da.add_argument("id", nargs="?")
    da.add_argument("--by", required=True, help="who is making the claim")
    da.add_argument("--note", default="", help="what changed, in one line")

    return parser


def command_specs() -> dict[str, set[str]]:
    """Every command path the CLI accepts, with the options it requires.

    `{"lens record": {"--lens"}, "task new": {"--feature", ...}, "status": set()}`. Published so
    that `aegis check commands` can hold a document to what the parser actually accepts: two
    shipped protocols quoted `aegis lens record <TASK>` without `--lens`, which cannot run.
    """
    specs: dict[str, set[str]] = {}

    def walk(parser, prefix: str) -> None:
        required = {action.option_strings[0] for action in parser._actions
                    if action.option_strings and action.required}
        if prefix:
            specs[prefix] = required
        for action in parser._actions:
            choices = getattr(action, "choices", None)
            if action.option_strings or not isinstance(choices, dict):
                continue
            for name, sub in choices.items():
                walk(sub, f"{prefix} {name}".strip())

    walk(build_parser(), "")
    return specs


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.root and not os.path.isdir(args.root):
        raise AegisError(f"--root {args.root!r} is not a directory")
    ctx = Ctx(find_root(args.root))

    if args.command == "detect":
        emit(json.dumps(detect.detect(ctx), indent=2, ensure_ascii=False))
        return 0

    if args.command == "diff":
        emit(flow.task_diff(ctx, args.id))
        return 0


    if args.command == "interview":
        plan = config.interview(ctx, include_deferred=args.all)
        if args.json:
            emit(json.dumps(plan, indent=2, ensure_ascii=False))
            return 0
        if plan["confirm"]:
            emit(f"Read from the repository — confirm as one screen ({len(plan['confirm'])} items):")
            for row in plan["confirm"]:
                emit(f"  {row['id']} = {json.dumps(row['value'], ensure_ascii=False)}"
                     f"   ({row['evidence']})")
            emit("")
        if not plan["batches"]:
            emit("Nothing left to ask. Setup is complete.")
            return 0
        emit(f"{sum(len(b) for b in plan['batches'])} question(s) left, "
             f"in {len(plan['batches'])} batch(es); irreversible ones first.\n")
        for i, batch in enumerate(plan["batches"], 1):
            emit(f"Batch {i}:")
            for q in batch:
                mark = " [irreversible]" if q["irreversible"] else ""
                emit(f"  {q['ask']}{mark}")
                if q["options"]:
                    emit(f"    options: {', '.join(str(o) for o in q['options'])}")
                if q["default"] is not None:
                    emit(f"    default: {json.dumps(q['default'], ensure_ascii=False)}")
                emit(f"    why:     {q['why']}")
                emit(f"    record:  {q['record']}")
            emit("")
        return 0

    if args.command == "next":
        def show(step: dict) -> None:
            emit(f"next: {step['do']}  [{step['who']}]")
            emit(f"  why: {step['why']}")
            if step.get("command"):
                emit(f"  run: {step['command']}")
            if step.get("note"):
                emit(f"  then: {step['note']}")

        step = flow.next_action(ctx)
        show(step)
        if not args.run:
            return 0
        # Run consecutive CLI steps without being asked again. Only steps marked `cli` —
        # self-contained `aegis …` commands — qualify: a step that needs a dispatch or a
        # person is printed and left alone, because auto-running an editor or an agent would
        # make this a different kind of tool than it claims to be. The old test parsed a
        # trailing shell comment out of the command; the instruction is now its own field.
        seen: set[str] = set()
        while True:
            command = step.get("command") or ""
            if step["who"] != "cli" or not command.startswith("aegis "):
                emit("  (stopping here: this step needs "
                     + ("you" if step["who"] == "human" else "an agent") + ")")
                return 0
            if command in seen:
                emit("  (stopping here: the same step came round again — it is not advancing)")
                return 1
            seen.add(command)
            emit("")
            code = main((["--root", args.root] if args.root else []) + command.split()[1:])
            if code != 0:
                return code
            step = flow.next_action(ctx)
            emit("")
            show(step)

    if args.command == "init":
        summary = scaffold.initialise(ctx, args.mode, args.profile, args.force, args.yes)
        emit(f"Aegis initialised — profile {summary['profile']}, "
             f"{summary['project_type']}, {'existing codebase' if summary['brownfield'] else 'greenfield'}")
        if summary["packages"]:
            emit("\ndetected packages and the commands the gate will run:")
            for name, spec in sorted(summary["packages"].items()):
                commands = ", ".join(f"{k}=`{v}`" for k, v in spec.items() if k != "paths") or "(none found)"
                emit(f"  {name}: {commands}")
        else:
            emit("\nno build manifest found — set commands before the gate can verify anything:")
            emit('  aegis answer q.core.commands \'{"app": {"paths": ["src/**"], "test": "..."}}\'')
        env_n, route_n = summary["surfaces"].get("env", 0), summary["surfaces"].get("routes", 0)
        if env_n or route_n:
            emit(f"\nobserved: {env_n} environment variable{'' if env_n == 1 else 's'}, "
                 f"{route_n} route{'' if route_n == 1 else 's'} "
                 "— candidates, not facts; `aegis detect` shows each with its evidence path")
        if summary.get("accepted"):
            emit("\nassumptions accepted via --yes; they remain listed in .aegis/answers.json")
        if summary["ledger"]:
            emit(f"\n{len(summary['ledger'])} assumption(s) need a human before phase 3:")
            for row in summary["ledger"]:
                emit(f"  {row['question']} = {json.dumps(row['value'], ensure_ascii=False)[:60]}"
                     f"  ({row['note']})")
        emit("\nnext:")
        emit("  1. write .aegis/constitution.md by hand — it is the one file agents never touch")
        emit("  2. aegis gate --stage bootstrap")
        emit("  3. aegis next          # tells you the next action at any point")
        return 0

    if args.command == "scaffold":
        created = scaffold.scaffold(ctx, args.profile, args.doc_profile, args.force)
        emit("created:\n" + "\n".join(f"  {c}" for c in created) if created else "nothing to create")
        emit("\nnext: edit .aegis/constitution.md by hand, then `aegis compile && aegis gate --stage bootstrap`")
        return 0

    if args.command == "answer":
        try:
            value = json.loads(args.value)
        except json.JSONDecodeError:
            value = args.value
        config.set_answer(ctx, args.qid, value, args.source, args.rationale)
        changed, _ = config.materialize(ctx)
        emit(f"{args.qid} = {json.dumps(value, ensure_ascii=False)}")
        emit("recompiled:\n" + "\n".join(f"  {c}" for c in changed) if changed else "configuration unchanged")
        return 0

    if args.command == "compile":
        changed, _out = config.materialize(ctx)
        emit("compiled:\n" + "\n".join(f"  {c}" for c in changed) if changed else "already current")
        return 0

    if args.command == "land":
        for line in flow.land(ctx):
            emit(line)
        return 0
    if args.command == "git-hooks":
        results = scaffold.install_git_hooks(ctx, force=args.force)
        if not results:
            die("not a git repository, so there is nowhere to install a hook")
        for name, outcome in sorted(results.items()):
            emit(f"{name}: {outcome}")
        emit("`git commit --no-verify` still skips a git hook; CI runs the same gate and does not.")
        return 0

    if args.command == "migrate":
        # Deliberately a diagnostic, not a migration engine. Registry schemas have never
        # changed incompatibly; building a framework to replay migrations that do not exist
        # would be the ceremony this project spends its effort avoiding. What a project
        # upgrading the framework actually needs is: recompile, re-canonicalise, and a list
        # of the entries a human must now touch — each with the field that broke.
        baselined = scaffold.record_baseline_if_missing(ctx)
        if baselined is not None:
            emit(f"recorded the adoption baseline: {baselined} uncommitted file(s), excluding "
                 "paths leased to open tasks")
        renamed = scaffold.complete_baseline_renames(ctx)
        if renamed:
            emit("adoption baseline: recorded as absent the source side of a pending rename "
                 "whose destination it already holds: " + ", ".join(renamed))
        changed, _ = config.materialize(ctx)
        # Repair overwritten pointers: re-append the import without touching the rest of
        # whatever the agent wrote.
        for rel, marker, patch in (
            ("CLAUDE.md", "@.aegis/generated/rules.md",
             "\n@.aegis/generated/rules.md\n<!-- aegis:pointer -->\n"),
            ("AGENTS.md", ".aegis/generated/rules.md",
             "\n## Aegis\n\nBefore working here, read `.aegis/generated/rules.md` — the "
             "compiled agent rules.\n<!-- aegis:pointer -->\n"),
        ):
            path = os.path.join(ctx.root, rel)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    body = fh.read()
                if marker not in body:
                    # Append, never rewrite: the rest of the file is whatever the team or an
                    # agent put there, and repairing the import must not destroy it.
                    with open(path, "a", encoding="utf-8") as fh:
                        fh.write(patch)
                    emit(f"repaired pointer in {rel}")
        revendored = scaffold.vendor_protocols(ctx)
        formatted = flow.fmt(ctx)
        flow.build_indexes(ctx)
        emit(f"recompiled: {', '.join(changed) or 'nothing'}")
        emit(f"protocols refreshed: {len(revendored)}")
        emit(f"re-canonicalised: {', '.join(formatted) or 'nothing'}")
        report = checks.check_registry(ctx)
        failures = [f for f in report.findings if f.severity == "fail"]
        if not failures:
            emit("registries validate against the current schemas — nothing to migrate")
            return 0
        emit(f"\n{len(failures)} registry entr{'y' if len(failures) == 1 else 'ies'} need a human:")
        for finding in failures:
            emit(f"  {finding.path}: {finding.message}")
        emit("\nEach is a field the current schema requires and the entry lacks. Fill it in; "
             "there is no safe default the framework could invent for you.")
        return 1

    if args.command == "index":
        written = flow.build_indexes(ctx)
        emit("regenerated:\n" + "\n".join(f"  {w}" for w in written) if written else "indexes already current")
        return 0

    if args.command == "fmt":
        changed = flow.fmt(ctx)
        emit("formatted:\n" + "\n".join(f"  {c}" for c in changed) if changed else "already canonical")
        return 0

    if args.command == "status":
        emit(flow.status(ctx))
        return 0

    if args.command == "budget":
        report = checks.check_budget(ctx)
        emit(report.render("budget"))
        return 1 if report.failed else 0

    if args.command == "metrics":
        emit(json.dumps(flow.metrics(ctx), indent=2, ensure_ascii=False))
        return 0

    if args.command == "check":
        if args.name == "all":
            report = Report()
            for name in ("structure", "protocols", "commands", "banks", "drift", "registry",
                         "budget", "requirements"):
                report.extend(CHECKS[name](ctx, args))
            if args.task:
                for name in ("env", "surfaces", "routes", "testing", "trace", "docs", "handoff", "reviews"):
                    report.extend(CHECKS[name](ctx, args))
        else:
            report = CHECKS[args.name](ctx, args)
        report = checks.apply_waivers(ctx, report)
        emit(report.render(f"check {args.name}"))
        return 1 if report.failed else 0

    if args.command == "gate":
        import time
        _gate_started = time.monotonic()
        report = flow.gate(ctx, args.stage, args.task, run_commands=not args.no_run)
        flow._record_gate(ctx, args.stage, args.task, report, _gate_started)
        emit(report.render(f"gate {args.stage}"))
        if report.failed:
            emit("\nGATE FAILED — the findings above are blocking.")
            return 1
        emit("\ngate passed")
        return 0

    if args.command == "task":
        if args.task_command == "new":
            manifest = flow.task_new(
                ctx, args.id,
                feature=args.feature,
                objective=args.objective,
                owns=[g.strip() for g in args.owns.split(",") if g.strip()],
                requirements=[r.strip() for r in args.requirements.split(",") if r.strip()],
                kinds=[k.strip() for k in args.kinds.split(",") if k.strip()],
                acceptance=[a.strip() for a in args.acceptance.split(";") if a.strip()],
                reads=[r.strip() for r in args.reads.split(",") if r.strip()],
                size=args.size,
            )
            emit(f"created .aegis/runs/{args.id}/manifest.json")
            emit(f"  lease: {', '.join(manifest['owns'])}")
            return 0
        if args.task_command == "claim":
            claimed = flow.task_claim(ctx, args.id)
            emit(f"claimed {args.id}: lease declared, status {claimed['status']}, "
                 f"packet ≈{claimed['packet_tokens']} tokens (budget {claimed['budget']})")
            if claimed["over_budget"]:
                emit("  OVER BUDGET — narrow the task or trim the spec excerpt")
            emit(f"  then: aegis packet {args.id}, and dispatch aegis-builder with that text")
            return 0
        if args.task_command == "status":
            flow.task_status(ctx, args.id, args.value)
            emit(f"{args.id} -> {args.value}")
            return 0
        for task in checks.active_tasks(ctx):
            emit(f"{task['id']:<20} {task.get('status', '?'):<10} {task.get('objective', '')[:60]}")
        return 0

    if args.command == "packet":
        text, meta = flow.build_packet(ctx, args.id)
        if args.json:
            emit(json.dumps(meta, indent=2, ensure_ascii=False))
            return 0
        emit(text)
        over = meta["tokens"] > meta["budget"]
        sys.stderr.write(
            f"\n[packet ≈{meta['tokens']} tokens, budget {meta['budget']}, risk tier {meta['risk_tier']}]"
            + ("  OVER BUDGET — narrow the task or trim the spec excerpt\n" if over else "\n")
        )
        return 1 if over else 0

    if args.command == "lens":
        if args.lens_command == "plan":
            plan = flow.lens_plan(ctx, args.id, args.closing)
            emit(json.dumps(plan, indent=2, ensure_ascii=False))
            return 0
        if args.lens_command == "record":
            raw = sys.stdin.read()
            try:
                payload = json.loads(raw)
            except RecursionError as exc:
                raise AegisError(
                    "the lens report on stdin is nested too deeply to parse. "
                    "A lens report is a flat object with a findings array; this is not one."
                ) from exc
            except json.JSONDecodeError as exc:
                preview = raw.strip()[:120] or "(empty input)"
                raise AegisError(
                    f"the lens report on stdin is not valid JSON ({exc.msg} at line {exc.lineno}).\n"
                    f"  got: {preview}\n"
                    "  A lens must return only the JSON object — no prose before or after it."
                ) from exc
            # The transport envelope belongs to the transport. A model echoing provenance
            # is a failure mode, not a proof.
            if args.reviewer:
                payload["reviewer"] = args.reviewer
            if args.digest:
                payload["diff_digest"] = args.digest
            record = flow.lens_record(ctx, args.id, payload, args.lens)
            blocking = [f for f in record["findings"]
                        if f["severity"] >= 3 and f["disposition"] == "open"]
            emit(f"recorded {record['lens']} round {record['round']}: verdict {record['verdict']}, "
                 f"{len(blocking)} blocking open")
            for finding in blocking:
                emit(f"  {finding['id']} sev{finding['severity']} {finding.get('path') or ''} — {finding['message'][:100]}")
            if record["reopened"]:
                emit(f"  REOPENED: {', '.join(record['reopened'])} — simplify the mechanism, do not patch again")
            return 0
        finding = flow.disposition(ctx, args.id, args.finding, args.value, args.reason, args.by)
        emit(f"{finding['id']} -> {finding['disposition']}")
        return 0

    if args.command == "docs":
        touched = flow.docs_attest(ctx, args.id, args.by, args.note)
        emit(f"attested by {args.by}: " + (", ".join(touched) if touched else "nothing changed"))
        return 0

    raise AegisError(f"unhandled command {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AegisError as exc:
        sys.stderr.write(f"aegis: {exc}\n")
        raise SystemExit(2)
    except KeyboardInterrupt:
        raise SystemExit(130)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        # A raw traceback tells an agent nothing it can act on and tells a human that the
        # tool is broken rather than that the input was. Set AEGIS_DEBUG=1 to see it.
        if os.environ.get("AEGIS_DEBUG") == "1":
            raise
        sys.stderr.write(
            f"aegis: unexpected {type(exc).__name__}: {exc}\n"
            "       this is a bug in aegis, not in your project. "
            "Re-run with AEGIS_DEBUG=1 for the traceback.\n"
        )
        raise SystemExit(3)
