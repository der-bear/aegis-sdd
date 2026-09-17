import os, io, sys
p=os.path.join(os.environ["AEGIS_PATCH_ROOT"], "tests", "test_aegis.py"); t=io.open(p,encoding="utf-8").read()
def sub(old,new,count=1):
    global t
    if new in t:
        print("already"); return
    n=t.count(old)
    if n!=count: sys.exit(f"expected {count} of {old[:90]!r}, found {n}")
    t=t.replace(old,new)
sub('''        script = open(os.path.join(ROOT, "scripts", "aegis", "codex-lens.sh")).read()
        for needed in ('diff "$task"', "lens plan", "diff_digest"):
            self.assertIn(needed, script, f"codex-lens.sh must include {needed}")''', '''        script = open(os.path.join(ROOT, "scripts", "aegis", "external-lens.sh")).read()
        for needed in ("lens prompt", "lens plan", "diff_digest"):
            self.assertIn(needed, script, f"external-lens.sh must include {needed}")''')
sub('''        workflow, codex = self.read("workflows/aegis-task.js"), self.read("scripts/aegis/codex-lens.sh")
        self.assertIn("${AEGIS} diff ${task}", workflow)
        self.assertIn('diff "$task"', codex)''', '''        workflow, codex = self.read("workflows/aegis-task.js"), self.read("scripts/aegis/external-lens.sh")
        self.assertIn("${AEGIS} diff ${task}", workflow)
        self.assertIn("lens prompt", codex)  # the prompt carries `aegis diff`''')
sub('''        codex = self.read("scripts/aegis/codex-lens.sh")
        self.assertIn('--lens "$lens"', codex)
        self.assertNotIn('\\\\"reviewer\\\\": \\\\"codex:$model\\\\"', codex)''', '''        codex = self.read("scripts/aegis/external-lens.sh")
        self.assertIn('--lens "$lens"', codex)
        self.assertNotIn('\\\\"reviewer\\\\"', codex)''')
sub('''        codex = self.read("scripts/aegis/codex-lens.sh")
        self.assertIn("reviews/$lens.json", codex)
        self.assertIn("reconciled", codex)''', '''        # The reconciliation brief is built once, by `aegis lens prompt`, for every engine.
        self.assertIn("lens prompt", self.read("scripts/aegis/external-lens.sh"))
        self.assertIn("reconciled", self.read("scripts/aegis/aegis_cli/flow.py"))''')
sub('''        self.assertNotIn('"reviewer": "lens-correctness"', self.read("agents/lens-correctness.md"))''', '''        for profile in ("agents/lens-auditor.md", "agents/lens-runner.md"):
            self.assertNotIn('"reviewer":', self.read(profile))''')
sub('''        workflow = self.read("workflows/aegis-task.js")
        self.assertIn("reviews/${lens}.json", workflow)
        self.assertNotIn("reviews/*.json", workflow)''', '''        workflow = self.read("workflows/aegis-task.js")
        self.assertIn("lens prompt ${task} ${lens}", workflow)  # the brief carries this lens's own ids
        self.assertNotIn("reviews/*.json", workflow)''')
io.open(p,"w",encoding="utf-8").write(t); print("existing tests adapted to ADR-3")
