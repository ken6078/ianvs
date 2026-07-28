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

"""Collect validator results and publish human-readable reports.

This script is intentionally dependency-free so GitHub Actions can run it before
project dependencies are installed. It accepts JSON reports emitted by
validation_runner.py, merges them, writes a Markdown report, emits GitHub
workflow annotations, and updates a pull request comment when running in a PR.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
COMMENT_MARKER = "<!-- ianvs-example-validation-report -->"
MAX_COMMENT_BODY_CHARS = 60000
DEFAULT_RESULT_PATTERNS = ("validation-results", "validator-results")
GITHUB_PULL_REQUEST_EVENTS = ("pull_request", "pull_request_target")
GITHUB_API_VERSION = "2022-11-28"
GITHUB_USER_AGENT = "ianvs-example-validator"


@dataclass
class CheckResult:
    name: str
    status: str
    message: str = ""
    file: str = ""
    details: List[str] = field(default_factory=list)

    @property
    def issue_count(self) -> int:
        return len(self.details) if self.details else 1


@dataclass
class ExampleResult:
    name: str
    path: str
    passed: bool
    checks: List[CheckResult] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(check.issue_count for check in self.checks if check.status == status)


@dataclass
class CombinedReport:
    examples: List[ExampleResult]
    source_files: List[str]

    @property
    def passed(self) -> bool:
        return all(example.passed for example in self.examples)

    def check_count(self, status: str) -> int:
        return sum(example.count(status) for example in self.examples)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect Ianvs validator JSON results and publish reports."
    )
    parser.add_argument(
        "--results",
        action="append",
        default=[],
        help="JSON result file, directory, or glob. Can be repeated.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional Markdown report output path.",
    )
    parser.add_argument(
        "--regression-json",
        default="",
        help="Optional regression detector JSON output to include as a summary section.",
    )
    parser.add_argument(
        "--step-summary",
        action="store_true",
        help="Append the Markdown report to GITHUB_STEP_SUMMARY when available.",
    )
    parser.add_argument(
        "--annotations",
        action="store_true",
        help="Emit GitHub Actions error annotations for failed checks.",
    )
    parser.add_argument(
        "--pr-comment",
        action="store_true",
        help="Create or update a pull request comment when running in a PR event.",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Generate a passing empty report when no result files are found.",
    )
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Exit 0 even when collected validation results contain failures.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    result_paths = discover_result_paths(args.results)
    if not result_paths and not args.allow_empty:
        print("No validation result JSON files were found.", file=sys.stderr)
        return 2

    report = load_combined_report(result_paths)
    rendered = render_full_report(report, regression_json=args.regression_json)
    publish_report(rendered, report, args)

    if report.passed or args.no_fail:
        return 0
    return 1


def discover_result_paths(inputs: Sequence[str]) -> List[Path]:
    patterns = list(inputs) if inputs else list(DEFAULT_RESULT_PATTERNS)
    paths = []

    for value in patterns:
        paths.extend(discover_json_paths(value))

    return unique_paths(paths)


def discover_json_paths(value: str) -> List[Path]:
    path = Path(value)
    if path.is_dir():
        return sorted(
            candidate for candidate in path.rglob("*.json") if candidate.is_file()
        )
    if path.is_file():
        return [path]

    matches = [Path(match) for match in glob.glob(value, recursive=True)]
    return sorted(
        match for match in matches if match.is_file() and match.suffix == ".json"
    )


def unique_paths(paths: Sequence[Path]) -> List[Path]:
    seen = set()
    unique_paths = []
    for path in paths:
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(path)
    return unique_paths


def load_combined_report(paths: Sequence[Path]) -> CombinedReport:
    examples = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        examples.extend(parse_examples(payload, source_path=path))

    examples = merge_duplicate_examples(examples)
    examples.sort(key=lambda example: (example.path, example.name))
    return CombinedReport(
        examples=examples,
        source_files=[path.as_posix() for path in paths],
    )


def merge_duplicate_examples(examples: Sequence[ExampleResult]) -> List[ExampleResult]:
    merged: Dict[str, ExampleResult] = {}

    for example in examples:
        key = example.path
        if key not in merged:
            merged[key] = ExampleResult(
                name=example.name,
                path=example.path,
                passed=example.passed,
                checks=[copy_check(check) for check in example.checks],
            )
            continue

        target = merged[key]
        target.passed = target.passed and example.passed
        target.checks = merge_checks([*target.checks, *example.checks])

    return list(merged.values())


def merge_checks(checks: Sequence[CheckResult]) -> List[CheckResult]:
    merged: Dict[Tuple[str, str, str, str], CheckResult] = {}

    for check in checks:
        key = (check.name, check.status, check.message, check.file)
        if key not in merged:
            merged[key] = copy_check(check)
            continue

        target = merged[key]
        seen_details = set(target.details)
        for detail in check.details:
            if detail in seen_details:
                continue
            seen_details.add(detail)
            target.details.append(detail)

    return sorted(
        merged.values(),
        key=lambda check: (check.name, check.status, check.file, check.message),
    )


def copy_check(check: CheckResult) -> CheckResult:
    return CheckResult(
        name=check.name,
        status=check.status,
        message=check.message,
        file=check.file,
        details=list(check.details),
    )


def parse_examples(payload: Dict[str, object], source_path: Path) -> List[ExampleResult]:
    raw_examples = payload.get("examples")
    if not isinstance(raw_examples, list):
        raise ValueError("{} does not contain an examples list".format(source_path))

    examples = []
    for raw_example in raw_examples:
        if not isinstance(raw_example, dict):
            continue

        examples.append(
            ExampleResult(
                name=str(raw_example.get("name") or raw_example.get("path") or ""),
                path=str(raw_example.get("path") or raw_example.get("name") or ""),
                passed=bool(raw_example.get("passed", False)),
                checks=parse_checks(raw_example.get("checks", [])),
            )
        )
    return examples


def parse_checks(raw_checks: object) -> List[CheckResult]:
    if not isinstance(raw_checks, list):
        return []

    checks = []
    for raw_check in raw_checks:
        if not isinstance(raw_check, dict):
            continue
        checks.append(
            CheckResult(
                name=str(raw_check.get("name", "")),
                status=str(raw_check.get("status", "")),
                message=str(raw_check.get("message", "")),
                file=str(raw_check.get("file", "")),
                details=string_list(raw_check.get("details", [])),
            )
        )
    return checks


def string_list(value: object) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def render_full_report(report: CombinedReport, regression_json: str = "") -> str:
    rendered = render_markdown(report)
    if regression_json:
        rendered = append_regression_summary(rendered, Path(regression_json))
    return append_collected_result_files(rendered, report.source_files)


def publish_report(
    rendered: str,
    report: CombinedReport,
    args: argparse.Namespace,
) -> None:
    write_or_print_report(rendered, args.output)

    if args.step_summary:
        append_step_summary(rendered)

    if args.annotations:
        emit_annotations(report)

    if args.pr_comment:
        maybe_update_pr_comment(rendered)


def write_or_print_report(rendered: str, output: str) -> None:
    if not output:
        print(rendered, end="")
        return

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    print("Combined validation report written to {}".format(output_path))


def render_markdown(report: CombinedReport) -> str:
    result = PASS if report.passed else FAIL
    lines = [
        COMMENT_MARKER,
        "# Ianvs Example Validation Report",
        "",
        "**Overall result:** {}".format(result),
        "",
        "| Examples | Errors | Skipped checks |",
        "|---:|---:|---:|",
        "| {} | {} | {} |".format(
            len(report.examples),
            report.check_count(FAIL),
            report.check_count(SKIP),
        ),
        "",
    ]

    if not report.examples:
        lines.append("No validation results were collected.")
        return "\n".join(lines).rstrip() + "\n"

    lines.extend(
        [
            "## Example Summary",
            "",
            "| Example | Result | Errors | Skip |",
            "|---|---:|---:|---:|",
        ]
    )
    for example in report.examples:
        lines.append(
            "| `{}` | {} | {} | {} |".format(
                escape_table(example.path),
                example_result(example),
                example.count(FAIL),
                example.count(SKIP),
            )
        )

    return "\n".join(lines).rstrip() + "\n"


def example_result(example: ExampleResult) -> str:
    if example.count(FAIL):
        return FAIL
    if example.count(SKIP):
        return SKIP
    return PASS


def append_regression_summary(rendered: str, regression_json_path: Path) -> str:
    if not regression_json_path.is_file():
        return rendered

    payload = json.loads(regression_json_path.read_text(encoding="utf-8"))
    comparisons = payload.get("comparisons", [])
    if not isinstance(comparisons, list):
        comparisons = []

    summary = [
        "",
        "## Regression Summary",
        "",
        "| Example | Current errors | Pre-existing errors | New errors | Fixed errors |",
        "|---|---:|---:|---:|---:|",
    ]
    for example in regression_examples(comparisons):
        summary.append(
            "| `{}` | {} | {} | {} | {} |".format(
                escape_table(example),
                count_regression_field(
                    comparisons,
                    "head_issue_count",
                    example=example,
                ),
                count_regression_field(
                    comparisons,
                    "pre_existing_issue_count",
                    fallback_classification="Failed: Pre-existing failure",
                    example=example,
                ),
                count_regression_field(
                    comparisons,
                    "new_issue_count",
                    fallback_classification="Failed: PR regression",
                    example=example,
                ),
                count_regression_field(
                    comparisons,
                    "fixed_issue_count",
                    fallback_classification="Fixed: Pre-existing failure resolved",
                    example=example,
                ),
            )
        )
    if len(summary) == 5:
        summary.append("| No regression comparisons were collected. | 0 | 0 | 0 | 0 |")
    summary.append("")
    return rendered.rstrip() + "\n" + "\n".join(summary).rstrip() + "\n"


def append_collected_result_files(rendered: str, source_files: Sequence[str]) -> str:
    if not source_files:
        return rendered

    lines = [
        "",
        "## Collected Result Files",
        "",
    ]
    for source_file in source_files:
        lines.append("- `{}`".format(source_file))
    return rendered.rstrip() + "\n" + "\n".join(lines).rstrip() + "\n"


def regression_examples(comparisons: Sequence[object]) -> List[str]:
    examples = []
    seen = set()
    for comparison in comparisons:
        if not isinstance(comparison, dict):
            continue
        example = str(comparison.get("example") or "")
        if not example or example in seen:
            continue
        seen.add(example)
        examples.append(example)
    return sorted(examples)


def count_regression_field(
    comparisons: Sequence[object],
    field: str,
    fallback_classification: str = "",
    example: str = "",
) -> int:
    count = 0
    for comparison in comparisons:
        if not isinstance(comparison, dict):
            continue
        if example and comparison.get("example") != example:
            continue
        if field in comparison:
            count += int(comparison.get(field) or 0)
            continue
        if fallback_classification and comparison.get("classification") == fallback_classification:
            count += int(comparison.get("issue_count") or 0)
    return count


def append_step_summary(rendered: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as summary:
        summary.write(rendered)
        summary.write("\n")


def emit_annotations(report: CombinedReport) -> None:
    for example in report.examples:
        for check in example.checks:
            if check.status != FAIL:
                continue
            file_name = check.file or infer_file_from_details(check.details) or example.path
            message = check.message or check.name
            title = "{}: {}".format(example.path, check.name)
            print(
                "::{command} file={file},title={title}::{message}".format(
                    command="error",
                    file=escape_command_property(file_name),
                    title=escape_command_property(title),
                    message=escape_command_value(message),
                )
            )


def infer_file_from_details(details: Sequence[str]) -> str:
    if not details:
        return ""
    first = details[0]
    if " -> " in first:
        return first.split(" -> ", 1)[0]
    if ":" in first:
        return first.split(":", 1)[0]
    return first


def maybe_update_pr_comment(rendered: str) -> None:
    context = github_context()
    if not context:
        print("Not a pull_request event or GitHub context is incomplete; skipping PR comment.")
        return

    owner_repo, pr_number, token, api_url = context
    body = truncate_comment(rendered)
    comments_url = "{}/repos/{}/issues/{}/comments".format(api_url, owner_repo, pr_number)

    try:
        comments = github_request("GET", comments_url + "?per_page=100", token)
        existing_url = find_existing_comment_url(comments)
        if existing_url:
            github_request("PATCH", existing_url, token, {"body": body})
            print("Updated Ianvs validation report comment on PR #{}.".format(pr_number))
        else:
            github_request("POST", comments_url, token, {"body": body})
            print("Created Ianvs validation report comment on PR #{}.".format(pr_number))
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        print("Failed to update PR comment: {}".format(exc), file=sys.stderr)


def github_context() -> Optional[Tuple[str, int, str, str]]:
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    if event_name not in GITHUB_PULL_REQUEST_EVENTS:
        return None

    token = os.environ.get("GITHUB_TOKEN", "")
    owner_repo = os.environ.get("GITHUB_REPOSITORY", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    if not token or not owner_repo or not event_path:
        return None

    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pull_request = payload.get("pull_request") or {}
    pr_number = pull_request.get("number") or payload.get("number")
    if not pr_number:
        return None

    return owner_repo, int(pr_number), token, api_url


def github_request(
    method: str,
    url: str,
    token: str,
    payload: Optional[Dict[str, object]] = None,
):
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer {}".format(token),
            "Content-Type": "application/json",
            "User-Agent": GITHUB_USER_AGENT,
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        text = response.read().decode("utf-8")
        if not text:
            return None
        return json.loads(text)


def find_existing_comment_url(comments) -> str:
    if not isinstance(comments, list):
        return ""
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        body = comment.get("body", "")
        if COMMENT_MARKER in body:
            return str(comment.get("url", ""))
    return ""


def truncate_comment(rendered: str) -> str:
    if len(rendered) <= MAX_COMMENT_BODY_CHARS:
        return rendered
    suffix = "\n\n_Report truncated because it exceeded the GitHub comment size limit._\n"
    return rendered[: MAX_COMMENT_BODY_CHARS - len(suffix)] + suffix


def escape_table(value: str) -> str:
    return value.replace("|", "\\|")


def escape_command_value(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_command_property(value: str) -> str:
    return (
        escape_command_value(value)
        .replace(":", "%3A")
        .replace(",", "%2C")
    )


if __name__ == "__main__":
    raise SystemExit(main())
