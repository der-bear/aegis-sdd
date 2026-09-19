"""The configuration compiler: answers.json + question banks -> generated/*.json.

This is the one place where interview answers turn into framework configuration. It is
a pure function of (answers, banks, compiler version): same inputs always produce the
same bytes. That property is what makes `aegis check drift` meaningful and what lets a
human review a configuration change as a diff instead of an archaeology exercise.

Two rules hold the design together:

  * The compiler never writes outside `.aegis/generated/`. `constitution.md` is authored
    by a human and only *references* generated policy, so "the constitution is
    human-owned" and "configuration is regenerated" stop contradicting each other.
  * Every question declares a `writes` target drawn from a closed registry below. A
    question with no configuration consequence, or with an unknown target, fails
    bank-lint rather than silently doing nothing.
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Any

from . import detect
from .core import (
    AegisError,
    Ctx,
    Report,
    asset_dirs,
    canonical,
    read_json,
    read_text,
    write_json,
    write_text,
)

COMPILER_VERSION = 3  # 3: adoption baseline compiled into capabilities
# Targets several questions contribute to rather than overwrite. Core asks about frozen
# zones once; the brownfield pack asks again with the codebase in view, and both answers
# are real. Everywhere else, two writers means one of them is silently discarded.
MERGED_TARGETS = {"standards.frozen_zones"}

# --------------------------------------------------------------- writable targets

# artifact -> field -> (kind, description). A `writes` value outside this table is a
# bank-lint failure, which is what stops packs from inventing configuration silently.
TARGETS: dict[str, dict[str, str]] = {
    "policy": {
        "profile": "S | M | L framework profile",
        "mode": "init interview mode",
        "autonomy_limits": "decision classes agents may take without a human",
        "testing_mandate": "how tests are required to accompany code",
        "nfr_priorities": "ranked non-functional priorities",
        "lens_strictness": "minimal | standard | strict",
        "parallel_builders": "maximum concurrent builders",
        "refinement_rounds": "maximum lens/fix rounds before escalation",
        "pii": "whether the system carries personal data",
        "legacy_baseline": "ratchet-from-today | fix-before-adopting",
        "mainline": "the branch work lands on, when it is not main or master",
    },
    "doc_profile": {
        "kind": "web-saas | api-service | data-etl | library | stateful",
        "required": "documentation artifacts the profile mandates",
        "diagram_tool": "mermaid | structurizr",
        "frontend_model": "spa | ssr | hybrid",
    },
    "capabilities": {
        "packages": "package name -> command set",
        "default_package": "package used when a change matches no other",
    },
    "standards": {
        "api_errors": "error envelope convention",
        "schema_evolution": "how data contracts may change",
        "frozen_zones": "paths agents must not modify",
        "tenancy": "single-tenant | multi-tenant-shared-db | multi-tenant-isolated",
        "compatibility": "public API compatibility promise",
        "recovery": "what must survive a restart",
    },
}

# Profile defaults. Questions override these; the table exists so that a profile choice
# alone yields a complete, runnable configuration.
# Fields a profile owns. A question may override one only when it was actually answered;
# letting its declared default win turned `--profile L` back into standard strictness.
PROFILE_OWNED = {"lens_strictness", "parallel_builders", "refinement_rounds"}

PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "S": {
        "parallel_builders": 1,
        "refinement_rounds": 2,
        "lens_strictness": "minimal",
        "registries": ["env", "integrations"],
        "self_governance": [],
    },
    "M": {
        "parallel_builders": 2,
        "refinement_rounds": 3,
        "lens_strictness": "standard",
        "registries": ["env", "integrations", "events", "flags", "diagrams"],
        "self_governance": ["retro"],
    },
    "L": {
        "parallel_builders": 3,
        "refinement_rounds": 3,
        "lens_strictness": "strict",
        "registries": ["env", "integrations", "events", "flags", "diagrams"],
        "self_governance": ["retro", "audit"],
    },
}

# Which lens runs when. Selection is computed from machine-readable change kinds, never
# guessed from prose: see flow.lens_plan.
# Three lenses, not five. Documentation obligations are checked deterministically by
# `aegis check docs` and `check registry`, which is cheaper and does not vary between runs;
# architecture and chain-consistency were one question asked at two moments, so they are one
# lens with two modes. Every lens left here has a tool set or a failure mode the others
# cannot cover.
LENS_MATRIX: dict[str, dict[str, list[str]]] = {
    "minimal": {
        "always": ["correctness"],
        "route": ["security"],
        "auth": ["security"],
        "dependency": ["security"],
        "data-migration": ["security"],
        "feature-close": ["design"],
    },
    "standard": {
        "always": ["correctness"],
        "route": ["security"],
        "auth": ["security"],
        "dependency": ["security"],
        "contract": ["design"],
        "cross-module": ["design"],
        "data-migration": ["security", "design"],
        "money": ["security", "design"],
        "concurrency": ["design"],
        "feature-close": ["design"],
    },
    "strict": {
        "always": ["correctness", "security"],
        "contract": ["design"],
        "cross-module": ["design"],
        "auth": ["design"],
        "data-migration": ["design"],
        "money": ["design"],
        "concurrency": ["design"],
        "feature-close": ["design"],
    },
}

# Risk tier decides how much verification a change earns. Borrowed from a production
# multi-agent build where a flat "run every lens" policy proved unaffordable.
RISK_TIERS: dict[str, dict[str, Any]] = {
    "A": {
        "match_change_kinds": ["auth", "data-migration", "money", "concurrency"],
        "review_rounds": 2,
        "independent_reviewer": True,
        "description": "irreversible or authority-bearing; builder is never final reviewer",
    },
    "B": {
        "match_change_kinds": ["route", "contract", "cross-module", "dependency"],
        "review_rounds": 1,
        "independent_reviewer": True,
        "description": "standard feature work behind a contract",
    },
    "C": {
        "match_change_kinds": ["code", "docs", "test"],
        "review_rounds": 1,
        "independent_reviewer": False,
        "description": "mechanical; batched review is acceptable",
    },
}

DOC_PROFILES: dict[str, dict[str, Any]] = {
    "web-saas": {
        "required": ["context-diagram", "container-diagram", "erd", "api-reference", "sequence-critical"],
        "generated": ["erd", "api-reference"],
    },
    "api-service": {
        "required": ["context-diagram", "api-reference", "erd"],
        "generated": ["erd", "api-reference"],
    },
    "data-etl": {
        "required": ["dataflow", "lineage", "schema-registry"],
        "generated": ["schema-registry"],
    },
    "library": {
        "required": ["api-reference", "usage-examples"],
        "generated": ["api-reference"],
    },
    "stateful": {
        "required": ["state-machine", "context-diagram"],
        "generated": [],
    },
}


# ------------------------------------------------------------------ `when` grammar

_TOKEN = re.compile(
    r"\s*(\(|\)|and\b|or\b|not\b|in\b|==|!=|detected\(|[A-Za-z0-9_.\-]+|\[|\]|,)"
)


class WhenSyntaxError(AegisError):
    pass


def _tokenize(expr: str) -> list[str]:
    pos, out = 0, []
    while pos < len(expr):
        m = _TOKEN.match(expr, pos)
        if not m:
            if expr[pos:].strip() == "":
                break
            raise WhenSyntaxError(f"cannot parse `when` at: {expr[pos:]!r}")
        out.append(m.group(1))
        pos = m.end()
    return out


def eval_when(expr: str | None, env: dict[str, Any], detected: dict[str, Any]) -> bool:
    """Evaluate a closed boolean grammar. No eval(), no arbitrary attribute access.

    Grammar:  expr := term (('and'|'or') term)*
              term := 'not' term | '(' expr ')' | comparison | 'detected(' name ')'
              comparison := ident ('=='|'!='|'in') value
    """
    if not expr or expr.strip() in ("", "true"):
        return True
    tokens = _tokenize(expr)
    pos = 0

    def peek() -> str | None:
        return tokens[pos] if pos < len(tokens) else None

    def take() -> str:
        nonlocal pos
        if pos >= len(tokens):
            raise WhenSyntaxError(f"unexpected end of `when`: {expr!r}")
        pos += 1
        return tokens[pos - 1]

    def parse_value() -> Any:
        tok = take()
        if tok == "[":
            items = []
            while peek() != "]":
                items.append(take().strip("'\""))
                if peek() == ",":
                    take()
            take()
            return items
        return tok.strip("'\"")

    def parse_term() -> bool:
        tok = peek()
        if tok == "not":
            take()
            return not parse_term()
        if tok == "(":
            take()
            value = parse_expr()
            if take() != ")":
                raise WhenSyntaxError(f"unbalanced parentheses in {expr!r}")
            return value
        if tok == "detected(":
            take()
            name = take()
            if take() != ")":
                raise WhenSyntaxError(f"detected(...) not closed in {expr!r}")
            # `False` is a detection result meaning "looked, and it is not there". Treating
            # it as present made `detected(brownfield)` true on a greenfield repository.
            return name in detected and detected[name] not in (None, "", [], {}, False)
        ident = take()
        op = take()
        rhs = parse_value()
        lhs = env.get(ident)
        if op == "==":
            return lhs == rhs
        if op == "!=":
            return lhs != rhs
        if op == "in":
            return lhs in (rhs if isinstance(rhs, list) else [rhs])
        raise WhenSyntaxError(f"unsupported operator {op!r} in {expr!r}")

    def parse_and() -> bool:
        value = parse_term()
        while peek() == "and":
            take()
            value = parse_term() and value
        return value

    def parse_expr() -> bool:
        # `and` binds tighter than `or`, as everywhere else. Flat left-associativity read
        # `a or b and c` as `(a or b) and c`, quietly inverting conditions in question banks.
        value = parse_and()
        while peek() == "or":
            take()
            value = parse_and() or value
        return value

    result = parse_expr()
    if pos != len(tokens):
        raise WhenSyntaxError(f"trailing tokens in `when`: {expr!r}")
    return result


# ------------------------------------------------------------------- loading banks


def bank_dirs(ctx: Ctx) -> list[str]:
    """Project banks win over framework banks with the same question id."""
    return asset_dirs(ctx, "interview")


def load_banks(ctx: Ctx) -> dict[str, dict]:
    banks: dict[str, dict] = {}
    for directory in bank_dirs(ctx):
        for dirpath, _dirnames, filenames in os.walk(directory):
            for name in sorted(filenames):
                if not name.endswith(".json"):
                    continue
                full = os.path.join(dirpath, name)
                bank = read_json(full)
                bank["_path"] = os.path.relpath(full, ctx.root)
                banks[bank.get("id") or name[:-5]] = bank
    return banks


def resolve_questions(banks: dict[str, dict], selected: list[str]) -> list[dict]:
    """Flatten selected banks, following `extends`, later definitions overriding earlier."""
    seen: dict[str, dict] = {}
    order: list[str] = []

    def visit(bank_id: str, stack: tuple[str, ...] = ()) -> None:
        if bank_id in stack:
            raise AegisError(f"circular bank extends: {' -> '.join(stack + (bank_id,))}")
        bank = banks.get(bank_id)
        if not bank:
            raise AegisError(f"unknown question bank: {bank_id}")
        parent = bank.get("extends")
        if parent:
            visit(parent, stack + (bank_id,))
        for question in bank.get("questions", []):
            qid = question["id"]
            if qid not in seen:
                order.append(qid)
            merged = dict(question)
            merged["_bank"] = bank_id
            seen[qid] = merged

    for bank_id in selected:
        visit(bank_id)
    return [seen[qid] for qid in order]


def select_banks(answers: dict) -> list[str]:
    banks = ["core"]
    ptype = _value(answers, "q.core.project-type")
    if ptype:
        banks.append(f"project-type/{ptype}")
    if answers.get("detected", {}).get("brownfield"):
        banks.append("context/brownfield")
    return banks + list(answers.get("extra_banks", []))


# ----------------------------------------------------------------------- bank lint


AUTONOMY_RE = re.compile(r"^(always-ask|auto-default|detect-only|auto-if-detected:0\.\d+)$")


def auto_threshold(question: dict) -> float | None:
    """The confidence at which this question's detected answer is taken without asking.

    None when the question does not resolve from detection. Reading the number the question
    declares is what makes `auto-if-detected:0.9` mean anything: a constant in the code made
    every such declaration decorative.
    """
    match = re.match(r"^auto-if-detected:(0\.\d+)$", str(question.get("autonomy") or ""))
    return float(match.group(1)) if match else None
VALID_KINDS = {"single", "multi", "scale", "free", "confirm"}
VALID_SEVERITY_RE = re.compile(r"^(blocking|optional|deferrable:[a-z0-9\-]+)$")


def lint_banks(ctx: Ctx) -> Report:
    """Static guarantees that make `--mode autonomous` honest.

    A pack reaches autonomous only when every question in it has a resolution path that
    needs no human: a declared default, or a detect rule. Without this check, autonomous
    mode is a promise the interview cannot keep.
    """
    report = Report()
    banks = load_banks(ctx)
    if not banks:
        report.warn("bank-lint", "no question banks found", hint="ship interview/ with the plugin")
        return report

    seen: dict[str, str] = {}
    writers: dict[str, list[str]] = {}
    for bank_id, bank in sorted(banks.items()):
        where = bank.get("_path", bank_id)
        parent = bank.get("extends")
        if parent and parent not in banks:
            report.fail("bank-lint", f"{bank_id} extends unknown bank {parent!r}", where)
        for question in bank.get("questions", []):
            qid = question.get("id", "<missing id>")
            if qid in seen and seen[qid] != bank_id and not question.get("overrides"):
                report.fail(
                    "bank-lint",
                    f"duplicate question id {qid} (also in {seen[qid]})",
                    where,
                    hint='set "overrides": true when the redefinition is intentional',
                )
            seen[qid] = bank_id

            autonomy = str(question.get("autonomy") or "")
            detect_key = question.get("detect")
            if autonomy.startswith("auto-if-detected") and not detect_key:
                report.fail("bank-lint", f"{qid} is auto-if-detected but names no detect key", where,
                            hint="name a fact detection produces, or make it auto-default")
            if detect_key and detect_key not in detect.DETECT_KEYS:
                # The declaration was decorative: two shipped questions named facts the scanner
                # never produced, so `auto-if-detected` on them could never fire.
                report.fail("bank-lint",
                            f"{qid} detects {detect_key!r}, which detection never produces", where,
                            hint=f"detection produces: {', '.join(sorted(detect.DETECT_KEYS))}")

            writes = question.get("writes")
            if not writes:
                report.fail(
                    "bank-lint", f"{qid} has no `writes` target", where,
                    hint="a question with no configuration consequence must be removed",
                )
            else:
                artifact, _, field = writes.partition(".")
                if artifact not in TARGETS or field not in TARGETS.get(artifact, {}):
                    report.fail(
                        "bank-lint", f"{qid} writes unknown target {writes!r}", where,
                        hint=f"known artifacts: {', '.join(sorted(TARGETS))}",
                    )
                else:
                    writers.setdefault(writes, []).append(qid)

            autonomy = question.get("autonomy", "")
            if not AUTONOMY_RE.match(autonomy):
                report.fail("bank-lint", f"{qid} has invalid autonomy {autonomy!r}", where)
            elif autonomy != "always-ask":
                has_default = "default" in question
                has_detect = bool(question.get("detect"))
                if not (has_default or has_detect):
                    report.fail(
                        "bank-lint",
                        f"{qid} is auto-resolvable but declares neither default nor detect",
                        where,
                        hint="autonomous mode cannot resolve it; add a default or make it always-ask",
                    )

            kind = question.get("kind")
            if kind not in VALID_KINDS:
                report.fail("bank-lint", f"{qid} has invalid kind {kind!r}", where)
            if kind in ("single", "multi") and not question.get("options"):
                report.fail("bank-lint", f"{qid} is {kind} but lists no options", where)
            default = question.get("default")
            options = question.get("options") or []
            if kind == "single" and default is not None and options and default not in options:
                report.fail("bank-lint", f"{qid} default {default!r} is not among its options", where)
            if kind == "multi" and isinstance(default, list) and options:
                unknown = [d for d in default if d not in options]
                if unknown:
                    report.fail("bank-lint", f"{qid} default contains unknown options {unknown}", where)

            severity = question.get("severity", "")
            if not VALID_SEVERITY_RE.match(severity):
                report.fail("bank-lint", f"{qid} has invalid severity {severity!r}", where)
            if not question.get("rationale"):
                report.warn("bank-lint", f"{qid} has no rationale shown to the user", where)
            try:
                eval_when(question.get("when"), {}, {})
            except WhenSyntaxError as exc:
                report.fail("bank-lint", f"{qid}: {exc}", where)

    for target, qids in sorted(writers.items()):
        if len(qids) > 1 and target not in MERGED_TARGETS:
            report.warn(
                "bank-lint",
                f"{len(qids)} questions write {target}: {', '.join(qids)}",
                hint="last one wins; confirm the precedence is intended",
            )
    report.note(f"{len(seen)} questions across {len(banks)} banks")
    return report


# ------------------------------------------------------------------------ compile


def _value(answers: dict, qid: str, fallback: Any = None) -> Any:
    entry = answers.get("resolved", {}).get(qid)
    if isinstance(entry, dict):
        return entry.get("value", fallback)
    return entry if entry is not None else fallback


def compile_config(ctx: Ctx, answers: dict) -> dict[str, Any]:
    """Pure: (answers, banks, COMPILER_VERSION) -> generated artifacts as a dict of
    relative path -> content. The caller decides whether to write or only compare."""
    banks = load_banks(ctx)
    questions = resolve_questions(banks, select_banks(answers)) if banks else []
    detected = answers.get("detected", {})

    env: dict[str, Any] = {}
    for question in questions:
        env[question["id"]] = _value(answers, question["id"], question.get("default"))
    env["type"] = _value(answers, "q.core.project-type", detected.get("project_type"))
    env["profile"] = _value(answers, "q.core.profile", "S")

    # Start from profile defaults, then let answered questions override.
    profile = str(env["profile"] or "S").upper()
    if profile not in PROFILE_DEFAULTS:
        raise AegisError(f"unknown profile {profile!r}; expected S, M or L")
    base = PROFILE_DEFAULTS[profile]

    policy: dict[str, Any] = {
        "profile": profile,
        "mode": _value(answers, "q.core.mode", "hybrid"),
        "parallel_builders": base["parallel_builders"],
        "refinement_rounds": base["refinement_rounds"],
        "lens_strictness": base["lens_strictness"],
        "registries": list(base["registries"]),
        "self_governance": list(base["self_governance"]),
        "autonomy_limits": [],
        "testing_mandate": "tests-with-code",
        "nfr_priorities": [],
    }
    doc_profile: dict[str, Any] = {"kind": None, "required": [], "generated": [], "diagram_tool": "mermaid"}
    capabilities: dict[str, Any] = {"packages": {}, "default_package": None}
    standards: dict[str, Any] = {}

    artifacts = {"policy": policy, "doc_profile": doc_profile, "capabilities": capabilities, "standards": standards}

    for question in questions:
        try:
            if not eval_when(question.get("when"), env, detected):
                continue
        except WhenSyntaxError as exc:
            raise AegisError(f"{question['id']}: {exc}") from exc
        writes = question.get("writes")
        if not writes:
            continue
        artifact_name, _, field_name = writes.partition(".")
        target = artifacts.get(artifact_name)
        if target is None:
            continue
        answered = question["id"] in (answers.get("resolved") or {})
        value = _value(answers, question["id"], question.get("default"))
        if value is None or (field_name in PROFILE_OWNED and not answered):
            continue
        if field_name == "frozen_zones":
            # Several banks contribute frozen zones — core asks once, brownfield asks again
            # with more context. Overwriting meant the later question's empty default erased
            # the answer the human actually gave.
            merged = list(target.get(field_name) or [])
            for entry in (value if isinstance(value, list) else [value]):
                if entry and entry not in merged:
                    merged.append(entry)
            target[field_name] = merged
        else:
            target[field_name] = value

    # Path globs come from detection, and they arrive through `answers.detected` like every
    # other input. Patching them into generated/ after compiling would make `check drift`
    # fail against configuration that is in fact correct — the compiler must be the only
    # writer, or its purity buys nothing.
    for key in ("test_paths", "migration_paths", "generated_paths", "shared_paths",
                "env_patterns", "env_ignore", "api_contract", "route_patterns", "baseline"):
        if detected.get(key):
            capabilities[key] = detected[key]
    if detected.get("default_package") and not capabilities.get("default_package"):
        # Without it, a change outside every package path selected no package and the gate
        # failed with "nothing was verified" on an ordinary root-level edit.
        capabilities["default_package"] = detected["default_package"]

    # Derived, not asked: the lens matrix and risk tiers follow from strictness.
    policy["lens_matrix"] = {k: list(v) for k, v in LENS_MATRIX[str(policy["lens_strictness"])].items()}
    if policy.get("pii") == "yes":
        # An answer that changes nothing is a question that should not have been asked.
        # Personal data makes the security lens unconditional, not conditional on the diff.
        always = policy["lens_matrix"].setdefault("always", [])
        if "security" not in always:
            always.append("security")
    policy["risk_tiers"] = RISK_TIERS
    policy["budgets"] = _budgets(profile)

    kind = doc_profile.get("kind") or _default_doc_profile(env, detected)
    doc_profile["kind"] = kind
    preset = DOC_PROFILES.get(kind, DOC_PROFILES["api-service"])
    if not doc_profile.get("required"):
        doc_profile["required"] = list(preset["required"])
    doc_profile["generated"] = list(preset["generated"])
    if profile == "S":
        # A solo project pays for at most one hand-written diagram.
        doc_profile["required"] = [d for d in doc_profile["required"] if d in preset["generated"] or d.endswith("context-diagram")]

    out = {
        "generated/rules.md": _render_rules(policy, capabilities, standards),
        "generated/policy.json": policy,
        "generated/doc-profile.json": doc_profile,
        "generated/capabilities.json": capabilities,
        "generated/standards.json": standards,
    }
    digest = hashlib.sha256(canonical({k: v for k, v in out.items()
                                       if not isinstance(v, str)}).encode("utf-8")).hexdigest()
    # The ledger and status are review bookkeeping, not compiler inputs. Hashing them made
    # "I reviewed the assumptions" look identical to "I edited generated config by hand".
    inputs = {k: v for k, v in answers.items()
              if k not in ("ledger", "status", "preserved_human_answers")}
    out["generated/materialization.json"] = {
        "compiler_version": COMPILER_VERSION,
        "answers_digest": hashlib.sha256(canonical(inputs).encode("utf-8")).hexdigest(),
        "config_digest": digest,
        "banks": sorted(banks),
        "note": "Regenerate with `aegis compile`. Never hand-edit anything under generated/.",
    }
    return out


def _render_rules(policy: dict, capabilities: dict, standards: dict) -> str:
    """The agent rules, compiled — not scaffolded once and then abandoned.

    These are what CLAUDE.md imports and what AGENTS.md tells other runners to read.
    Compiling them buys three things the old prefilled files could not have: they carry the
    project's *actual* commands and limits rather than placeholders; they are a pure
    function of answers, so `check drift` notices tampering; and they live under
    `generated/`, where the write hook refuses agent edits. An agent can overwrite the
    pointer files — that is detected and repaired — but it cannot rewrite the rules.
    """
    commands = []
    for name, spec in sorted((capabilities.get("packages") or {}).items()):
        pairs = " · ".join(f"{k}: `{v}`" for k, v in spec.items() if k != "paths")
        if pairs:
            commands.append(f"- {name} — {pairs}")
    frozen = standards.get("frozen_zones") or []
    limits = policy.get("autonomy_limits") or []
    lines = [
        "# Agent rules (compiled — edit answers.json, never this file)",
        "",
        "Project truth lives in `.aegis/`. Read `.aegis/generated/index/INDEX.md` before",
        "searching the tree, and run `aegis next` to get the current step.",
        "",
        "Rules always in force:",
        "",
        "1. Every change belongs to a TASK with an exclusive write lease. No task, no code.",
        "2. Code and its tests are written together, by the same agent. Done means the",
        "   verification commands ran green, not that they should.",
        "3. An event, environment variable or feature flag exists only once it is in",
        "   `.aegis/registry/`; a route exists only once it is in the API contract.",
        "4. Never edit `.aegis/generated/` (compiled) or `.aegis/constitution.md`",
        "   (human-owned). Change configuration with `aegis answer <question> <value>`.",
        "5. Review findings are resolved or explicitly dispositioned; a finding that",
        "   returns after being marked fixed means the mechanism is wrong — simplify it.",
        "6. Between unrelated tasks, start a fresh context.",
        "",
        f"Profile: {policy.get('profile', 'S')} · parallel builders: "
        f"{policy.get('parallel_builders', 1)} · testing mandate: "
        f"{policy.get('testing_mandate', 'tests-with-code')}",
    ]
    if limits:
        lines += ["", f"Agents decide alone: {', '.join(limits)}. Everything else escalates."]
    if frozen:
        lines += ["", f"Frozen zones (never modify): {', '.join(frozen)}"]
    if commands:
        lines += ["", "Verification commands the gate runs:", ""] + commands
    return "\n".join(lines) + "\n"


def _budgets(profile: str) -> dict[str, int]:
    """Token ceilings, measured by `aegis budget` against the estimator in core.

    These count what actually lands in a role's context at startup, including injected
    skill bodies — not only the project artifacts, which is where naive budgets go wrong.
    """
    scale = {"S": 1.0, "M": 1.0, "L": 1.25}[profile]
    return {
        "claude_md": 2000,
        "skill_body": 2500,
        "skill_metadata_total": int(3000 * scale),
        "builder_startup": int(12000 * scale),
        "lens_startup": int(8000 * scale),
        "packet": int(6000 * scale),
        "handoff": 1500,
        "lens_report": 1000,
        "notes": 3000,
    }


def _default_doc_profile(env: dict, detected: dict) -> str:
    explicit = env.get("type") or detected.get("project_type")
    if explicit in DOC_PROFILES:
        return explicit
    return "api-service"


def interview(ctx: Ctx, answers: dict | None = None, include_deferred: bool = False) -> dict:
    """The questions still worth a human's attention, batched and ordered.

    The banks have always existed; nothing turned them into a conversation, so `/aegis:init`
    had to improvise which questions to ask and in what order. Improvised interviews drift
    between projects and ask about things the detector already knows.

    Ordering is deliberate: irreversible decisions first, while attention is fresh, then
    the ones that merely tune behaviour. Anything the detector established confidently is
    not asked at all — it is listed separately for a single batch confirmation.
    """
    answers = answers if answers is not None else read_json(ctx.path("answers.json"), default={})
    banks = load_banks(ctx)
    if not banks:
        return {"batches": [], "confirm": [], "skipped": []}

    questions = resolve_questions(banks, select_banks(answers))
    detected = answers.get("detected", {})
    resolved = answers.get("resolved", {})
    env: dict[str, Any] = {q["id"]: _value(answers, q["id"], q.get("default")) for q in questions}
    env["type"] = _value(answers, "q.core.project-type", detected.get("project_type"))
    env["profile"] = _value(answers, "q.core.profile", "S")

    ask: list[dict] = []
    confirm: list[dict] = []
    skipped: list[dict] = []

    for question in questions:
        qid = question["id"]
        try:
            if not eval_when(question.get("when"), env, detected):
                continue
        except WhenSyntaxError:
            continue
        severity = question.get("severity", "optional")
        if severity.startswith("deferrable") and not include_deferred:
            skipped.append({"id": qid, "why": "deferred to phase 2, when the feature gives it context"})
            continue

        entry = resolved.get(qid)
        source = entry.get("source") if isinstance(entry, dict) else None
        confidence = entry.get("confidence", 0) if isinstance(entry, dict) else 0

        if source == "human":
            skipped.append({"id": qid, "why": "already answered by a human"})
            continue
        if source in ("detected", "heuristic") and confidence >= (auto_threshold(question) or 0.8):
            confirm.append({"id": qid, "ask": question.get("ask"), "value": entry.get("value"),
                            "evidence": entry.get("rationale", ""), "confidence": confidence})
            continue

        ask.append({
            "id": qid,
            "ask": question.get("ask"),
            "kind": question.get("kind"),
            "options": question.get("options") or [],
            "default": entry.get("value") if isinstance(entry, dict) else question.get("default"),
            "why": question.get("rationale", ""),
            "writes": question.get("writes"),
            "irreversible": question.get("autonomy") == "always-ask",
            "record": f"aegis answer {qid} <value>",
        })

    # Irreversible first: tenancy and PII shape everything downstream and cannot be undone
    # by a revert, so they deserve the attention a human still has at the start.
    ask.sort(key=lambda q: (not q["irreversible"], q["id"]))
    batches = [ask[i:i + 3] for i in range(0, len(ask), 3)]
    return {
        "project_type": env["type"],
        "profile": env["profile"],
        "batches": batches,
        "confirm": confirm,
        "skipped": skipped,
        "note": ("Ask one batch at a time, hardest first. Record each answer with `aegis answer`. "
                 "Everything under `confirm` was read from the repository — show it as one screen, "
                 "not as questions."),
    }


def set_answer(ctx: Ctx, qid: str, value: Any, source: str = "human", rationale: str = "") -> dict:
    """Record an answer and recompile.

    Exists so that changing configuration never means editing `generated/`. Every route to
    a configuration change goes through answers.json, which is what makes the drift check
    a real invariant instead of a suggestion.
    """
    banks = load_banks(ctx)
    known = {q["id"] for bank in banks.values() for q in bank.get("questions", [])}
    if known and qid not in known:
        import difflib
        close = difflib.get_close_matches(qid, sorted(known), n=3)
        raise AegisError(
            f"no question {qid!r}"
            + (f"; did you mean {', '.join(close)}?" if close else
               f"; known ids start with {', '.join(sorted(known)[:4])}")
            + "\nA typo would otherwise be stored and compiled as if it meant something."
        )

    question = next((q for bank in banks.values() for q in bank.get("questions", [])
                     if q["id"] == qid), None)
    if question:
        options = question.get("options") or []
        kind = question.get("kind")
        candidates = value if isinstance(value, list) else [value]
        unknown = [v for v in candidates if isinstance(v, str) and options and v not in options]
        if kind in ("single", "multi", "scale") and unknown:
            raise AegisError(
                f"{unknown} is not a valid answer to {qid}. Allowed: {', '.join(options)}.\n"
                "An unchecked value compiles into configuration that silently means nothing —"
                " `q.core.testing off` disabled the testing mandate without ever being rejected."
            )

    path = ctx.path("answers.json")
    answers = read_json(path, default={"mode": "hybrid", "status": "provisional", "detected": {}, "resolved": {}, "ledger": []})
    entry: dict[str, Any] = {"value": value, "source": source, "confidence": 1.0 if source == "human" else 0.5}
    if rationale:
        entry["rationale"] = rationale
    answers.setdefault("resolved", {})[qid] = entry
    if source == "human":
        answers["ledger"] = [row for row in answers.get("ledger", []) if row.get("question") != qid]
    if answers.get("status") == "provisional" and not answers.get("ledger"):
        # `provisional` means "assumptions await a human". Once the last row is answered
        # there is nothing left to review, and a status that says otherwise sends
        # `aegis status` and every reader of answers.json looking for a ledger that is empty.
        answers["status"] = "complete"
    write_json(path, answers)
    return answers


def materialize(ctx: Ctx, answers: dict | None = None) -> tuple[list[str], dict]:
    answers = answers if answers is not None else read_json(ctx.path("answers.json"))
    out = compile_config(ctx, answers)
    changed = []
    for rel, data in out.items():
        wrote = (write_text(ctx.path(rel), data) if isinstance(data, str)
                 else write_json(ctx.path(rel), data))
        if wrote:
            changed.append(rel)
    return changed, out


def check_drift(ctx: Ctx) -> Report:
    """Recompile and compare. A difference means someone hand-edited generated config,
    which would make every later review argue against the wrong baseline."""
    report = Report()
    if not os.path.exists(ctx.path("answers.json")):
        report.warn("drift", "no answers.json; project not initialised")
        return report
    expected = compile_config(ctx, read_json(ctx.path("answers.json")))

    # An upgraded framework and a hand-edited file both show up as a difference, but they
    # are different problems with different fixes. Reporting the first as tampering sends
    # the reader looking for an edit nobody made.
    recorded = read_json(ctx.gen("materialization.json"), default={})
    if recorded and recorded.get("compiler_version") != COMPILER_VERSION:
        report.warn(
            "drift",
            f"configuration was compiled by version {recorded.get('compiler_version')} and this "
            f"is version {COMPILER_VERSION}",
            hint="run `aegis compile` and review the diff; the answers are unchanged",
        )
        # Returning here skipped the comparison entirely, so a tampered generated/ file went
        # unnoticed for as long as the version stayed behind.

    for rel in ("generated/index/skills.json", "generated/index/INDEX.md"):
        if not os.path.exists(ctx.path(rel)):
            # `aegis packet` reads the skills index to decide which protocols apply; without
            # it a builder silently receives none.
            report.fail("drift", f"{rel} is missing", rel, hint="run `aegis index`")

    for rel, data in expected.items():
        actual_path = ctx.path(rel)
        if not os.path.exists(actual_path):
            report.fail("drift", f"{rel} is missing", rel, hint="run `aegis compile`")
            continue
        if isinstance(data, str):
            if read_text(actual_path, default="") != data:
                report.fail("drift", f"{rel} does not match what answers.json compiles to", rel,
                            hint="agents cannot edit compiled rules; change answers.json instead")
            continue
        if canonical(read_json(actual_path)) != canonical(data):
            report.fail(
                "drift", f"{rel} does not match what answers.json compiles to", rel,
                hint="if you edited generated/ by hand, revert it; if you meant to change "
                     "configuration, use `aegis answer <qid> <value>` which recompiles",
            )
    return report
