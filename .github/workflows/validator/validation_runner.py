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

"""Entry point for local and CI example validation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Mapping, Optional, Sequence

from services.inventory_loader import DEFAULT_INVENTORY_PATH, load_inventory_examples
from static_validator import render_json, render_markdown, validate_examples

REPORT_FORMAT_JSON = "json"
REPORT_FORMAT_MARKDOWN = "markdown"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Ianvs example validation modules."
    )
    parser.add_argument(
        "--inventory",
        default=DEFAULT_INVENTORY_PATH,
        help="Example inventory YAML path.",
    )
    parser.add_argument(
        "--example",
        action="append",
        default=[],
        help="Example name or path to validate. Can be repeated.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Validate all active examples in the inventory.",
    )
    parser.add_argument(
        "--static",
        action="store_true",
        help="Run Tier 0 static validation.",
    )
    parser.add_argument(
        "--format",
        choices=(REPORT_FORMAT_MARKDOWN, REPORT_FORMAT_JSON),
        default=REPORT_FORMAT_MARKDOWN,
        help="Report output format.",
    )
    parser.add_argument(
        "--report",
        default="",
        help="Optional path to write the validation report.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Reserved for future smoke validation support.",
    )
    parser.add_argument(
        "--jsonl",
        action="store_true",
        help="Reserved for future JSONL validation support.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    repo_root = Path.cwd()
    inventory_path = repo_root / args.inventory

    static_mode = args.static or not (args.smoke or args.jsonl)
    include_inactive = static_mode and bool(args.example)
    examples = load_inventory_examples(inventory_path, active_only=not include_inactive)
    selected_examples = select_examples(examples, args.example, args.all)

    if not selected_examples:
        print("No inventory examples matched the requested selection.", file=sys.stderr)
        return 1

    if args.smoke or args.jsonl:
        print(
            "Smoke and JSONL validation are not implemented in this runner yet.",
            file=sys.stderr,
        )
        return 1

    if static_mode:
        report = validate_examples(repo_root=repo_root, examples=selected_examples)
        rendered = render_report(report, args.format)
        write_or_print_report(rendered, args.report)
        return 0

    return 1


def select_examples(
    examples: Sequence[Mapping[str, object]],
    requested: Sequence[str],
    include_all: bool,
) -> List[Mapping[str, object]]:
    if include_all or not requested:
        return list(examples)

    requested_values = {normalize_selector(value) for value in requested}
    selected = []
    for example in examples:
        if example_matches_selectors(example, requested_values):
            selected.append(example)

    return selected


def example_matches_selectors(
    example: Mapping[str, object],
    selectors: Sequence[str],
) -> bool:
    values = (
        normalize_selector(str(example.get("name", ""))),
        normalize_selector(str(example.get("path", ""))),
        normalize_selector(str(example.get("benchmark_file", ""))),
    )
    return any(value in selectors for value in values)


def normalize_selector(value: str) -> str:
    value = value.strip().strip("\"'")
    if value.startswith("./"):
        value = value[2:]
    return value.rstrip("/")


def render_report(report, report_format: str) -> str:
    if report_format == REPORT_FORMAT_JSON:
        return render_json(report)
    return render_markdown(report)


def write_or_print_report(rendered: str, report_path: str) -> None:
    if not report_path:
        print(rendered, end="")
        return

    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    print("Validation report written to {}".format(path))


if __name__ == "__main__":
    raise SystemExit(main())
