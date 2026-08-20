import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


VALIDATOR_DIR = Path(__file__).resolve().parents[1]
if str(VALIDATOR_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATOR_DIR))

import static_validator as validator


class StaticValidatorTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write(self, relative_path, text=""):
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def example(self, **updates):
        result = {
            "name": "fixture",
            "path": "examples/fixture",
            "benchmark_file": "examples/fixture/benchmarkingjob.yaml",
        }
        result.update(updates)
        return result

    @staticmethod
    def check(report, name):
        return next(check for check in report.checks if check.name == name)

    def test_clean_example_passes_and_serializes(self):
        self.write("examples/fixture/benchmarkingjob.yaml", "benchmarkingjob: {}\n")

        report = validator.validate_example(self.root, self.example())

        self.assertTrue(report.passed)
        self.assertEqual(validator.PASS, self.check(report, "YAML syntax").status)
        self.assertEqual(validator.SKIP, self.check(report, "Metric empty-pair guard").status)
        payload = json.loads(validator.render_json(validator.StaticValidationReport([report])))
        self.assertTrue(payload["passed"])
        self.assertEqual("fixture", payload["examples"][0]["name"])

    def test_missing_required_paths_are_errors_with_diagnostics(self):
        report = validator.validate_example(self.root, self.example())

        self.assertFalse(report.passed)
        missing = self.check(report, "benchmarkingjob.yaml exists")
        self.assertEqual(validator.ERROR, missing.status)
        self.assertIn("Line N/A", missing.details[0])
        rendered = validator.render_markdown(validator.StaticValidationReport([report]))
        self.assertIn("Overall result: ERROR", rendered)
        self.assertIn("Required path is missing", rendered)

    def test_invalid_yaml_and_broken_repository_references_are_reported(self):
        self.write(
            "examples/fixture/benchmarkingjob.yaml",
            "broken: [\nscript: examples/missing/run.py\ndata: examples/absent/data.json\n",
        )

        report = validator.validate_example(self.root, self.example())

        self.assertEqual(validator.ERROR, self.check(report, "YAML syntax").status)
        self.assertEqual(
            validator.ERROR,
            self.check(report, "Repository path references exist").status,
        )
        self.assertEqual(
            validator.WARNING,
            self.check(report, "Repository path parent references exist").status,
        )

    def test_portability_checks_detect_paths_model_and_cuda(self):
        self.write("examples/fixture/benchmarkingjob.yaml", "benchmarkingjob: {}\n")
        self.write(
            "examples/fixture/run.py",
            "data = '/home/alice/data.json'\n"
            "model_path = '/models/private/model'\n"
            "device = 'cuda'\n",
        )

        report = validator.validate_example(self.root, self.example())

        for name in (
            "Hardcoded local path check",
            "Local model path check",
            "CUDA-only device check",
        ):
            with self.subTest(name=name):
                self.assertEqual(validator.WARNING, self.check(report, name).status)

    def test_cuda_fallback_and_metric_guard_are_accepted(self):
        self.write("examples/fixture/benchmarkingjob.yaml", "benchmarkingjob: {}\n")
        self.write(
            "examples/fixture/run.py",
            "device = 'cuda' if torch.cuda.is_available() else 'cpu'\n",
        )
        self.write(
            "examples/fixture/testenv/metric.py",
            "score = matches / len(same_elements) if same_elements else 0.0\n",
        )

        report = validator.validate_example(self.root, self.example())

        self.assertEqual(validator.PASS, self.check(report, "CUDA-only device check").status)
        metric = self.check(report, "Metric empty-pair guard")
        self.assertEqual(validator.PASS, metric.status)
        self.assertTrue(metric.details)

    def test_unguarded_metric_division_warns(self):
        self.write("examples/fixture/benchmarkingjob.yaml", "benchmarkingjob: {}\n")
        self.write("examples/fixture/testenv/metric.py", "score = hits / len(pairs)\n")

        report = validator.validate_example(self.root, self.example())

        metric = self.check(report, "Metric empty-pair guard")
        self.assertEqual(validator.WARNING, metric.status)
        self.assertIn("Line 1", metric.details[0])

    def test_prepare_environment_contract_accepts_valid_step(self):
        self.write("examples/fixture/benchmarkingjob.yaml", "benchmarkingjob: {}\n")
        self.write("examples/fixture/scripts/prepare.py", "pass\n")
        example = self.example(
            prepare_env={
                "working_directory": "examples/fixture",
                "steps": [{
                    "name": "prepare", "type": "python", "script": "scripts/prepare.py",
                    "args": ["--offline"], "timeout": 10,
                }],
            }
        )

        report = validator.validate_example(self.root, example)

        self.assertEqual(
            validator.PASS,
            self.check(report, "Environment preparation contract").status,
        )

    def test_prepare_environment_contract_rejects_invalid_shapes(self):
        self.write("examples/fixture/benchmarkingjob.yaml", "benchmarkingjob: {}\n")
        examples = [
            self.example(prepare_env="bad"),
            self.example(prepare_env={"working_directory": "missing", "steps": []}),
            self.example(prepare_env={"working_directory": "examples/fixture", "steps": [None]}),
            self.example(prepare_env={"working_directory": "examples/fixture", "steps": [{
                "name": "x", "type": "python", "script": "missing.py", "args": [1], "timeout": True,
            }]}),
        ]

        for example in examples:
            with self.subTest(config=example["prepare_env"]):
                report = validator.validate_example(self.root, example)
                self.assertEqual(
                    validator.ERROR,
                    self.check(report, "Environment preparation contract").status,
                )

    def test_mock_runtime_contract_validates_paths(self):
        self.write("examples/fixture/benchmarkingjob.yaml", "benchmarkingjob: {}\n")
        (self.root / "shared").mkdir()
        (self.root / "fixture-runtime").mkdir()
        valid = self.example(mock_runtime={
            "enabled": True,
            "shared_pythonpath": ["shared"],
            "example_pythonpath": ["fixture-runtime"],
        })
        invalid = self.example(mock_runtime={
            "enabled": True,
            "shared_pythonpath": [],
            "example_pythonpath": ["missing"],
        })

        self.assertEqual(
            validator.PASS,
            self.check(validator.validate_example(self.root, valid), "Mock LLM runtime contract").status,
        )
        self.assertEqual(
            validator.ERROR,
            self.check(validator.validate_example(self.root, invalid), "Mock LLM runtime contract").status,
        )

    def test_yaml_check_skips_when_pyyaml_is_unavailable(self):
        report = validator.ExampleReport("x", "examples/x")
        with mock.patch.dict(sys.modules, {"yaml": None}):
            validator._check_yaml_syntax(report, [])
        self.assertEqual(validator.SKIP, report.checks[0].status)

    def test_helpers_normalize_and_escape_values(self):
        self.assertEqual("examples/x", validator._normalize_repo_path(" './examples/x/' "))
        self.assertTrue(validator._looks_like_generated_dataset_path("examples/x/dataset/train.jsonl"))
        self.assertTrue(validator._is_code_or_config_reference("examples/x/run.py"))
        self.assertEqual("a\\|b", validator._escape_table("a|b"))


if __name__ == "__main__":
    unittest.main()
