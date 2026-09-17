"""Round-3 findings on TASK-UNBLOCK-01: the commit-hook exemption class survived three rounds.
Simplify by deletion: exempt only the exact bookkeeping command; detect git in tested Python;
stop exempting a baselined file once a commit touched it; refuse the bare lens name."""
import os, sys, io, re
ROOT = os.environ["AEGIS_PATCH_ROOT"]
def rd(rel): return io.open(f"{ROOT}/{rel}",encoding="utf-8").read()
def wr(rel,t): io.open(f"{ROOT}/{rel}","w",encoding="utf-8").write(t)
def patch(rel, old, new, count=1):
    p=f"{ROOT}/{rel}"; t=io.open(p,encoding="utf-8").read()
    if new and new in t:
        print("already",rel); return
    n=t.count(old)
    if n!=count: sys.exit(f"{rel}: expected {count}, found {n}:\n{old[:220]!r}")
    io.open(p,"w",encoding="utf-8").write(t.replace(old,new)); print("patched",rel)
CORE="scripts/aegis/aegis_cli/core.py"; FLOW="scripts/aegis/aegis_cli/flow.py"

t=rd(CORE)
_already_core = "_BOOKKEEPING = re.compile" in t
start=t.index("# What a `git commit` would contain, decided from the command text alone") if not _already_core else 0
end=t.index("def untracked_files(ctx: Ctx) -> set[str]:") if not _already_core else 0
if _already_core:
    print("already core commit_scope")
else:
  t=t[:start]+'''# The commit hook's decision, made from the command text in tested Python rather than in shell.
#
# Detection over-approximates the ordinary spellings of running git — `git`, `\\git`,
# `/usr/bin/git`, a quoted "git", behind `command`/`env`/`exec` or variable assignments — and
# stays clear of a quoted phrase such as `grep "git commit"`. It is an early error, not a
# barrier: a shell can always construct a command no pattern recognises, which is why landing
# requires a passing merge gate and a gate receipt.
#
# The one exemption is the exact bookkeeping command the shipped workflow runs. Three review
# rounds each found a new way through a parser that tried to decide what an arbitrary commit
# would record (a second line, `bash -c`, `GIT_INDEX_FILE`, a staged rename, `$(…)` inside a
# message, git's abbreviated `--inc`). The parser was deleted; an exact match has nothing to
# get around.
_GIT_COMMIT_OR_PUSH = re.compile(
    r"(?:^|[\\s;&|(){}])"
    r"(?:(?:command|exec|env|nice|time|sudo)\\s+(?:-\\S+\\s+)*)*"
    r"(?:[A-Za-z_][A-Za-z0-9_]*=\\S*\\s+)*"
    r"\\\\?(?:[^\\s;&|\\"']*/)?(?P<q>[\\"']?)git(?P=q)"
    r"(?:\\s+(?:-C|-c|--git-dir|--work-tree|--namespace)\\s+\\S+|\\s+-\\S+)*"
    r"\\s+(?P<r>[\\"']?)(?:commit|push)(?P=r)(?=\\s|$|[;&|)}])")
_TASK_ID = r"[A-Za-z0-9][A-Za-z0-9._-]*"
_BOOKKEEPING = re.compile(
    rf"(?:git add -f \\.aegis/runs/(?P<added>{_TASK_ID}) && )?"
    rf"git commit -q -m \\"chore\\((?P<task>{_TASK_ID})\\): task manifest\\" -- \\.aegis/runs/(?P=task)"
    r"(?: \\|\\| true)?")


def commit_scope(command: str) -> str:
    """`none` — not a git commit or push; `exempt` — exactly the bookkeeping commit
    `git [add -f .aegis/runs/T && ]commit -q -m "chore(T): task manifest" -- .aegis/runs/T`;
    `gate` — any other commit or push."""
    flat = " ".join(command.replace("\\\\\\n", " ").split())
    if not _GIT_COMMIT_OR_PUSH.search(flat):
        return "none"
    match = _BOOKKEEPING.fullmatch(flat)
    if match and match.group("added") in (None, match.group("task")):
        return "exempt"
    return "gate"


'''+t[end:]
  t=t.replace("import re\nimport shlex\nimport subprocess\n","import re\nimport subprocess\n")
  wr(CORE,t); print("patched",CORE,"commit_scope → exact match")

patch(CORE, '''    # Still uncommitted: once a task commits a file, it is that task's change to history.
    candidates = files & set(baseline) & set(working_tree_files(ctx))''', '''    # Still uncommitted since adoption: a file any commit has touched since the baseline head
    # is part of history, even if its bytes were later reverted to the adoption state.
    head = recorded.get("head")
    since = f"{head}..HEAD" if head and ref_exists(ctx, head) else "HEAD"
    committed = {f for f in git(ctx, "log", "--name-only", "--format=", since).splitlines() if f} \\
        if ref_exists(ctx, "HEAD") else set()
    candidates = (files & set(baseline) & set(working_tree_files(ctx))) - committed''')

H="hooks/pre-commit-gate.sh"
t=rd(H)
_already_hook = "Cheap pre-filter" in t
start=t.index("# Flatten the command first:") if not _already_hook else 0
end=t.index('if output="$("$aegis" --root "$root" gate --stage merge --no-run 2>&1)"; then')
if not _already_hook:
  t=t[:start]+'''# Cheap pre-filter: only a command mentioning commit or push is worth a Python start-up.
case "$command_text" in
  *commit*|*push*) ;;
  *) exit 0 ;;
esac

root="${CLAUDE_PROJECT_DIR:-$PWD}"
[ -d "$root/.aegis" ] || exit 0

aegis="${CLAUDE_PLUGIN_ROOT}/scripts/aegis/aegis"
[ -x "$aegis" ] || exit 0

# `aegis commit-scope` decides: none (not a git commit or push), exempt (exactly the workflow's
# bookkeeping commit), gate (anything else). An empty answer — the CLI failed — runs the gate.
scope="$(printf '%s' "$command_text" | "$aegis" --root "$root" commit-scope 2>/dev/null)"
case "$scope" in
  none|exempt) exit 0 ;;
esac

'''+t[end:]
t=t.replace('''  echo "Fix the findings above. Only a commit that names .aegis/runs/ paths and nothing else is"
  echo "exempt (git commit -m ... -- .aegis/runs/<TASK>); a switch anyone can set would be the"
  echo "absence of a gate."''','''  echo "Fix the findings above. The only exempt command is the bookkeeping commit:"
  echo "  git commit -q -m \\"chore(<TASK>): task manifest\\" -- .aegis/runs/<TASK>"
  echo "A switch anyone can set would be the absence of a gate."''')
wr(H,t); print("patched",H)

patch(FLOW, '''def _closed_by_a_person(finding: dict, builder: str) -> bool:''', '''def _closed_by_a_person(finding: dict, builder: str, lens: str = "") -> bool:''')
patch(FLOW, '''    by = (finding.get("disposition_by") or "").strip()
    return bool(by) and by.lower() != (builder or "").strip().lower() and not FRAMEWORK_AGENT.match(by)''', '''    by = (finding.get("disposition_by") or "").strip()
    return (bool(by) and by.lower() not in ((builder or "").strip().lower(), (lens or "").strip().lower())
            and not FRAMEWORK_AGENT.match(by))''')
patch(FLOW, '''if f.get("reopened_in") and not _closed_by_a_person(f, builder)]''', '''if f.get("reopened_in") and not _closed_by_a_person(f, builder, lens)]''', count=2)
patch("scripts/aegis/aegis_cli/__main__.py", '''help="read a shell command on stdin; print exempt|gate for the commit hook")''',
      '''help="read a shell command on stdin; print none|exempt|gate for the commit hook")''')
print("hook simplification applied")
