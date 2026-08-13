import sys
import unittest
from pathlib import Path


VALIDATOR_DIR = Path(__file__).resolve().parents[1]
if str(VALIDATOR_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATOR_DIR))

from services.regression_detector import CheckResult, compare_check


class RegressionDetectorTest(unittest.TestCase):
    def test_runtime_smoke_traceback_is_one_pre_existing_error(self):
        base = self._runtime_failure("/tmp/base/benchmarkingjob.yaml", "base-id")
        head = self._runtime_failure("/tmp/head/benchmarkingjob.yaml", "head-id")

        comparison = compare_check(base, head)

        self.assertIsNotNone(comparison)
        self.assertEqual(1, comparison.base_issue_count)
        self.assertEqual(1, comparison.head_issue_count)
        self.assertEqual(1, comparison.pre_existing_issue_count)
        self.assertEqual(0, comparison.new_issue_count)
        self.assertEqual(
            ["RuntimeError: Demo execution failure"],
            comparison.pre_existing_details,
        )

    @staticmethod
    def _runtime_failure(file_name, testcase_id):
        return CheckResult(
            example="examples/llm_simple_qa",
            name="Runtime smoke test (mocked_llm)",
            status="FAIL",
            message="Smoke test failed with exit code 1.",
            file=file_name,
            details=[
                "Traceback (most recent call last):",
                "RuntimeError: Demo execution failure",
                "RuntimeError: testcase(id={}) runs failed".format(testcase_id),
            ],
        )


if __name__ == "__main__":
    unittest.main()
