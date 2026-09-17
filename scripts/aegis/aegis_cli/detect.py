"""Deterministic repository detection.

The interview is only short if the detector is good. Every fact established here is one
question the human is never asked, and — more importantly — one fact that is *read* rather
than guessed. `capabilities.packages` in particular decides which commands the gate runs;
an LLM's plausible guess at a test command turns the gate into noise on the first run.

Everything returned carries a confidence and the file it came from. A fact with no
evidence path is a guess, and is labelled one.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from .core import Ctx, git, git_available, read_text

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - older interpreters
    tomllib = None  # type: ignore[assignment]

SKIP_DIRS = {
    ".git", "node_modules", "dist", "build", "out", ".venv", "venv", "__pycache__",
    ".next", ".nuxt", "target", "vendor", ".terraform", "coverage", ".mypy_cache",
    ".pytest_cache", ".gradle", "bin", "obj", ".idea", ".vscode", ".aegis", ".claude",
    ".codex", ".cache", "tmp", ".tox", "site-packages", ".serverless",
}

MANIFESTS = (
    "package.json", "pyproject.toml", "setup.py", "requirements.txt", "go.mod",
    "Cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts", "Gemfile",
    "composer.json", "Makefile", "justfile", "mix.exs", "Package.swift",
    "build.sbt", "deno.json", "deno.jsonc", "CMakeLists.txt", "*.cabal",
    "Taskfile.yml", "Rakefile",
)

# Simple ecosystems: a manifest name maps directly to the commands its users run. Kept as
# data because the alternative — a branch per language in one long function — is where
# support for the next ecosystem stops being a one-line change.
SIMPLE_STACKS: dict[str, dict[str, str]] = {
    "mix.exs": {"test": "mix test", "lint": "mix format --check-formatted", "build": "mix compile"},
    "Package.swift": {"test": "swift test", "build": "swift build"},
    "build.sbt": {"test": "sbt test", "build": "sbt compile"},
    "deno.json": {"test": "deno test -A", "lint": "deno lint", "typecheck": "deno check ."},
    "deno.jsonc": {"test": "deno test -A", "lint": "deno lint", "typecheck": "deno check ."},
    "CMakeLists.txt": {"build": "cmake -S . -B build && cmake --build build",
                       "test": "ctest --test-dir build --output-on-failure"},
}


def detect(ctx: Ctx) -> dict[str, Any]:
    files, truncated = _walk(ctx)
    fileset = set(files)
    packages, evidence = _packages(ctx, files, fileset)
    project_type, type_conf, type_why = _project_type(ctx, files, fileset, packages)

    result: dict[str, Any] = {
        "brownfield": _brownfield(ctx, files),
        "project_type": project_type,
        "project_type_confidence": type_conf,
        "project_type_evidence": type_why,
        "packages": packages,
        "default_package": _default_package(packages),
        "test_paths": _test_paths(files),
        "migration_paths": _migration_paths(files),
        "generated_paths": _generated_paths(fileset),
        "shared_paths": _shared_paths(files),
        "frozen_candidates": _frozen_candidates(files),
        "api_contract": _api_contract(fileset),
        "frontend_model": _frontend_model(_manifest_blob(ctx, files), _layout(files)),
        "error_format": _error_format(ctx, _api_contract(fileset)),
        "surfaces": _surfaces(ctx, files),
        "evidence": evidence,
    }
    result["repo_size"] = "S" if len(files) < 200 else ("M" if len(files) < 2000 else "L")
    result["truncated"] = truncated
    if truncated:
        result["evidence"].append({
            "fact": f"walk stopped listing ordinary files past {WALK_LIMIT}",
            "source": "filesystem", "confidence": 1.0,
            "note": "build manifests were still collected; raise AEGIS_WALK_LIMIT or run per sub-tree "
                    "if conventions look wrong",
        })
    return result


# ------------------------------------------------------------------------- walking


WALK_LIMIT = int(os.environ.get("AEGIS_WALK_LIMIT", "200000"))


def _walk(ctx: Ctx) -> tuple[list[str], bool]:
    """Files belonging to *this* checkout, and whether the walk was cut short.

    Nested checkouts are skipped: a git worktree or submodule under the root contains a
    complete second copy of the project, and walking into it reports every package once per
    branch. Found on a real repository with agent worktrees under `.claude/`, where it
    produced six copies of two packages.

    Manifests are collected even past the limit. Stopping mid-walk and then reasoning
    confidently from the prefix is how a monorepo silently loses half its packages; the
    truncation is now reported instead.
    """
    out: list[str] = []
    truncated = False
    for dirpath, dirnames, filenames in os.walk(ctx.root):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in SKIP_DIRS
            # `.git` only — a prefix test also swallowed `.github`, so CI configuration was
            # invisible to detection for as long as it existed.
            and d != ".git"
            and not os.path.exists(os.path.join(dirpath, d, ".git"))
        )
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), ctx.root).replace(os.sep, "/")
            if len(out) < WALK_LIMIT or name in MANIFESTS or name.endswith((".csproj", ".sln")):
                out.append(rel)
            else:
                truncated = True
    return sorted(set(out)), truncated


def _is_manifest(basename: str) -> bool:
    return basename in MANIFESTS or basename.endswith((".cabal", ".csproj", ".sln"))


CI_RUN = re.compile(r"^\s*(?:-\s*)?(?:run|script)\s*:\s*[|>]?\s*(.+)$", re.MULTILINE)


def ci_commands(ctx: Ctx, files: list[str]) -> dict[str, str]:
    """Commands the project's own CI runs, as a fallback when manifests say nothing.

    CI is the most reliable statement of how a project is actually built and tested — it is
    the version that has to work. Read last, so it never overrides a manifest or Makefile,
    but read, because an unusual stack often has nothing else to offer.
    """
    out: dict[str, str] = {}
    for rel in files:
        if not (rel.startswith((".github/workflows/", ".gitlab-ci")) or rel.endswith((".circleci/config.yml",))):
            continue
        if not rel.endswith((".yml", ".yaml")):
            continue
        for line in CI_RUN.findall(read_text(os.path.join(ctx.root, rel), default="")):
            command = line.strip().strip("\"'")
            if not command or command.startswith(("actions/", "uses")) or len(command) > 200:
                continue
            low = command.lower()
            for key, needles in (("test", ("test", "spec")), ("lint", ("lint", "fmt", "format")),
                                 ("typecheck", ("typecheck", "tsc", "mypy")), ("build", ("build",))):
                if key in out:
                    continue
                head = low.split("#")[0].strip()
                if not head or head.startswith(("git ", "echo ", "cd ", "true", ":", "export ",
                                                "apt", "brew", "pip install", "npm ci", "npm install")):
                    continue
                # Classify on the command itself, not on a trailing comment: `true # install
                # pytest` was being recorded as the project's test command.
                if any(n in head for n in needles):
                    out[key] = command
    return out


def _load_toml(path: str) -> dict:
    text = read_text(path, default="")
    if tomllib:
        try:
            return tomllib.loads(text)
        except Exception:
            return {}
    # Minimal fallback: only the handful of keys the detector reads.
    out: dict[str, Any] = {}
    section = out
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = out.setdefault(line[1:-1], {})
        elif "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            section[key.strip()] = value.strip().strip('"\'')
    return out


def _load_json(path: str) -> dict:
    try:
        return json.loads(read_text(path, default="{}")) or {}
    except json.JSONDecodeError:
        return {}


# ------------------------------------------------------------------------ packages


def _packages(ctx: Ctx, files: list[str], fileset: set[str]) -> tuple[dict[str, dict], list[dict]]:
    """One entry per independently buildable unit, with its real commands.

    A monorepo that reports one root package makes every task pay for the whole repository's
    test suite, which is the fastest way to get the gate disabled.
    """
    packages: dict[str, dict] = {}
    evidence: list[dict] = []

    def add(name: str, spec: dict, source: str, confidence: float) -> None:
        spec = {k: v for k, v in spec.items() if v}
        if not spec.get("paths"):
            return
        base = name or "root"
        candidate, n = base, 2
        while candidate in packages:
            candidate, n = f"{base}-{n}", n + 1
        packages[candidate] = spec
        evidence.append({"fact": f"package {candidate}", "source": source, "confidence": confidence})

    root_make = _make_targets(ctx, fileset)
    runner = _js_runner(fileset)

    for rel in files:
        base = os.path.basename(rel)
        if not _is_manifest(base):
            continue
        directory = os.path.dirname(rel)
        prefix = f"{directory}/" if directory else ""
        full = os.path.join(ctx.root, rel)
        name = os.path.basename(directory) if directory else os.path.basename(ctx.root)

        if base == "package.json":
            data = _load_json(full)
            if data.get("workspaces") and not directory:
                continue  # the workspace root delegates; its members are detected on their own
            scripts = data.get("scripts") or {}
            local = _js_runner({f[len(prefix):] for f in fileset if f.startswith(prefix)}) \
                if directory else runner
            runner_here = local if local != "npm run" else runner
            add(data.get("name") or name, {
                "paths": [f"{prefix}**"],
                "test": _npm(scripts, ("test", "test:unit", "vitest", "jest"), directory, runner_here),
                "lint": _npm(scripts, ("lint", "eslint"), directory, runner_here),
                "typecheck": _npm(scripts, ("typecheck", "type-check", "tsc"), directory, runner_here),
                "build": _npm(scripts, ("build",), directory, runner_here),
            }, rel, 0.95)

        elif base == "pyproject.toml":
            data = _load_toml(full)
            deps = json.dumps(data)
            cd = f"cd {directory} && " if directory else ""
            add(_py_name(data) or name, {
                "paths": [f"{prefix}**"],
                # Inventing `pytest` for a unittest project produces a command that does not
                # exist. Only claim it when the project actually depends on it.
                "test": (f"{cd}pytest -q" if ("pytest" in deps or f"{prefix}conftest.py" in files)
                         else (f"{cd}python -m unittest discover" if _has_tests(files, prefix) else None)),
                "lint": f"{cd}ruff check ." if "ruff" in deps else (f"{cd}flake8" if "flake8" in deps else None),
                "typecheck": f"{cd}mypy ." if "mypy" in deps else None,
            }, rel, 0.85)

        elif base in ("requirements.txt", "setup.py") and not any(
            f"{prefix}pyproject.toml" == f for f in files
        ):
            cd = f"cd {directory} && " if directory else ""
            add(name, {"paths": [f"{prefix}**"],
                       "test": f"{cd}pytest -q" if _has_tests(files, prefix) else None}, rel, 0.6)

        elif base == "go.mod":
            cd = f"cd {directory} && " if directory else ""
            add(name, {"paths": [f"{prefix}**"],
                       "test": f"{cd}go test ./...",
                       "lint": f"{cd}go vet ./...",
                       "build": f"{cd}go build ./..."}, rel, 0.95)

        elif base == "Cargo.toml":
            data = _load_toml(full)
            if "workspace" in data and "package" not in data:
                continue
            cd = f"cd {directory} && " if directory else ""
            add((data.get("package") or {}).get("name") or name, {
                "paths": [f"{prefix}**"],
                "test": f"{cd}cargo test",
                "lint": f"{cd}cargo clippy -- -D warnings",
                "build": f"{cd}cargo build"}, rel, 0.95)

        elif base == "pom.xml":
            cd = f"cd {directory} && " if directory else ""
            add(name, {"paths": [f"{prefix}**"], "test": f"{cd}mvn -q test",
                       "build": f"{cd}mvn -q -DskipTests package"}, rel, 0.8)

        elif base in ("build.gradle", "build.gradle.kts"):
            # A root wrapper is not reachable as `./gradlew` after cd-ing into a module.
            if f"{prefix}gradlew" in fileset:
                wrapper, cd = "./gradlew", (f"cd {directory} && " if directory else "")
            elif "gradlew" in fileset:
                wrapper, cd = "./gradlew", ""
                if directory:
                    wrapper = f"./gradlew -p {directory}"
            else:
                wrapper, cd = "gradle", (f"cd {directory} && " if directory else "")
            add(name, {"paths": [f"{prefix}**"], "test": f"{cd}{wrapper} test",
                       "build": f"{cd}{wrapper} build"}, rel, 0.8)

        elif base == "Gemfile":
            cd = f"cd {directory} && " if directory else ""
            has_rspec = any(f.startswith(f"{prefix}spec/") for f in files)
            add(name, {"paths": [f"{prefix}**"],
                       "test": f"{cd}bundle exec rspec" if has_rspec else f"{cd}bundle exec rake test",
                       "lint": f"{cd}bundle exec rubocop" if "rubocop" in read_text(full, "") else None},
                rel, 0.7)

        elif base == "composer.json":
            data = _load_json(full)
            scripts = data.get("scripts") or {}
            cd = f"cd {directory} && " if directory else ""
            add(data.get("name", name).split("/")[-1], {
                "paths": [f"{prefix}**"],
                "test": f"{cd}composer test" if "test" in scripts else None}, rel, 0.7)

        elif base in SIMPLE_STACKS:
            cd = f"cd {directory} && " if directory else ""
            add(name, {"paths": [f"{prefix}**"],
                       **{k: f"{cd}{v}" for k, v in SIMPLE_STACKS[base].items()}}, rel, 0.85)

        elif base.endswith(".cabal"):
            cd = f"cd {directory} && " if directory else ""
            add(name, {"paths": [f"{prefix}**"], "test": f"{cd}cabal test",
                       "build": f"{cd}cabal build"}, rel, 0.8)

    for rel in files:
        if os.path.basename(rel).endswith((".csproj", ".sln")) and rel.count("/") <= 2:
            directory = os.path.dirname(rel)
            prefix = f"{directory}/" if directory else ""
            add(os.path.basename(rel).rsplit(".", 1)[0],
                {"paths": [f"{prefix}**"], "test": f"dotnet test {rel}", "build": f"dotnet build {rel}"},
                rel, 0.7)
            break

    # A Makefile is the project's own front door. When it exposes the standard targets it
    # outranks anything inferred from a manifest, because it is what the team actually runs.
    if root_make and not packages:
        add(os.path.basename(ctx.root), {"paths": ["**"], **root_make}, "Makefile", 0.9)
    elif root_make:
        # Authoritative for the keys it defines: `make test` running the suite in Docker and
        # an inferred host `pytest -q` are not two commands to run, they are one command and
        # a wrong guess.
        for spec in packages.values():
            spec.update(root_make)
        evidence.append({"fact": f"Makefile targets override inferred {', '.join(sorted(root_make))}",
                         "source": "Makefile", "confidence": 0.9})

    # Last resort, and only for gaps: CI states how the project is really built, but a
    # manifest states it more precisely and a Makefile states it more deliberately.
    from_ci = ci_commands(ctx, files)
    if from_ci:
        if not packages:
            add(os.path.basename(ctx.root), {"paths": ["**"], **from_ci}, "CI configuration", 0.7)
            evidence.append({"fact": "no manifest; commands read from CI",
                             "source": "CI configuration", "confidence": 0.7})
        elif len(packages) == 1:
            only = next(iter(packages))
            filled = {k: v for k, v in from_ci.items() if k not in packages[only]}
            if filled:
                packages[only].update(filled)
                evidence.append({"fact": f"filled {', '.join(sorted(filled))} from CI",
                                 "source": "CI configuration", "confidence": 0.7})

    return packages, evidence


def _js_runner(fileset: set[str]) -> str:
    """Pick the package manager from the lockfile actually present.

    Running `npm run test` in a pnpm workspace resolves different dependencies than the
    team's own command, so the gate would test something nobody ships.
    """
    if "pnpm-lock.yaml" in fileset:
        return "pnpm run"
    if "yarn.lock" in fileset:
        return "yarn"
    if "bun.lockb" in fileset or "bun.lock" in fileset:
        return "bun run"
    return "npm run"


def _npm(scripts: dict, names: tuple[str, ...], directory: str, runner: str) -> str | None:
    for candidate in names:
        if candidate in scripts:
            prefix = f"cd {directory} && " if directory else ""
            return f"{prefix}{runner} {candidate}"
    return None


def _py_name(data: dict) -> str | None:
    for section in ("project", "tool"):
        node = data.get(section) or {}
        if section == "project" and node.get("name"):
            return str(node["name"])
        poetry = (node.get("poetry") or {}) if section == "tool" else {}
        if poetry.get("name"):
            return str(poetry["name"])
    return None


TEST_FILE = re.compile(r"(^|/)(tests?|spec)/|(^|/)test_[^/]+\.py$|_test\.py$|\.(test|spec)\.[jt]sx?$")


def _has_tests(files: list[str], prefix: str) -> bool:
    """Real test files, not any path containing the letters "test".

    Substring matching gave `contest.md` a pytest command, and a wrong test command turns
    the gate into noise on the very first run.
    """
    return any(f.startswith(prefix) and TEST_FILE.search(f[len(prefix):]) for f in files)


MAKE_TARGET = re.compile(r"^([A-Za-z0-9_.-]+):", re.MULTILINE)


def _make_targets(ctx: Ctx, fileset: set[str]) -> dict[str, str]:
    if "Makefile" not in fileset:
        return {}
    targets = set(MAKE_TARGET.findall(read_text(os.path.join(ctx.root, "Makefile"), default="")))
    out = {}
    for key, candidates in (("test", ("test", "tests", "check")),
                            ("lint", ("lint", "fmt-check")),
                            ("typecheck", ("typecheck", "types")),
                            ("build", ("build", "all"))):
        for candidate in candidates:
            if candidate in targets:
                out[key] = f"make {candidate}"
                break
    return out


def _default_package(packages: dict) -> str | None:
    if not packages:
        return None
    root = [name for name, spec in packages.items() if spec.get("paths") == ["**"]]
    return root[0] if root else sorted(packages)[0]


# --------------------------------------------------------------------- project type


WEB_DEPS = ("react", "vue", "svelte", "next", "nuxt", "angular", "remix", "astro")
SERVER_DEPS = ("express", "fastify", "nestjs", "koa", "hapi", "fastapi", "flask", "django",
               "gin-gonic", "actix", "axum", "spring-boot", "rails", "laravel")
DATA_DEPS = ("airflow", "dbt-core", "prefect", "dagster", "pyspark", "luigi", "kafka", "beam")
STATE_DEPS = ("xstate", "statemachine", "embedded-hal", "rtic")


# The facts a question may name in `detect:`. A key outside this set is a declaration the
# interview cannot keep — `auto-if-detected` on it could never fire — so `bank-lint` refuses it.
DETECT_KEYS = frozenset({"project_type", "packages", "repo_size", "frontend_model", "error_format"})

SSR_DEPS = ("next", "nuxt", "remix", "@sveltejs/kit", "astro", "gatsby")
SPA_DEPS = ("vite", "react-scripts", "@angular/core", "webpack-dev-server", "parcel")


def answerable(facts: dict) -> dict[str, tuple[Any, float, str]]:
    """What detection can answer, as {detect key: (value, confidence, evidence)}.

    One table, so a question's `detect:` key and what the scanner produces cannot drift apart.
    A key missing from the result means detection found nothing and the question is asked.
    """
    out: dict[str, tuple[Any, float, str]] = {}
    if facts.get("project_type"):
        out["project_type"] = (facts["project_type"], float(facts.get("project_type_confidence") or 0),
                               facts.get("project_type_evidence") or "detected")
    if facts.get("packages"):
        out["packages"] = (facts["packages"], 0.9,
                           f"{len(facts['packages'])} package(s) found in manifests")
    if facts.get("repo_size"):
        out["repo_size"] = (facts["repo_size"], 0.7, "repository size")
    for key in ("frontend_model", "error_format"):
        found = facts.get(key)
        if found:
            out[key] = (found["value"], float(found.get("confidence") or 0), found.get("evidence", ""))
    return out


def _frontend_model(blob: str, layout: set[str]) -> dict | None:
    """`ssr`, `spa` or `hybrid`, from the dependency that decides it.

    A meta-framework renders on the server whatever else is present; a bundler with no
    meta-framework is a single-page app. Both together is the hybrid the question means.
    """
    ssr = [dep for dep in SSR_DEPS if f'"{dep}"' in blob]
    spa = [dep for dep in SPA_DEPS if f'"{dep}"' in blob]
    if ssr and spa:
        return {"value": "hybrid", "confidence": 0.8, "evidence": f"{ssr[0]} with {spa[0]}"}
    if ssr:
        return {"value": "ssr", "confidence": 0.9, "evidence": f"{ssr[0]} in dependencies"}
    if spa:
        return {"value": "spa", "confidence": 0.85, "evidence": f"{spa[0]} in dependencies"}
    if "index.html" in layout:
        return {"value": "spa", "confidence": 0.6, "evidence": "index.html at the root, no framework found"}
    return None


def _error_format(ctx: Ctx, contract: str | None) -> dict | None:
    """`problem+json` or `custom`, from the published contract — never from a guess.

    With no contract there is no evidence, so the question is asked rather than answered at a
    confidence the repository does not support.
    """
    if not contract:
        return None
    text = read_text(os.path.join(ctx.root, contract), default="").lower()
    if "problem+json" in text:
        return {"value": "problem+json", "confidence": 0.95, "evidence": f"problem+json in {contract}"}
    if "error" in text:
        return {"value": "custom", "confidence": 0.7, "evidence": f"error schemas in {contract}, not problem+json"}
    return None


def _project_type(ctx: Ctx, files: list[str], fileset: set[str], packages: dict) -> tuple[str, float, str]:
    blob = ""
    for rel in files:
        if os.path.basename(rel) in ("package.json", "pyproject.toml", "requirements.txt",
                                     "go.mod", "Cargo.toml", "Gemfile", "composer.json"):
            blob += read_text(os.path.join(ctx.root, rel), default="").lower()

    has_web = any(dep in blob for dep in WEB_DEPS)
    has_server = any(dep in blob for dep in SERVER_DEPS)
    has_data = any(dep in blob for dep in DATA_DEPS)
    has_state = any(dep in blob for dep in STATE_DEPS)

    # More than one strong signal means the repository genuinely spans types. Reporting a
    # confident single answer there would put a wrong documentation profile in place without
    # anyone noticing; a low confidence sends it to the ledger for one human glance instead.
    signals = sum([has_data, has_web or has_server, has_state])
    mixed = signals > 1

    if has_data:
        return ("data-etl", 0.5 if mixed else 0.8,
                "pipeline framework in dependencies" + (", alongside other stacks — confirm" if mixed else ""))
    if has_web and has_server:
        return "web-saas", 0.5 if mixed else 0.85, "frontend and server frameworks together"
    if has_web:
        return "web-saas", 0.7, "frontend framework, no server framework found"
    if has_server:
        return "api-service", 0.5 if mixed else 0.85, "server framework in dependencies"
    if has_state:
        return "stateful", 0.7, "state machine or embedded runtime in dependencies"
    if not files:
        return "api-service", 0.2, "empty repository; default"

    # Layout is weaker evidence than a dependency but far better than a coin flip, and it is
    # what keeps the common cases out of the assumption ledger — a question the human has to
    # answer about something the repository plainly shows is a question that should not
    # have been asked.
    layout = {p.split("/")[0] for p in files if "/" in p} | {os.path.basename(p) for p in files}
    if {"migrations", "alembic", "dbt_project.yml", "dags", "pipelines"} & layout:
        return "data-etl", 0.65, "pipeline or migration layout"
    if {"public", "static", "pages", "app", "components", "index.html"} & layout:
        return "web-saas", 0.65, "web application layout"
    if {"routes", "controllers", "handlers", "api", "endpoints", "openapi.json", "openapi.yaml"} & layout:
        return "api-service", 0.7, "request-handling layout"
    if {"examples", "docs", "include", "lib"} & layout and "src" in layout:
        return "library", 0.6, "library layout: a public surface with examples"

    published = any(os.path.basename(f) in ("package.json", "pyproject.toml", "Cargo.toml") for f in files)
    if published and not has_server:
        return "library", 0.6, "publishable manifest with no server framework"
    return "api-service", 0.3, "no decisive signal; default"


# ------------------------------------------------------------------------- surfaces


ENV_PATTERNS = [
    r"process\.env\.([A-Z][A-Z0-9_]{2,})",
    r"process\.env\[[\"']([A-Z][A-Z0-9_]{2,})[\"']\]",
    r"os\.environ(?:\.get)?[\[\(][\"']([A-Z][A-Z0-9_]{2,})[\"']",
    r"os\.Getenv\([\"']([A-Z][A-Z0-9_]{2,})[\"']\)",
    r"System\.getenv\([\"']([A-Z][A-Z0-9_]{2,})[\"']\)",
    r"env::var\([\"']([A-Z][A-Z0-9_]{2,})[\"']\)",
    r"ENV\[[\"']([A-Z][A-Z0-9_]{2,})[\"']\]",
]
ROUTE_PATTERNS = [
    r"(?:app|router)\.(?:get|post|put|patch|delete)\([\"'`]([^\"'`]+)",
    r"@(?:app|router)\.(?:get|post|put|patch|delete)\([\"']([^\"']+)",
    r"@(?:Get|Post|Put|Patch|Delete)Mapping\([\"']([^\"']+)",
    r"http\.HandleFunc\([\"']([^\"']+)",
]
CODE_EXT = (".js", ".jsx", ".ts", ".tsx", ".py", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".cs")


def _surfaces(ctx: Ctx, files: list[str]) -> dict[str, list[dict]]:
    """Observed surfaces with evidence paths. Deliberately not written to a registry:
    static scanning cannot tell a live route from a dead one, so these are candidates a
    human confirms, never facts the framework acts on."""
    env_hits: dict[str, str] = {}
    routes: list[dict] = []
    scanned = 0
    for rel in files:
        if not rel.endswith(CODE_EXT) or scanned > 3000:
            continue
        scanned += 1
        try:
            text = read_text(os.path.join(ctx.root, rel))
        except Exception:
            continue
        for pattern in ENV_PATTERNS:
            for match in re.finditer(pattern, text):
                env_hits.setdefault(match.group(1), rel)
        if len(routes) < 200:
            for pattern in ROUTE_PATTERNS:
                for match in re.finditer(pattern, text):
                    routes.append({"path": match.group(1), "evidence": rel})
    return {
        "env": [{"name": name, "evidence": path} for name, path in sorted(env_hits.items())],
        "routes": routes[:200],
    }


# ---------------------------------------------------------------------------- globs


def _test_paths(files: list[str]) -> list[str]:
    found = set()
    for rel in files:
        low = rel.lower()
        if "/test/" in f"/{low}" or "/tests/" in f"/{low}" or "/spec/" in f"/{low}":
            top = rel.split("/")[0]
            found.add(f"{top}/**" if "/" in rel and top in ("test", "tests", "spec") else "**/test/**")
        if re.search(r"(_test\.|\.test\.|\.spec\.|test_.*\.py$)", low):
            found.add("**/*_test.*")
            found.add("**/*.test.*")
            found.add("**/*.spec.*")
            found.add("**/test_*.py")
    return sorted(found) or ["**/test/**", "**/tests/**", "**/*_test.*", "**/*.test.*"]


def _migration_paths(files: list[str]) -> list[str]:
    found = set()
    for rel in files:
        parts = rel.split("/")
        for i, part in enumerate(parts[:-1]):
            if part in ("migrations", "migrate", "alembic", "db"):
                found.add("/".join(parts[: i + 1]) + "/**")
    return sorted(found) or ["**/migrations/**"]


def _generated_paths(fileset: set[str]) -> list[str]:
    base = ["**/*.lock", "**/dist/**", "**/build/**", "**/__generated__/**", "**/*.snap",
            ".aegis/generated/**"]
    for lock in ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "Cargo.lock",
                 "composer.lock", "Gemfile.lock", "go.sum"):
        if lock in fileset:
            base.append(lock)
    return sorted(set(base))


def _manifest_blob(ctx: Ctx, files: list[str]) -> str:
    """Every build manifest's text, lowercased: what the dependency detectors read."""
    blob = ""
    for rel in files:
        if os.path.basename(rel) in ("package.json", "pyproject.toml", "requirements.txt",
                                     "go.mod", "Cargo.toml", "Gemfile", "composer.json"):
            blob += read_text(os.path.join(ctx.root, rel), default="").lower()
    return blob


def _layout(files: list[str]) -> set[str]:
    return {p.split("/")[0] for p in files if "/" in p} | {os.path.basename(p) for p in files}


def _api_contract(fileset: set[str]) -> str | None:
    """The published API description, when the project has one.

    Without it the route check has nothing authoritative to compare against and stays quiet,
    which is better than inventing a registry for every internal endpoint.
    """
    for candidate in ("openapi.json", "openapi.yaml", "openapi.yml", "swagger.json",
                      "api/openapi.yaml", "docs/openapi.yaml", "schema.graphql", "api.proto"):
        if candidate in fileset:
            return candidate
    return None


def _shared_paths(files: list[str]) -> list[str]:
    """Paths several tasks legitimately touch, so `check trace` does not call them orphans.

    The agent pointer files belong here because the framework writes them itself: leaving
    them out makes `aegis init` produce a repository whose very first gate run fails on
    files it just created.
    """
    shared = ["README.md", "CHANGELOG.md", ".github/**", "CLAUDE.md", "AGENTS.md"]
    for rel in files:
        if os.path.basename(rel) in ("package.json", "go.mod", "Cargo.toml", "pyproject.toml") and "/" not in rel:
            shared.append(rel)
    return sorted(set(shared))


def _frozen_candidates(files: list[str]) -> list[str]:
    candidates = set()
    for rel in files:
        top = rel.split("/")[0]
        if top in ("vendor", "third_party", "legacy", "archive", "generated", "proto"):
            candidates.add(f"{top}/**")
    return sorted(candidates)


def _brownfield(ctx: Ctx, files: list[str]) -> bool:
    code = [f for f in files if f.endswith(CODE_EXT)]
    if len(code) > 5:
        return True
    if git_available(ctx):
        commits = git(ctx, "rev-list", "--count", "HEAD").strip()
        return commits.isdigit() and int(commits) > 3
    return False
