import os, io
p=os.path.join(os.environ["AEGIS_PATCH_ROOT"], "tests", "test_aegis.py"); t=io.open(p,encoding="utf-8").read()
if "class TheThirdReviewRoundFindings" not in t:
    t += '''

class TheThirdReviewRoundFindings(ProjectFixture):
    def test_a_staged_rename_keeps_its_source_in_scope(self):
        self.write("src/auth.py", "SECRET_CHECK = True\\n")
        subprocess.run(["git", "-C", self.dir, "add", "src/auth.py"], check=True)
        subprocess.run(["git", "-C", self.dir, "commit", "-qm", "auth"], check=True)
        os.makedirs(os.path.join(self.dir, ".aegis/runs/T-9"), exist_ok=True)
        subprocess.run(["git", "-C", self.dir, "mv", "src/auth.py", ".aegis/runs/T-9/k.py"], check=True)
        ctx = core.Ctx(self.dir)
        self.assertIn("src/auth.py", core.staged_files(ctx))
        self.assertIn("src/auth.py", core.changed_files(ctx, None))

    def test_an_inline_alias_for_commit_is_a_commit(self):
        self.assertEqual(core.commit_scope("git -c alias.ci=commit ci -am x"), "gate")
        self.assertEqual(core.commit_scope("git -c 'alias.p=push' p"), "gate")

    def test_brace_expansion_cannot_ride_the_bookkeeping_exemption(self):
        self.assertEqual(core.commit_scope("git commit -m x -- .aegis/runs/{T,../../src/auth.py}"), "gate")

    def test_answers_json_is_not_edited_by_an_agent(self):
        proc = subprocess.run(["bash", os.path.join(ROOT, "hooks", "protect-paths.sh")],
                              input=json.dumps({"tool_input": {"file_path": ".aegis/answers.json"}}),
                              capture_output=True, text=True,
                              env=dict(os.environ, CLAUDE_PROJECT_DIR=self.dir))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("aegis answer", proc.stderr)
'''
io.open(p,"w",encoding="utf-8").write(t); print("round-3 security tests appended")
