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
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote, urlencode

try:
    from inventory_loader import DEFAULT_INVENTORY_PATH, load_inventory_examples
except ImportError:  # Support importing this file as services.report_generator.
    from services.inventory_loader import (
        DEFAULT_INVENTORY_PATH,
        load_inventory_examples,
    )


PASS = "PASS"
FAIL = "FAIL"
ERROR = "ERROR"
WARNING = "WARNING"
SKIP = "SKIP"
MODE_STATIC = "static"
MODE_DYNAMIC = "dynamic"
BLOCKING_STATUSES = {ERROR, FAIL}
DYNAMIC_ELIGIBILITY_CHECK = "Dynamic validation eligibility"
UNVALIDATED_REASON = "CI/CD ongoing"
ONGOING_REASON = "Example ongoing"
COMMENT_MARKER = "<!-- ianvs-example-validation-report -->"
MAX_COMMENT_BODY_CHARS = 60000
DEFAULT_RESULT_PATTERNS = ("validation-results", "validator-results")
GITHUB_PULL_REQUEST_EVENTS = ("pull_request", "pull_request_target")
GITHUB_API_VERSION = "2022-11-28"
GITHUB_USER_AGENT = "ianvs-example-validator"
STATUS_RUNNABLE = "Runnable"
STATUS_BROKEN = "Broken"
STATUS_CICD_ONGOING = "CI/CD onGoing"
STATUS_EXAMPLE_ONGOING = "Example onGoing"
STATUS_EXTERNAL = "Requires external dataset or model download"
STATUS_HARDWARE = "Requires GPU or special hardware"
STATUS_QUARANTINED = "Quarantined"
STATUS_KNOWN = "Known issue"
REASON_DEPENDENCY = "Dependency drift"
REASON_RESOURCE = "Dataset or resource unavailable"
STATUS_COLORS = {
    STATUS_RUNNABLE: "brightgreen",
    STATUS_BROKEN: "red",
    STATUS_CICD_ONGOING: "lightgrey",
    STATUS_EXAMPLE_ONGOING: "yellow",
    STATUS_EXTERNAL: "blue",
    STATUS_HARDWARE: "orange",
    STATUS_QUARANTINED: "8a2be2",
    STATUS_KNOWN: "critical",
}
REASON_COLORS = {
    REASON_DEPENDENCY: "ff69b4",
    REASON_RESOURCE: "795548",
}
MANUAL_STATUS_BY_INVENTORY = {
    "quarantined": STATUS_QUARANTINED,
    "known issue": STATUS_KNOWN,
    "known_issue": STATUS_KNOWN,
    "hardware": STATUS_HARDWARE,
    "requires_hardware": STATUS_HARDWARE,
    "external": STATUS_EXTERNAL,
    "requires_external_resource": STATUS_EXTERNAL,
    "broken": STATUS_BROKEN,
}
SKIP_REASON_STATUSES = (
    STATUS_QUARANTINED,
    STATUS_KNOWN,
    STATUS_HARDWARE,
)
STATUS_REPOSITORY = "kubeedge/ianvs"
STATUS_BRANCH = "example-status"
STATUS_RESULT_ROOT = ".github/example-status"


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

    @property
    def identity(self) -> Tuple[str, str]:
        return self.name, self.path.rstrip("/")

    def count(self, status: str) -> int:
        return sum(check.issue_count for check in self.checks if check.status == status)

    def count_any(self, statuses: Sequence[str]) -> int:
        return sum(
            check.issue_count for check in self.checks if check.status in statuses
        )

    @property
    def has_blocking_errors(self) -> bool:
        return any(check.status in BLOCKING_STATUSES for check in self.checks)


@dataclass
class CombinedReport:
    examples: List[ExampleResult]
    source_files: List[str]

    @property
    def passed(self) -> bool:
        return all(not example.has_blocking_errors for example in self.examples)

    def check_count(self, status: str) -> int:
        return sum(example.count(status) for example in self.examples)

    def check_count_any(self, statuses: Sequence[str]) -> int:
        return sum(example.count_any(statuses) for example in self.examples)


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
        "--mode",
        choices=(MODE_STATIC, MODE_DYNAMIC),
        default=MODE_DYNAMIC,
        help=(
            "Report layout. Static includes ERROR and WARNING; "
            "dynamic keeps the error-only layout."
        ),
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
    parser.add_argument(
        "--example-health-readme",
        default="",
        help="Optional examples/README.md path to update from the collected results.",
    )
    parser.add_argument(
        "--inventory",
        default=DEFAULT_INVENTORY_PATH,
        help="Inventory used when rendering the example health README.",
    )
    parser.add_argument(
        "--health-metadata",
        default="",
        help="Optional JSON metadata containing T2/T3 source and validation time.",
    )
    parser.add_argument(
        "--example-status-output",
        default="",
        help="Optional directory for example-status snapshot JSON files.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    result_paths = discover_result_paths(args.results)
    if not result_paths and not args.allow_empty:
        print("No validation result JSON files were found.", file=sys.stderr)
        return 2

    report = load_combined_report(result_paths)
    rendered = render_full_report(
        report,
        mode=args.mode,
        regression_json=args.regression_json,
    )
    publish_report(rendered, report, args, mode=args.mode)
    if args.example_health_readme:
        inventory_examples = load_inventory_examples(
            Path(args.inventory), active_only=False
        )
        metadata = load_health_metadata(args.health_metadata)
        health_readme = render_example_health_readme(
            inventory_examples, report, metadata
        )
        write_text_file(health_readme, args.example_health_readme)
    if args.example_status_output:
        inventory_examples = load_inventory_examples(
            Path(args.inventory), active_only=False
        )
        metadata = load_health_metadata(args.health_metadata)
        snapshots = create_example_status_snapshots(
            report,
            inventory_examples,
            str(metadata["validated_at"]),
            str(metadata["source_sha"]),
        )
        if not snapshots:
            print("No validation results matched the example inventory.", file=sys.stderr)
            return 2
        write_example_status_snapshots(
            snapshots,
            {
                "validated_at": str(metadata["validated_at"]),
                "validated_at_display": format_validation_time(
                    str(metadata["validated_at"])
                ),
                "commit": str(metadata["source_sha"]),
            },
            Path(args.example_status_output),
        )

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
    merged: Dict[Tuple[str, str], ExampleResult] = {}

    for example in examples:
        key = example.identity
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
        target.passed = not target.has_blocking_errors

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

        checks = parse_checks(raw_example.get("checks", []))
        examples.append(
            ExampleResult(
                name=str(raw_example.get("name") or raw_example.get("path") or ""),
                path=str(raw_example.get("path") or raw_example.get("name") or ""),
                passed=not any(check.status in BLOCKING_STATUSES for check in checks),
                checks=checks,
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


def render_full_report(
    report: CombinedReport,
    mode: str = MODE_DYNAMIC,
    regression_json: str = "",
) -> str:
    if mode == MODE_DYNAMIC:
        rendered = render_dynamic_markdown(report, include_skipped_examples=False)
    else:
        rendered = render_markdown(report, mode=mode)
    if regression_json:
        rendered = append_regression_summary(
            rendered,
            Path(regression_json),
            mode=mode,
            excluded_examples=dynamic_skipped_example_paths(report)
            if mode == MODE_DYNAMIC
            else (),
        )
    rendered = append_collected_result_files(rendered, report.source_files)
    if mode == MODE_DYNAMIC:
        rendered = append_dynamic_skipped_examples(rendered, report)
    return rendered


def publish_report(
    rendered: str,
    report: CombinedReport,
    args: argparse.Namespace,
    mode: str = MODE_DYNAMIC,
) -> None:
    write_or_print_report(rendered, args.output)

    if args.step_summary:
        append_step_summary(rendered)

    if args.annotations:
        emit_annotations(report, mode=mode)

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


def write_text_file(rendered: str, output: str) -> None:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    print("Example health report written to {}".format(output_path))


def load_health_metadata(path: str) -> Dict[str, object]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Health metadata must be a JSON object")
    return payload


def parse_utc(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_validation_time(value: str) -> str:
    return parse_utc(value).strftime("%Y-%m-%d %H:%M UTC")


def render_example_health_readme(
    inventory_examples: Sequence[dict],
    report: CombinedReport,
    metadata: Dict[str, object],
) -> str:
    lines = [
        "# Ianvs Examples",
        "",
        (
            "For status meanings, badge definitions, and broken-status subtypes, "
            "see [`status_directions.md`](../docs/proposals/scenarios/"
            "example-restoration/phase-3-2026-term-2/status_directions.md)."
        ),
        "",
    ]
    lines.append(
        "**Last T2/T3 Validation Time:** {}".format(
            dynamic_json_badge(
                "validated at", "summary.json", "$.validated_at_display"
            )
        )
    )

    lines.extend(
        [
            "",
            "## Example Classification Matrix",
            "",
            "<table>",
            "  <thead>",
            "    <tr>",
            "      <th>Example</th>",
            "      <th>Benchmark Unit</th>",
            "      <th>Status</th>",
            "    </tr>",
            "  </thead>",
            "  <tbody>",
        ]
    )
    grouped_examples: Dict[str, List[dict]] = {}
    for inventory_example in inventory_examples:
        example_name = str(
            inventory_example.get("example")
            or inventory_example.get("name")
            or inventory_example.get("path", "")
        )
        grouped_examples.setdefault(example_name, []).append(inventory_example)

    for example_name in sorted(grouped_examples):
        benchmark_units = sorted(
            grouped_examples[example_name],
            key=lambda item: (
                str(item.get("name", "")),
                str(item.get("benchmark_file", "")),
                str(item.get("path", "")),
            ),
        )
        for index, inventory_example in enumerate(benchmark_units):
            path = str(inventory_example.get("path", "")).rstrip("/")
            benchmark_name = str(inventory_example.get("name") or path)
            readme_path = path[9:] if path.startswith("examples/") else path
            benchmark_link = '<a href="./{}">{}</a>'.format(
                quote(readme_path, safe="/"),
                html.escape(benchmark_name),
            )
            lines.append("    <tr>")
            if index == 0:
                if len(benchmark_units) > 1:
                    lines.append(
                        '      <td rowspan="{}">{}</td>'.format(
                            len(benchmark_units), html.escape(example_name)
                        )
                    )
                else:
                    lines.append(
                        "      <td>{}</td>".format(html.escape(example_name))
                    )
            lines.extend(
                [
                    "      <td>{}</td>".format(benchmark_link),
                    "      <td>{}</td>".format(
                        endpoint_json_badge(
                            "status", status_file_name(example_name)
                        )
                    ),
                    "    </tr>",
                ]
            )
    lines.extend(["  </tbody>", "</table>"])
    return "\n".join(lines).rstrip() + "\n"


def status_file_name(example: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", example.strip())
    normalized = normalized.strip("._")
    if not normalized:
        raise ValueError("Example name does not contain a safe filename character")
    return normalized + ".json"


def create_example_status_snapshots(
    report: CombinedReport,
    inventory_examples: Sequence[dict],
    validated_at: str,
    commit: str,
) -> Dict[str, dict]:
    result_by_identity = {example.identity: example for example in report.examples}
    grouped_inventory: Dict[str, List[dict]] = {}
    grouped_results: Dict[str, List[ExampleResult]] = {}

    for inventory_example in inventory_examples:
        example = str(
            inventory_example.get("example")
            or inventory_example.get("name")
            or inventory_example.get("path", "")
        )
        grouped_inventory.setdefault(example, []).append(inventory_example)
        name = str(inventory_example.get("name", ""))
        path = str(inventory_example.get("path", "")).rstrip("/")
        result = result_by_identity.get((name, path))
        if result is not None:
            grouped_results.setdefault(example, []).append(result)

    snapshots = {}
    for example, inventory_group in grouped_inventory.items():
        results = grouped_results.get(example, [])
        has_failure = any(result.has_blocking_errors for result in results)
        inventory_statuses = {
            str(item.get("status", "active")).lower() for item in inventory_group
        }
        manual_statuses = {
            MANUAL_STATUS_BY_INVENTORY.get(inventory_status)
            for inventory_status in inventory_statuses
        }
        skip_reason = next(
            (
                status
                for status in SKIP_REASON_STATUSES
                if status in manual_statuses
            ),
            "",
        )
        if has_failure:
            status = "failing"
            message = STATUS_BROKEN
            label = "status"
        elif skip_reason:
            status = "skipped"
            message = skip_reason
            label = "reason"
        elif "ongoing" in inventory_statuses:
            status = STATUS_EXAMPLE_ONGOING
            message = STATUS_EXAMPLE_ONGOING
            label = "status"
        elif "unvalidated" in inventory_statuses or not results:
            status = STATUS_CICD_ONGOING
            message = STATUS_CICD_ONGOING
            label = "status"
        else:
            status = "passing"
            message = STATUS_RUNNABLE
            label = "status"
        snapshots[status_file_name(example)] = {
            "example": example,
            "status": status,
            "validated_at": validated_at,
            "commit": commit,
            "schemaVersion": 1,
            "label": label,
            "message": message,
            "color": STATUS_COLORS[message],
        }
    return snapshots


def write_example_status_snapshots(
    snapshots: Dict[str, dict], summary: dict, output: Path
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for filename, payload in sorted(snapshots.items()):
        (output / filename).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def dynamic_json_badge(label: str, filename: str, query: str) -> str:
    raw_url = "https://raw.githubusercontent.com/{}/{}/{}/{}".format(
        STATUS_REPOSITORY, STATUS_BRANCH, STATUS_RESULT_ROOT, filename
    )
    badge_url = "https://img.shields.io/badge/dynamic/json?{}".format(
        urlencode(
            {
                "url": raw_url,
                "query": query,
                "label": label,
                "cacheSeconds": "300",
            }
        )
    )
    return '<img alt="{}" src="{}">'.format(
        html.escape(label, quote=True), html.escape(badge_url, quote=True)
    )


def endpoint_json_badge(label: str, filename: str) -> str:
    raw_url = "https://raw.githubusercontent.com/{}/{}/{}/{}".format(
        STATUS_REPOSITORY, STATUS_BRANCH, STATUS_RESULT_ROOT, filename
    )
    badge_url = "https://img.shields.io/endpoint?{}".format(
        urlencode({"url": raw_url, "cacheSeconds": "300"})
    )
    return '<img alt="{}" src="{}">'.format(
        html.escape(label, quote=True), html.escape(badge_url, quote=True)
    )


def classify_health_status(
    inventory_example: dict,
    result: Optional[ExampleResult],
) -> Tuple[str, str]:
    inventory_status = str(inventory_example.get("status", "unvalidated")).lower()
    if inventory_status in MANUAL_STATUS_BY_INVENTORY:
        return MANUAL_STATUS_BY_INVENTORY[inventory_status], ""
    if inventory_status == "unvalidated":
        return STATUS_CICD_ONGOING, ""
    if inventory_status == "ongoing":
        return STATUS_EXAMPLE_ONGOING, ""
    if inventory_status != "active" or result is None:
        return STATUS_CICD_ONGOING, ""

    failed_checks = [
        check for check in result.checks if check.status in BLOCKING_STATUSES
    ]
    if not failed_checks:
        return STATUS_RUNNABLE, ""
    failure_text = " ".join(
        " ".join([check.name, check.message, check.file, " ".join(check.details)])
        .lower()
        for check in failed_checks
    )
    if any(
        word in failure_text
        for word in ("dependency", "requirements", "package", "pip")
    ):
        return STATUS_BROKEN, REASON_DEPENDENCY
    if any(
        word in failure_text
        for word in ("dataset", "jsonl", "model", "resource", "download")
    ):
        return STATUS_BROKEN, REASON_RESOURCE
    return STATUS_BROKEN, ""


def render_health_badges(status: str, reason: str) -> str:
    rendered = health_badge("status", status, STATUS_COLORS[status])
    if reason:
        rendered += " " + health_badge("reason", reason, REASON_COLORS[reason])
    return rendered


def health_badge(label: str, value: str, color: str) -> str:
    image_url = "https://img.shields.io/badge/{}-{}-{}".format(
        quote(label, safe=""), quote(value, safe=""), color
    )
    return '<img alt="{}" src="{}">'.format(
        html.escape(value, quote=True),
        html.escape(image_url, quote=True),
    )


def render_markdown(
    report: CombinedReport,
    mode: str = MODE_DYNAMIC,
) -> str:
    if mode == MODE_STATIC:
        return render_static_markdown(report)
    return render_dynamic_markdown(report)


def render_static_markdown(report: CombinedReport) -> str:
    result = static_overall_result(report)
    lines = [
        COMMENT_MARKER,
        "# Ianvs Static Validation Report",
        "",
        "**Overall result:** {}".format(result),
        "",
        "| Examples | Errors | Warnings | Skipped checks |",
        "|---:|---:|---:|---:|",
        "| {} | {} | {} | {} |".format(
            len(report.examples),
            report.check_count_any(BLOCKING_STATUSES),
            report.check_count(WARNING),
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
            "| Example | Result | Errors | Warnings | Skip |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for example in report.examples:
        lines.append(
            "| `{}` | {} | {} | {} | {} |".format(
                escape_table(example.path),
                static_example_result(example),
                example.count_any(BLOCKING_STATUSES),
                example.count(WARNING),
                example.count(SKIP),
            )
        )

    return "\n".join(lines).rstrip() + "\n"


def render_dynamic_markdown(
    report: CombinedReport,
    include_skipped_examples: bool = True,
) -> str:
    skipped_examples = dynamic_skipped_examples(report)
    runnable_examples = [
        example for example in report.examples if example.path not in skipped_examples
    ]
    result = PASS if all(
        not example.has_blocking_errors for example in runnable_examples
    ) else FAIL
    lines = [
        COMMENT_MARKER,
        "# Ianvs Dynamic Validation Report",
        "",
        "**Overall result:** {}".format(result),
        "",
        "| Examples | Errors | Skipped checks |",
        "|---:|---:|---:|",
        "| {} | {} | {} |".format(
            len(runnable_examples),
            sum(
                example.count_any(BLOCKING_STATUSES)
                for example in runnable_examples
            ),
            sum(example.count(SKIP) for example in runnable_examples),
        ),
        "",
    ]

    if not runnable_examples and not skipped_examples:
        lines.append("No validation results were collected.")
        return "\n".join(lines).rstrip() + "\n"

    if runnable_examples:
        lines.extend(
            [
                "## Example Summary",
                "",
                "| Example | Result | Errors | Skip |",
                "|---|---:|---:|---:|",
            ]
        )
        for example in runnable_examples:
            lines.append(
                "| `{}` | {} | {} | {} |".format(
                    escape_table(example.path),
                    dynamic_example_result(example),
                    example.count_any(BLOCKING_STATUSES),
                    example.count(SKIP),
                )
            )

    rendered = "\n".join(lines).rstrip() + "\n"
    if include_skipped_examples:
        return append_dynamic_skipped_examples(rendered, report)
    return rendered


def append_dynamic_skipped_examples(
    rendered: str,
    report: CombinedReport,
) -> str:
    skipped_examples = dynamic_skipped_examples(report)
    if not skipped_examples:
        return rendered

    lines = [
        "",
        "## Skipped Examples",
        "",
        "| Example | Reason |",
        "|---|---|",
    ]
    for example_path, reason in sorted(skipped_examples.items()):
        lines.append("| `{}` | {} |".format(escape_table(example_path), reason))
    return rendered.rstrip() + "\n" + "\n".join(lines).rstrip() + "\n"


def dynamic_skipped_examples(report: CombinedReport) -> Dict[str, str]:
    skipped = {}
    for example in report.examples:
        reason = dynamic_skip_reason(example)
        if reason:
            skipped[example.path] = reason
    return skipped


def dynamic_skipped_example_paths(report: CombinedReport) -> List[str]:
    return sorted(dynamic_skipped_examples(report))


def dynamic_skip_reason(example: ExampleResult) -> str:
    for check in example.checks:
        if check.name != DYNAMIC_ELIGIBILITY_CHECK or check.status != SKIP:
            continue
        inventory_status = inventory_status_from_check(check)
        if inventory_status == "unvalidated":
            return UNVALIDATED_REASON
        if inventory_status == "ongoing":
            return ONGOING_REASON
        manual_status = MANUAL_STATUS_BY_INVENTORY.get(inventory_status)
        if manual_status in SKIP_REASON_STATUSES:
            return health_badge(
                "reason", manual_status, STATUS_COLORS[manual_status]
            )
    return ""


def inventory_status_from_check(check: CheckResult) -> str:
    for detail in check.details:
        prefix = "inventory status:"
        if detail.lower().startswith(prefix):
            return detail[len(prefix):].strip().lower()
    return ""


def static_overall_result(report: CombinedReport) -> str:
    if report.check_count_any(BLOCKING_STATUSES):
        return ERROR
    if report.check_count(WARNING):
        return WARNING
    return PASS


def static_example_result(example: ExampleResult) -> str:
    if example.count_any(BLOCKING_STATUSES):
        return ERROR
    if example.count(WARNING):
        return WARNING
    if example.count(SKIP):
        return SKIP
    return PASS


def dynamic_example_result(example: ExampleResult) -> str:
    if example.count_any(BLOCKING_STATUSES):
        return FAIL
    if example.count(SKIP):
        return SKIP
    return PASS


def append_regression_summary(
    rendered: str,
    regression_json_path: Path,
    mode: str = MODE_DYNAMIC,
    excluded_examples: Sequence[str] = (),
) -> str:
    if not regression_json_path.is_file():
        return rendered

    payload = json.loads(regression_json_path.read_text(encoding="utf-8"))
    comparisons = payload.get("comparisons", [])
    if not isinstance(comparisons, list):
        comparisons = []
    excluded = set(excluded_examples)
    comparisons = [
        comparison
        for comparison in comparisons
        if not isinstance(comparison, dict)
        or str(comparison.get("example") or "") not in excluded
    ]

    examples = regression_examples(comparisons)
    if mode == MODE_STATIC:
        summary = static_regression_summary(comparisons, examples)
    else:
        summary = dynamic_regression_summary(comparisons, examples)
    summary.append("")
    return rendered.rstrip() + "\n" + "\n".join(summary).rstrip() + "\n"


def static_regression_summary(
    comparisons: Sequence[object],
    examples: Sequence[str],
) -> List[str]:
    summary = [
        "",
        "## Regression Summary",
        "",
        "### ERROR",
        "",
        "| Example | Current errors | Pre-existing errors | New errors | Fixed errors |",
        "|---|---:|---:|---:|---:|",
    ]
    for example in examples:
        summary.append(regression_error_summary_row(comparisons, example))
    if not examples:
        summary.append("| No regression comparisons were collected. | 0 | 0 | 0 | 0 |")

    summary.extend(
        [
            "",
            "### Warnings",
            "",
            "| Example | Current warnings | Pre-existing warnings | New warnings | Fixed warnings |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for example in examples:
        summary.append(regression_warning_summary_row(comparisons, example))
    if not examples:
        summary.append("| No regression comparisons were collected. | 0 | 0 | 0 | 0 |")
    return summary


def dynamic_regression_summary(
    comparisons: Sequence[object],
    examples: Sequence[str],
) -> List[str]:
    summary = [
        "",
        "## Regression Summary",
        "",
        "| Example | Current errors | Pre-existing errors | New errors | Fixed errors |",
        "|---|---:|---:|---:|---:|",
    ]
    for example in examples:
        summary.append(regression_error_summary_row(comparisons, example))
    if not examples:
        summary.append("| No regression comparisons were collected. | 0 | 0 | 0 | 0 |")
    return summary


def regression_error_summary_row(
    comparisons: Sequence[object],
    example: str,
) -> str:
    current_errors = count_regression_field(
        comparisons,
        "head_issue_count",
        example=example,
    )
    pre_existing_errors = count_regression_field(
        comparisons,
        "pre_existing_issue_count",
        fallback_classification="Failed: Pre-existing failure",
        example=example,
    )
    new_errors = count_regression_field(
        comparisons,
        "new_issue_count",
        fallback_classification="Failed: PR regression",
        example=example,
    )
    fixed_errors = count_regression_field(
        comparisons,
        "fixed_issue_count",
        fallback_classification="Fixed: Pre-existing failure resolved",
        example=example,
    )
    return "| `{}` | {} | {} | {} | {} |".format(
        escape_table(example),
        current_errors,
        pre_existing_errors,
        new_errors,
        fixed_errors,
    )


def regression_warning_summary_row(
    comparisons: Sequence[object],
    example: str,
) -> str:
    current_warnings = count_regression_field(
        comparisons,
        "head_warning_count",
        example=example,
    )
    pre_existing_warnings = count_regression_field(
        comparisons,
        "pre_existing_warning_count",
        example=example,
    )
    new_warnings = count_regression_field(
        comparisons,
        "new_warning_count",
        example=example,
    )
    fixed_warnings = count_regression_field(
        comparisons,
        "fixed_warning_count",
        example=example,
    )
    return "| `{}` | {} | {} | {} | {} |".format(
        escape_table(example),
        current_warnings,
        pre_existing_warnings,
        new_warnings,
        fixed_warnings,
    )


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


def emit_annotations(
    report: CombinedReport,
    mode: str = MODE_DYNAMIC,
) -> None:
    for example in report.examples:
        for check in example.checks:
            is_warning = mode == MODE_STATIC and check.status == WARNING
            if check.status not in BLOCKING_STATUSES and not is_warning:
                continue
            file_name = check.file or infer_file_from_details(check.details) or example.path
            message = check.message or check.name
            title = "{}: {}".format(example.path, check.name)
            command = "warning" if is_warning else "error"
            print(
                "::{command} file={file},title={title}::{message}".format(
                    command=command,
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
