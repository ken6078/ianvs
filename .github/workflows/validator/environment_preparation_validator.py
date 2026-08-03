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

"""Execute inventory-defined example environment preparation steps."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List, Mapping, Sequence

from static_validator import FAIL, PASS, SKIP, CheckResult, ExampleReport, StaticValidationReport


REQUIRED_STEP_FIELDS = ("name", "type", "script", "args", "timeout")


def validate_examples(
    repo_root: Path,
    examples: Sequence[Mapping[str, object]],
) -> StaticValidationReport:
    return StaticValidationReport(
        reports=[prepare_example(repo_root, example) for example in examples]
    )


def prepare_example(
    repo_root: Path,
    example: Mapping[str, object],
) -> ExampleReport:
    example_path = _normalize_repo_path(str(example.get("path", "")))
    report = ExampleReport(
        name=str(example.get("name") or example_path),
        path=example_path,
    )
    config = example.get("prepare_env")
    if not isinstance(config, Mapping):
        _append_check(
            report,
            name="Environment preparation",
            status=SKIP,
            message="No prepare_env configuration is declared.",
        )
        return report

    working_directory = config.get("working_directory")
    steps = config.get("steps")
    if not isinstance(working_directory, str) or not working_directory.strip():
        _configuration_failure(report, "prepare_env.working_directory must be a string.")
        return report
    if not isinstance(steps, list) or not steps:
        _configuration_failure(report, "prepare_env.steps must be a non-empty array.")
        return report

    try:
        workdir = _resolve_within_repo(repo_root, working_directory)
    except ValueError as exc:
        _configuration_failure(report, str(exc))
        return report
    if not workdir.is_dir():
        _configuration_failure(
            report,
            "Working directory does not exist: {}".format(working_directory),
        )
        return report

    for index, step in enumerate(steps, 1):
        issue = _validate_step(step, index)
        if issue:
            _configuration_failure(report, issue)
            break
        assert isinstance(step, Mapping)
        if not _run_step(report, repo_root, workdir, step):
            break
    return report


def _validate_step(step: object, index: int) -> str:
    prefix = "prepare_env.steps[{}]".format(index - 1)
    if not isinstance(step, Mapping):
        return "{} must be an object.".format(prefix)
    missing = [field for field in REQUIRED_STEP_FIELDS if field not in step]
    if missing:
        return "{} is missing required fields: {}.".format(prefix, ", ".join(missing))
    for field in ("name", "type", "script"):
        if not isinstance(step[field], str) or not str(step[field]).strip():
            return "{}.{} must be a non-empty string.".format(prefix, field)
    args = step["args"]
    if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
        return "{}.args must be an array of strings.".format(prefix)
    timeout = step["timeout"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        return "{}.timeout must be a positive integer.".format(prefix)
    return ""


def _run_step(
    report: ExampleReport,
    repo_root: Path,
    workdir: Path,
    step: Mapping[str, object],
) -> bool:
    name = str(step["name"])
    step_type = str(step["type"])
    script = str(step["script"])
    args = list(step["args"])
    timeout = int(step["timeout"])
    try:
        script_path = _resolve_within_repo(workdir, script, root=repo_root)
    except ValueError as exc:
        _append_step_result(report, name, step_type, script, FAIL, str(exc))
        return False
    if not script_path.is_file():
        _append_step_result(
            report,
            name,
            step_type,
            script,
            FAIL,
            "Preparation script does not exist.",
        )
        return False

    command: List[str]
    if script_path.suffix == ".py":
        command = [sys.executable, str(script_path), *args]
    else:
        command = [str(script_path), *args]

    try:
        completed = subprocess.run(
            command,
            cwd=str(workdir),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        _append_step_result(
            report,
            name,
            step_type,
            script,
            FAIL,
            "Preparation step timed out after {} seconds.".format(timeout),
            _summarize_output(output),
        )
        return False
    except OSError as exc:
        _append_step_result(
            report,
            name,
            step_type,
            script,
            FAIL,
            "Could not start preparation step: {}".format(exc),
        )
        return False

    passed = completed.returncode == 0
    _append_step_result(
        report,
        name,
        step_type,
        script,
        PASS if passed else FAIL,
        (
            "Preparation step completed successfully."
            if passed
            else "Preparation step failed with exit code {}.".format(completed.returncode)
        ),
        _summarize_output(completed.stdout),
    )
    return passed


def _resolve_within_repo(base: Path, value: str, root: Path = None) -> Path:
    repository = (root or base).resolve()
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = base / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(repository)
    except ValueError:
        raise ValueError("Path escapes the repository: {}".format(value))
    return candidate


def _configuration_failure(report: ExampleReport, message: str) -> None:
    _append_check(
        report,
        name="Environment preparation configuration",
        status=FAIL,
        message=message,
    )


def _append_step_result(
    report: ExampleReport,
    name: str,
    step_type: str,
    script: str,
    status: str,
    message: str,
    details: Sequence[str] = (),
) -> None:
    _append_check(
        report,
        name="Environment preparation: {} ({})".format(name, step_type),
        status=status,
        file=script,
        message=message,
        details=details,
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


def _summarize_output(output: str, max_lines: int = 60) -> List[str]:
    lines = [line.rstrip() for line in output.splitlines() if line.strip()]
    if len(lines) <= max_lines:
        return lines
    return lines[:max_lines] + ["... output truncated ..."]


def _normalize_repo_path(value: str) -> str:
    value = value.strip().strip("\"'")
    if value.startswith("./"):
        value = value[2:]
    return value.rstrip("/")
