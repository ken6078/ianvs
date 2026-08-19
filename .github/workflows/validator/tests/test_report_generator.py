import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


VALIDATOR_DIR = Path(__file__).resolve().parents[1]
if str(VALIDATOR_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATOR_DIR))

from services import report_generator as report


def check(name="check", status="PASS", details=None, **updates):
    value = report.CheckResult(name=name, status=status, details=list(details or []))
    for key, item in updates.items():
        setattr(value, key, item)
    return value


def example(name="unit", path="examples/unit", checks=None):
    checks = list(checks or [])
    return report.ExampleResult(
        name=name,
        path=path,
        passed=not any(item.status in report.BLOCKING_STATUSES for item in checks),
        checks=checks,
    )


class ReportGeneratorTest(unittest.TestCase):
    def test_check_counts_runtime_failure_as_one_issue(self):
        runtime = check("Runtime smoke test", "FAIL", ["one", "two"])
        regular = check("Static", "FAIL", ["one", "two"])
        self.assertEqual(1, runtime.issue_count)
        self.assertEqual(2, regular.issue_count)
        result = example(checks=[runtime, regular])
        self.assertEqual(3, result.count("FAIL"))
        self.assertTrue(result.has_blocking_errors)

    def test_parse_merge_and_load_combined_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "one.json"
            second = root / "two.json"
            first.write_text(json.dumps({"examples": [{
                "name": "unit", "path": "examples/unit/", "checks": [
                    {"name": "same", "status": "WARNING", "message": "m", "details": ["a"]},
                    {"name": "bad", "status": "FAIL", "details": "not-a-list"},
                ],
            }]}))
            second.write_text(json.dumps({"examples": [{
                "name": "unit", "path": "examples/unit", "checks": [
                    {"name": "same", "status": "WARNING", "message": "m", "details": ["a", "b"]}
                ],
            }, "ignored"]}))
            combined = report.load_combined_report([first, second])
        self.assertEqual(1, len(combined.examples))
        self.assertFalse(combined.passed)
        warning = next(item for item in combined.examples[0].checks if item.name == "same")
        self.assertEqual(["a", "b"], warning.details)

    def test_invalid_payload_and_non_list_checks_are_safe(self):
        with self.assertRaises(ValueError):
            report.parse_examples({}, Path("bad.json"))
        parsed = report.parse_examples(
            {"examples": [{"name": "unit", "checks": "bad"}]}, Path("x.json")
        )
        self.assertEqual([], parsed[0].checks)
        self.assertEqual([], report.string_list("bad"))

    def test_result_discovery_handles_directory_glob_and_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "a.json"
            second = root / "nested/b.json"
            second.parent.mkdir()
            first.write_text("{}")
            second.write_text("{}")
            (root / "not.txt").write_text("{}")
            found = report.discover_result_paths([str(root), str(first), str(root / "**/*.json")])
            self.assertEqual({first.resolve(), second.resolve()}, {item.resolve() for item in found})

    def test_artifact_links_map_base_and_pr_by_example_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_path = root / "unit.json"
            result_path.write_text(json.dumps({"examples": [{"name": "unit-name", "path": "examples/unit"}]}))
            artifacts = root / "artifacts.json"
            artifacts.write_text(json.dumps({"artifacts": [
                {"name": "dynamic-validation-base-unit", "id": 11},
                {"name": "dynamic-validation-pr-unit", "id": 12},
                {"name": "expired", "id": 13, "expired": True},
            ]}))
            env = {
                "GITHUB_SERVER_URL": "https://github.example",
                "GITHUB_REPOSITORY": "owner/repo",
                "GITHUB_RUN_ID": "99",
            }
            with mock.patch.dict(os.environ, env, clear=False):
                links = report.load_validation_artifact_links(str(artifacts), [result_path])
        self.assertIn("artifacts/11", links["base"]["examples/unit"])
        self.assertIn("artifacts/12", links["pr"]["examples/unit"])
        self.assertIn(report.example_artifact_key("unit-name", "examples/unit"), links["pr"])

    def test_artifact_links_fail_closed_on_missing_context_or_bad_json(self):
        self.assertEqual({"base": {}, "pr": {}}, report.load_validation_artifact_links("", []))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text("not json")
            with mock.patch.dict(os.environ, {
                "GITHUB_SERVER_URL": "x", "GITHUB_REPOSITORY": "y", "GITHUB_RUN_ID": "z"
            }):
                self.assertEqual({"base": {}, "pr": {}}, report.load_validation_artifact_links(str(path), []))

    def test_health_classification_covers_inventory_and_failure_reasons(self):
        passing = example()
        dependency = example(checks=[check("pip dependency", "FAIL")])
        resource = example(checks=[check("JSONL dataset", "ERROR")])
        generic = example(checks=[check("syntax", "FAIL")])
        cases = [
            ({"status": "active"}, passing, (report.STATUS_RUNNABLE, "")),
            ({"status": "active"}, dependency, (report.STATUS_BROKEN, report.REASON_DEPENDENCY)),
            ({"status": "active"}, resource, (report.STATUS_BROKEN, report.REASON_RESOURCE)),
            ({"status": "active"}, generic, (report.STATUS_BROKEN, "")),
            ({"status": "unvalidated"}, None, (report.STATUS_CICD_ONGOING, "")),
            ({"status": "ongoing"}, None, (report.STATUS_EXAMPLE_ONGOING, "")),
            ({"status": "hardware"}, None, (report.STATUS_HARDWARE, "")),
        ]
        for inventory, result, expected in cases:
            with self.subTest(inventory=inventory, expected=expected):
                self.assertEqual(expected, report.classify_health_status(inventory, result))

    def test_status_snapshots_aggregate_benchmark_units(self):
        results = report.CombinedReport(
            examples=[example("one", "examples/group/one"), example("two", "examples/group/two", [check("bad", "FAIL")])],
            source_files=[],
        )
        inventory = [
            {"example": "group", "name": "one", "path": "examples/group/one", "status": "active"},
            {"example": "group", "name": "two", "path": "examples/group/two", "status": "active"},
            {"example": "waiting", "name": "waiting", "path": "examples/waiting", "status": "unvalidated"},
            {"example": "gpu", "name": "gpu", "path": "examples/gpu", "status": "hardware"},
        ]
        snapshots = report.create_example_status_snapshots(results, inventory, "now", "sha")
        self.assertEqual(report.STATUS_BROKEN, snapshots["group.json"]["message"])
        self.assertEqual(report.STATUS_CICD_ONGOING, snapshots["waiting.json"]["message"])
        self.assertEqual(report.STATUS_HARDWARE, snapshots["gpu.json"]["message"])

    def test_status_filename_rejects_empty_and_snapshots_write_summary(self):
        self.assertEqual("a_b.json", report.status_file_name(" a/b "))
        with self.assertRaises(ValueError):
            report.status_file_name("///")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "status"
            report.write_example_status_snapshots(
                {"a.json": {"status": "passing"}}, {"validated_at": "now"}, output
            )
            self.assertEqual("passing", json.loads((output / "a.json").read_text())["status"])
            self.assertEqual("now", json.loads((output / "summary.json").read_text())["validated_at"])

    def test_health_readme_escapes_names_groups_rows_and_has_badges(self):
        inventory = [
            {"example": "group & more", "name": "b", "path": "examples/group/b"},
            {"example": "group & more", "name": "a", "path": "examples/group/a"},
        ]
        rendered = report.render_example_health_readme(inventory, report.CombinedReport([], []), {})
        self.assertIn('rowspan="2"', rendered)
        self.assertIn("group &amp; more", rendered)
        self.assertIn("img.shields.io/endpoint", rendered)
        self.assertIn("validated_at_display", rendered)

    def test_markdown_modes_render_statuses_details_and_skips(self):
        combined = report.CombinedReport(
            examples=[
                example("failed", "examples/f", [check("broken", "ERROR", ["file.py:1: bad"], message="bad", file="file.py")]),
                example("waiting", "examples/w", [check(report.DYNAMIC_ELIGIBILITY_CHECK, "SKIP", ["inventory status: unvalidated"])]),
            ],
            source_files=["results/a.json"],
        )
        static = report.render_full_report(combined, mode=report.MODE_STATIC)
        dynamic = report.render_full_report(combined, mode=report.MODE_DYNAMIC)
        static_regression = "\n".join(report.static_regression_summary([], []))
        dynamic_regression = "\n".join(report.dynamic_regression_summary([], []))
        self.assertIn("Static Validation Report", static)
        self.assertIn("ERROR", static)
        self.assertIn("the base branch and PR validation results", static_regression)
        self.assertIn("Pre-existing failures do not block", static_regression)
        self.assertIn("Dynamic Validation Report", dynamic)
        self.assertIn("the base branch and PR validation results", dynamic_regression)
        self.assertIn("Skipped Examples", dynamic)
        self.assertIn("| `examples/w` | CI/CD ongoing |", dynamic)
        self.assertTrue(dynamic.rstrip().endswith("</details>"))

    def test_main_empty_policy_and_allow_empty(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(2, report.main(["--results", "definitely-missing"] ))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, report.main(["--results", "definitely-missing", "--allow-empty"]))

    def test_formatting_and_escape_helpers(self):
        self.assertEqual("2026-08-20 01:02 UTC", report.format_validation_time("2026-08-20T01:02:03Z"))
        self.assertIn("Dependency%20drift", report.render_health_badges(report.STATUS_BROKEN, report.REASON_DEPENDENCY))
        self.assertEqual("a\\|b", report.escape_table("a|b"))
        self.assertEqual("a%25b%0Ac", report.escape_command_value("a%b\nc"))


if __name__ == "__main__":
    unittest.main()
