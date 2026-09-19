"""Shared primitives: paths, canonical JSON, token estimation, git, schema validation.

Every Aegis check is a pure core plus a thin caller. Nothing here reads global state
except through `Ctx`, so checks stay unit-testable and reproducible.
"""
from __future__ import annotations

import datetime as _dt
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Iterable

AEGIS_DIR = ".aegis"
GENERATED = "generated"


# --------------------------------------------------------------------------- context


class AegisError(Exception):
    """Fatal, user-facing error. Printed without a traceback."""


@dataclass
class Ctx:
    root: str

    @property
    def aegis(self) -> str:
        return os.path.join(self.root, AEGIS_DIR)

    def path(self, *parts: str) -> str:
        return os.path.join(self.aegis, *parts)

    def gen(self, *parts: str) -> str:
        return os.path.join(self.aegis, GENERATED, *parts)

    def real(self, path: str) -> str:
        """Absolute path with symlinks resolved.

        A lease check on the lexical name approves `src/orders/policy` while the write lands
        on whatever it points at — including the constitution. Ownership has to be decided
        about the file, not about the spelling.
        """
        return os.path.realpath(os.path.abspath(path))

    def rel(self, abspath: str) -> str:
        """Repo-relative when the file is inside the project, absolute when it is not.

        Plugin assets live outside the project, and `os.path.relpath` would render them as a
        chain of `../..` that is unreadable and breaks the moment anything moves.
        """
        full = os.path.abspath(abspath)
        root = os.path.abspath(self.root)
        if full == root or full.startswith(root + os.sep):
            return os.path.relpath(full, root)
        return full

    def exists(self, *parts: str) -> bool:
        return os.path.exists(self.path(*parts))


def plugin_root() -> str:
    """Where the framework itself lives.

    Installed as a Claude Code plugin this is `${CLAUDE_PLUGIN_ROOT}`; run from a checkout
    it is the repository containing `scripts/aegis/`. Resolving it in one place keeps the
    two deployment shapes from drifting apart.
    """
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env and os.path.isdir(env):
        return os.path.abspath(env)
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))


def asset_dirs(ctx: "Ctx", name: str) -> list[str]:
    """Framework assets, then project overrides. Later entries win by convention."""
    candidates = [os.path.join(plugin_root(), name), os.path.join(ctx.root, ".claude", name), ctx.path(name)]
    seen, out = set(), []
    for path in candidates:
        real = os.path.realpath(path)
        if os.path.isdir(path) and real not in seen:
            seen.add(real)
            out.append(path)
    return out


def find_root(start: str | None = None) -> str:
    """Nearest ancestor containing .aegis/, else nearest git root, else cwd."""
    cur = os.path.abspath(start or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    probe = cur
    while True:
        if os.path.isdir(os.path.join(probe, AEGIS_DIR)):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    probe = cur
    while True:
        # `.git` is a file in a linked worktree. Requiring a directory here meant that in a
        # worktree the search walked past the real root and initialised a subdirectory.
        if os.path.exists(os.path.join(probe, ".git")):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            return cur
        probe = parent


# ------------------------------------------------------------------------------- io


def read_text(path: str, default: str | None = None) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        if default is None:
            raise AegisError(f"missing file: {path}")
        return default


def write_text(path: str, content: str) -> bool:
    """Write only when content differs. Returns True when the file changed."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            if fh.read() == content:
                return False
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return True


def read_json(path: str, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        if default is None:
            raise AegisError(f"missing file: {path}")
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AegisError(f"{path}: invalid JSON at line {exc.lineno}: {exc.msg}") from exc


def canonical(data: Any) -> str:
    """Canonical serialization. Stable key order and indentation make every
    generated artifact byte-reproducible, which is what drift detection compares."""
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def write_json(path: str, data: Any) -> bool:
    return write_text(path, canonical(data))


def read_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def append_jsonl(path: str, record: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


# --------------------------------------------------------------------------- tokens


# Scripts that tokenize far denser than Latin: Cyrillic, Greek, Hebrew, Arabic, CJK.
_NON_LATIN = re.compile(r"[\u0370-\u1CFF\u2C00-\uD7FF\uF900-\uFAFF]")
_WORD = re.compile(r"\w+", re.UNICODE)


def estimate_tokens(text: str) -> int:
    """Character-class weighted estimate of Claude tokens.

    Deliberately an estimate, not a claim: no tokenizer ships with Python. Latin prose runs
    ~3.7 chars/token, code and punctuation-dense JSON ~3.1, and non-Latin scripts around 2.0
    because their words split into several byte-level pieces. Budgets are calibrated against
    this function, so it only has to be consistent, not exact. A project needing exactness
    sets AEGIS_TOKENIZER to a command that reads stdin and prints a count.
    """
    if not text:
        return 0
    hook = os.environ.get("AEGIS_TOKENIZER")
    if hook:
        try:
            out = subprocess.run(
                hook, shell=True, input=text, capture_output=True, text=True, timeout=60
            )
            if out.returncode == 0 and out.stdout.strip().isdigit():
                return int(out.stdout.strip())
        except Exception:
            pass  # fall through to the estimate
    dense = len(_NON_LATIN.findall(text))
    total = len(text)
    latin = total - dense
    non_word = total - sum(len(m.group()) for m in _WORD.finditer(text))
    density = 3.7 if non_word / max(total, 1) < 0.22 else 3.1
    return int(round(latin / density + dense / 2.0))


def tokens_of_file(path: str) -> int:
    try:
        return estimate_tokens(read_text(path))
    except AegisError:
        return 0


def human_tokens(n: int) -> str:
    return f"{n/1000:.1f}k" if n >= 1000 else str(n)


# ------------------------------------------------------------------------------ git


def git(ctx: Ctx, *args: str, check: bool = False) -> str:
    proc = subprocess.run(
        ("git", "-C", ctx.root) + args, capture_output=True, text=True
    )
    if check and proc.returncode != 0:
        raise AegisError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def git_available(ctx: Ctx) -> bool:
    # `.git` is a *file* in a linked worktree and a submodule. Testing only for a directory
    # silently classified every worktree as "not a repository", which made every diff-scoped
    # check return an empty scope — a green gate that had inspected nothing.
    return os.path.exists(os.path.join(ctx.root, ".git"))


def working_tree_files(ctx: Ctx) -> list[str]:
    # `--untracked-files=all` matters: the default collapses a new directory to `src/`,
    # which then matches no task lease and hides every check that works per file.
    # `-z` matters too: without it a path containing a space arrives quoted, and every later
    # comparison is against a name no file has.
    out = git(ctx, "status", "--porcelain", "--untracked-files=all", "-z")
    files, records = [], [r for r in out.split("\0") if r]
    skip_next = False
    for record in records:
        if skip_next:
            # The source of a rename is removed from its old place — that is a change to the
            # old path, and scope must see it. A copy's source is untouched and stays out.
            if skip_next == "rename":
                files.append(record)
            skip_next = False
            continue
        if len(record) > 3:
            # By letter, not by listed pairs: `RD`, `RT` and the rest also carry their source
            # as the next record, and a missed pair read that source as a path of its own.
            if "R" in record[:2]:
                skip_next = "rename"
            elif "C" in record[:2]:
                skip_next = "copy"
            files.append(record[3:])
    return files


def changed_files(ctx: Ctx, base: str | None, head: str = "HEAD") -> list[str]:
    """Every file this task has touched: committed since `base`, plus the working tree.

    The union is the point. Returning only the committed diff whenever one exists hides
    uncommitted work from the lenses, the trace check and package selection — the reviewer
    then passes a diff that is not the diff, and the gate is green on code nobody read.
    """
    if not git_available(ctx):
        return []
    files: set[str] = set()
    if not base and git_available(ctx):
        # A task created before the first commit records no base. Once it commits, the
        # working tree is clean and only the empty tree can still show its work — testing
        # for "HEAD exists now" made the code vanish the moment it was committed.
        base = EMPTY_TREE
    if base:
        if base != EMPTY_TREE and not ref_exists(ctx, base):
            # Falling back silently would report a working-tree diff as if it were the
            # requested comparison, and every scoped check downstream would be wrong.
            raise AegisError(f"unknown git ref {base!r}; nothing to compare against")
        # Two dots against the empty tree: `A...B` asks for changes since the merge base, and
        # the empty tree shares no history with anything, so the three-dot form returns
        # nothing — silently emptying the scope for exactly the repositories this covers.
        spec = [base, head] if base == EMPTY_TREE else [f"{base}...{head}"]
        # `-z`: without it git quotes a path with non-ASCII bytes, and the quoted name matches
        # no file, no lease and no baseline entry.
        files.update(f for f in git(ctx, "diff", "--name-only", "--no-renames", "-z", *spec).split("\0") if f)
    files.update(f for f in working_tree_files(ctx) if f)
    files -= _pre_adoption_files(ctx, files)
    return sorted(files)


def untracked_files(ctx: Ctx) -> set[str]:
    out = git(ctx, "ls-files", "--others", "--exclude-standard", "-z")
    return {f for f in out.split("\0") if f}


def file_sha256(path: str) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


ABSENT = "absent"  # what the baseline records for a path that was missing at adoption


def content_key(full: str) -> str | None:
    """What the baseline records for a path on disk, or None when there is nothing there.

    A symlink is recorded as its target, not as the bytes it points at: `file_sha256` follows
    the link, so replacing a recorded file with a symlink to identical content left the path
    attributed to adoption while `diff_digest` — which hashes the type and the target — counted
    the same swap as a change.
    """
    if os.path.islink(full):
        return "symlink:" + os.readlink(full)
    if os.path.isfile(full):
        try:
            return file_sha256(full)
        except OSError:
            return None
    return None


def _git_key(mode: str, blob: bytes) -> str:
    """What git holds, in the namespace `content_key` records, so the two can be compared.

    Git stores a symlink as a blob holding its target, and `content_key` records a link as
    `symlink:<target>`. Hashing that blob gave a 64-hex digest that could never equal the
    record, so a baselined symlink was never in the adoption state at HEAD: it stayed in the
    scope of every task and the baseline could not retire by being committed, which is the one
    thing ADR-4 exists to make possible.
    """
    if mode == "120000":
        return "symlink:" + blob.decode("utf-8", "surrogateescape")
    # Bytes, not text: a baseline covers binary files too, and decoding them would make two
    # different files hash the same.
    return hashlib.sha256(blob).hexdigest()


def _blob_key(ctx: Ctx, mode: str, sha: str) -> str | None:
    proc = subprocess.run(("git", "-C", ctx.root, "cat-file", "blob", sha), capture_output=True)
    if proc.returncode != 0:
        return None
    return _git_key(mode, proc.stdout)


def _digest_at(ctx: Ctx, rev: str, rel: str) -> str | None:
    """What `rev` holds at `rel`, keyed as the baseline records it, or None when it holds nothing.

    `ls-tree` rather than `show`, because the mode is part of the answer and `show` drops it.
    """
    entry = git(ctx, "ls-tree", rev, "--", rel).split(maxsplit=3)
    if len(entry) < 3 or entry[1] != "blob":
        return None  # missing, a directory, or a submodule: nothing a baseline records
    return _blob_key(ctx, entry[0], entry[2])


def _digest_in_index(ctx: Ctx, rel: str) -> str | None:
    entry = git(ctx, "ls-files", "-s", "--", rel).split()
    if len(entry) < 2:
        return None
    return _blob_key(ctx, entry[0], entry[1])


def _is_adoption_state(record: str, digest: str | None, at_baseline_head: str | None,
                       absence_is_removal: bool) -> bool:
    """Does a git location still hold the adoption state for this path?

    Three ways to say yes: it holds exactly what was recorded, which is what the adoption commit
    puts there; it holds what the baseline head held, so nothing has been recorded for it since;
    or it holds nothing and nothing was ever expected there.

    That last one is why `absence_is_removal` exists. For a path untracked at adoption, HEAD
    holding nothing is the ordinary case. The index holding nothing, while a removal is staged
    for it, is a deletion someone is about to commit — and reading the two as the same thing let
    a staged `git rm` of a baselined file reach a commit unowned and unreviewed.
    """
    if digest is None:
        if record == ABSENT:
            return True
        return not absence_is_removal and at_baseline_head is None
    if digest == record:
        return True
    return at_baseline_head is not None and digest == at_baseline_head


def _staged_raw(ctx: Ctx) -> list[str]:
    # `--no-renames`: a staged `git mv src/auth.py .aegis/runs/T/k.py` otherwise lists only the
    # new path, and the deletion of src/auth.py reached a commit unowned and unreviewed.
    if not git_available(ctx):
        return []
    return sorted(f for f in git(ctx, "diff", "--cached", "--name-only", "--no-renames", "-z").split("\0") if f)


def _pre_adoption_files(ctx: Ctx, files: set[str]) -> set[str]:
    """Paths that are still exactly as the repository left them at adoption.

    `legacy_baseline: ratchet-from-today` promises that adopting Aegis does not turn the whole
    repository red on day one. On a committed tree the diff against `base_sha` keeps that
    promise by itself; on a tree with uncommitted work — the common state of a repository
    someone is trying a tool on — every uncommitted file counted as changed by the first task,
    so `trace`, the environment scan and the lenses all judged code the task never touched.
    `aegis init` records those files and their content hashes once, and a path missing at
    adoption as `absent`.

    Attribution is by content, not by history (ADR-4). A path is attributed to adoption while
    the working tree holds its record, nothing different is staged for it, and no commit has
    recorded anything else for it. So committing the adoption state keeps it attributed to
    adoption — that is how a repository retires its baseline — while a commit that records
    different content, even if the working tree is put back afterwards, puts the path in scope.
    """
    if not files:
        return set()
    recorded = read_json(os.path.join(ctx.root, ".aegis", "generated", "capabilities.json"),
                         default={}).get("baseline") or {}
    baseline = {rel: value for rel, value in (recorded.get("files") or {}).items()
                if not rel.startswith((".aegis/", ".agents/"))}
    if not baseline:
        return set()
    # The recorder excludes framework state; so does the consumer. Trusting the record verbatim
    # meant a write to answers.json could baseline any path — answers.json included — and the
    # path then left `changed_files`, the digest and every lens diff, concealing the widening.
    policy = read_json(os.path.join(ctx.root, ".aegis", "generated", "policy.json"), default={})
    if policy.get("legacy_baseline", "ratchet-from-today") != "ratchet-from-today":
        return set()
    head = recorded.get("head")
    known_head = bool(head) and ref_exists(ctx, head)
    since = f"{head}..HEAD" if known_head else "HEAD"
    # Two cheap queries decide which paths need any git inspection at all: one for the names
    # commits have touched since adoption, one for what is staged now.
    touched = {f for f in git(ctx, "log", "-z", "--no-renames", "--name-only", "--format=", since).split("\0")
               if f.strip()} if ref_exists(ctx, "HEAD") else set()
    staged = set(_staged_raw(ctx))
    exempt: set[str] = set()
    for rel in files & set(baseline):
        record = baseline[rel]
        full = os.path.join(ctx.root, rel)
        if record == ABSENT:
            if os.path.lexists(full):
                continue  # it came back; whoever brought it back owns it
        elif content_key(full) != record:
            continue
        at_baseline_head = _digest_at(ctx, head, rel) if known_head else None
        if rel in touched and not _is_adoption_state(
                record, _digest_at(ctx, "HEAD", rel), at_baseline_head, absence_is_removal=False):
            continue
        # A path in the staged set is one the index has something to say about, so nothing there
        # means a removal is staged rather than "it was never tracked".
        if rel in staged and not _is_adoption_state(
                record, _digest_in_index(ctx, rel), at_baseline_head, absence_is_removal=True):
            continue
        exempt.add(rel)
    return exempt


def _is_task_manifest(rel: str) -> bool:
    """`.aegis/runs/<TASK>/manifest.json` and nothing else.

    Matching any `*/manifest.json` meant a web app's `public/manifest.json` was hashed as a
    task contract — five keys an ordinary manifest does not have, so its bytes never entered
    the digest and a change to it after a review stayed certified as reviewed.
    """
    return rel.startswith(".aegis/runs/") and rel.endswith("/manifest.json")


def in_review_scope(rel: str) -> bool:
    """Is this path part of the change a review is a verdict on?

    One answer, used by `diff_digest` and by `task_diff`, because two copies of this rule
    disagreed: `.aegis/waivers.json` was inside the digest and outside the diff, so the
    review meant to be the control on a waiver could not see the waiver. A comment claiming
    the two filters were "mirrored exactly" is not a mechanism; calling the same function is.

    Bookkeeping is out — recording a review must not invalidate the review being recorded.
    The *contract* is in: specifications, the task manifest, `answers.json` (it recompiles
    every rule) and `waivers.json` (it silences checks), because a verdict on code that met
    the old terms says nothing about the new ones.
    """
    if rel in ("CLAUDE.md", "AGENTS.md"):
        return False
    if rel.startswith(".aegis/"):
        return (rel.startswith(".aegis/specs/") or rel == ".aegis/answers.json"
                or rel == ".aegis/waivers.json" or _is_task_manifest(rel))
    return True


def diff_digest(ctx: Ctx, base: str | None) -> str:
    """Identity of the current change set: content, not just file names.

    A review is evidence only about the code it read. Binding a lens report to this digest
    is what stops "the security lens passed" from surviving an edit made afterwards.
    """
    hasher = hashlib.sha256()
    for rel in changed_files(ctx, base):
        if not in_review_scope(rel):
            continue
        if _is_task_manifest(rel):
            # The contract half of the manifest only: requirements, acceptance, lease.
            try:
                data = json.loads(read_text(os.path.join(ctx.root, rel)))
                contract = {k: data.get(k) for k in
                            ("requirements", "acceptance", "owns", "feature", "objective")}
                hasher.update(rel.encode("utf-8"))
                hasher.update(canonical(contract).encode("utf-8"))
                continue
            except Exception:
                pass
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        full = os.path.join(ctx.root, rel)
        try:
            # Mode and type matter: making a script executable, or replacing a file with a
            # symlink, changes what runs without changing a byte of content.
            stat = os.lstat(full)
            hasher.update(f"{stat.st_mode & 0o777}:{'L' if os.path.islink(full) else 'F'}".encode())
            if os.path.islink(full):
                hasher.update(os.readlink(full).encode("utf-8"))
            else:
                with open(full, "rb") as fh:
                    hasher.update(hashlib.sha256(fh.read()).digest())
        except (OSError, IsADirectoryError):
            hasher.update(b"<absent>")
        hasher.update(b"\n")
    return hasher.hexdigest()[:16]


def staged_files(ctx: Ctx) -> list[str]:
    """What is staged, minus what adoption accounts for.

    The merge stage unions this with `changed_files`, which applies the adoption baseline. While
    this half did not, a baselined path that was merely staged — the destination of a rename
    prepared before adoption, for instance — was unowned at the merge gate and nothing could own
    it, because the path a lease would need may sit in a frozen zone.
    """
    if not git_available(ctx):
        return []
    files = set(_staged_raw(ctx))
    return sorted(files - _pre_adoption_files(ctx, files))


EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_SHA = re.compile(r"^[0-9a-f]{40}$")


def head_sha(ctx: Ctx) -> str | None:
    """None on an unborn branch.

    `git rev-parse HEAD` prints the literal string `HEAD` to stdout *and* exits non-zero
    when there are no commits, so taking stdout at face value bakes `"base_sha": "HEAD"`
    into every manifest created before the first commit.
    """
    out = git(ctx, "rev-parse", "HEAD").strip()
    return out if _SHA.match(out) else None


def ref_exists(ctx: Ctx, ref: str) -> bool:
    return bool(git(ctx, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").strip())


def merge_base(ctx: Ctx, ref: str) -> str | None:
    out = git(ctx, "merge-base", "HEAD", ref).strip()
    return out or None


def default_base(ctx: Ctx) -> str | None:
    """Where this branch left the mainline, or None when no mainline ref exists.

    The merge stage's scope and the base-agreement check in `trace` both need one answer to
    "what did this branch inherit", so it lives beside `merge_base` rather than in the flow
    that happened to need it first.
    """
    for ref in ("origin/HEAD", "origin/main", "main", "master"):
        base = merge_base(ctx, ref)
        if base:
            return base
    return None


def is_ancestor(ctx: Ctx, older: str, newer: str) -> bool:
    return bool(older) and git(ctx, "merge-base", older, newer).strip() == older




# ---------------------------------------------------------------------------- globs


def normalise_glob(pattern: str) -> str:
    """`./src//foo/**` and `src/foo/**` are the same lease and must compare equal."""
    pattern = pattern.strip().replace("\\", "/")
    while pattern.startswith("./"):
        pattern = pattern[2:]
    while "//" in pattern:
        pattern = pattern.replace("//", "/")
    return pattern.lstrip("/")


def glob_head(pattern: str) -> str:
    """The literal path prefix before the first wildcard. `src/billing/**` -> `src/billing/`."""
    cut = len(pattern)
    for i, ch in enumerate(pattern):
        if ch in "*?[":
            cut = i
            break
    return pattern[:cut]


def _glob_depth(pattern: str) -> int | None:
    """How many path segments the pattern matches, or None when it spans any depth."""
    return None if "**" in pattern else pattern.count("/") + 1


def globs_overlap(a: str, b: str) -> bool:
    """Can two write leases claim the same file?

    An exact string comparison answers "are these the same pattern", which is a weaker and
    different question: `src/foo/**` and `src/foo/bar.py` are different strings that both own
    `bar.py`. Two agents handed those leases collide silently — the exact failure the lease
    exists to prevent.

    Conservative where it is genuinely ambiguous, precise where it can be: a false conflict
    costs one clarifying decomposition, a missed one costs a lost write nobody can attribute.
    """
    a, b = normalise_glob(a), normalise_glob(b)
    if a == b:
        return True

    head_a, head_b = glob_head(a), glob_head(b)
    if (head_a and matches_any(head_a.rstrip("/"), [b])) or (head_b and matches_any(head_b.rstrip("/"), [a])):
        return True

    depth_a, depth_b = _glob_depth(a), _glob_depth(b)

    # Neither spans arbitrary depth: they collide exactly when they sit at the same depth
    # and every segment pair is mutually satisfiable. Comparing segments only when both
    # patterns were rooted wildcards missed the common case — `src/foo/*.py` against
    # `src/foo/bar.*`, which share a literal head and both own `src/foo/bar.py`.
    if depth_a is not None and depth_b is not None:
        if depth_a != depth_b:
            return False
        return all(_segments_compatible(sa, sb) for sa, sb in zip(a.split("/"), b.split("/")))

    if head_a == head_b:
        # Same anchor. When either side spans arbitrary depth the only thing that can
        # separate them is the final segment: `src/**/config.py` and `src/*/config.py` both
        # own `src/api/config.py`, and comparing the whole remainder said otherwise.
        rest_a, rest_b = a[len(head_a):], b[len(head_b):]
        if "**" in rest_a or "**" in rest_b:
            return _segments_compatible(rest_a.rsplit("/", 1)[-1], rest_b.rsplit("/", 1)[-1])
        return _segments_compatible(rest_a, rest_b)
    if not head_a or not head_b:
        # One side is wildcarded from the root and the other spans arbitrary depth: the
        # direct matches above already settled the clear cases, so resolve conservatively.
        return True

    shallow, deep, shallow_pattern = (
        (head_a, head_b, a) if len(head_a) <= len(head_b) else (head_b, head_a, b)
    )
    if deep.startswith(shallow) and shallow != deep:
        return "**" in shallow_pattern
    return False


def _segments_compatible(x: str, y: str) -> bool:
    """Could one path segment satisfy both patterns?

    `*.py` and `*.ts` cannot. `*.py` and `bar.*` can — `bar.py` satisfies both — and probing
    with a single placeholder missed exactly that case, which is how two overlapping leases
    were accepted as disjoint.

    The probe set is built from each pattern's literal runs substituted into the other's
    wildcards. That is not a general regular-language intersection, but it decides every
    shape a write lease is written in, and it errs toward declaring a conflict.
    """
    if x == y:
        return True
    if "*" not in x and "?" not in x and "[" not in x and "*" not in y and "?" not in y and "[" not in y:
        return False
    for candidate in _probes(x, y) | _probes(y, x):
        if fnmatch.fnmatch(candidate, x) and fnmatch.fnmatch(candidate, y):
            return True
    return False


_LITERAL_RUN = re.compile(r"[^*?\[\]]+")


def _class_sample(match: re.Match) -> str:
    """A character the class admits. For `[!abc]` that must be one it does not list."""
    negated, body = match.group(1) == "!", match.group(2)
    if not negated:
        return (body or "x")[:1]
    for candidate in "xyzabcdefghijklmnopqrstuvw0123456789":
        if candidate not in body:
            return candidate
    return "x"


def _probes(pattern: str, other: str) -> set[str]:
    """Concrete names `pattern` matches, biased toward also matching `other`."""
    fillers = {"x", ""} | set(_LITERAL_RUN.findall(other))
    out: set[str] = set()
    for filler in fillers:
        candidate = pattern.replace("**", filler).replace("*", filler).replace("?", filler[:1] or "x")
        # Expand a positive class into each of its members: `[ab]` against `[!a]` overlaps on
        # `b`, and sampling only the first member missed it.
        classes = re.findall(r"\[(!?)([^\]]*)\]", candidate)
        if classes and not classes[0][0] and len(classes[0][1]) <= 8:
            for member in classes[0][1]:
                out.add(re.sub(r"\[!?[^\]]*\]", member, candidate, count=1))
        out.add(re.sub(r"\[(!?)([^\]]*)\]", _class_sample, candidate))
    return out


_GLOB_CACHE: dict[str, re.Pattern] = {}


def glob_regex(pattern: str) -> re.Pattern:
    """Path-aware glob translation: `*` stops at a separator, `**` crosses them.

    `fnmatch` lets `*` cross `/`, so `src/*.py` matched `src/deep/nested/file.py` — a lease
    silently owning an entire subtree it never named.
    """
    pattern = normalise_glob(pattern)
    cached = _GLOB_CACHE.get(pattern)
    if cached:
        return cached
    out, i, n = [], 0, len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "*":
            if pattern[i:i + 2] == "**":
                if pattern[i:i + 3] == "**/":
                    out.append("(?:.*/)?")
                    i += 3
                    continue
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
            i += 1
            continue
        if ch == "?":
            out.append("[^/]")
        elif ch == "[":
            end = pattern.find("]", i)
            if end == -1:
                out.append(r"\[")
            else:
                body = pattern[i + 1:end]
                # Glob spells negation `[!abc]`; a regex character class spells it `[^abc]`.
                # Passing it through unchanged made `[!a]` *permit* `a`, inverting the rule.
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append(f"[{body}]")
                i = end + 1
                continue
        else:
            out.append(re.escape(ch))
        i += 1
    compiled = re.compile("^" + "".join(out) + "$")
    _GLOB_CACHE[pattern] = compiled
    return compiled


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    """Glob match with `**` support, evaluated against a repo-relative path."""
    path = normalise_glob(path)
    for pat in patterns:
        pat = normalise_glob(pat)
        if glob_regex(pat).match(path):
            return True
        # `src/foo/**` also owns the directory `src/foo` itself.
        if pat.endswith("/**") and (path == pat[:-3] or path.startswith(pat[:-3] + "/")):
            return True
    return False


# --------------------------------------------------------------------- findings/report


SEVERITY_ORDER = {"fail": 0, "warn": 1, "info": 2}


@dataclass
class Finding:
    check: str
    severity: str  # fail | warn | info
    message: str
    path: str | None = None
    hint: str | None = None

    def render(self) -> str:
        mark = {"fail": "FAIL", "warn": "warn", "info": "info"}[self.severity]
        loc = f" {self.path}" if self.path else ""
        line = f"  [{mark}] {self.check}:{loc} {self.message}"
        if self.hint:
            line += f"\n         fix: {self.hint}"
        return line


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, *findings: Finding) -> None:
        self.findings.extend(findings)

    def fail(self, check: str, message: str, path: str | None = None, hint: str | None = None):
        self.add(Finding(check, "fail", message, path, hint))

    def warn(self, check: str, message: str, path: str | None = None, hint: str | None = None):
        self.add(Finding(check, "warn", message, path, hint))

    def info(self, check: str, message: str, path: str | None = None):
        self.add(Finding(check, "info", message, path))

    def note(self, text: str) -> None:
        self.notes.append(text)

    @property
    def failed(self) -> bool:
        return any(f.severity == "fail" for f in self.findings)

    def extend(self, other: "Report") -> None:
        self.findings.extend(other.findings)
        self.notes.extend(other.notes)

    def render(self, title: str) -> str:
        lines = [title]
        lines.extend(f"  {n}" for n in self.notes)
        ordered = sorted(self.findings, key=lambda f: SEVERITY_ORDER[f.severity])
        lines.extend(f.render() for f in ordered)
        if not self.findings:
            lines.append("  ok")
        return "\n".join(lines)


# -------------------------------------------------------------- mini JSON Schema


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _valid_date(value: str) -> bool:
    # A regex alone accepts 2026-99-99, and `fromisoformat` alone accepts `20260101` and
    # `2026-W01-1` — spellings that sort above an ISO date, so an expiry written that way
    # never expires. Both checks, one shape.
    if not _ISO_DATE.match(value or ""):
        return False
    try:
        _dt.date.fromisoformat(value)
        return True
    except ValueError:
        return False


_FORMATS = {
    "date": _valid_date,
    "uri-reference": lambda v: bool(v) and not v.isspace(),
}


def validate(data: Any, schema: dict, path: str = "$") -> list[str]:
    """Validating subset of JSON Schema draft 2020-12.

    Supports: type, enum, const, required, properties, patternProperties,
    additionalProperties, items, uniqueItems, min/maxItems, min/maxLength, pattern,
    minimum, maximum, format, oneOf, anyOf, allOf, not, if/then/else. Anything outside
    that list is ignored, so registry schemas stay inside the subset by convention —
    a schema that reaches for $ref or unevaluatedProperties will pass silently and is
    therefore a review finding, not a runtime error.
    """
    errors: list[str] = []
    if not isinstance(schema, dict):
        return errors

    t = schema.get("type")
    if t:
        types = t if isinstance(t, list) else [t]
        if not any(_is_type(data, one) for one in types):
            return [f"{path}: expected {'/'.join(types)}, got {_type_name(data)}"]

    if "const" in schema and data != schema["const"]:
        errors.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and data not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']}")

    if isinstance(data, str):
        if "pattern" in schema and not re.search(schema["pattern"], data):
            errors.append(f"{path}: {data!r} does not match /{schema['pattern']}/")
        if "minLength" in schema and len(data) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(data) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
        fmt = schema.get("format")
        if fmt in _FORMATS and not _FORMATS[fmt](data):
            errors.append(f"{path}: {data!r} is not a valid {fmt}")

    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if "minimum" in schema and data < schema["minimum"]:
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and data > schema["maximum"]:
            errors.append(f"{path}: above maximum {schema['maximum']}")

    if isinstance(data, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(data):
                errors.extend(validate(item, item_schema, f"{path}[{i}]"))
        if "minItems" in schema and len(data) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            seen = [json.dumps(x, sort_keys=True) for x in data]
            if len(set(seen)) != len(seen):
                errors.append(f"{path}: items must be unique")

    if isinstance(data, dict):
        props = schema.get("properties", {})
        pattern_props = schema.get("patternProperties", {})
        for key in schema.get("required", []):
            if key not in data:
                errors.append(f"{path}: missing required property {key!r}")
        for key, value in data.items():
            child = f"{path}.{key}"
            if key in props:
                errors.extend(validate(value, props[key], child))
                continue
            matched = False
            for pat, sub in pattern_props.items():
                if re.search(pat, key):
                    errors.extend(validate(value, sub, child))
                    matched = True
                    break
            if matched:
                continue
            if schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected property {key!r}")
            elif isinstance(schema.get("additionalProperties"), dict):
                errors.extend(validate(value, schema["additionalProperties"], child))

    for combinator in ("allOf",):
        for sub in schema.get(combinator, []):
            errors.extend(validate(data, sub, path))
    if "anyOf" in schema:
        if not any(not validate(data, sub, path) for sub in schema["anyOf"]):
            errors.append(f"{path}: matches none of the allowed shapes")
    if "oneOf" in schema:
        hits = sum(1 for sub in schema["oneOf"] if not validate(data, sub, path))
        if hits != 1:
            errors.append(f"{path}: must match exactly one allowed shape (matched {hits})")
    if "not" in schema and not validate(data, schema["not"], path):
        errors.append(f"{path}: must not match the forbidden shape")
    if "if" in schema:
        branch = "then" if not validate(data, schema["if"], path) else "else"
        if branch in schema:
            errors.extend(validate(data, schema[branch], path))
    return errors


def _is_type(value: Any, name: str) -> bool:
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    return True


def _type_name(value: Any) -> str:
    for name in ("null", "boolean", "integer", "number", "string", "array", "object"):
        if _is_type(value, name):
            return name
    return "unknown"


# ------------------------------------------------------------------------- printing


def emit(text: str) -> None:
    sys.stdout.write(text.rstrip("\n") + "\n")


def die(message: str, code: int = 1) -> None:
    sys.stderr.write(f"aegis: {message}\n")
    raise SystemExit(code)
