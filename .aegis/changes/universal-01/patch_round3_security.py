"""Security round-3 findings on TASK-UNBLOCK-01, applied after patch_hook_simplify.py."""
import os, sys, io
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
CORE="scripts/aegis/aegis_cli/core.py"

# F-3c8485a5: a rename's source is a change too — list both sides everywhere scope is built.
patch(CORE, '''    return sorted(f for f in git(ctx, "diff", "--cached", "--name-only").splitlines() if f)''',
      '''    # `--no-renames`: a staged `git mv src/auth.py .aegis/runs/T/k.py` otherwise lists only the
    # new path, and the deletion of src/auth.py reached a commit unowned and unreviewed.
    return sorted(f for f in git(ctx, "diff", "--cached", "--name-only", "--no-renames").splitlines() if f)''')
patch(CORE, '''        files.update(f for f in git(ctx, "diff", "--name-only", *spec).splitlines() if f)''',
      '''        files.update(f for f in git(ctx, "diff", "--name-only", "--no-renames", *spec).splitlines() if f)''')
patch(CORE, '''    for record in records:
        if skip_next:  # rename entries emit the old path as its own record
            skip_next = False
            continue
        if len(record) > 3:
            if record[:2] in ("R ", "RM", " R", "C ", "CM"):
                skip_next = True
            files.append(record[3:])''', '''    for record in records:
        if skip_next:
            # The source of a rename is removed from its old place — that is a change to the
            # old path, and scope must see it. A copy's source is untouched and stays out.
            if skip_next == "rename":
                files.append(record)
            skip_next = False
            continue
        if len(record) > 3:
            if record[:2] in ("R ", "RM", " R"):
                skip_next = "rename"
            elif record[:2] in ("C ", "CM"):
                skip_next = "copy"
            files.append(record[3:])''')

# F-7fc9bd6d: an alias defined in the command itself is visible — treat it as a commit.
patch(CORE, '''    flat = " ".join(command.replace("\\\\\\n", " ").split())
    if not _GIT_COMMIT_OR_PUSH.search(flat):
        return "none"''', '''    flat = " ".join(command.replace("\\\\\\n", " ").split())
    if _INLINE_ALIAS.search(flat):
        return "gate"  # `git -c alias.ci=commit ci`: the alias is in the text, so it is not hidden
    if not _GIT_COMMIT_OR_PUSH.search(flat):
        return "none"''')
patch(CORE, '''_TASK_ID = r"[A-Za-z0-9][A-Za-z0-9._-]*"''', '''_INLINE_ALIAS = re.compile(r"(?:^|\\s)(?:-c\\s*|--config-env[=\\s])[\\"']?alias\\.[^=\\s]+=[^\\s;&|]*(?:commit|push)", re.I)
_TASK_ID = r"[A-Za-z0-9][A-Za-z0-9._-]*"''')

# F-310ded7e: answers.json is configuration input; it changes through `aegis answer`, not an edit.
patch("hooks/protect-paths.sh", '''  */.aegis/constitution.md)''', '''  */.aegis/answers.json)
    echo "Blocked: .aegis/answers.json changes through 'aegis answer <question-id> <value>'." >&2
    echo "Frozen zones and autonomy limits live there; an edit would unfreeze a path with no" >&2
    echo "record of who decided it. A human changes those answers." >&2
    exit 2
    ;;
  */.aegis/constitution.md)''')
patch("hooks/protect-paths.sh", '''# the constitution. Role-scoped ownership is enforced where it can actually be verified:''',
      '''# the constitution and the answers it is compiled from. Role-scoped ownership is enforced
# where it can actually be verified:''')
print("security round-3 fixes applied")
