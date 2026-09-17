"""Replace the commit-scope table and hook test with the exact-match semantics."""
import os, io, re, sys
p=os.path.join(os.environ["AEGIS_PATCH_ROOT"], "tests", "test_aegis.py"); t=io.open(p,encoding="utf-8").read()
start=t.index("class TheCommitHookExemptsOnlyBookkeeping(ProjectFixture):")
end=t.index("class MigrateBaselinesOutsideOpenLeases(unittest.TestCase):")
t=t[:start]+'''class TheCommitHookExemptsOnlyBookkeeping(ProjectFixture):
    BOOKKEEPING = 'git add -f .aegis/runs/T-1 && git commit -q -m "chore(T-1): task manifest" -- .aegis/runs/T-1 || true'
    CASES = [
        (BOOKKEEPING, "exempt"),
        ('git commit -q -m "chore(T-1): task manifest" -- .aegis/runs/T-1', "exempt"),
        ('git add -f .aegis/runs/T-2 && git commit -q -m "chore(T-1): task manifest" -- .aegis/runs/T-1', "gate"),
        ("git commit -m x -- .aegis/runs/T-1", "gate"),
        ("git commit -m x", "gate"),
        ("git push", "gate"),
        ('git commit -qm "$(git commit -qam w)" -- .aegis/runs/T-1', "gate"),
        ("git commit --inc -qm m -- .aegis/runs/T-1", "gate"),
        ("\\\\git commit -qam w", "gate"),
        ("/usr/bin/git commit -qam w", "gate"),
        ('"git" commit -qam w', "gate"),
        ("command git commit -am w", "gate"),
        ("GIT_INDEX_FILE=/tmp/i git commit -m x", "gate"),
        ("cd /repo\\ngit commit -am y", "gate"),
        ('grep -rn "git commit" docs/', "none"),
        ("git status", "none"),
        ("echo pushing on", "none"),
    ]

    def test_the_scope_is_decided_from_the_command(self):
        for command, expected in self.CASES:
            with self.subTest(command=command):
                self.assertEqual(core.commit_scope(command), expected)

    def hook(self, command):
        env = dict(os.environ, CLAUDE_PLUGIN_ROOT=ROOT, CLAUDE_PROJECT_DIR=self.dir)
        return subprocess.run(["bash", os.path.join(ROOT, "hooks", "pre-commit-gate.sh")],
                              input=json.dumps({"tool_input": {"command": command}}),
                              capture_output=True, text=True, env=env, cwd=self.dir)

    def test_bookkeeping_is_exempt_and_nothing_else_is(self):
        self.make_task()
        self.write("lib/orphan.py", "X = 1\\n")  # owned by no task, so the merge gate fails
        self.assertEqual(self.hook(self.BOOKKEEPING).returncode, 0)
        self.assertEqual(self.hook('grep -rn "git commit" docs/').returncode, 0)
        for bypass in ("git commit -m manifest -- .aegis/runs/T-1", "git push", "git commit -a -m x",
                       "/usr/bin/git commit -qam w", '"git" commit -qam w',
                       'git commit -qm "$(git commit -qam w)" -- .aegis/runs/T-1'):
            with self.subTest(command=bypass):
                self.assertEqual(self.hook(bypass).returncode, 2)


'''+t[end:]
old='''        proc = sp.run([os.path.join(ROOT, "hooks", "pre-commit-gate.sh")],
                      input=json.dumps({"tool_input": {"command": "git commit -m x -- .aegis/runs/T-1"}}),'''
new='''        proc = sp.run([os.path.join(ROOT, "hooks", "pre-commit-gate.sh")],
                      input=json.dumps({"tool_input": {"command":
                          'git commit -q -m "chore(T-1): task manifest" -- .aegis/runs/T-1'}}),'''
if t.count(old)==1: t=t.replace(old,new)
if 'class ABaselinedFileLeavesTheBaselineOnceCommitted' not in t:
  t += '''

class ABaselinedFileLeavesTheBaselineOnceCommitted(unittest.TestCase):
    setUp = AdoptionRatchetsFromToday.setUp
    write = AdoptionRatchetsFromToday.write

    def test_reverting_a_committed_file_to_its_adoption_bytes_does_not_hide_it(self):
        ctx = core.Ctx(self.dir)
        original = open(os.path.join(self.dir, "legacy/old.py")).read()
        self.write("legacy/old.py", original + "# fixed\\n")
        subprocess.run(["git", "-C", self.dir, "add", "legacy/old.py"], check=True)
        subprocess.run(["git", "-C", self.dir, "commit", "-qm", "fix legacy"], check=True)
        self.write("legacy/old.py", original)  # back to the adoption bytes, uncommitted
        self.assertIn("legacy/old.py", core.changed_files(ctx, None))


class ALensCannotCloseItsOwnSecondStrike(ProjectFixture):
    def test_the_bare_lens_name_is_not_a_person(self):
        finding = {"reopened_in": [3], "disposition_by": "correctness"}
        self.assertFalse(flow._closed_by_a_person(finding, "aegis-builder", "correctness"))
        self.assertTrue(flow._closed_by_a_person({"reopened_in": [3], "disposition_by": "Alex"},
                                                 "aegis-builder", "correctness"))
'''
io.open(p,"w",encoding="utf-8").write(t); print("hook tests replaced")
