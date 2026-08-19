import sys
import unittest
from pathlib import Path


VALIDATOR_DIR = Path(__file__).resolve().parents[1]
if str(VALIDATOR_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATOR_DIR))

from services.report_generator import regression_example_change_summary


class ReportGeneratorExampleChangesTest(unittest.TestCase):
    def test_added_and_removed_examples_are_rendered_with_counts(self):
        rendered = "\n".join(
            regression_example_change_summary(
                [
                    {
                        "change": "Added",
                        "name": "new-unit",
                        "path": "examples/new",
                        "validation": "Passed",
                        "classification": "Passed",
                        "blocks_pr": False,
                    },
                    {
                        "change": "Removed",
                        "name": "old-unit",
                        "path": "examples/old",
                        "validation": "Removed",
                        "classification": "Removed",
                        "blocks_pr": False,
                        "previous_validation_state": "Failed",
                    },
                ]
            )
        )

        self.assertIn("Added examples: 1", rendered)
        self.assertIn("Removed examples: 1", rendered)
        self.assertIn("`examples/new` (`new-unit`)", rendered)
        self.assertIn("Removed (base: Failed)", rendered)

    def test_no_changes_uses_compact_message(self):
        rendered = "\n".join(regression_example_change_summary([]))
        self.assertIn("Example changes:** None", rendered)
        self.assertNotIn("## Example Changes", rendered)


if __name__ == "__main__":
    unittest.main()
