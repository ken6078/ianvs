import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


VALIDATOR_DIR = Path(__file__).resolve().parents[1]
if str(VALIDATOR_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATOR_DIR))

from services.regression_detector import (
    CLASS_FIXED_BASELINE,
    CLASS_PASSED,
    CLASS_PRE_EXISTING,
    CLASS_PR_REGRESSION,
    DYNAMIC_ELIGIBILITY_CHECK,
    CheckResult,
    compare_check,
    compare_results,
    classify_cause,
    discover_result_paths,
    error_issue_map,
    git_diff_hunks,
    parse_detail_location,
    render_json,
    render_markdown,
    runtime_smoke_error_detail,
    truncate_comment,
    warning_issue_map,
)


class RegressionDetectorLifecycleTest(unittest.TestCase):
    def test_existing_example_regression_policy_is_preserved(self):
        cases = (
            ("PASS", "PASS", CLASS_PASSED, False),
            ("FAIL", "FAIL", CLASS_PRE_EXISTING, False),
            ("PASS", "FAIL", CLASS_PR_REGRESSION, True),
        )
        for base_status, head_status, classification, blocks_pr in cases:
            with self.subTest(base=base_status, head=head_status):
                report = self.compare(
                    [self.unit("unit", "examples/unit", base_status)],
                    [self.unit("unit", "examples/unit", head_status)],
                )
                self.assertEqual([], report.example_changes)
                self.assertEqual(classification, report.comparisons[0].classification)
                self.assertEqual(blocks_pr, report.blocks_pr)

    def test_added_examples(self):
        cases = (
            ("PASS", "Passed", CLASS_PASSED, False, ""),
            ("FAIL", "Failed", CLASS_PR_REGRESSION, True, ""),
            ("SKIP", "Skipped", "Skipped / inactive", False, "unvalidated"),
        )
        for status, validation, classification, blocks_pr, inventory_status in cases:
            with self.subTest(status=status):
                report = self.compare(
                    [],
                    [self.unit("new", "examples/new", status)],
                )
                change = report.example_changes[0]
                self.assertEqual("Added", change.change)
                self.assertEqual(validation, change.validation)
                self.assertEqual(classification, change.classification)
                self.assertEqual(inventory_status, change.inventory_status)
                self.assertEqual(blocks_pr, report.blocks_pr)

    def test_removed_examples_never_block(self):
        for status in ("PASS", "FAIL"):
            with self.subTest(status=status):
                report = self.compare(
                    [self.unit("old", "examples/old", status)],
                    [],
                )
                change = report.example_changes[0]
                self.assertEqual("Removed", change.change)
                self.assertEqual(
                    "Failed" if status == "FAIL" else "Passed",
                    change.previous_validation_state,
                )
                self.assertFalse(report.blocks_pr)
                self.assertEqual([], report.comparisons)

    def test_rename_is_removed_and_added_without_fuzzy_matching(self):
        report = self.compare(
            [self.unit("old-name", "examples/example", "PASS")],
            [self.unit("new-name", "examples/example", "PASS")],
        )

        self.assertEqual(["Added", "Removed"], [c.change for c in report.example_changes])

    def test_line_mapper_keeps_moved_issue_pre_existing(self):
        class LineMapper:
            @staticmethod
            def maps_to(base_detail, head_detail):
                return base_detail.endswith("old") and head_detail.endswith("new")

        base = CheckResult(
            example="examples/unit",
            example_name="unit",
            name="Static check",
            status="ERROR",
            details=["examples/unit/file.py -> (Line 2): old"],
        )
        head = CheckResult(
            example="examples/unit",
            example_name="unit",
            name="Static check",
            status="ERROR",
            details=["examples/unit/file.py -> (Line 5): new"],
        )

        comparison = compare_check(base, head, line_mapper=LineMapper())

        self.assertEqual(CLASS_PRE_EXISTING, comparison.classification)
        self.assertFalse(comparison.blocks_pr)

    def test_fixed_blocking_issue_is_classified_as_fixed_baseline(self):
        base = CheckResult(
            example="examples/unit", example_name="unit", name="Static",
            status="ERROR", file="file.py", details=["old problem"],
        )
        head = CheckResult(
            example="examples/unit", example_name="unit", name="Static", status="PASS",
        )
        comparison = compare_check(base, head)
        self.assertEqual(CLASS_FIXED_BASELINE, comparison.classification)
        self.assertEqual(1, comparison.fixed_issue_count)
        self.assertFalse(comparison.blocks_pr)

    def test_warning_deltas_never_block_but_are_counted(self):
        base = CheckResult(
            example="examples/unit", example_name="unit", name="Portability",
            status="WARNING", details=["existing", "fixed"],
        )
        head = CheckResult(
            example="examples/unit", example_name="unit", name="Portability",
            status="WARNING", details=["existing", "new"],
        )
        comparison = compare_check(base, head)
        self.assertEqual(1, comparison.pre_existing_warning_count)
        self.assertEqual(1, comparison.new_warning_count)
        self.assertEqual(1, comparison.fixed_warning_count)
        self.assertFalse(comparison.blocks_pr)

    def test_runtime_smoke_collapses_traceback_to_exception(self):
        check = CheckResult(
            example="examples/unit", example_name="unit", name="Runtime smoke test",
            status="FAIL", message="failed", file="job.yaml",
            details=["Traceback line", "ValueError: invalid fixture", "later output"],
        )
        self.assertEqual("ValueError: invalid fixture", runtime_smoke_error_detail(check))
        issues = error_issue_map(check)
        self.assertEqual(1, len(issues))
        self.assertEqual("ValueError: invalid fixture", next(iter(issues.values())).detail)

    def test_issue_maps_fall_back_to_file_message_and_name(self):
        file_check = CheckResult("examples/u", "x", "ERROR", file="file.py")
        message_check = CheckResult("examples/u", "x", "FAIL", message="failed")
        warning = CheckResult("examples/u", "warn", "WARNING", message="careful")
        self.assertEqual("file.py", next(iter(error_issue_map(file_check).values())).detail)
        self.assertEqual("failed", next(iter(error_issue_map(message_check).values())).detail)
        self.assertEqual("careful", next(iter(warning_issue_map(warning).values())).detail)
        self.assertEqual({}, warning_issue_map(message_check))

    def test_detail_location_and_git_hunk_parsing(self):
        location = parse_detail_location("examples/a.py -> (Line 12): broken")
        self.assertEqual(("examples/a.py", 12, "broken"), (location.file, location.line, location.message))
        self.assertIsNone(parse_detail_location("not a diagnostic"))
        completed = mock.Mock(returncode=0, stdout="@@ -2,3 +2,5 @@\n@@ -10 +12 @@\n")
        with mock.patch("services.regression_detector.subprocess.run", return_value=completed):
            self.assertEqual([(2, 3, 5), (10, 1, 1)], git_diff_hunks("base", "head", "file.py"))

    def test_cause_classification_covers_known_categories(self):
        cases = {
            "GPU required": "Failed: Hardware assumption",
            "metric empty-pair": "Failed: Metric edge case",
            "model unavailable": "Failed: Model/resource drift",
            "JSONL dataset": "Failed: Dataset/resource drift",
            "requirements package": "Failed: Dependency drift",
            "YAML path": "Failed: Known issue",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(expected, classify_cause(CheckResult("e", text, "FAIL")))

    def test_renderers_include_counts_and_machine_readable_fields(self):
        report = self.compare(
            [self.unit("unit", "examples/unit", "PASS")],
            [self.unit("unit", "examples/unit", "FAIL")],
        )
        markdown = render_markdown(report)
        payload = json.loads(render_json(report))
        self.assertIn("PR Regression", markdown)
        self.assertIn("the base branch and PR validation results", markdown)
        self.assertIn("Pre-existing failures do not block", markdown)
        self.assertTrue(payload["blocks_pr"])
        self.assertEqual(1, payload["new_error_count"])

    def test_result_discovery_deduplicates_directory_file_and_glob(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "a.json"
            second = root / "nested/b.json"
            second.parent.mkdir()
            first.write_text("{}")
            second.write_text("{}")
            found = discover_result_paths([str(root), str(first), str(root / "**/*.json")])
            self.assertEqual({first.resolve(), second.resolve()}, {path.resolve() for path in found})

    def test_comment_truncation_and_escape_helpers(self):
        from services import regression_detector as detector
        short = "short"
        self.assertEqual(short, truncate_comment(short))
        truncated = truncate_comment("x" * (detector.MAX_COMMENT_BODY_CHARS + 1))
        self.assertLessEqual(len(truncated), detector.MAX_COMMENT_BODY_CHARS)
        self.assertIn("Report truncated", truncated)
        self.assertEqual("a%25b%0Ac", detector.escape_command_value("a%b\nc"))
        self.assertEqual("a%3Ab%2Cc", detector.escape_command_property("a:b,c"))

    def compare(self, base_units, head_units):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base_paths = self.write_results(root / "base.json", base_units)
            head_paths = self.write_results(root / "head.json", head_units)
            return compare_results(base_paths, head_paths)

    @staticmethod
    def write_results(path, units):
        if not units:
            return []
        path.write_text(json.dumps({"examples": units}), encoding="utf-8")
        return [path]

    @staticmethod
    def unit(name, path, status):
        if status == "SKIP":
            check = {
                "name": DYNAMIC_ELIGIBILITY_CHECK,
                "status": "SKIP",
                "details": ["inventory status: unvalidated"],
            }
        else:
            check = {
                "name": "Runtime smoke test",
                "status": status,
                "message": "Smoke failed" if status == "FAIL" else "Smoke passed",
                "details": ["RuntimeError: failure"] if status == "FAIL" else [],
            }
        return {"name": name, "path": path, "checks": [check]}


if __name__ == "__main__":
    unittest.main()
