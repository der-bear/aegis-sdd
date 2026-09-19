"""Deterministic checks. Each is a pure function of (ctx, scope) returning a Report.

Design rules that every check here obeys:

  * Scope is the candidate diff, never the whole repository. A brownfield project must be
    able to adopt Aegis on a Monday without its entire legacy surface turning red.
  * Facts come from artifacts, not from prose. A check that would need to interpret a
    sentence is not a check; it belongs to a lens.
  * Every failure names the minimal fix. A gate that says "no" without saying "then what"
    gets disabled by the third week.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import re
from typing import Any, Iterable

from .core import (
    ABSENT,
    AegisError,
    content_key,
    Ctx,
    Report,
    asset_dirs,
    canonical,
    changed_files,
    estimate_tokens,
    matches_any,
    read_json,
    read_text,
    tokens_of_file,
)

RUNNER_NEUTRAL = {"build-task", "review-lens", "doc-sync",
                  "registry-authoring", "doc-authoring", "protocol-authoring"}

REGISTRY_FILES = ("integrations", "events", "env", "flags", "diagrams")
_WALK_CACHE: dict[str, list[str]] = {}
TODAY = _dt.date.today
FINDING_ID = re.compile(r"^F-[0-9a-f]{8}$")


# ----------------------------------------------------------------------- policy io


def policy(ctx: Ctx) -> dict:
    return read_json(ctx.gen("policy.json"), default={"profile": "S", "budgets": {}, "registries": []})


def doc_profile(ctx: Ctx) -> dict:
    return read_json(ctx.gen("doc-profile.json"), default={"kind": "api-service", "required": [], "generated": []})


def capabilities(ctx: Ctx) -> dict:
    return read_json(ctx.gen("capabilities.json"), default={"packages": {}, "default_package": None})


# ------------------------------------------------------------------------ waivers


WAIVER_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["id", "check", "scope", "reason", "owner", "expires"],
        "properties": {
            "id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]*$"},
            # Deliberately excludes verify, reviews, handoff, structure, drift and trace:
            # those are the guarantees. A waiver that can silence them is not a waiver, it is
            # a documented way to turn the framework off.
            # `finding` never mutes a check. It is the record a deferred blocking review
            # finding needs: its scope lists finding ids, and only `check_reviews` reads it.
            "check": {"enum": ["registry", "env", "requirements", "docs", "budget",
                               "testing", "events", "flags", "integrations", "routes",
                               "protocols", "finding"]},
            "scope": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "reason": {"type": "string", "minLength": 12},
            "owner": {"type": "string", "minLength": 2},
            "expires": {"type": "string", "format": "date"},
            "ticket": {"type": "string"},
        },
        "additionalProperties": False,
    },
}



def is_person_name(name: str | None, builder: str = "", lens: str = "") -> bool:
    """A name the framework will accept as the person behind a decision.

    Not empty, not one character, and not the task's builder or the lens in question — the
    one attack this guards is a builder closing its own finding. It does not try to tell a
    person from an invented name or a model from a person: three rounds of a widening regex
    were beaten in every round, and a waiver is a record, not a signature.
    """
    by = (name or "").strip()
    low = by.lower()
    if len(by) < 3 or low.startswith(("aegis-", "lens-")):
        return False
    return low not in ((builder or "").strip().lower(), (lens or "").strip().lower(),
                       f"lens-{(lens or '').strip().lower()}")


def load_waivers(ctx: Ctx) -> list[dict]:
    """A waiver must name a specific check and a specific scope.

    `{"check": "*"}` with no owner and no reason is not a waiver, it is a global mute — and
    an unvalidated waivers file is the easiest way to turn every blocking gate off at once
    while the repository still looks governed.
    """
    from .core import validate

    waivers = read_json(ctx.path("waivers.json"), default=[])
    errors = validate(waivers, WAIVER_SCHEMA)
    ids = [w.get("id") for w in waivers if isinstance(w, dict)]
    duplicates = sorted({i for i in ids if ids.count(i) > 1 and i})
    if duplicates:
        errors.append(f"$: duplicate waiver ids {duplicates}; an audit reference must be unambiguous")
    for index, waiver in enumerate(waivers if isinstance(waivers, list) else []):
        if isinstance(waiver, dict) and not is_person_name(waiver.get("owner")):
            # An owner is who can be asked. An agent-named owner muted a check with nobody
            # accountable.
            errors.append(f"$[{index}].owner: {waiver.get('owner')!r} is not a person's name")
        if isinstance(waiver, dict) and waiver.get("check") == "finding":
            loose = [s for s in waiver.get("scope") or [] if not FINDING_ID.match(str(s))]
            if loose:
                # A glob here would read as "every finding under src/ is deferred" while
                # deferring nothing, so the file would claim more than the gate does.
                errors.append(f"$[{index}].scope: a finding waiver lists finding ids "
                              f"(F- and eight hex digits), not {loose[:3]}")
    if errors:
        raise AegisError(
            "waivers.json is invalid, so no waiver is applied:\n  " + "\n  ".join(errors[:6])
            + "\n  Each waiver needs id, check, scope, reason, owner and a real expiry date."
        )
    return waivers


def expired(waiver: dict, today: _dt.date | None = None) -> bool:
    """Compare dates, not strings: `date.fromisoformat` also reads `20260101` and `2026-W01-1`,
    and both sort above an ISO date, so a waiver spelled that way never expired."""
    try:
        return _dt.date.fromisoformat(str(waiver.get("expires", ""))) < (today or TODAY())
    except ValueError:
        return True  # not a date at all: the waiver does not apply, and the schema says why


def waiver_for(waivers: list[dict], check: str, path: str | None) -> dict | None:
    """A waiver is scoped, owned and expiring. Without all three it is just a disabled
    check with extra steps, which is how blocking gates quietly die."""
    for waiver in waivers:
        if waiver.get("check") != check:
            continue
        if expired(waiver):
            continue
        scope = waiver.get("scope") or ["**"]
        if path is None:
            # A finding with no path cannot be shown to be inside a narrow scope, and
            # treating that as a match let a waiver for `legacy/**` silence a failing test
            # command for entirely unrelated code.
            if scope == ["**"]:
                return waiver
            continue
        if matches_any(path, scope):
            return waiver
    return None


def apply_waivers(ctx: Ctx, report: Report) -> Report:
    try:
        waivers = load_waivers(ctx)
    except AegisError as err:
        # Fail closed, as a finding: no waiver applies, and the gate says which entry is wrong
        # instead of dying with a traceback that hides every other finding.
        out = Report(notes=list(report.notes))
        for finding in report.findings:
            out.add(finding)
        out.fail("waiver", " ".join(str(err).split()), ".aegis/waivers.json",
                 hint="no waiver applies until the file validates")
        return out
    if not waivers:
        return report
    out = Report(notes=list(report.notes))
    for finding in report.findings:
        if finding.severity != "fail":
            out.add(finding)
            continue
        waiver = waiver_for(waivers, finding.check, finding.path)
        if waiver:
            finding.severity = "warn"
            finding.message += f" [waived until {waiver['expires']} by {waiver.get('owner', '?')}: {waiver.get('reason', '')}]"
        out.add(finding)
    for waiver in waivers:
        if expired(waiver):
            out.warn("waiver", f"waiver {waiver.get('id')} expired on {waiver.get('expires')}",
                     hint="renew it with a fresh justification or fix the underlying issue")
    return out


# ----------------------------------------------------------------- registry checks


def _schema_path(ctx: Ctx, name: str) -> str | None:
    for base in _schema_dirs(ctx):
        candidate = os.path.join(base, f"{name}.schema.json")
        if os.path.exists(candidate):
            return candidate
    return None


def _schema_dirs(ctx: Ctx) -> list[str]:
    return asset_dirs(ctx, "schemas")


SECRET_VALUE = re.compile(r"(?i)(secret|token|password|api[_-]?key)")


def check_registry(ctx: Ctx, scope: list[str] | None = None) -> Report:
    """Schema-validate the hand-owned registries and enforce the conventions a schema
    cannot express: sorted ids, no literal secrets, lifecycle sanity."""
    from .core import validate

    report = Report()
    enabled = set(policy(ctx).get("registries") or REGISTRY_FILES)
    for name in REGISTRY_FILES:
        path = ctx.path("registry", f"{name}.json")
        if not os.path.exists(path):
            if name in enabled:
                # Blocking, not advisory: while it was a warning, deleting the file was the
                # quickest way to switch off the scanner that reads it.
                report.fail("registry", f"{name}.json is enabled by the profile but absent",
                            ctx.rel(path),
                            hint=f"create it as [], or remove {name} from policy.registries "
                                 "through answers.json if the project genuinely does not need it")
            continue
        entries = read_json(path)
        rel = ctx.rel(path)
        if not isinstance(entries, list):
            report.fail("registry", f"{name}.json must be a JSON array", rel)
            continue

        schema_file = _schema_path(ctx, name)
        if schema_file:
            for error in validate(entries, read_json(schema_file)):
                report.fail("registry", error, rel)
        else:
            report.fail("registry", f"no schema for {name}, so its entries are unvalidated", rel,
                        hint=f"restore schemas/{name}.schema.json; deleting a schema was the "
                             "simplest way to stop its registry being checked")

        ids = [e.get("id") for e in entries if isinstance(e, dict)]
        duplicates = sorted({i for i in ids if ids.count(i) > 1 and i})
        if duplicates:
            report.fail("registry", f"duplicate ids: {', '.join(duplicates)}", rel)
        if ids != sorted(i for i in ids if i is not None) and len(ids) == len([i for i in ids if i]):
            report.fail("registry", "entries must be sorted by id", rel,
                        hint="run `aegis fmt` to sort and canonicalise")
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for key, value in entry.items():
                if isinstance(value, str) and SECRET_VALUE.search(key) and not value.startswith("env:"):
                    report.fail("registry", f"{entry.get('id')}: {key} holds a literal value", rel,
                                hint="reference the variable instead: \"env:NAME\"")
            if entry.get("status") == "deprecated" and not entry.get("superseded_by"):
                report.warn("registry", f"{entry.get('id')} is deprecated without superseded_by", rel)
    return report


DOC_SUFFIXES = (".md", ".mdx", ".rst", ".txt", ".adoc", ".org", ".html")
# What the documentation profile is about. `.txt` and `.html` are prose for the purpose of not
# scanning them as source, and are not prose by themselves for the purpose of "this file is
# undocumented documentation": `requirements.txt` and `CMakeLists.txt` are manifests, and
# treating them as stray documents refused every commit that added one.
PROSE_SUFFIXES = (".md", ".mdx", ".rst", ".adoc", ".org")
# Named manifests that end in a prose-looking suffix. A list, because the alternative is
# guessing from content, and a check that guesses is a check that gets waived.
MANIFEST_NAMES = frozenset({
    "requirements.txt", "requirements-dev.txt", "requirements-test.txt", "constraints.txt",
    "CMakeLists.txt", "robots.txt", "CODEOWNERS.txt", "LICENSE.txt", "NOTICE.txt",
})


def _is_unrequested_doc_candidate(rel: str) -> bool:
    """Is this file documentation the profile should have asked for?

    Prose anywhere, and anything under `docs/`, which is a documentation root by convention.
    Not a manifest that happens to end in `.txt`.
    """
    if os.path.basename(rel) in MANIFEST_NAMES:
        return False
    if rel.endswith(PROSE_SUFFIXES):
        return True
    return rel.startswith("docs/") and rel.endswith(DOC_SUFFIXES)


def _is_doc(rel: str) -> bool:
    """Prose is not source. An environment read quoted in a guide is an example, not a
    read, and an event name in a README is a mention, not an emission — scanning
    documentation reported both as unregistered surfaces on the framework's own repository
    (this docstring, quoting one, was the second instance)."""
    return rel.lower().endswith(DOC_SUFFIXES)


def check_env(ctx: Ctx, scope: list[str] | None = None) -> Report:
    """Every environment variable read by changed code has a registry entry.

    Scoped to the diff on purpose: this ratchets coverage forward on legacy repositories
    instead of demanding a complete inventory before the first commit.
    """
    report = Report()
    path = ctx.path("registry", "env.json")
    if not os.path.exists(path):
        # `check_registry` fails on the missing file; returning silently here as well meant
        # deleting it removed the finding rather than surfacing two.
        return report
    known = {e.get("id") for e in read_json(path) if isinstance(e, dict)}
    patterns = capabilities(ctx).get("env_patterns") or [
        r"process\.env\.([A-Z][A-Z0-9_]{2,})",
        r"process\.env\[[\"']([A-Z][A-Z0-9_]{2,})[\"']\]",
        r"os\.environ(?:\.get)?[\[\(][\"']([A-Z][A-Z0-9_]{2,})[\"']",
        # `os.getenv` is the common Python spelling and was missing; so were Rust and Ruby.
        r"(?:os|System)\.[Gg]etenv\(\s*[\"']([A-Z][A-Z0-9_]{2,})[\"']",
        r"env::var(?:_os)?\(\s*[\"']([A-Z][A-Z0-9_]{2,})[\"']",
        r"ENV\.fetch\(\s*[\"']([A-Z][A-Z0-9_]{2,})[\"']",
        r"ENV\[[\"']([A-Z][A-Z0-9_]{2,})[\"']\]",
        r"\bgetenv\(\s*[\"']([A-Z][A-Z0-9_]{2,})[\"']",
        r"Deno\.env\.get\(\s*[\"']([A-Z][A-Z0-9_]{2,})[\"']",
    ]
    compiled = [re.compile(p) for p in patterns]
    ignore = set(capabilities(ctx).get("env_ignore") or ["NODE_ENV", "CI", "HOME", "PATH", "PWD", "TZ", "LANG"])
    for rel in scope or []:
        full = os.path.join(ctx.root, rel)
        if not os.path.isfile(full) or _is_binary(full) or _is_doc(rel):
            continue
        try:
            text = read_text(full)
        except (AegisError, UnicodeDecodeError):
            continue
        seen: set[str] = set()
        for pattern in compiled:
            for match in pattern.finditer(text):
                name = match.group(1)
                # Several patterns match the same spelling; reporting one variable three
                # times reads as three problems and trains people to skim the output.
                if name in ignore or name in known or name in seen:
                    continue
                seen.add(name)
                report.fail("env", f"{name} is read here but not registered", rel,
                            hint=f'add {{"id": "{name}", ...}} to .aegis/registry/env.json. '
                                 "This is a pattern scan: it finds literal names, not computed "
                                 "ones — extend capabilities.env_patterns for other spellings")
    return report


SURFACE_PATTERNS: dict[str, list[str]] = {
    "events": [
        r"(?:emit|publish|dispatch|sendEvent|produce)\(\s*[\"']([a-z][a-z0-9_.\-]{2,})[\"']",
        r"(?:emit|publish|dispatch)\(\s*[\"']([A-Z][A-Za-z0-9_.]{2,})[\"']",
    ],
    "flags": [
        r"(?:isEnabled|featureFlag|getFlag|flagEnabled|is_enabled)\(\s*[\"']([a-z][a-z0-9_.\-]{2,})[\"']",
    ],
    "integrations": [
        r"(?:fetch|axios\.\w+|requests\.\w+|http\.(?:Get|Post)|HttpClient\.\w+)\(\s*[\"']https?://([a-z0-9.\-]+)",
    ],
}


def check_surfaces(ctx: Ctx, scope: list[str] | None = None) -> Report:
    """Every event, flag and outbound integration introduced by this diff has a registry entry.

    Until this existed, only environment variables were actually correlated with code — the
    other registries were schema ceremony, and the rule "an endpoint exists only once it is
    registered" was enforced by nobody. Scoped to the diff, so a legacy codebase is not
    required to be complete before it can adopt anything.
    """
    report = Report()
    enabled = set(policy(ctx).get("registries") or [])
    caps = capabilities(ctx)
    known: dict[str, set[str]] = {}
    for registry in ("events", "flags", "integrations"):
        path = ctx.path("registry", f"{registry}.json")
        if registry in enabled and os.path.exists(path):
            entries = read_json(path)
            ids = {e.get("id") for e in entries if isinstance(e, dict)}
            if registry == "integrations":
                # `<system>.<resource>`: a registered host need not be re-registered per
                # endpoint. Applying the same aliasing to events and flags made
                # `order.cancelled` pass because `order.created` was registered.
                ids |= {str(i).split(".")[0] for i in ids if i}
            known[registry] = ids

    if not known:
        return report

    compiled = {name: [re.compile(p) for p in (caps.get(f"{name}_patterns") or SURFACE_PATTERNS[name])]
                for name in known}
    for rel in scope or []:
        full = os.path.join(ctx.root, rel)
        if not os.path.isfile(full) or _is_binary(full) or _is_doc(rel) \
                or matches_any(rel, caps.get("test_paths") or []):
            continue
        try:
            text = read_text(full)
        except (AegisError, UnicodeDecodeError):
            continue
        for registry, patterns in compiled.items():
            for pattern in patterns:
                for match in pattern.finditer(text):
                    name = match.group(1)
                    aliases = {name}
                    if registry == "integrations":
                        aliases.add(name.split(".")[0])
                    if aliases & known[registry]:
                        continue
                    report.fail(registry, f"{name} appears here but is not registered", rel,
                                hint=f"add it to .aegis/registry/{registry}.json "
                                     f"(the builder drafts it in handoff registry_drafts). "
                                     f"This is a pattern scan: it finds literals, not computed "
                                     f"names — extend capabilities.{registry}_patterns if your "
                                     f"project spells them differently")
    return report


ROUTE_DECL = [
    r"(?:app|router)\.(?:get|post|put|patch|delete)\(\s*[\"'`]([^\"'`]+)",
    r"@(?:app|router)\.(?:get|post|put|patch|delete)\(\s*[\"']([^\"']+)",
    r"@(?:Get|Post|Put|Patch|Delete)Mapping\(\s*[\"']([^\"']+)",
    r"http\.HandleFunc\(\s*[\"']([^\"']+)",
]


def check_routes(ctx: Ctx, scope: list[str] | None = None) -> Report:
    """A route introduced in this diff must appear in the project's API contract.

    The generated rules promise that an endpoint exists only once it is declared. Nothing
    checked it, so the promise was decoration. This checks it where it can be checked —
    against the contract file the project actually publishes — and stays silent when no
    contract is configured rather than inventing a registry for internal routes.
    """
    report = Report()
    caps = capabilities(ctx)
    contract = caps.get("api_contract")
    if not contract or not scope:
        return report
    contract_path = os.path.join(ctx.root, contract)
    if not os.path.exists(contract_path):
        report.fail("routes", f"the declared API contract {contract} does not exist", contract)
        return report
    declared = read_text(contract_path)
    patterns = [re.compile(p) for p in (caps.get("route_patterns") or ROUTE_DECL)]
    test_globs = caps.get("test_paths") or []
    for rel in scope:
        full = os.path.join(ctx.root, rel)
        if not os.path.isfile(full) or _is_binary(full) or _is_doc(rel) or matches_any(rel, test_globs):
            continue
        try:
            text = read_text(full)
        except (AegisError, UnicodeDecodeError):
            continue
        for pattern in patterns:
            for match in pattern.finditer(text):
                route = match.group(1).split("?")[0]
                stem = re.sub(r"[:{][^/}]*[}]?", "", route).rstrip("/") or route
                tail = [p for p in stem.split("/") if p]
                if route in declared or (len(stem) > 1 and stem in declared):
                    continue
                if tail and all(part in declared for part in tail):
                    continue  # mounted under a prefix the scanner cannot compose
                report.fail("routes", f"{route} is served here but absent from {contract}", rel,
                            hint=f"add it to {contract}, or regenerate that contract from the code. "
                                 f"This is a pattern scan over route declarations, not a proof "
                                 f"that every route is contracted")
    return report


def check_testing_mandate(ctx: Ctx, scope: list[str] | None = None) -> Report:
    """Hold the testing mandate the project chose, rather than compiling it and hoping.

    `tests-with-code` and `strict-tdd` both mean a change to behaviour arrives with a change
    to its tests. That is checkable from the diff, so it is checked.
    """
    report = Report()
    mandate = policy(ctx).get("testing_mandate", "tests-with-code")
    if not scope:
        return report
    caps = capabilities(ctx)
    if mandate == "critical-paths-only":
        # Not "no mandate": tests are required where the project says correctness matters.
        # Without this branch, choosing it disabled the check entirely.
        critical = (caps.get("critical_paths") or
                    (caps.get("migration_paths") or []) + ["**/auth/**", "**/security/**",
                                                           "**/payment*/**", "**/billing/**"])
        scope = [f for f in scope if matches_any(f, critical)]
        if not scope:
            return report
    elif mandate not in ("tests-with-code", "strict-tdd"):
        return report
    test_globs = caps.get("test_paths") or ["**/test/**", "**/tests/**", "**/*_test.*", "**/*.test.*"]
    generated = caps.get("generated_paths") or []
    code = [f for f in scope
            if not matches_any(f, test_globs) and not matches_any(f, generated)
            and not f.startswith(".aegis/") and not f.endswith((".md", ".json", ".yml", ".yaml", ".toml", ".txt"))
            # A file with no suffix is not source for this mandate: LICENSE, NOTICE, Makefile,
            # justfile, Dockerfile. Adding a licence to a repository asked for a test.
            and os.path.splitext(f)[1] != ""]
    tests = [f for f in scope if matches_any(f, test_globs)
             or matches_any(f.lower(), [g.lower() for g in test_globs])
             or re.search(r"(?i)(^|/)tests?/|_test\.|\.test\.|\.spec\.|test_[^/]+\.py$", f)]
    if not tests:
        # Rust keeps unit tests inside the module they test; a path pattern can never see them.
        for rel in scope:
            full = os.path.join(ctx.root, rel)
            if rel.endswith(".rs") and os.path.isfile(full) and "#[cfg(test)]" in read_text(full, default=""):
                tests.append(rel)
                break
    if code and not tests:
        report.fail("testing", f"{len(code)} code file(s) changed and no test did", None,
                    hint=f"the project's mandate is `{mandate}`; add the test that would fail "
                         "without this change, or record a waiver with a reason. This compares "
                         "changed paths against the test globs — it cannot tell a real test "
                         "from an empty one")
    return report


def _is_binary(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return b"\0" in fh.read(2048)
    except OSError:
        return True


# --------------------------------------------------------------------- trace check


def load_task(ctx: Ctx, task_id: str) -> dict:
    return read_json(ctx.path("runs", task_id, "manifest.json"))


def active_tasks(ctx: Ctx) -> list[dict]:
    runs = ctx.path("runs")
    if not os.path.isdir(runs):
        return []
    out = []
    for task_id in sorted(os.listdir(runs)):
        manifest = os.path.join(runs, task_id, "manifest.json")
        if os.path.exists(manifest):
            data = read_json(manifest)
            data.setdefault("id", task_id)
            out.append(data)
    return out


HOLDING = ("building", "gated")
"""The statuses in which a task holds its write lease: from claim to merge.

A `planned` task is a plan. It owns nothing, so a backlog of them neither blocks a merge nor
claims a file twice — and code written under a planned task's globs belongs to no task, which
is stricter than asking that task for a handoff, not looser.
"""








def check_trace(ctx: Ctx, scope: list[str], task_id: str | None = None) -> Report:
    """Map every changed file to exactly one owning task.

    Commit-message conventions cannot do this: a squashed branch carries several tasks and
    a shared helper belongs to none of them. The task manifest's `owns` globs can, and
    they are written before the work starts, so the mapping is a plan rather than an
    after-the-fact guess.
    """
    report = Report()
    tasks = active_tasks(ctx)
    # What the framework itself materialises is owned by the framework, before and after the
    # first task exists. Judging it only when a task existed refused the adoption commit of a
    # fresh `aegis init`, which is the first thing the documentation tells a project to do.
    framework_owned = ["CLAUDE.md", "AGENTS.md", ".agents/**", ".aegis/**"]
    frozen = read_json(ctx.gen("standards.json"), default={}).get("frozen_zones") or []
    # Case-folded, as `lease_violation` does it: two implementations of one rule that disagree
    # on spelling let a path be refused to an agent and passed by the gate.
    folded = [zone.lower() for zone in frozen]
    for rel in scope:
        if frozen and matches_any(rel.lower(), folded):
            # R-23: a frozen zone is refused to every agent and is not exempt here either. The
            # framework-owned skip below would otherwise hide a change to a frozen path inside
            # `.aegis/`, which is exactly where a project freezes its standards.
            report.fail("trace", "changed file is inside a frozen zone", rel,
                        hint="a human unfreezes the path in answers.json first; no task owns it")
    if ".aegis/waivers.json" in scope:
        # A waiver is a record, not a signature: the file is ordinary and a hand-typed entry
        # with a plausible owner loads like any other. What the gate can do is say the
        # candidate changed it, and put it in the digest so every review of this candidate
        # is re-taken.
        report.warn("trace", "this candidate changes what the gate is allowed to waive",
                    ".aegis/waivers.json",
                    hint="a waiver is a record with a name and a reason; the review of this "
                         "candidate is what checks it")
    if ".aegis/answers.json" in scope:
        # A shell write plus `aegis compile` leaves no drift and no lease trail, so the one
        # thing the gate can do is say it out loud and invalidate every review of this
        # candidate — the digest covers the file for that reason.

        report.warn("trace", "this candidate changes the project's answers", ".aegis/answers.json",
                    hint="frozen zones, autonomy limits and commands live there: a person "
                         "confirms the change, and `aegis answer` is how it is meant to happen")
    if not tasks:
        considered = [f for f in scope if not matches_any(f, framework_owned)]
        if considered:
            # Code exists that no lease governs. Warning here let a whole branch land with
            # no task, no review and no requirement behind it.
            report.fail("trace", f"{len(considered)} changed file(s) belong to no task", None,
                        hint="`aegis task new <TASK-ID> --owns …` before writing code; "
                             "work without a lease cannot be attributed or reviewed")
        else:
            report.warn("trace", "no task manifests under .aegis/runs/")
        return report

    # Build output only. Lockfiles were excluded as "generated" and are nothing of the
    # kind: they record which code the project will actually run.
    exclude = [g for g in (capabilities(ctx).get("generated_paths") or [])
               if "lock" not in g.lower()] or [
        "**/dist/**", "**/build/**", ".aegis/generated/**", "**/__generated__/**", "**/*.snap",
    ]
    # Files the framework itself materialises are owned by the framework, not by a task.
    # Listing them as orphans made `aegis init` produce a repository whose first gate failed
    # on files it had just written.
    # Only what the framework itself writes is genuinely ownerless. Root manifests and CI
    # configuration are product changes: exempting them let a dependency bump or a workflow
    # edit land with no task and no security review.
    shared = list(framework_owned)
    # An explicit lease beats an inferred default: `**/build/**` in the generated paths
    # excluded `skills/build/SKILL.md` — a source file in a directory named build — from
    # attribution entirely, and every adopter with a `build/` or `dist/` source tree inherits
    # that. Held leases only: a planned row naming `build/**` must not lift the exclusion.
    held = [g for t in tasks if t.get("status") in HOLDING for g in (t.get("owns") or [])]
    considered = [f for f in scope if matches_any(f, held) or not matches_any(f, exclude)]

    owners: dict[str, list[str]] = {}
    for task in tasks:
        if task.get("status") not in HOLDING:
            continue  # a plan is not a lease; an abandoned or landed task holds none
        for rel in considered:
            if matches_any(rel, task.get("owns") or []):
                owners.setdefault(rel, []).append(task["id"])

    mine = 0
    for rel in considered:
        holders = owners.get(rel, [])
        if not holders:
            if matches_any(rel, shared) or rel.startswith(".aegis/"):
                continue
            # The hint used to offer `capabilities.shared_paths` as a way out. The code never
            # read it — deliberately, because exempting CI and root manifests let a
            # dependency bump land unreviewed — so the hint promised a knob that did nothing.
            report.fail("trace", "changed file belongs to no task", rel,
                        hint="`aegis task claim <ID>` the planned task whose globs name it — a "
                             "plan owns nothing until it is claimed — or add the path to the "
                             "owning task's `owns` globs, or create the task "
                             "that owns it; a path recorded at adoption is attributed to adoption "
                             "while the repository still holds what was recorded, so committing "
                             "the adoption state as it is keeps it attributed and retires the "
                             "baseline, while a commit that records anything else puts it in scope")
        elif len(holders) > 1:
            report.fail("trace", f"claimed by several tasks: {', '.join(holders)}", rel,
                        hint="write leases must not overlap; narrow the `owns` globs")
        elif task_id and holders == [task_id]:
            mine += 1

    if task_id and not considered:
        report.fail("trace", f"{task_id} changed nothing", None,
                    hint="a task with no diff cannot be evidence that its requirement is met")
    if task_id and considered and not mine:
        # Otherwise a task passes its own gate on a diff owned entirely by a different task:
        # every file has an owner, so nothing fails, and nothing was actually verified.
        report.fail("trace", f"{task_id} owns none of the changed files", None,
                    hint="either this task did no work, or its `owns` globs do not describe it")

    for task in tasks:
        if task.get("status") in ("merged", "abandoned"):
            continue
        if not task.get("requirements"):
            report.fail("trace", f"{task['id']} closes no requirement", None,
                        hint="every task cites at least one R-* from its spec")
        if not task.get("acceptance"):
            report.warn("trace", f"{task['id']} has no acceptance criteria")
    if task_id:
        report.note(f"candidate scope: {len(considered)} files, task {task_id}")
    return report


def check_requirements(ctx: Ctx, feature: str | None = None, planned: bool = False) -> Report:
    """Bidirectional coverage, scoped per feature.

    Requirement ids restart at `R-1` in every spec, so a single global set of citations let
    a task for feature A satisfy feature B's unrelated `R-1`. Coverage is therefore computed
    from the tasks that actually belong to each feature.
    """
    report = Report()
    specs_dir = ctx.path("specs")
    tasks = active_tasks(ctx)
    if not os.path.isdir(specs_dir):
        live = [t for t in tasks if t.get("status") != "abandoned"]
        if live:
            report.fail("requirements",
                        f"{len(live)} task(s) exist but .aegis/specs/ does not, so no "
                        "requirement they cite can be validated", None,
                        hint="write the feature's spec.md, or abandon tasks that have none")
        return report

    features = set(os.listdir(specs_dir))
    for task in tasks:
        if task.get("status") == "abandoned":
            continue
        if task.get("feature") and task["feature"] not in features:
            # Otherwise `--feature typo --requirements R-999` is never validated by anything.
            report.fail("requirements",
                        f"{task['id']} cites feature {task['feature']!r}, which has no spec", None,
                        hint="fix the feature name, or write .aegis/specs/"
                             f"{task['feature']}/spec.md")

    for name in sorted(os.listdir(specs_dir)):
        if feature and name != feature:
            continue
        spec_file = os.path.join(specs_dir, name, "spec.md")
        if not os.path.exists(spec_file):
            continue
        declared = set(re.findall(r"^\s*(R-\d+)\.", read_text(spec_file), re.MULTILINE))
        if not declared:
            citing = [t["id"] for t in tasks
                      if t.get("feature") == name and t.get("status") != "abandoned"
                      and t.get("requirements")]
            if citing:
                # Deleting the requirement headings otherwise disabled coverage for the
                # whole feature without a word.
                report.fail("requirements",
                            f"{name}: tasks cite requirements but the spec declares none",
                            ctx.rel(spec_file),
                            hint="requirements are lines starting `R-1.`; restore them or "
                                 "abandon the tasks that cite them")
            continue
        cited: set[str] = set()
        pending: set[str] = set()
        for task in tasks:
            if task.get("feature") != name or task.get("status") == "abandoned":
                continue
            # Only requirements this spec declares: citing R-999 covered nothing and said so
            # to nobody.
            declared_here = {r for r in (task.get("requirements") or []) if r in declared}
            # A `planned` manifest citing every requirement would otherwise report a feature
            # fully covered before a line of it exists. At the merge stage a requirement an
            # open task cites is *pending*: one spec split into several tasks is the ordinary
            # case, and calling the later tasks' requirements "uncovered" failed the first
            # task's merge gate for work that was planned and leased.
            if planned or task.get("status") in ("gated", "merged"):
                cited.update(declared_here)
            else:
                pending.update(declared_here)
        pending -= cited
        uncovered = sorted(declared - cited - pending)
        if uncovered:
            report.fail("requirements", f"{name}: not covered by any task: {', '.join(uncovered)}",
                        ctx.rel(spec_file), hint="`/aegis:tasks` for the feature gives it a task; a requirement "
                             "delivered or deleted elsewhere is retired by striking its line — "
                             "`~~R-N.~~ *(delivered|deleted <date>, <where>)* …` — since a "
                             "requirement is a line that starts `R-N.`")
        if pending:
            report.info("requirements", f"{name}: pending in open tasks: {', '.join(sorted(pending))}",
                        ctx.rel(spec_file))
        stray = sorted(cited - declared)
        if stray:
            report.warn("requirements", f"{name}: tasks cite requirements this spec does not declare: "
                        f"{', '.join(stray)}", ctx.rel(spec_file))
    return report


# ---------------------------------------------------------------------- doc checks


NORMALISE = re.compile(r"[ \t]+")


def source_digest(ctx: Ctx, patterns: Iterable[str]) -> str:
    """Digest of the normalised content of every file a diagram watches.

    Content-addressed rather than timestamp-based: a `verified_at` date can be bumped by
    anyone to turn a gate green, a digest cannot be satisfied without actually looking at
    what changed.
    """
    hasher = hashlib.sha256()
    for rel in sorted(_walk_repo(ctx)):
        if not matches_any(rel, patterns):
            continue
        full = os.path.join(ctx.root, rel)
        if _is_binary(full):
            continue
        try:
            text = read_text(full)
        except (AegisError, UnicodeDecodeError):
            continue
        # Leading whitespace is preserved: collapsing it made two Python programs with
        # different control flow hash identically, so the diagram stayed "fresh" across a
        # semantic change.
        normalised = "\n".join(
            re.match(r"[ \t]*", line).group(0) + NORMALISE.sub(" ", line.strip())
            for line in text.splitlines() if line.strip())
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(normalised.encode("utf-8"))
        hasher.update(b"\n")
    return hasher.hexdigest()[:16]


_SKIP_DIRS = {".git", "node_modules", "dist", "build", ".venv", "__pycache__", ".next", "target", "vendor"}


def _walk_repo(ctx: Ctx) -> list[str]:
    cached = _WALK_CACHE.get(ctx.root)
    if cached is not None:
        return cached
    out = []
    for dirpath, dirnames, filenames in os.walk(ctx.root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            out.append(os.path.relpath(os.path.join(dirpath, name), ctx.root))
    # The commit hook runs the merge gate for every command that mentions commit or push, and
    # check_docs walked the whole repository once per diagram: 2.5s on a 20k-file tree.
    _WALK_CACHE[ctx.root] = out
    return out


def check_docs(ctx: Ctx, scope: list[str] | None = None, closing_feature: bool = False) -> Report:
    """Enforce the documentation profile and diagram freshness — nothing else.

    Documentation outside the profile is not merely unchecked, it is a finding: unrequested
    documents are the bloat this framework exists to prevent.
    """
    report = Report()
    profile = doc_profile(ctx)
    diagrams_path = ctx.path("registry", "diagrams.json")
    if not os.path.exists(diagrams_path):
        if profile.get("required"):
            severity = report.fail if closing_feature else report.warn
            severity("docs", "the profile requires diagrams but registry/diagrams.json is absent",
                     hint="create it as [], or narrow doc-profile.required through answers.json")
        report.extend(_check_unrequested_docs(ctx, scope or [], [], closing_feature))
        return report

    diagrams = read_json(diagrams_path)
    present = {d.get("kind") for d in diagrams if isinstance(d, dict)}
    missing = [k for k in profile.get("required", []) if k not in present]
    # A document is required once there is something to document. Demanded on a candidate that
    # carries no code — the adoption commit of a freshly initialised project — it refused the
    # first commit the documentation tells a project to make.
    if missing and closing_feature and not _carries_code(ctx, scope or []):
        report.warn("docs", f"the profile will require diagrams that do not exist: {', '.join(missing)}",
                    hint="required once a candidate carries code; create them with `/aegis:plan` "
                         "or narrow doc-profile.required through answers.json")
        missing = []
    if missing and closing_feature:
        report.fail("docs", f"profile requires diagrams that do not exist: {', '.join(missing)}",
                    hint="create them or narrow doc-profile.required, then `aegis docs attest`")
    elif missing:
        report.warn("docs", f"profile diagrams not yet created: {', '.join(missing)}")

    for entry in diagrams:
        if not isinstance(entry, dict):
            continue
        rel = entry.get("path")
        watches = entry.get("watches") or []
        if not rel:
            continue
        if not os.path.exists(os.path.join(ctx.root, rel)):
            report.fail("docs", f"{entry.get('id')} points at a missing file", rel)
            continue
        if entry.get("kind") == "record":
            # A dated record — an evaluation, a retro — describes what happened, not current
            # code. Watching code made it "stale" on every task and blocked every commit.
            continue
        if entry.get("generated") and not entry.get("generator"):
            report.fail("docs", f"{entry.get('id')} is marked generated but names no generator",
                        rel, hint="add the command that produces it, or set generated: false")
        if not watches:
            report.warn("docs", f"{entry.get('id')} watches nothing, so it can never be detected stale", rel)
            continue
        if not any(matches_any(f, watches) for f in _walk_repo(ctx)):
            report.fail("docs", f"{entry.get('id')} watches globs that match no file", rel,
                        hint="its digest can never change, so staleness could never be detected")
            continue
        current = source_digest(ctx, watches)
        recorded = entry.get("verified_source_digest")
        if recorded != current:
            severity = report.fail if closing_feature else report.warn
            severity(
                "docs", f"{entry.get('id')} is stale: watched sources changed since it was verified", rel,
                hint=("regenerate it" if entry.get("generated") else "review and update it")
                     + f", then `aegis docs attest {entry.get('id')}`",
            )

    report.extend(_check_unrequested_docs(ctx, scope or [], diagrams, closing_feature))
    return report


ALWAYS_ALLOWED_DOCS = ["README.md", "CLAUDE.md", "AGENTS.md", "CHANGELOG.md", "LICENSE.md",
                       "CONTRIBUTING.md", ".github/**", ".aegis/**", "**/node_modules/**"]


def _carries_code(ctx: Ctx, scope: Iterable[str]) -> bool:
    """Does this candidate contain anything but prose, configuration and framework state?"""
    for rel in scope:
        if rel.startswith((".aegis/", ".agents/")) or rel in ("CLAUDE.md", "AGENTS.md"):
            continue
        if rel.endswith(PROSE_SUFFIXES):
            continue
        # Configuration and lockfiles count: `check_trace` refuses to treat a lockfile as
        # generated because it records which code will actually run, and the same reasoning
        # applies to deciding whether a candidate has anything to document.
        return True
    return False


def _check_unrequested_docs(ctx: Ctx, scope: list[str], diagrams: list, closing: bool) -> Report:
    """Documentation nobody asked for is a finding, not a bonus.

    This replaces what a documentation review agent would otherwise be dispatched to notice.
    A path comparison answers it exactly, for no tokens and with no run-to-run variation —
    and the cases it cannot judge (is this paragraph a copy?) are cheaper to catch in the
    design lens than to fund a whole extra context for.
    """
    report = Report()
    registered = {d.get("path") for d in diagrams if isinstance(d, dict)}
    # Protocols and agent profiles are procedure, not documentation; frozen zones are
    # human-owned; shared paths were declared as such at detection. Flagging the
    # framework's own skills as "unrequested documents" buried the one warning that
    # mattered under twenty that did not.
    framework = {ctx.rel(p) for p in skill_files(ctx) + role_files(ctx)}
    frozen = read_json(ctx.gen("standards.json"), default={}).get("frozen_zones") or []
    shared = capabilities(ctx).get("shared_paths") or []
    for rel in scope:
        if not _is_unrequested_doc_candidate(rel) or matches_any(rel, ALWAYS_ALLOWED_DOCS) \
                or rel in registered:
            continue
        if rel in framework or rel.startswith(".agents/") or matches_any(rel, frozen + shared):
            continue
        if not os.path.exists(os.path.join(ctx.root, rel)):
            continue
        severity = report.fail if closing else report.warn
        where = "inside docs/ but not registered" if rel.startswith("docs/") else "outside the profile"
        severity("docs", f"documentation {where}", rel,
                 hint="register it in registry/diagrams.json, fold it into the feature spec, "
                      "or delete it — an unrequested document is the bloat this profile exists to prevent")
    return report


# -------------------------------------------------------------------- budget check


def role_files(ctx: Ctx) -> list[str]:
    out = []
    for root in asset_dirs(ctx, "agents"):
        for dirpath, _dirs, files in os.walk(root):
            out.extend(os.path.join(dirpath, f) for f in files if f.endswith(".md"))
    return sorted(set(out))


def skill_files(ctx: Ctx) -> list[str]:
    out = []
    for root in asset_dirs(ctx, "skills"):
        for dirpath, _dirs, files in os.walk(root):
            if "SKILL.md" in files:
                out.append(os.path.join(dirpath, "SKILL.md"))
    return sorted(set(out))


FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Minimal YAML front-matter reader: scalars and inline lists, which is all the
    Claude Code frontmatter surface uses."""
    match = FRONTMATTER.match(text)
    if not match:
        return {}, text
    data: dict[str, Any] = {}
    key = None
    for raw in match.group(1).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith((" ", "\t")) and key:
            data[key] = f"{data[key]} {raw.strip()}".strip()
            continue
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            data[key] = [v.strip().strip("\"'") for v in value[1:-1].split(",") if v.strip()]
        elif value.startswith("{") and value.endswith("}"):
            # Inline flow map, which is how `metadata:` carries Aegis's own fields without
            # colliding with the frontmatter keys Claude Code owns.
            inner: dict[str, Any] = {}
            for pair in re.split(r",(?![^\[]*\])", value[1:-1]):
                if ":" in pair:
                    k, _, v = pair.partition(":")
                    v = v.strip()
                    if v.startswith("[") and v.endswith("]"):
                        inner[k.strip()] = [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()]
                    else:
                        inner[k.strip()] = v.strip("\"'")
            data[key] = inner
        else:
            data[key] = value
    return data, text[match.end():]


def _agents_chain(ctx: Ctx) -> list[str]:
    """Paths the root AGENTS.md sends a runner to, one level deep.

    Codex reads a chain of AGENTS.md files and the paths they name; measuring only the root
    file certified a surface the runner does not actually load alone.
    """
    text = read_text(os.path.join(ctx.root, "AGENTS.md"), default="")
    out = []
    for match in re.finditer(r"`([\w./-]+\.(?:md|json))`", text):
        rel = match.group(1)
        if rel != "AGENTS.md" and os.path.isfile(os.path.join(ctx.root, rel)):
            out.append(rel)
    for dirpath, dirnames, filenames in os.walk(ctx.root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        if "AGENTS.md" in filenames and os.path.abspath(dirpath) != os.path.abspath(ctx.root):
            out.append(os.path.relpath(os.path.join(dirpath, "AGENTS.md"), ctx.root))
    return sorted(set(out))


# Evidence that a test command executed tests, by runner. A heuristic, and labelled as one:
# it recognises the summaries the common runners print, and says so when it recognises nothing.
_TESTS_NONE = (
    re.compile(r"^Ran 0 tests?", re.M), re.compile(r"no tests ran", re.I),
    re.compile(r"no tests? (?:were )?found", re.I), re.compile(r"no test files", re.I),
    re.compile(r"^Tests:\s+0\b", re.M), re.compile(r"\b0 passed\b"),
    re.compile(r"test result: \w+\. 0 passed", re.M), re.compile(r"OK \(0 tests", re.M),
    re.compile(r"^Tests run: 0", re.M), re.compile(r"\b0 examples?, 0 failures", re.M),
)
_TESTS_RAN = (
    re.compile(r"^Ran (\d+) tests?", re.M),                      # python -m unittest
    re.compile(r"(\d+) passed", re.M),                           # pytest, jest, vitest
    re.compile(r"^Tests:\s+(?:\d+ failed, )?(\d+) passed", re.M),  # jest summary
    re.compile(r"test result: \w+\. (\d+) passed", re.M),        # cargo test
    re.compile(r"^Tests run: (\d+)", re.M),                      # maven surefire
    re.compile(r"(\d+) examples?, \d+ failures?", re.M),         # rspec
    re.compile(r"OK \((\d+) tests?", re.M),                      # phpunit
    re.compile(r"^ok \d+\b", re.M),                               # tap
    # `(cached)` too: a warm build cache is the ordinary case on a re-run, and reading it as
    # "nothing ran" hard-failed a green suite.
    re.compile(r"^ok\s+\S+\s+(?:[\d.]+m?s|\(cached\))", re.M),      # go test, per package
    re.compile(r"^(?:--- )?PASS\b", re.M),                        # go test
    re.compile(r"(\d+) (?:tests?|specs?|assertions?) (?:passed|completed|succeeded)", re.I),
)


def tests_ran(output: str) -> str:  # noqa: D401
    """`ran`, `none` or `unknown` for what a test command's output shows.

    Exit code 0 from a command that ran no tests is the cheapest false green there is: `true`
    as a test command produces it, and so does a filter that matches nothing. `unknown` is not
    `ran`: it means the gate could not tell, and the gate says so rather than implying evidence
    it does not have.
    """
    # Evidence of a run outweighs a phrase about part of the tree: `go test ./...` prints
    # "no test files" for every package without tests and "ok <pkg>" for the ones with them, and
    # reading the first line as "nothing ran" failed a genuinely green suite.
    for pattern in _TESTS_RAN:
        match = pattern.search(output)
        if match:
            counts = [group for group in match.groups() if group and group.isdigit()]
            return "none" if counts and int(counts[0]) == 0 else "ran"
    return "none" if any(pattern.search(output) for pattern in _TESTS_NONE) else "unknown"


# A command quoted in a document, in backticks or in a fenced block. Prose that merely says the
# word "aegis" is not a command and is left alone.
_QUOTED_COMMAND = re.compile(r"`\s*\$?\s*(aegis\s[^`\n]+)`")
_FENCED_COMMAND = re.compile(r"^\s*\$?\s*(aegis\s.+)$", re.M)


def check_commands(ctx: Ctx) -> Report:
    """Every `aegis …` a document quotes as a command must run as written.

    Leadmaster's lesson, and this project's own: two shipped protocols quoted a `lens record`
    line without the option the parser requires, so a reader or a non-Claude runner copying it
    got a usage error. An instruction that cannot execute is a defect, not a typo.

    What counts as a command: a backticked or fenced line with arguments or options. A bare
    `aegis lens record` in prose is a reference to the command, and a table row or a diagram
    aligned with two spaces is neither — both are left alone, because a check that flags
    ordinary writing gets switched off.
    """
    from .__main__ import command_specs

    report = Report()
    specs = command_specs()
    groups = {key.split()[0] for key in specs if " " in key}
    paths = [os.path.join(ctx.root, rel) for rel in ("README.md", "CLAUDE.md", "AGENTS.md")]
    paths += skill_files(ctx) + role_files(ctx)
    for base in ("docs", os.path.join(".aegis", "protocols"), os.path.join(".aegis", "standards")):
        for dirpath, _dirnames, filenames in os.walk(os.path.join(ctx.root, base)):
            paths += [os.path.join(dirpath, n) for n in filenames if n.endswith(".md")]
    seen: set[tuple[str, str]] = set()
    for path in sorted(set(paths)):
        if not os.path.isfile(path):
            continue
        text = read_text(path, default="")
        quoted = [m.group(1) for m in _QUOTED_COMMAND.finditer(text)]
        for block in re.findall(r"```[a-z]*\n(.*?)```", text, re.S):
            # A shell continuation is one command, and the indentation that follows it is not
            # the column alignment the next step cuts at.
            joined = re.sub(r"\s*\\\n\s*", " ", block)
            quoted += [m.group(1) for m in _FENCED_COMMAND.finditer(joined)]
        for raw in quoted:
            line = re.split(r"  +|#|→", raw)[0].strip()  # alignment, comments and diagrams
            words = line.split()[1:]
            positional = [w for w in words if not w.startswith("-")]
            options = [w for w in words if w.startswith("-")]
            if not positional or "|" in positional[0] or positional[0].startswith(("<", "…", "[")):
                continue
            command = positional[0]
            if command not in {key.split()[0] for key in specs}:
                _say(report, seen, path, line, f"there is no `aegis {command}` command",
                     "run `aegis --help`; a command a document invents is an instruction that fails")
                continue
            depth, deepest = 1, command
            if command in groups and len(positional) > 1:
                candidate = positional[1]
                if f"{command} {candidate}" in specs:
                    depth, deepest = 2, f"{command} {candidate}"
                elif not candidate.startswith(("<", "…", "[")) and "|" not in candidate:
                    _say(report, seen, path, line,
                         f"`aegis {command}` has no `{candidate}` subcommand",
                         "one of: " + ", ".join(sorted(k.split()[1] for k in specs
                                                       if k.startswith(command + " "))))
                    continue
            if len(positional) <= depth and not options:
                continue  # a reference to the command, not an invocation of it
            missing = sorted(option for option in specs.get(deepest, set()) if option not in line)
            if missing:
                _say(report, seen, path, line,
                     f"`aegis {deepest}` requires {', '.join(missing)}",
                     "quote the command as it must be run, including its required options")
    return report


def _say(report: Report, seen: set, path: str, line: str, message: str, hint: str) -> None:
    key = (os.path.basename(path), line.strip())
    if key in seen:
        return
    seen.add(key)
    report.fail("commands", f"{message}: `{line.strip()}`", os.path.relpath(path), hint=hint)


def check_budget(ctx: Ctx) -> Report:
    """Measure what actually enters context, not what we hoped would.

    The number that matters for a role is its *startup* load: system prompt body plus every
    skill body the frontmatter preloads. `skills:` injects full bodies, so a 500-line
    protocol is not a cheap pointer — it is the single largest line item.
    """
    report = Report()
    budgets = policy(ctx).get("budgets") or {}

    claude_md = os.path.join(ctx.root, "CLAUDE.md")
    if os.path.exists(claude_md):
        used = tokens_of_file(claude_md)
        # @imports are expanded into context at launch, so the cap covers stub + rules;
        # measuring only the three-line stub would certify nothing.
        rules = ctx.gen("rules.md")
        if "@.aegis/generated/rules.md" in read_text(claude_md, default="") and os.path.exists(rules):
            used += tokens_of_file(rules)
        cap = budgets.get("claude_md", 2000)
        message = f"≈{used} tokens incl. imported rules (cap {cap})"
        if used > cap:
            report.fail("budget", message, "CLAUDE.md",
                        hint="move detail into a skill or a registry; CLAUDE.md is an index")
        else:
            report.info("budget", message, "CLAUDE.md")

    # AGENTS.md is the bootstrap surface for every runner that is not Claude Code, and OpenAI
    # Codex truncates the chain of them at 32 KiB. A limit nothing measures is a wish.
    agents_md = os.path.join(ctx.root, "AGENTS.md")
    if os.path.exists(agents_md):
        chain = [agents_md] + [os.path.join(ctx.root, rel) for rel in _agents_chain(ctx)]
        size = sum(os.path.getsize(p) for p in chain if os.path.isfile(p))
        cap = budgets.get("agents_md_bytes", 32768)
        detail = f"{size} bytes across {len([p for p in chain if os.path.isfile(p)])} file(s) (cap {cap})"
        if size > cap:
            report.fail("budget", detail, "AGENTS.md",
                        hint="a runner reading this chain is truncated at the cap: move detail "
                             "into .agents/skills/ and reference it by path")
        else:
            report.info("budget", detail, "AGENTS.md")

    skills = {}
    metadata_total = 0
    for path in skill_files(ctx):
        text = read_text(path)
        front, body = parse_frontmatter(text)
        name = front.get("name") or os.path.basename(os.path.dirname(path))
        skills[name] = {"path": path, "body_tokens": estimate_tokens(body), "front": front}
        metadata_total += estimate_tokens(f"{name}: {front.get('description', '')}")
        cap = budgets.get("skill_body", 2500)
        if skills[name]["body_tokens"] > cap:
            report.fail("budget", f"skill {name} body ≈{skills[name]['body_tokens']} tokens (cap {cap})",
                        ctx.rel(path), hint="move tables and long examples into references/ and link them")
        if not front.get("description"):
            report.fail("budget", f"skill {name} has no description, so it can never trigger", ctx.rel(path))

    cap = budgets.get("skill_metadata_total", 3000)
    if metadata_total > cap:
        report.fail("budget", f"skill metadata totals ≈{metadata_total} tokens (cap {cap})",
                    hint="merge overlapping skills; every session pays this on every turn")
    else:
        report.info("budget", f"skill metadata ≈{metadata_total} tokens across {len(skills)} skills")

    for path in role_files(ctx):
        text = read_text(path)
        front, body = parse_frontmatter(text)
        name = front.get("name") or os.path.basename(path)[:-3]
        total = estimate_tokens(body)
        injected = front.get("skills") or []
        if isinstance(injected, str):
            injected = [s.strip() for s in injected.split(",") if s.strip()]
        unknown = []
        for skill_name in injected:
            key = skill_name.split(":")[-1].split("/")[-1]
            match = skills.get(skill_name) or skills.get(key)
            if match:
                total += match["body_tokens"]
            else:
                unknown.append(skill_name)
        if unknown:
            report.fail("budget", f"role {name} preloads unknown skills: {', '.join(unknown)}", ctx.rel(path),
                        hint="the frontmatter `skills:` list must name existing skills")
        limit = budgets.get("lens_startup" if name.startswith("lens") else "builder_startup", 12000)
        if total > limit:
            report.fail("budget", f"role {name} startup ≈{total} tokens (cap {limit})", ctx.rel(path),
                        hint="preload fewer skills; pass domain protocols as paths in the packet instead")
        else:
            report.info("budget", f"role {name} startup ≈{total} tokens (cap {limit})")

    # Artefacts a running project grows. Declaring a ceiling and never measuring it is how
    # NOTES.md turns into an append-only log — the exact failure the checkpoint design exists
    # to prevent, and one seen at 337 KB on a real project.
    notes = ctx.path("memory", "NOTES.md")
    if os.path.exists(notes):
        used, cap = tokens_of_file(notes), budgets.get("notes", 3000)
        if used > cap:
            # A warning, never a failure: the owner's rule is that no artefact is rewritten
            # for tokens, because the rewrite costs more than the overage and loses context.
            report.warn("budget", f"NOTES.md ≈{used} tokens (warning line {cap})", ctx.rel(notes),
                        hint="it is a checkpoint, not a log: rewrite it rather than appending")
        else:
            report.info("budget", f"NOTES.md ≈{used} tokens (cap {cap})", ctx.rel(notes))

    runs = ctx.path("runs")
    cap = budgets.get("lens_report", 1000)
    if os.path.isdir(runs):
        for task_id in sorted(os.listdir(runs)):
            reviews = os.path.join(runs, task_id, "reviews")
            if not os.path.isdir(reviews):
                continue
            for name in sorted(os.listdir(reviews)):
                path = os.path.join(reviews, name)
                # The cap is on what a lens *submitted* in its latest round — what a reader
                # takes into context. The stored record accumulates every round's findings
                # plus bookkeeping, so measuring the file failed a review for having had
                # rounds. Records written before `report_tokens` existed are measured whole.
                record = read_json(path, default={})
                used = record.get("report_tokens") if isinstance(record, dict) else None
                if not isinstance(used, int):
                    used = tokens_of_file(path)
                if used > cap:
                    report.warn("budget", f"{task_id}/{name}: the latest lens report is ≈{used} tokens (warning line {cap})",
                                ctx.rel(path),
                                hint="size is not correctness: the report is read as it is; keep each "
                                     "message to two sentences (review-lens protocol)")
    return report


# ----------------------------------------------------------------------- structure


def check_protocol_copies(ctx: Ctx) -> Report:
    """The vendored protocols must match the framework's.

    Copying protocols into the project buys portable packet paths, and it buys a second copy
    that can go stale — which is the failure this framework warns about everywhere else. An
    agent following a stale copy follows rules the gate no longer enforces, or misses ones it
    does. Caught here, fixed by `aegis migrate`.
    """
    report = Report()
    vendored = ctx.path("protocols")
    agents_dir = os.path.join(ctx.root, ".agents", "skills")
    if not os.path.isdir(vendored):
        # Packets cite paths under here. Returning clean when the directory is gone made
        # deleting it the simplest way to silence the check that guards those paths.
        report.fail("protocols", ".aegis/protocols/ is missing", None,
                    hint="run `aegis migrate`; task packets cite protocol paths inside it")
        return report
    for source in skill_files(ctx):
        if os.path.abspath(source).startswith(os.path.abspath(vendored)):
            continue
        front, _ = parse_frontmatter(read_text(source))
        name = front.get("name") or os.path.basename(os.path.dirname(source))
        copy = os.path.join(vendored, f"{name}.md")
        if not os.path.exists(copy):
            report.fail("protocols", f"{name} has no copy in .aegis/protocols/", None,
                        hint="run `aegis migrate` to refresh the project's protocol copies")
        elif read_text(copy) != read_text(source):
            report.fail("protocols", f"{name} differs from the framework's version",
                        ctx.rel(copy),
                        hint="run `aegis migrate`; agents read this copy, so a stale one "
                             "makes them follow rules the gate no longer enforces")
        codex_copy = os.path.join(agents_dir, name, "SKILL.md")
        if os.path.isdir(agents_dir) and name in RUNNER_NEUTRAL and not os.path.exists(codex_copy):
            # Checking it only when present made deleting it the way to stop it being checked.
            report.fail("protocols", f"{name} is missing from .agents/skills/ (the copy Codex reads)",
                        None, hint="run `aegis migrate`")
        elif os.path.exists(codex_copy) and read_text(codex_copy) != read_text(source):
            report.fail("protocols", f"{name} differs in .agents/skills/ (the copy Codex reads)",
                        ctx.rel(codex_copy), hint="run `aegis migrate`")
    return report


def git_hook_installed(ctx: Ctx) -> bool:
    from .scaffold import GIT_HOOK_MARK
    from .core import git
    # `git rev-parse --git-path hooks`, as the installer uses: in a linked worktree `.git` is
    # a file and the hooks live in the main repository, so reading `<root>/.git/hooks` told
    # every builder worktree that the gate it was running under was not installed.
    hooks = git(ctx, "rev-parse", "--git-path", "hooks").strip() or ".git/hooks"
    if not os.path.isabs(hooks):
        hooks = os.path.join(ctx.root, hooks)
    path = os.path.join(hooks, "pre-commit")
    if not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return GIT_HOOK_MARK in fh.read()
    except OSError:
        return False


def check_setup(ctx: Ctx) -> Report:
    """Is the project's own setup finished enough to vouch for work?

    Separate from `check_structure` on purpose. Bootstrap answers "is the framework
    installed and coherent", and a freshly initialised project must pass it. This answers
    "may a gate now certify work here", which needs the two things only a human supplies:
    a real constitution and a reviewed assumption ledger.
    """
    report = Report()
    constitution = ctx.path("constitution.md")
    if os.path.exists(constitution) and "<one paragraph" in read_text(constitution, default=""):
        report.fail("setup", "constitution.md is still the scaffolded template",
                    hint="a human writes its purpose and non-negotiables before work is gated")
    answers = read_json(ctx.path("answers.json"), default={})
    if answers.get("status") == "provisional" and answers.get("ledger"):
        report.fail("setup", f"{len(answers['ledger'])} auto-resolved assumption(s) are unreviewed",
                    hint="confirm them with `aegis answer`, or accept them deliberately "
                         "with `aegis init --yes`")
    from .core import git_available
    if git_available(ctx) and not git_hook_installed(ctx):
        # The barrier for commits nobody routes through Claude Code. Nothing installs it
        # automatically, so a fresh clone has no local gate until someone opts in — and the
        # session that does not know that is the one that commits past it.
        report.warn("setup", "the git-level gate is not installed in this checkout", None,
                    hint="`aegis git-hooks install` — CI runs the same gate, so this is the "
                         "early error, not the barrier")

    return report


def check_pointers(ctx: Ctx) -> Report:
    """The pointer files may be rewritten by any agent; the rules may not.

    That asymmetry is the design: rules live in `generated/` (hook-protected,
    drift-checked), and CLAUDE.md/AGENTS.md only need to keep one line alive. This check
    turns "an agent overwrote the file" from silent rule loss into a blocking finding with
    a one-command repair.
    """
    report = Report()
    if not os.path.exists(ctx.gen("rules.md")):
        return report  # not initialised yet; structure covers that
    claude = os.path.join(ctx.root, "CLAUDE.md")
    if os.path.exists(claude) and "@.aegis/generated/rules.md" not in read_text(claude, default=""):
        report.fail("pointers", "CLAUDE.md no longer imports the compiled rules",
                    "CLAUDE.md", hint="run `aegis migrate`; an agent likely rewrote the file")
    agents = os.path.join(ctx.root, "AGENTS.md")
    if os.path.exists(agents) and ".aegis/generated/rules.md" not in read_text(agents, default=""):
        report.fail("pointers", "AGENTS.md no longer points at the compiled rules",
                    "AGENTS.md", hint="run `aegis migrate`; an agent likely rewrote the file")
    return report


def check_structure(ctx: Ctx) -> Report:
    """The invariants that make everything else meaningful: a human-owned constitution,
    a generated-only generated/ directory, and registries that parse."""
    report = Report()
    if not os.path.isdir(ctx.aegis):
        report.fail("structure", ".aegis/ is absent", hint="run /aegis:init")
        return report
    if not os.path.exists(ctx.path("constitution.md")):
        report.fail("structure", "constitution.md is missing", hint="run /aegis:init; a human authors it")
    marker = ctx.gen("materialization.json")
    if not os.path.exists(ctx.path("answers.json")):
        # Without it, `check drift` has nothing to compile and generated policy becomes
        # whatever is on disk — deleting one file disabled configuration integrity.
        report.fail("structure", "answers.json is missing, so generated config cannot be verified",
                    hint="restore it from git; configuration is compiled from it, not the reverse")
    elif not os.path.exists(marker):
        report.fail("structure", "generated/ has never been compiled", hint="run `aegis compile`")
    for name in ("runs", "registry"):
        if not os.path.isdir(ctx.path(name)):
            report.warn("structure", f".aegis/{name}/ is absent")
    return report
