import sys
import unittest
from pathlib import Path


VALIDATOR_DIR = Path(__file__).resolve().parents[1]
if str(VALIDATOR_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATOR_DIR))

from services.report_generator import CheckResult, dynamic_regression_summary


class ReportGeneratorRegressionTest(unittest.TestCase):
    def test_dynamic_regression_lists_at_most_ten_new_warnings(self):
        comparisons = [
            {
                "example": "examples/example-{:02d}".format(index),
                "check": "lint",
                "new_warning_count": 1,
                "new_warning_details": ["new-warning-{:02d}".format(index)],
            }
            for index in range(12)
        ]

        rendered = "\n".join(
            dynamic_regression_summary(
                comparisons,
                [comparison["example"] for comparison in comparisons],
            )
        )

        self.assertIn("**Result:** PASS — No new ERRORs were detected.", rendered)
        self.assertIn("new-warning-09", rendered)
        self.assertNotIn("new-warning-10", rendered)
        self.assertNotIn("new-warning-11", rendered)
        self.assertIn("### New warnings (10 of 12)", rendered)

        rendered_five = "\n".join(
            dynamic_regression_summary(
                comparisons[:5],
                [comparison["example"] for comparison in comparisons[:5]],
            )
        )
        self.assertIn("### New warnings (5 of 5)", rendered_five)

    def test_runtime_smoke_traceback_counts_as_one_error(self):
        check = CheckResult(
            name="Runtime smoke test (mocked_llm)",
            status="FAIL",
            message="Smoke test failed with exit code 1.",
            details=[
                "Traceback (most recent call last):",
                "  File \"benchmarking.py\", line 37, in main",
                "RuntimeError: Demo execution failure",
            ],
        )

        self.assertEqual(1, check.issue_count)


if __name__ == "__main__":
    unittest.main()
