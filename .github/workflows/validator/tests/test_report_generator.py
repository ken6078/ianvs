import json
import sys
import tempfile
import unittest
from pathlib import Path


VALIDATOR_DIR = Path(__file__).resolve().parents[1]
if str(VALIDATOR_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATOR_DIR))

from services.report_generator import (
    DYNAMIC_ELIGIBILITY_CHECK,
    SKIP,
    CheckResult,
    CombinedReport,
    ExampleResult,
    render_full_report,
)


class ReportGeneratorTest(unittest.TestCase):
    def test_dynamic_skipped_examples_are_the_last_section(self):
        report = CombinedReport(
            examples=[
                ExampleResult(
                    name="waiting_for_ci",
                    path="examples/waiting_for_ci",
                    passed=True,
                    checks=[
                        CheckResult(
                            name=DYNAMIC_ELIGIBILITY_CHECK,
                            status=SKIP,
                            details=["inventory status: unvalidated"],
                        )
                    ],
                )
            ],
            source_files=["validator-results/result.json"],
        )

        with tempfile.TemporaryDirectory() as directory:
            regression_json = Path(directory) / "regression.json"
            regression_json.write_text(
                json.dumps({"comparisons": []}), encoding="utf-8"
            )
            rendered = render_full_report(
                report,
                regression_json=str(regression_json),
            )

        self.assertLess(
            rendered.index("## Regression Summary"),
            rendered.index("## Collected Result Files"),
        )
        self.assertLess(
            rendered.index("## Collected Result Files"),
            rendered.index("## Skipped Examples"),
        )
        self.assertTrue(
            rendered.rstrip().endswith(
                "| `examples/waiting_for_ci` | CI/CD ongoing |"
            )
        )


if __name__ == "__main__":
    unittest.main()
