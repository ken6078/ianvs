import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


VALIDATOR_DIR = Path(__file__).resolve().parents[1]
if str(VALIDATOR_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATOR_DIR))

import smoke_test_validator as validator


class SmokeTestValidatorTest(unittest.TestCase):
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
    def check(report, prefix):
        return next(check for check in report.checks if check.name.startswith(prefix))

    def test_missing_benchmark_fails_without_running(self):
        report = validator.validate_example(self.root, self.example(), True, 5, ())
        self.assertFalse(report.passed)
        self.assertEqual(validator.FAIL, report.checks[0].status)

    def test_no_execute_validates_inventory_jsonl_and_skips_runtime(self):
        self.write("examples/fixture/benchmarkingjob.yaml", "benchmarkingjob: {}\n")
        self.write("examples/fixture/dataset/test.jsonl", '{"question": "q"}\n')
        example = self.example(dataset={
            "root": "examples/fixture/dataset",
            "structure": ["test.jsonl"],
        })

        report = validator.validate_example(self.root, example, False, 5, ())

        self.assertTrue(report.passed)
        self.assertEqual(validator.PASS, self.check(report, "JSONL dataset").status)
        self.assertEqual(validator.SKIP, self.check(report, "Runtime smoke").status)

    def test_jsonl_validation_reports_missing_empty_blank_invalid_and_non_object(self):
        valid = self.write("data/valid.jsonl", '{"a": 1}\n')
        invalid = self.write("data/invalid.jsonl", '\nnot-json\n[]\n')
        empty = self.write("data/empty.jsonl", "")
        missing = self.root / "data/missing.jsonl"

        self.assertEqual([], validator._validate_jsonl_file(valid, self.root))
        issues = validator._validate_jsonl_file(invalid, self.root)
        self.assertTrue(any("blank line" in issue for issue in issues))
        self.assertTrue(any("Expecting value" in issue for issue in issues))
        self.assertTrue(any("not a JSON object" in issue for issue in issues))
        self.assertIn("file is empty", validator._validate_jsonl_file(empty, self.root)[0])
        self.assertEqual([], validator._validate_jsonl_file(empty, self.root, allow_empty=True))
        self.assertIn("file is missing", validator._validate_jsonl_file(missing, self.root)[0])

    def test_dataset_paths_fall_back_to_testenv_and_compute_common_root(self):
        self.write(
            "examples/fixture/benchmarkingjob.yaml",
            "benchmarkingjob:\n  testenv: examples/fixture/testenv.yaml\n",
        )
        self.write(
            "examples/fixture/testenv.yaml",
            "testenv:\n  dataset:\n    train_data: dataset/corpus/train/data.jsonl\n"
            "    test_data: dataset/corpus/test/data.jsonl\n",
        )
        config = validator._dataset_config_from_example(self.root, self.example())
        self.assertEqual(2, len(config.paths))
        self.assertEqual("dataset/corpus", config.root)

    def test_dataset_preparation_runs_supported_flags(self):
        script = self.write(
            "examples/fixture/prepare.py",
            "# supports --dataset-root and --smoke\n",
        )
        report = validator.ExampleReport("fixture", "examples/fixture")
        completed = SimpleNamespace(returncode=0, stdout="prepared\n")
        with mock.patch.object(validator.subprocess, "run", return_value=completed) as run:
            result = validator._prepare_dataset(
                report,
                self.root,
                self.example(dataset={"prepare_script": str(script.relative_to(self.root))}),
                self.root / "temporary-data",
                7,
            )
        self.assertEqual(self.root / "temporary-data", result)
        self.assertIn("--dataset-root", run.call_args.args[0])
        self.assertIn("--smoke", run.call_args.args[0])
        self.assertEqual(validator.PASS, report.checks[-1].status)

    def test_dataset_preparation_handles_missing_failure_and_timeout(self):
        example = self.example(dataset={"prepare_script": "missing.py"})
        report = validator.ExampleReport("fixture", "examples/fixture")
        self.assertIsNone(validator._prepare_dataset(report, self.root, example, self.root / "d", 2))
        self.assertEqual(validator.FAIL, report.checks[-1].status)

        script = self.write("prepare.py", "pass\n")
        example = self.example(dataset={"prepare_script": "prepare.py"})
        with mock.patch.object(
            validator.subprocess, "run", return_value=SimpleNamespace(returncode=3, stdout="bad")
        ):
            self.assertIsNone(validator._prepare_dataset(report, self.root, example, self.root / "d", 2))
        with mock.patch.object(
            validator.subprocess, "run", side_effect=subprocess.TimeoutExpired("prepare", 2)
        ):
            self.assertIsNone(validator._prepare_dataset(report, self.root, example, self.root / "d", 2))

    def test_environment_preparation_executes_steps_in_order_and_stops_on_failure(self):
        self.write("examples/fixture/one.py", "pass\n")
        self.write("examples/fixture/two.py", "pass\n")
        example = self.example(prepare_env={
            "working_directory": "examples/fixture",
            "steps": [
                {"name": "one", "type": "python", "script": "one.py", "args": [], "timeout": 5},
                {"name": "two", "type": "python", "script": "two.py", "args": [], "timeout": 5},
            ],
        })
        results = [
            SimpleNamespace(returncode=0, stdout="first"),
            SimpleNamespace(returncode=1, stdout="second"),
        ]
        with mock.patch.object(validator.subprocess, "run", side_effect=results) as run:
            report = validator._prepare_example_environment(self.root, example)
        self.assertEqual(2, run.call_count)
        self.assertEqual([validator.PASS, validator.FAIL], [c.status for c in report.checks])

    def test_environment_preparation_rejects_bad_configuration_and_escape(self):
        cases = [
            self.example(),
            self.example(prepare_env={"working_directory": "", "steps": []}),
            self.example(prepare_env={"working_directory": "../outside", "steps": [{}]}),
            self.example(prepare_env={"working_directory": "missing", "steps": [{}]}),
        ]
        expected = [validator.SKIP, validator.FAIL, validator.FAIL, validator.FAIL]
        for example, status in zip(cases, expected):
            with self.subTest(example=example):
                report = validator._prepare_example_environment(self.root, example)
                self.assertEqual(status, report.checks[0].status)

    def test_preparation_step_schema_is_fully_validated(self):
        invalid_steps = [
            None,
            {},
            {"name": "", "type": "python", "script": "x", "args": [], "timeout": 1},
            {"name": "x", "type": "python", "script": "x", "args": [1], "timeout": 1},
            {"name": "x", "type": "python", "script": "x", "args": [], "timeout": True},
        ]
        for step in invalid_steps:
            with self.subTest(step=step):
                self.assertTrue(validator._validate_preparation_step(step, 1))

    def test_mock_runtime_configures_environment_and_preserves_pythonpath(self):
        (self.root / "shared").mkdir()
        (self.root / "specific").mkdir()
        env = {"PYTHONPATH": "existing"}
        mocked, error = validator._configure_mock_runtime(
            env,
            self.root,
            self.example(mock_runtime={
                "enabled": True,
                "shared_pythonpath": ["shared"],
                "example_pythonpath": ["specific"],
            }),
        )
        self.assertTrue(mocked)
        self.assertEqual("", error)
        self.assertEqual("1", env["IANVS_LLM_MOCK"])
        self.assertTrue(env["PYTHONPATH"].endswith("existing"))

    def test_mock_runtime_rejects_invalid_paths(self):
        configs = [
            {"enabled": True, "shared_pythonpath": [], "example_pythonpath": ["x"]},
            {"enabled": True, "shared_pythonpath": [1], "example_pythonpath": ["x"]},
            {"enabled": True, "shared_pythonpath": ["../escape"], "example_pythonpath": ["x"]},
            {"enabled": True, "shared_pythonpath": ["missing"], "example_pythonpath": ["x"]},
        ]
        for config in configs:
            with self.subTest(config=config):
                mocked, error = validator._configure_mock_runtime({}, self.root, self.example(mock_runtime=config))
                self.assertTrue(mocked)
                self.assertTrue(error)

    @mock.patch.object(validator.subprocess, "run")
    def test_smoke_command_success_failure_and_timeout(self, run):
        report = validator.ExampleReport("fixture", "examples/fixture")
        run.return_value = SimpleNamespace(returncode=0, stdout="ok")
        validator._run_smoke_command(report, self.root, self.example(), "job.yaml", None, ["run"], 3)
        self.assertEqual(validator.PASS, report.checks[-1].status)

        run.return_value = SimpleNamespace(returncode=2, stdout="bad")
        validator._run_smoke_command(report, self.root, self.example(), "job.yaml", None, ["run"], 3)
        self.assertEqual(validator.FAIL, report.checks[-1].status)

        run.side_effect = subprocess.TimeoutExpired("run", 3)
        validator._run_smoke_command(report, self.root, self.example(), "job.yaml", None, ["run"], 3)
        self.assertIn("timed out", report.checks[-1].message)

    def test_materialized_benchmark_rewrites_dataset_and_workspace(self):
        self.write(
            "examples/fixture/benchmarkingjob.yaml",
            "benchmarkingjob:\n  testenv: examples/fixture/testenv.yaml\n  workspace: old\n",
        )
        self.write(
            "examples/fixture/testenv.yaml",
            "testenv:\n  dataset:\n    test_data: dataset/original/test.jsonl\n",
        )
        with tempfile.TemporaryDirectory() as directory:
            result = validator._materialize_smoke_benchmark(
                self.root,
                "examples/fixture/benchmarkingjob.yaml",
                self.root / "prepared",
                Path(directory),
            )
            payload = __import__("yaml").safe_load(Path(result).read_text())
            testenv = __import__("yaml").safe_load(Path(payload["benchmarkingjob"]["testenv"]).read_text())
            self.assertIn("prepared", testenv["testenv"]["dataset"]["test_data"])
            self.assertIn("workspace", payload["benchmarkingjob"]["workspace"])

    def test_path_and_dataset_helpers_cover_boundaries(self):
        self.assertTrue(validator._path_is_within("dataset/a.jsonl", "dataset"))
        self.assertFalse(validator._path_is_within("dataset-other/a.jsonl", "dataset"))
        self.assertEqual("a.jsonl", validator._relative_dataset_path("dataset/a.jsonl", "dataset"))
        self.assertTrue(validator._looks_like_training_data_path(Path("data/train/file.jsonl")))
        self.assertEqual("example-name", validator._safe_path_component("example/name"))
        config = validator.DatasetConfig([], "")
        root = validator._temporary_dataset_root("/tmp/work", config, {"name": "a/b"})
        self.assertEqual(Path("/tmp/work/dataset/a-b"), root)
        self.assertEqual(["0", "... output truncated ..."], validator._summarize_output("0\n1", 1))


if __name__ == "__main__":
    unittest.main()
