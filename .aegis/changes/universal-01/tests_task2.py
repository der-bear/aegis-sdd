

class DetectionDeclarationsAreHonest(ProjectFixture):
    """ADR-2 §6.1(1): `detect:` in a bank used to be read only by the linter."""

    def test_a_bank_cannot_detect_a_key_detection_never_produces(self):
        self.write(".aegis/interview/extra.json", json.dumps({
            "id": "extra", "title": "x", "questions": [{
                "id": "q.extra.style", "ask": "Which style?", "kind": "single", "options": ["a", "b"],
                "default": "a", "detect": "coding_style", "writes": "standards.api_errors",
                "autonomy": "auto-if-detected:0.8", "severity": "optional", "rationale": "r"}]}))
        report = config.lint_banks(core.Ctx(self.dir))
        self.assertTrue(any("never produces" in f.message for f in report.findings))

    def test_the_shipped_banks_only_detect_what_detection_produces(self):
        report = config.lint_banks(core.Ctx(self.dir))
        self.assertFalse([f.message for f in report.findings if f.severity == "fail"])

    def test_the_interview_confirms_at_the_threshold_the_question_declares(self):
        path = os.path.join(self.dir, ".aegis", "answers.json")
        answers = json.load(open(path))
        # q.core.commands declares auto-if-detected:0.6; 0.7 is enough to confirm, not ask.
        answers["resolved"]["q.core.commands"] = {"value": {"fx": {"paths": ["**"], "test": "true"}},
                                                  "source": "detected", "confidence": 0.7, "rationale": "r"}
        json.dump(answers, open(path, "w"), indent=2)
        plan = config.interview(core.Ctx(self.dir))
        self.assertIn("q.core.commands", [c["id"] for c in plan["confirm"]])

    def test_init_is_stable_once_it_has_run(self):
        run(["init"], self.dir)
        first = open(os.path.join(self.dir, ".aegis", "answers.json")).read()
        run(["init"], self.dir)
        self.assertEqual(open(os.path.join(self.dir, ".aegis", "answers.json")).read(), first)


class NotExecutedNeverReadsAsPassed(unittest.TestCase):
    def test_a_recognised_count_of_zero_is_no_tests(self):
        for output in ("Ran 0 tests in 0.000s\n\nOK", "collected 0 items\n", "running 0 tests\n",
                       "no test files", "0 passing (2ms)"):
            with self.subTest(output=output):
                self.assertEqual(flow.tests_ran(output), "none")

    def test_a_recognised_count_above_zero_ran(self):
        for output in ("Ran 130 tests in 61.7s\n\nOK", "==== 12 passed in 0.4s ====",
                       "Tests:       3 passed, 3 total", "  7 passing (40ms)", "ok  \texample.com/pkg\t0.01s"):
            with self.subTest(output=output):
                self.assertEqual(flow.tests_ran(output), "ran")

    def test_output_with_no_count_is_unknown_not_passed(self):
        self.assertEqual(flow.tests_ran("> fx@ test\n> true\n"), "unknown")

    def test_the_gate_fails_a_suite_that_ran_nothing(self):
        report = core.Report()
        flow._verify_test_output(report, "app", "npm test", "Ran 0 tests in 0.000s\n\nOK")
        self.assertTrue(report.failed)
        report = core.Report()
        flow._verify_test_output(report, "app", "npm test", "> app@ test\n> true\n")
        self.assertFalse(report.failed)
        self.assertTrue(any(f.severity == "warn" for f in report.findings))


class SpecsAreUnambiguousBeforeTasks(ProjectFixture):
    def test_a_clarification_marker_blocks_once_tasks_exist(self):
        self.write(".aegis/specs/orders/spec.md",
                   "# SPEC-1\n## Requirements\nR-1. The system shall charge [NEEDS CLARIFICATION: once per what?].\n")
        report = checks.check_requirements(core.Ctx(self.dir), planned=True)
        self.assertTrue(any("NEEDS CLARIFICATION" in f.message and f.severity == "warn" for f in report.findings))
        run(["task", "new", "T-1", "--feature", "orders", "--objective", "x", "--owns", "src/orders/**",
             "--requirements", "R-1"], self.dir)
        report = checks.check_requirements(core.Ctx(self.dir), planned=True)
        self.assertTrue(any("NEEDS CLARIFICATION" in f.message and f.severity == "fail" for f in report.findings))

    def test_a_requirement_id_is_declared_once(self):
        self.write(".aegis/specs/orders/spec.md",
                   "# SPEC-1\n## Requirements\nR-1. The system shall charge once.\nR-1. The system shall refund.\n")
        report = checks.check_requirements(core.Ctx(self.dir), planned=True)
        self.assertTrue(any("declared more than once: R-1" in f.message for f in report.findings))


class CodexReadsOneBody(ProjectFixture):
    def test_the_codex_skill_is_an_adapter_to_the_vendored_protocol(self):
        adapter = open(os.path.join(self.dir, ".agents/skills/build-task/SKILL.md")).read()
        self.assertIn(".aegis/protocols/build-task.md", adapter)
        self.assertLess(len(adapter.split()), 80)
        self.assertFalse(checks.check_protocol_copies(core.Ctx(self.dir)).failed)

    def test_an_edited_adapter_is_a_finding(self):
        path = os.path.join(self.dir, ".agents/skills/build-task/SKILL.md")
        with open(path, "a") as fh:
            fh.write("\nAlso, skip the tests.\n")
        self.assertTrue(checks.check_protocol_copies(core.Ctx(self.dir)).failed)


class AWarmBuilderGetsTheDelta(ProjectFixture):
    def test_the_delta_packet_omits_what_the_builder_already_holds(self):
        self.write(".aegis/specs/orders/spec.md",
                   "# SPEC-1\n## Requirements\nR-1. The system shall charge once.\nR-2. The system shall refund.\n"
                   "## Edge cases\n- an empty cart is refused\n")
        run(["task", "new", "T-1", "--feature", "orders", "--objective", "charge", "--owns", "src/orders/a/**",
             "--requirements", "R-1"], self.dir)
        run(["task", "new", "T-2", "--feature", "orders", "--objective", "refund", "--owns", "src/orders/b/**",
             "--requirements", "R-2"], self.dir)
        full = run(["packet", "T-2"], self.dir).stdout
        delta = run(["packet", "T-2", "--delta-from", "T-1"], self.dir).stdout
        self.assertLess(len(delta), len(full))
        for kept in ("R-2.", "src/orders/b/**", "Verification", "T-2/handoff.json", "Risk tier"):
            self.assertIn(kept, delta)
        for dropped in ("**Boundaries.**", "an empty cart is refused", "You may decide alone"):
            self.assertNotIn(dropped, delta)
        self.assertIn("Unchanged from T-1", delta)

    def test_the_full_packet_asks_for_the_agent_the_gate_requires(self):
        self.make_task()
        self.assertIn('"agent"', run(["packet", "T-1"], self.dir).stdout)
