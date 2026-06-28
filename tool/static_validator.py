# Copyright 2026 The KubeEdge Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Static validation checks for Ianvs examples.

The validator is intentionally lightweight. It catches common example
maintenance issues before running heavyweight dependency or smoke tests.
"""

from __future__ import print_function

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only in incomplete envs.
    yaml = None


README_NAMES = (
    "README.md",
    "readme.md",
    "README.rst",
    "README.txt",
    "README",
)

YAML_SUFFIXES = (".yaml", ".yml")

TEXT_SUFFIXES = (
    ".cfg",
    ".ini",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".rst",
    ".sh",
    ".text",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
)

SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "workspace",
}

LOCAL_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![:\w])"
    r"("
    r"/(?:home|Users|root|mnt|media|data|workspace|tmp)/"
    r"[^\s'\"`,)\]}<>]+"
    r")"
)

WINDOWS_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![\w])([A-Za-z]:\\[^\s'\"`,)\]}<>]+)"
)

HOME_RELATIVE_PATH_RE = re.compile(r"(?<![\w])(~\/[^\s'\"`,)\]}<>]+)")

CUDA_ONLY_PATTERNS = (
    re.compile(
        r"^\s*(?:device|DEVICE)\s*=\s*['\"]cuda(?::\d+)?['\"]\s*(?:#.*)?$"
    ),
    re.compile(r"^\s*device\s*:\s*['\"]?cuda(?::\d+)?['\"]?\s*(?:#.*)?$"),
    re.compile(r"torch\.device\(\s*['\"]cuda(?::\d+)?['\"]\s*\)"),
    re.compile(r"\.to\(\s*['\"]cuda(?::\d+)?['\"]\s*\)"),
)

LOCAL_MODEL_RE = re.compile(
    r"(?:model(?:_path)?|from_pretrained|AutoModel|AutoTokenizer|path)"
    r".*?"
    r"(['\"])(?P<path>(?:/[^'\"]*models?[^'\"]*|~\/[^'\"]*models?[^'\"]*|"
    r"[A-Za-z]:\\[^'\"]*models?[^'\"]*|\.{0,2}\/[^'\"]*models?[^'\"]*))\1",
    re.IGNORECASE,
)

REPO_PATH_RE = re.compile(
    r"(?P<path>(?:\.\/)?(?:examples|dataset|resources)/"
    r"[A-Za-z0-9_./@+=: -]+)"
)

TRAILING_PATH_CHARS = ".,:;)'\"`]}<>"


class ValidationIssue:
    """One static validation failure."""

    def __init__(
        self,
        check: str,
        severity: str,
        example: str,
        file: Optional[str],
        line: Optional[int],
        message: str,
        value: Optional[str] = None,
    ):
        self.check = check
        self.severity = severity
        self.example = example
        self.file = file
        self.line = line
        self.message = message
        self.value = value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity,
            "example": self.example,
            "file": self.file,
            "line": self.line,
            "message": self.message,
            "value": self.value,
        }


class StaticValidationReport:
    """Static validation result for one repository scan."""

    def __init__(
        self,
        root: str,
        examples_checked: List[str],
        issues: List[ValidationIssue],
    ):
        self.root = root
        self.examples_checked = examples_checked
        self.issues = issues

    @property
    def passed(self) -> bool:
        return not self.issues

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root": self.root,
            "passed": self.passed,
            "examples_checked": self.examples_checked,
            "issue_count": len(self.issues),
            "issues": [issue.to_dict() for issue in self.issues],
        }


class StaticValidator:
    """Run static checks over Ianvs example directories."""

    def __init__(self, root_path: str = "."):
        self.root = Path(root_path).resolve()
        self.issues: List[ValidationIssue] = []
        self._line_cache: Dict[Path, List[str]] = {}

    def validate(
        self, examples: Optional[Sequence[str]] = None
    ) -> StaticValidationReport:
        example_paths = self._resolve_examples(examples)

        for example_path in example_paths:
            self._validate_example(example_path)

        return StaticValidationReport(
            root=str(self.root),
            examples_checked=[self._relpath(path) for path in example_paths],
            issues=self.issues,
        )

    def _resolve_examples(
        self, examples: Optional[Sequence[str]]
    ) -> List[Path]:
        if examples:
            return [self._resolve_input_path(example) for example in examples]

        examples_root = self.root / "examples"
        if not examples_root.exists():
            return []

        discovered = [
            path.parent
            for path in examples_root.rglob("benchmarkingjob.yaml")
            if not self._is_skipped(path)
        ]
        return sorted(set(discovered), key=lambda path: self._relpath(path))

    def _resolve_input_path(self, value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self.root / path
        return path.resolve()

    def _validate_example(self, example_path: Path) -> None:
        example_name = self._relpath(example_path)

        if not example_path.exists():
            self._add_issue(
                "missing_example",
                "error",
                example_name,
                None,
                None,
                "Example directory does not exist.",
                str(example_path),
            )
            return

        if not example_path.is_dir():
            self._add_issue(
                "invalid_example_path",
                "error",
                example_name,
                None,
                None,
                "Example path is not a directory.",
                str(example_path),
            )
            return

        self._validate_required_files(example_path)
        self._validate_yaml_syntax(example_path)
        self._scan_text_files(example_path)
        self._validate_benchmarkingjob(example_path)

    def _validate_required_files(self, example_path: Path) -> None:
        example_name = self._relpath(example_path)
        benchmarkingjob = example_path / "benchmarkingjob.yaml"

        if not benchmarkingjob.is_file():
            self._add_issue(
                "missing_yaml_file",
                "error",
                example_name,
                self._relpath(benchmarkingjob),
                None,
                "Missing required benchmarkingjob.yaml file.",
            )

        if not any((example_path / readme).is_file() for readme in README_NAMES):
            self._add_issue(
                "missing_readme_file",
                "error",
                example_name,
                self._relpath(example_path),
                None,
                "Missing README file for example.",
            )

    def _validate_yaml_syntax(self, example_path: Path) -> None:
        for yaml_path in self._iter_files(example_path, YAML_SUFFIXES):
            self._load_yaml(yaml_path, example_path)

    def _validate_benchmarkingjob(self, example_path: Path) -> None:
        benchmarkingjob = example_path / "benchmarkingjob.yaml"
        if not benchmarkingjob.is_file():
            return

        data = self._load_yaml(benchmarkingjob, example_path)
        if not isinstance(data, dict):
            return

        job = data.get("benchmarkingjob", data)
        if not isinstance(job, dict):
            return

        testenv_value = job.get("testenv")
        if not testenv_value:
            self._add_issue(
                "missing_yaml_reference",
                "error",
                self._relpath(example_path),
                self._relpath(benchmarkingjob),
                None,
                "benchmarkingjob.yaml does not define a testenv YAML file.",
            )
        else:
            testenv_path = self._validate_referenced_yaml(
                example_path,
                benchmarkingjob,
                str(testenv_value),
                "missing_testenv_yaml",
                "Broken or missing test environment YAML reference.",
            )
            if testenv_path and testenv_path.is_file():
                self._validate_testenv_yaml(example_path, testenv_path)

        for value in self._extract_algorithm_urls(job):
            algorithm_path = self._validate_referenced_yaml(
                example_path,
                benchmarkingjob,
                value,
                "missing_algorithm_yaml",
                "Broken or missing algorithm YAML reference.",
            )
            if algorithm_path and algorithm_path.is_file():
                self._validate_algorithm_yaml(example_path, algorithm_path)

    def _validate_testenv_yaml(self, example_path: Path, testenv_path: Path) -> None:
        data = self._load_yaml(testenv_path, example_path)
        if not isinstance(data, dict):
            return

        testenv = data.get("testenv", data)
        if not isinstance(testenv, dict):
            return

        for key_path, value in self._iter_keyed_string_values(testenv, "url"):
            self._validate_path_exists(
                example_path,
                testenv_path,
                value,
                "broken_testenv_path",
                "Test environment referenced file does not exist.",
                key_path,
            )

    def _validate_algorithm_yaml(
        self, example_path: Path, algorithm_path: Path
    ) -> None:
        data = self._load_yaml(algorithm_path, example_path)
        if not isinstance(data, dict):
            return

        for key_path, value in self._iter_keyed_string_values(data, "url"):
            self._validate_path_exists(
                example_path,
                algorithm_path,
                value,
                "broken_algorithm_path",
                "Algorithm referenced file does not exist.",
                key_path,
            )

    def _validate_referenced_yaml(
        self,
        example_path: Path,
        source_file: Path,
        value: str,
        check: str,
        message: str,
    ) -> Optional[Path]:
        resolved = self._resolve_local_path(value, source_file)
        if not resolved:
            return None

        if resolved.suffix.lower() not in YAML_SUFFIXES:
            self._add_issue(
                "invalid_yaml_reference",
                "error",
                self._relpath(example_path),
                self._relpath(source_file),
                self._find_line(source_file, value),
                "Referenced configuration file is not YAML.",
                value,
            )
            return resolved

        if not resolved.is_file():
            self._add_issue(
                check,
                "error",
                self._relpath(example_path),
                self._relpath(source_file),
                self._find_line(source_file, value),
                message,
                value,
            )
        return resolved

    def _validate_path_exists(
        self,
        example_path: Path,
        source_file: Path,
        value: str,
        check: str,
        message: str,
        key_path: Optional[str] = None,
    ) -> None:
        resolved = self._resolve_local_path(value, source_file)
        if not resolved:
            return

        if resolved.exists():
            return

        detail = message
        if key_path:
            detail = "{} ({})".format(message, key_path)

        self._add_issue(
            check,
            "error",
            self._relpath(example_path),
            self._relpath(source_file),
            self._find_line(source_file, value),
            detail,
            value,
        )

    def _scan_text_files(self, example_path: Path) -> None:
        for path in self._iter_files(example_path, TEXT_SUFFIXES):
            for line_number, line in enumerate(self._read_lines(path), start=1):
                self._check_hardcoded_paths(example_path, path, line_number, line)
                self._check_local_model_paths(example_path, path, line_number, line)
                self._check_cuda_only(example_path, path, line_number, line)

                if path.name.lower().startswith("readme"):
                    self._check_readme_repo_paths(
                        example_path, path, line_number, line
                    )

    def _check_hardcoded_paths(
        self, example_path: Path, path: Path, line_number: int, line: str
    ) -> None:
        matches: List[str] = []
        for pattern in (
            LOCAL_ABSOLUTE_PATH_RE,
            WINDOWS_ABSOLUTE_PATH_RE,
            HOME_RELATIVE_PATH_RE,
        ):
            matches.extend(match.group(1) for match in pattern.finditer(line))

        for value in sorted(set(matches)):
            self._add_issue(
                "hardcoded_absolute_path",
                "error",
                self._relpath(example_path),
                self._relpath(path),
                line_number,
                "Hardcoded local absolute path detected.",
                value,
            )

    def _check_local_model_paths(
        self, example_path: Path, path: Path, line_number: int, line: str
    ) -> None:
        if "model" not in line.lower() and "from_pretrained" not in line:
            return

        values = set()
        match = LOCAL_MODEL_RE.search(line)
        if match:
            values.add(match.group("path"))

        for pattern in (
            LOCAL_ABSOLUTE_PATH_RE,
            WINDOWS_ABSOLUTE_PATH_RE,
            HOME_RELATIVE_PATH_RE,
        ):
            for path_match in pattern.finditer(line):
                local_path = path_match.group(1)
                if "model" in local_path.lower():
                    values.add(local_path)

        for value in sorted(values):
            self._add_issue(
                "local_model_path",
                "error",
                self._relpath(example_path),
                self._relpath(path),
                line_number,
                "Local-only model path detected; use a portable model id or override.",
                value,
            )

    def _check_cuda_only(
        self, example_path: Path, path: Path, line_number: int, line: str
    ) -> None:
        if path.suffix.lower() not in (".py", ".yaml", ".yml"):
            return

        if not any(pattern.search(line) for pattern in CUDA_ONLY_PATTERNS):
            return

        self._add_issue(
            "cuda_only_hardcoding",
            "error",
            self._relpath(example_path),
            self._relpath(path),
            line_number,
            "CUDA-only device setting detected; provide CPU/MPS fallback.",
            line.strip(),
        )

    def _check_readme_repo_paths(
        self, example_path: Path, path: Path, line_number: int, line: str
    ) -> None:
        for match in REPO_PATH_RE.finditer(line):
            value = self._normalize_readme_repo_path(match.group("path"))
            if not value:
                continue
            resolved = self._resolve_local_path(value, path)
            if resolved and not resolved.exists():
                self._add_issue(
                    "broken_readme_path",
                    "error",
                    self._relpath(example_path),
                    self._relpath(path),
                    line_number,
                    "README references a repository path that does not exist.",
                    value,
                )

    def _normalize_readme_repo_path(self, value: str) -> str:
        value = value.strip().rstrip(TRAILING_PATH_CHARS)
        if not value:
            return value

        try:
            tokens = shlex.split(value, posix=True)
        except ValueError:
            tokens = value.split()

        if not tokens:
            return ""

        return tokens[0].rstrip(TRAILING_PATH_CHARS)

    def _extract_algorithm_urls(self, job: Dict[str, Any]) -> List[str]:
        test_object = job.get("test_object", {})
        if not isinstance(test_object, dict):
            return []

        algorithms = test_object.get("algorithms", [])
        if not isinstance(algorithms, list):
            return []

        urls = []
        for algorithm in algorithms:
            if isinstance(algorithm, dict) and algorithm.get("url"):
                urls.append(str(algorithm["url"]))
        return urls

    def _iter_keyed_string_values(
        self, value: Any, target_key: str, prefix: str = ""
    ) -> Iterable[Tuple[str, str]]:
        if isinstance(value, dict):
            for key, child in value.items():
                key_path = "{}.{}".format(prefix, key) if prefix else str(key)
                if key == target_key and isinstance(child, str):
                    yield key_path, child
                else:
                    for item in self._iter_keyed_string_values(
                        child, target_key, key_path
                    ):
                        yield item
        elif isinstance(value, list):
            for index, child in enumerate(value):
                key_path = "{}[{}]".format(prefix, index)
                for item in self._iter_keyed_string_values(
                    child, target_key, key_path
                ):
                    yield item

    def _iter_string_values(
        self, value: Any, prefix: str = ""
    ) -> Iterable[Tuple[str, str]]:
        if isinstance(value, dict):
            for key, child in value.items():
                key_path = "{}.{}".format(prefix, key) if prefix else str(key)
                for item in self._iter_string_values(child, key_path):
                    yield item
        elif isinstance(value, list):
            for index, child in enumerate(value):
                key_path = "{}[{}]".format(prefix, index)
                for item in self._iter_string_values(child, key_path):
                    yield item
        elif isinstance(value, str):
            yield prefix, value

    def _looks_like_path(self, value: str) -> bool:
        if self._is_external_reference(value):
            return False

        if value.startswith(("/", "./", "../", "~/", "examples/", "dataset/")):
            return True

        suffix = Path(value).suffix.lower()
        return suffix in (
            ".csv",
            ".json",
            ".jsonl",
            ".npy",
            ".txt",
            ".yaml",
            ".yml",
        )

    def _resolve_local_path(self, value: str, source_file: Path) -> Optional[Path]:
        value = value.strip().strip("'\"")
        if not value or self._is_external_reference(value):
            return None

        if value.startswith("$") or value.startswith("${"):
            return None

        if value.startswith("~/"):
            return Path(value).expanduser()

        raw_path = Path(value)
        if raw_path.is_absolute():
            return raw_path

        normalized = value[2:] if value.startswith("./") else value
        repo_candidate = (self.root / normalized).resolve()
        source_candidate = (source_file.parent / value).resolve()

        if repo_candidate.exists():
            return repo_candidate
        if source_candidate.exists():
            return source_candidate

        if normalized.startswith(("examples/", "dataset/", "resources/")):
            return repo_candidate
        return source_candidate

    def _is_external_reference(self, value: str) -> bool:
        lowered = value.lower()
        return lowered.startswith(
            ("http://", "https://", "s3://", "gs://", "hf://")
        )

    def _iter_files(self, root: Path, suffixes: Sequence[str]) -> Iterable[Path]:
        for path in root.rglob("*"):
            if self._is_skipped(path):
                continue
            if path.is_file() and path.suffix.lower() in suffixes:
                yield path

    def _is_skipped(self, path: Path) -> bool:
        return any(part in SKIP_DIRS for part in path.parts)

    def _load_yaml(self, path: Path, example_path: Path) -> Any:
        if yaml is None:
            self._add_issue(
                "yaml_parser_unavailable",
                "error",
                self._relpath(example_path),
                self._relpath(path),
                None,
                "PyYAML is required for YAML validation.",
            )
            return None

        try:
            with path.open("r", encoding="utf-8") as file:
                return yaml.safe_load(file) or {}
        except yaml.YAMLError as error:
            self._add_issue(
                "invalid_yaml_syntax",
                "error",
                self._relpath(example_path),
                self._relpath(path),
                self._yaml_error_line(error),
                "Invalid YAML syntax.",
                str(error),
            )
        except OSError as error:
            self._add_issue(
                "yaml_read_error",
                "error",
                self._relpath(example_path),
                self._relpath(path),
                None,
                "Unable to read YAML file.",
                str(error),
            )
        return None

    def _yaml_error_line(self, error: Exception) -> Optional[int]:
        mark = getattr(error, "problem_mark", None)
        if mark is None:
            return None
        return getattr(mark, "line", -1) + 1

    def _read_lines(self, path: Path) -> List[str]:
        if path not in self._line_cache:
            try:
                self._line_cache[path] = path.read_text(
                    encoding="utf-8"
                ).splitlines()
            except UnicodeDecodeError:
                self._line_cache[path] = path.read_text(
                    encoding="utf-8", errors="ignore"
                ).splitlines()
            except OSError:
                self._line_cache[path] = []
        return self._line_cache[path]

    def _find_line(self, path: Path, needle: str) -> Optional[int]:
        for index, line in enumerate(self._read_lines(path), start=1):
            if needle in line:
                return index
        return None

    def _relpath(self, path: Path) -> str:
        try:
            return os.path.relpath(str(path), str(self.root))
        except ValueError:
            return str(path)

    def _add_issue(
        self,
        check: str,
        severity: str,
        example: str,
        file: Optional[str],
        line: Optional[int],
        message: str,
        value: Optional[str] = None,
    ) -> None:
        self.issues.append(
            ValidationIssue(
                check=check,
                severity=severity,
                example=example,
                file=file,
                line=line,
                message=message,
                value=value,
            )
        )


def static_validator(
    root_path: str = ".", examples: Optional[Sequence[str]] = None
) -> StaticValidationReport:
    """Run static validation and return a structured report."""

    return StaticValidator(root_path).validate(examples)


def format_text_report(report: StaticValidationReport) -> str:
    status = "PASS" if report.passed else "FAIL"
    lines = [
        "Static validation: {}".format(status),
        "Root: {}".format(report.root),
        "Examples checked: {}".format(len(report.examples_checked)),
        "Issues: {}".format(len(report.issues)),
    ]

    if report.examples_checked:
        lines.append("")
        lines.append("Checked examples:")
        for example in report.examples_checked:
            lines.append("  - {}".format(example))

    if report.issues:
        lines.append("")
        lines.append("Failure details:")
        for issue in report.issues:
            location = issue.file or issue.example
            if issue.line:
                location = "{}:{}".format(location, issue.line)
            lines.append(
                "  - [{check}] {location}: {message}".format(
                    check=issue.check,
                    location=location,
                    message=issue.message,
                )
            )
            if issue.value:
                lines.append("    value: {}".format(issue.value))

    return "\n".join(lines)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run static validation checks for Ianvs examples."
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root path. Defaults to current directory.",
    )
    parser.add_argument(
        "--example",
        action="append",
        dest="examples",
        help=(
            "Example directory to validate. Can be passed multiple times. "
            "Defaults to all examples containing benchmarkingjob.yaml."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Report output format.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = static_validator(args.root, args.examples)

    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(format_text_report(report))

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
