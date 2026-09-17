

class LensesAreData(ProjectFixture):
    """ADR-3: a lens is a file with a focus and triggers; the plan is computed from the files."""

    # The constant ADR-3 replaced, kept here as the equivalence oracle.
    FORMER = {
        "minimal": {"always": ["correctness"], "route": ["security"], "auth": ["security"],
                    "dependency": ["security"], "data-migration": ["security"], "feature-close": ["design"]},
        "standard": {"always": ["correctness"], "route": ["security"], "auth": ["security"],
                     "dependency": ["security"], "contract": ["design"], "cross-module": ["design"],
                     "data-migration": ["security", "design"], "money": ["security", "design"],
                     "concurrency": ["design"], "feature-close": ["design"]},
        "strict": {"always": ["correctness", "security"], "contract": ["design"], "cross-module": ["design"],
                   "auth": ["design"], "data-migration": ["design"], "money": ["design"],
                   "concurrency": ["design"], "feature-close": ["design"]},
    }

    def test_the_shipped_lens_files_reproduce_the_former_matrix(self):
        ctx = core.Ctx(self.dir)
        for strictness, former in self.FORMER.items():
            matrix, _paths, _profiles = config.derive_lens_matrix(ctx, strictness, "api-service")
            for kind in sorted(set(flow.CHANGE_KINDS) | {"feature-close"}):
                with self.subTest(strictness=strictness, kind=kind):
                    expected = set(former["always"]) | set(former.get(kind, []))
                    self.assertEqual(set(matrix["always"]) | set(matrix.get(kind, [])), expected)

    def test_a_project_adds_a_lens_with_one_file(self):
        self.write(".aegis/lenses/tenancy.md",
                   "---\nname: tenancy\ndescription: tenant isolation\nexecutes: false\n"
                   "always_from: never\nkinds: {}\npaths: [src/orders/**]\n---\n"
                   "Check that every query is scoped to the tenant.\n")
        run(["compile"], self.dir)
        self.make_task()
        self.write("src/orders/a.py", "A = 1\n")
        plan = json.loads(run(["lens", "plan", "T-1"], self.dir).stdout)
        self.assertIn("tenancy", plan["lenses"])
        self.assertEqual((plan["profiles"]["tenancy"], plan["profiles"]["correctness"]),
                         ("lens-auditor", "lens-runner"))
        prompt = run(["lens", "prompt", "T-1", "tenancy"], self.dir).stdout
        self.assertIn("scoped to the tenant", prompt)
        self.assertIn("+++ b/src/orders/a.py", prompt)

    def test_project_type_lenses_stay_with_their_type(self):
        ctx = core.Ctx(self.dir)
        self.assertIn("accessibility", config.derive_lens_matrix(ctx, "standard", "web-saas")[2])
        library = config.derive_lens_matrix(ctx, "standard", "library")[2]
        self.assertNotIn("accessibility", library)
        self.assertNotIn("data-integrity", library)

    def test_the_prompt_carries_only_this_lens_prior_findings(self):
        self.make_task()
        self.write("src/orders/a.py", "A = 1\n")
        self.record("T-1", {"lens": "security", "verdict": "fail", "findings": [
            {"severity": 3, "message": "the webhook signature is never verified", "path": "src/orders/a.py"}]})
        security = run(["lens", "prompt", "T-1", "security", "--no-diff"], self.dir).stdout
        self.assertIn("PHASE 2", security)
        self.assertIn("webhook signature", security)
        self.assertNotIn("Diff under review", security)
        self.assertNotIn("webhook signature", run(["lens", "prompt", "T-1", "correctness", "--no-diff"], self.dir).stdout)

    def test_an_engine_without_the_contract_preloaded_gets_it(self):
        self.make_task()
        self.assertIn("Never a finding", run(["lens", "prompt", "T-1", "security", "--with-contract"], self.dir).stdout)

    def test_the_second_engine_is_an_answer_that_may_be_empty(self):
        self.make_task()
        plan = json.loads(run(["lens", "plan", "T-1"], self.dir).stdout)
        self.assertIsNone(plan["external_reviewer"])
        run(["answer", "q.core.second-engine", '"gemini -p"'], self.dir)
        plan = json.loads(run(["lens", "plan", "T-1"], self.dir).stdout)
        self.assertEqual(plan["external_reviewer"], "gemini -p")


class NoLensOrEngineIsHardWired(unittest.TestCase):
    def read(self, rel):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_the_workflow_names_no_lens_and_no_vendor(self):
        workflow = self.read("workflows/aegis-task.js")
        self.assertIn("lens prompt ${task} ${lens} --no-diff", workflow)
        for name in ("lens-correctness", "lens-security", "lens-design", "codex"):
            self.assertNotIn(name, workflow)

    def test_any_engine_runs_through_one_script(self):
        external = self.read("scripts/aegis/external-lens.sh")
        for needed in ('lens prompt "$task" "$lens" --with-contract', '--lens "$lens"', "diff_digest", "lens plan"):
            self.assertIn(needed, external)
        self.assertNotIn("codex", external.split("set -euo pipefail", 1)[1])
        self.assertIn("external-lens.sh", self.read("scripts/aegis/codex-lens.sh"))

    def test_lens_profiles_are_tool_sets_not_lenses(self):
        for name in ("lens-correctness", "lens-security", "lens-design"):
            self.assertFalse(os.path.exists(os.path.join(ROOT, "agents", f"{name}.md")))
        auditor, runner = self.read("agents/lens-auditor.md"), self.read("agents/lens-runner.md")
        self.assertIn("Bash", runner.split("---")[1])
        self.assertNotIn("tools: Read, Grep, Glob, Bash", auditor)
