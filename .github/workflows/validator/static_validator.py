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

"""Static validation for Ianvs examples.

The checks in this module intentionally avoid executing examples. They inspect
inventory metadata, YAML configuration, and source text for common portability
problems described by the example restoration proposal.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Mapping, Optional, Sequence


PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
YAML_SUFFIXES = (".yaml", ".yml")

HARDCODED_PATH_RE = re.compile(
    r"(?:^|[\s'\"`=:(])(?P<path>(?:/(?!/)[^\s'\"`,)]+)|(?:[A-Za-z]:[\\/](?![\\/])[^\s'\"`,)]+))",
    re.IGNORECASE,
)
LOCAL_MODEL_RE = re.compile(
    r"(?i)(?:model(?:_path|_url)?|path)\s*[:=]\s*[\"'](?P<path>(?:/home/|/Users/|\.?/models?/)[^\"']*)"
)
CUDA_ONLY_RE = re.compile(
    r"(?i)(?:device\s*=\s*[\"']cuda[\"']|torch\.device\([\"']cuda[\"']\)|\.cuda\()"
)
REPO_PATH_RE = re.compile(
    r"(?P<path>(?:\./)?(?:examples|\.github|resources)/[A-Za-z0-9_./-]+"
    r"(?:\.yaml|\.yml|\.py|\.txt|\.json|\.jsonl|\.whl|\.zip)?)"
)
STATIC_VALIDATED_FILE_SUFFIXES = (".yaml", ".yml", ".py")


@dataclass
class CheckResult:
    name: str
    status: str
    message: str = ""
    file: str = ""
    details: List[str] = field(default_factory=list)


@dataclass
class ExampleReport:
    name: str
    path: str
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(check.status == FAIL for check in self.checks)


@dataclass
class StaticValidationReport:
    reports: List[ExampleReport]

    @property
    def passed(self) -> bool:
        return all(report.passed for report in self.reports)


def validate_examples(repo_root: Path, examples: Sequence[Mapping[str, object]]) -> StaticValidationReport:
    reports = [validate_example(repo_root, example) for example in examples]
    return StaticValidationReport(reports=reports)


def validate_example(repo_root: Path, example: Mapping[str, object]) -> ExampleReport:
    example_path = _normalize_repo_path(str(example.get("path", "")))
    example_name = str(example.get("name") or example_path)
    report = ExampleReport(name=example_name, path=example_path)
    root = repo_root / example_path

    _check_path_exists(
        report,
        "Example directory exists",
        repo_root,
        example_path,
        is_dir=True,
    )
    benchmark_file = _example_file(example, "benchmark_file", example_path, "benchmarkingjob.yaml")
    requirements_file = _optional_example_file(example, "requirements_file")
    prepare_script = _nested_file(example, ("dataset", "prepare_script"))

    _check_path_exists(report, "benchmarkingjob.yaml exists", repo_root, benchmark_file)
    if requirements_file:
        _check_path_exists(report, "requirements file exists", repo_root, requirements_file)
    if prepare_script:
        _check_path_exists(report, "dataset prepare script exists", repo_root, prepare_script)

    files = _example_files(root)
    _check_yaml_syntax(report, files)
    _check_repo_path_references(report, repo_root, files)
    _check_hardcoded_paths(report, repo_root, files)
    _check_local_model_paths(report, repo_root, files)
    _check_cuda_only_assumptions(report, repo_root, files)
    _check_metric_empty_pair_guard(report, repo_root, example_path)

    return report


def render_markdown(report: StaticValidationReport) -> str:
    lines = ["# Static Validation Report", ""]
    lines.append("Overall result: {}".format(PASS if report.passed else FAIL))

    for example_report in report.reports:
        lines.extend(["", "## Example", "", example_report.path, "", "### Validation Result", ""])
        lines.extend(["| Check | Result |", "|---|---|"])
        for check in example_report.checks:
            lines.append("| {} | {} |".format(_escape_table(check.name), check.status))

        failures = [
            check for check in example_report.checks if check.status in (FAIL, SKIP)
        ]
        if failures:
            lines.extend(["", "### Details", ""])
            for check in failures:
                lines.append("#### {}".format(check.name))
                lines.append("")
                lines.append("Result: {}".format(check.status))
                if check.file:
                    lines.append("")
                    lines.append("File: `{}`".format(check.file))
                if check.message:
                    lines.append("")
                    lines.append(check.message)
                if check.details:
                    lines.append("")
                    lines.append("Detected:")
                    for detail in check.details:
                        lines.append("- `{}`".format(detail))
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_json(report: StaticValidationReport) -> str:
    payload = {
        "passed": report.passed,
        "examples": [
            {
                "name": example.name,
                "path": example.path,
                "passed": example.passed,
                "checks": [
                    {
                        "name": check.name,
                        "status": check.status,
                        "message": check.message,
                        "file": check.file,
                        "details": check.details,
                    }
                    for check in example.checks
                ],
            }
            for example in report.reports
        ],
    }
    return json.dumps(payload, indent=2)


def _check_path_exists(
    report: ExampleReport,
    name: str,
    repo_root: Path,
    repo_path: str,
    is_dir: bool = False,
) -> None:
    path = repo_root / repo_path
    exists = path.is_dir() if is_dir else path.is_file()
    _append_check(
        report,
        name=name,
        status=PASS if exists else FAIL,
        file=repo_path,
        message="Required path exists." if exists else "Required path is missing.",
    )


def _check_yaml_syntax(report: ExampleReport, files: Sequence[Path]) -> None:
    yaml_files = [path for path in files if path.suffix in YAML_SUFFIXES]
    try:
        import yaml
    except ImportError:
        _append_check(
            report,
            name="YAML syntax",
            status=SKIP,
            message="PyYAML is unavailable; YAML syntax validation was skipped.",
        )
        return

    failures = []
    for path in yaml_files:
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            failures.append("{}: {}".format(_repo_display_path(path), exc))

    _append_issue_check(
        report,
        name="YAML syntax",
        issues=failures,
        fail_message="Invalid YAML syntax found.",
        pass_message="All YAML files parsed successfully.",
    )


def _check_repo_path_references(
    report: ExampleReport,
    repo_root: Path,
    files: Sequence[Path],
) -> None:
    missing = []
    for path in files:
        text = _read_text(path)
        for match in REPO_PATH_RE.finditer(text):
            repo_path = _normalize_repo_path(match.group("path"))
            if _looks_like_generated_dataset_path(repo_path):
                continue
            if not (repo_root / repo_path).exists():
                missing.append(
                    _format_detected_value(
                        path,
                        _line_number_for_match(text, match, "path"),
                        repo_path,
                    )
                )

    _append_issue_check(
        report,
        name="Repository path references exist",
        issues=sorted(set(missing)),
        fail_message="Broken repository-local path references found.",
        pass_message="Repository-local path references resolve.",
    )


def _check_hardcoded_paths(
    report: ExampleReport,
    repo_root: Path,
    files: Sequence[Path],
) -> None:
    matches = _collect_regex_matches(repo_root, files, HARDCODED_PATH_RE)
    _append_issue_check(
        report,
        name="Hardcoded local path check",
        issues=matches,
        fail_message="Contributor-specific absolute paths were found.",
        pass_message="No contributor-specific absolute paths found.",
    )


def _check_local_model_paths(
    report: ExampleReport,
    repo_root: Path,
    files: Sequence[Path],
) -> None:
    matches = _collect_regex_matches(repo_root, files, LOCAL_MODEL_RE)
    _append_issue_check(
        report,
        name="Local model path check",
        issues=matches,
        fail_message="Local-only model path references were found.",
        pass_message="No local-only model paths found.",
    )


def _check_cuda_only_assumptions(
    report: ExampleReport,
    repo_root: Path,
    files: Sequence[Path],
) -> None:
    failures = []
    for path in files:
        if path.suffix != ".py":
            continue
        text = _read_text(path)
        if not CUDA_ONLY_RE.search(text):
            continue
        has_fallback = "torch.cuda.is_available()" in text and "cpu" in text
        if has_fallback:
            continue
        failures.append(_repo_display_path(path))

    _append_issue_check(
        report,
        name="CUDA-only device check",
        issues=failures,
        fail_message="CUDA-only device assumptions were found.",
        pass_message="No CUDA-only device assumptions found.",
    )


def _check_metric_empty_pair_guard(report: ExampleReport, repo_root: Path, example_path: str) -> None:
    metric_dir = repo_root / example_path / "testenv"
    metric_files = list(metric_dir.glob("*.py")) if metric_dir.is_dir() else []
    if not metric_files:
        _append_check(
            report,
            name="Metric empty-pair guard",
            status=SKIP,
            message="No metric Python files were found.",
        )
        return

    risky = []
    guarded = []
    for path in metric_files:
        text = _read_text(path)
        if "/ len(" not in text:
            continue
        has_guard = "if same_elements else 0.0" in text or "if len(" in text
        if has_guard:
            guarded.append(_repo_display_path(path))
        else:
            risky.append(_repo_display_path(path))

    _append_issue_check(
        report,
        name="Metric empty-pair guard",
        issues=risky,
        fail_message="Metric division may crash on empty prediction-answer pairs.",
        pass_message="Metric files include an empty-pair guard or do not divide by a collection length.",
        pass_details=guarded,
    )


def _collect_regex_matches(
    repo_root: Path,
    files: Sequence[Path],
    pattern: re.Pattern,
) -> List[str]:
    matches = []
    for path in files:
        text = _read_text(path)
        for match in pattern.finditer(text):
            value = match.groupdict().get("path") or match.group(0)
            matches.append(
                _format_detected_value(
                    path,
                    _line_number_for_match(text, match, "path"),
                    value,
                )
            )
    return sorted(set(matches))


def _format_detected_value(path: Path, line_number: int, value: str) -> str:
    return "{} -> (Line {}): {}".format(_repo_display_path(path), line_number, value)


def _line_number_for_match(text: str, match: re.Match, group_name: str = "") -> int:
    start = -1
    if group_name:
        try:
            start = match.start(group_name)
        except IndexError:
            start = -1
    if start < 0:
        start = match.start()
    return text.count("\n", 0, start) + 1


def _append_issue_check(
    report: ExampleReport,
    name: str,
    issues: Sequence[str],
    fail_message: str,
    pass_message: str,
    pass_details: Sequence[str] = (),
) -> None:
    has_issues = bool(issues)
    _append_check(
        report,
        name=name,
        status=FAIL if has_issues else PASS,
        message=fail_message if has_issues else pass_message,
        details=issues if has_issues else pass_details,
    )


def _append_check(
    report: ExampleReport,
    name: str,
    status: str,
    message: str = "",
    file: str = "",
    details: Sequence[str] = (),
) -> None:
    report.checks.append(
        CheckResult(
            name=name,
            status=status,
            message=message,
            file=file,
            details=list(details),
        )
    )


def _example_files(root: Path) -> List[Path]:
    if not root.is_dir():
        return []
    ignored_parts = {"__pycache__", ".pytest_cache"}
    files = []
    for path in root.rglob("*"):
        if not path.is_file() or ignored_parts.intersection(path.parts):
            continue
        if path.suffix.lower() not in STATIC_VALIDATED_FILE_SUFFIXES:
            continue
        files.append(path)
    return files


def _optional_example_file(
    example: Mapping[str, object],
    key: str,
) -> Optional[str]:
    value = example.get(key)
    if not value:
        return None
    return _normalize_repo_path(str(value))


def _example_file(
    example: Mapping[str, object],
    key: str,
    example_path: str,
    default_name: str,
) -> str:
    value = _optional_example_file(example, key)
    if value:
        return value
    return _join_repo_path(example_path, default_name)


def _nested_file(example: Mapping[str, object], keys: Sequence[str]) -> Optional[str]:
    value: object = example
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    if not value:
        return None
    return _normalize_repo_path(str(value))


def _join_repo_path(*parts: str) -> str:
    return _normalize_repo_path("/".join(part.strip("/") for part in parts if part))


def _normalize_repo_path(value: str) -> str:
    value = value.strip().strip("\"'")
    if value.startswith("./"):
        value = value[2:]
    return value.rstrip("/")


def _looks_like_generated_dataset_path(repo_path: str) -> bool:
    return "/dataset/" in repo_path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def _repo_display_path(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|")
