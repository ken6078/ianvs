import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


VALIDATOR_DIR = Path(__file__).resolve().parents[1]
if str(VALIDATOR_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATOR_DIR))

import validation_runner as runner
from static_validator import CheckResult, ExampleReport, StaticValidationReport


def arguments(**updates):
    values = dict(
        inventory="inventory.yaml", example=[], all=False, static=False,
        dependency=False, prepare_env=False, jsonl=False, smoke=False,
        pip_install_check=False, pip_install=False, no_execute_smoke=False,
        timeout=5, format="json", report="",
    )
    values.update(updates)
    return argparse.Namespace(**values)


class ValidationRunnerTest(unittest.TestCase):
    def test_default_mode_is_static_and_dynamic_flags_disable_implicit_static(self):
        self.assertTrue(runner.runs_static_validation(arguments()))
        self.assertFalse(runner.runs_dynamic_validation(arguments()))
        self.assertFalse(runner.runs_static_validation(arguments(smoke=True)))
        self.assertTrue(runner.runs_dynamic_validation(arguments(jsonl=True)))

    def test_selectors_match_name_path_and_benchmark(self):
        examples = [{"name": "unit", "path": "examples/unit", "benchmark_file": "examples/unit/job.yaml"}]
        for selector in ("unit", "./examples/unit/", "examples/unit/job.yaml"):
            with self.subTest(selector=selector):
                self.assertEqual(examples, runner.select_examples(examples, [selector], False))
        self.assertEqual([], runner.select_examples(examples, ["missing"], False))

    def test_dynamic_pipeline_skips_inactive_and_runs_only_active(self):
        active = {"name": "active", "path": "examples/active", "status": "active"}
        inactive = {"name": "waiting", "path": "examples/waiting", "status": "unvalidated"}
        generated = StaticValidationReport([ExampleReport("active", "examples/active", [CheckResult("dep", "PASS")])])
        with mock.patch.object(runner, "validate_dependencies", return_value=generated) as validate:
            report = runner.run_validation_pipeline(
                Path("."), [active, inactive], arguments(dependency=True)
            )
        validate.assert_called_once()
        self.assertEqual([active], validate.call_args.kwargs["examples"])
        self.assertEqual(2, len(report.reports))
        skipped = next(item for item in report.reports if item.name == "waiting")
        self.assertEqual("SKIP", skipped.checks[0].status)

    def test_static_pipeline_includes_inactive_examples(self):
        examples = [{"name": "waiting", "path": "examples/waiting", "status": "unvalidated"}]
        generated = StaticValidationReport([ExampleReport("waiting", "examples/waiting")])
        with mock.patch.object(runner, "validate_static_examples", return_value=generated) as validate:
            report = runner.run_validation_pipeline(Path("."), examples, arguments(static=True))
        validate.assert_called_once_with(repo_root=Path("."), examples=examples)
        self.assertEqual(1, len(report.reports))

    def test_all_pipeline_stages_are_merged_for_same_identity(self):
        example = {"name": "unit", "path": "examples/unit", "status": "active"}
        def generated(name):
            return StaticValidationReport([ExampleReport("unit", "examples/unit", [CheckResult(name, "PASS")])])
        with mock.patch.object(runner, "validate_static_examples", return_value=generated("static")), \
             mock.patch.object(runner, "validate_dependencies", return_value=generated("dependency")), \
             mock.patch.object(runner, "prepare_example_environments", return_value=generated("prepare")), \
             mock.patch.object(runner, "validate_jsonl_examples", return_value=generated("jsonl")), \
             mock.patch.object(runner, "validate_smoke_examples", return_value=generated("smoke")):
            report = runner.run_validation_pipeline(
                Path("."), [example], arguments(static=True, dependency=True, prepare_env=True, jsonl=True, smoke=True)
            )
        self.assertEqual(["static", "dependency", "prepare", "jsonl", "smoke"], [c.name for c in report.reports[0].checks])

    def test_install_mode_precedence(self):
        self.assertEqual(runner.INSTALL_MODE_SKIP, runner.dependency_install_mode(arguments()))
        self.assertEqual(runner.INSTALL_MODE_DRY_RUN, runner.dependency_install_mode(arguments(pip_install_check=True)))
        self.assertEqual(runner.INSTALL_MODE_INSTALL, runner.dependency_install_mode(arguments(pip_install=True, pip_install_check=True)))

    def test_unexpected_failure_becomes_one_blocking_report_per_example(self):
        examples = [
            {"name": "a", "path": "./examples/a/", "benchmark_file": "a.yaml"},
            {"path": "examples/b"},
        ]
        report = runner.unexpected_failure_report(examples, ValueError("bad"))
        self.assertFalse(report.passed)
        self.assertEqual(2, len(report.reports))
        self.assertEqual("ERROR", report.reports[0].checks[0].status)
        self.assertIn("ValueError: bad", report.reports[0].checks[0].details)

    def test_merge_reports_sorts_and_combines(self):
        reports = [
            StaticValidationReport([ExampleReport("b", "z", [CheckResult("one", "PASS")])]),
            StaticValidationReport([ExampleReport("a", "a"), ExampleReport("b", "z", [CheckResult("two", "PASS")])]),
        ]
        merged = runner.merge_reports(reports)
        self.assertEqual(["a", "z"], [item.path for item in merged.reports])
        self.assertEqual(2, len(merged.reports[1].checks))

    def test_main_handles_no_selection_and_internal_exception(self):
        with mock.patch.object(runner, "load_selected_examples", return_value=[]), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(1, runner.main([]))

        examples = [{"name": "unit", "path": "examples/unit"}]
        output = io.StringIO()
        with mock.patch.object(runner, "load_selected_examples", return_value=examples), \
             mock.patch.object(runner, "run_validation_pipeline", side_effect=RuntimeError("boom")), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(1, runner.main(["--format", "json"]))
        self.assertEqual("ERROR", json.loads(output.getvalue())["examples"][0]["checks"][0]["status"])

    def test_write_report_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested/report.json"
            with contextlib.redirect_stdout(io.StringIO()):
                runner.write_or_print_report("{}", str(target))
            self.assertEqual("{}", target.read_text())


if __name__ == "__main__":
    unittest.main()
