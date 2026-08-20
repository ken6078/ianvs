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

import dependency_validator as validator


class DependencyValidatorTest(unittest.TestCase):
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
        result = {"name": "fixture", "path": "examples/fixture"}
        result.update(updates)
        return result

    @staticmethod
    def check(report, name):
        return next(check for check in report.checks if check.name == name)

    def test_no_dependency_declaration_is_an_explicit_skip(self):
        report = validator.validate_example(
            self.root, self.example(), ("3.8",), validator.INSTALL_MODE_SKIP, 10
        )
        self.assertTrue(report.passed)
        self.assertEqual(validator.SKIP, report.checks[0].status)

    def test_missing_and_empty_dependency_files_fail(self):
        example = self.example(requirements_file="examples/fixture/requirements.txt")
        missing = validator.validate_example(
            self.root, example, ("3.8",), validator.INSTALL_MODE_SKIP, 10
        )
        self.assertEqual(validator.FAIL, missing.checks[0].status)

        self.write("examples/fixture/requirements.txt", "# only a comment\n")
        empty = validator.validate_example(
            self.root, example, ("3.8",), validator.INSTALL_MODE_SKIP, 10
        )
        self.assertEqual(
            validator.FAIL, self.check(empty, "Dependency file is not empty").status
        )

    def test_valid_requirements_cover_import_aliases_and_project_dependencies(self):
        self.write("requirements.txt", "requests>=2\n")
        self.write(
            "examples/fixture/requirements.txt",
            "PyYAML>=6\npillow>=10\nopencv-python>=4\nscikit-learn>=1\n",
        )
        self.write(
            "examples/fixture/run.py",
            "import yaml\nimport PIL\nimport cv2\nimport sklearn\nimport requests\nimport json\n",
        )
        example = self.example(requirements_file="examples/fixture/requirements.txt")

        report = validator.validate_example(
            self.root, example, ("3.8", "3.10"), validator.INSTALL_MODE_SKIP, 10
        )

        self.assertTrue(report.passed)
        self.assertEqual(validator.PASS, self.check(report, "Runtime imports declared").status)
        self.assertEqual(validator.SKIP, self.check(report, "pip install check").status)

    def test_undeclared_import_and_incompatible_marker_fail(self):
        self.write(
            "examples/fixture/requirements.txt",
            "requests; python_version >= '4.0'\n",
        )
        self.write("examples/fixture/run.py", "import third_party_missing\n")

        report = validator.validate_example(
            self.root,
            self.example(requirements_file="examples/fixture/requirements.txt"),
            ("3.8", "3.10"),
            validator.INSTALL_MODE_SKIP,
            10,
        )

        self.assertEqual(
            validator.FAIL,
            self.check(report, "Python version marker compatibility").status,
        )
        self.assertEqual(
            ["third_party_missing"], self.check(report, "Runtime imports declared").details
        )

    def test_requirement_parser_handles_options_references_urls_and_errors(self):
        self.write("deps/extra.txt", "valid-package\n")
        lines = [
            (1, "-r extra.txt"),
            (2, "-r absent.txt"),
            (3, "--index-url https://index.invalid/simple"),
            (4, "pkg @ https://example.invalid/pkg.whl"),
            (5, "not a valid requirement !!!"),
            (6, "requests >= 2  # comment"),
        ]

        requirements, errors = validator._parse_requirements(lines, self.root / "deps")

        self.assertEqual(["requests>=2"], [str(value) for value in requirements])
        self.assertEqual(2, len(errors))
        self.assertTrue(any("absent.txt" in error for error in errors))

    def test_runtime_files_follow_benchmark_testenv_and_algorithm_metadata(self):
        self.write(
            "examples/fixture/benchmarkingjob.yaml",
            "benchmarkingjob:\n  testenv: examples/fixture/testenv.yaml\n"
            "  test_object:\n    algorithms:\n      - url: examples/fixture/algorithm.yaml\n",
        )
        self.write(
            "examples/fixture/testenv.yaml",
            "testenv:\n  metrics:\n    - url: examples/fixture/metric.py\n",
        )
        self.write(
            "examples/fixture/algorithm.yaml",
            "algorithm:\n  modules:\n    - url: examples/fixture/model.py\n",
        )
        metric = self.write("examples/fixture/metric.py", "import numpy\n")
        model = self.write("examples/fixture/model.py", "import torch\n")

        files = validator._runtime_python_files(
            self.root,
            self.example(benchmark_file="examples/fixture/benchmarkingjob.yaml"),
        )

        self.assertEqual({metric.resolve(), model.resolve()}, {path.resolve() for path in files})

    def test_python_import_parser_ignores_relative_and_invalid_source(self):
        source = self.write(
            "examples/fixture/source.py",
            "import os, external.submodule\nfrom package.child import item\nfrom . import local\n",
        )
        self.assertEqual(
            {"os", "external", "package"}, validator._imports_from_python_file(source)
        )
        source.write_text("not valid python !", encoding="utf-8")
        self.assertEqual(set(), validator._imports_from_python_file(source))

    @mock.patch.object(validator, "_ensure_pip_available", return_value=None)
    @mock.patch.object(validator.subprocess, "run")
    def test_dry_run_constructs_command_and_records_output(self, run, _ensure):
        run.return_value = SimpleNamespace(returncode=0, stdout="ok\n")
        report = validator.ExampleReport("x", "examples/x")

        validator._check_pip_install(
            report, self.root, "requirements.txt", validator.INSTALL_MODE_DRY_RUN, 9
        )

        command = run.call_args.args[0]
        self.assertIn("--dry-run", command)
        self.assertEqual(validator.PASS, report.checks[-1].status)
        self.assertEqual(["ok"], report.checks[-1].details)

    @mock.patch.object(validator, "_ensure_pip_available", return_value=None)
    @mock.patch.object(validator.subprocess, "run", side_effect=subprocess.TimeoutExpired("pip", 3))
    def test_pip_timeout_is_a_failure(self, _run, _ensure):
        report = validator.ExampleReport("x", "examples/x")
        validator._check_pip_install(
            report, self.root, "requirements.txt", validator.INSTALL_MODE_INSTALL, 3
        )
        self.assertEqual(validator.FAIL, report.checks[-1].status)
        self.assertIn("timed out", report.checks[-1].message)

    @mock.patch.object(validator.subprocess, "run")
    def test_pip_bootstrap_success_failure_and_timeout(self, run):
        unavailable = SimpleNamespace(returncode=1, stdout="no pip")
        bootstrapped = SimpleNamespace(returncode=0, stdout="installed")
        run.side_effect = [unavailable, bootstrapped]
        self.assertEqual(0, validator._ensure_pip_available(self.root, 5)["returncode"])

        run.side_effect = [unavailable, SimpleNamespace(returncode=2, stdout="failed")]
        self.assertEqual(2, validator._ensure_pip_available(self.root, 5)["returncode"])

        run.side_effect = [unavailable, subprocess.TimeoutExpired("ensurepip", 5)]
        self.assertEqual(1, validator._ensure_pip_available(self.root, 5)["returncode"])

    def test_selection_rendering_and_output_truncation(self):
        examples = [
            self.example(name="one", path="examples/one", benchmark_file="examples/one/job.yaml"),
            self.example(name="two", path="examples/two"),
        ]
        self.assertEqual(
            [examples[0]], validator._select_examples(examples, ["./examples/one/"], False)
        )
        self.assertEqual(examples, validator._select_examples(examples, [], False))
        self.assertEqual(
            ["0", "1", "... output truncated ..."],
            validator._summarize_output("0\n1\n2\n", max_lines=2),
        )
        rendered = validator.render_dependency_markdown(
            validator.StaticValidationReport([validator.ExampleReport("one", "examples/one")])
        )
        self.assertTrue(rendered.startswith("# Dependency Validation Report"))


if __name__ == "__main__":
    unittest.main()
