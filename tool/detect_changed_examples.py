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

"""Detect examples affected by changed files for GitHub Actions."""

from __future__ import print_function

import argparse
import json
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence, Set


WORKFLOW_RELATED_FILES = {
    ".github/workflows/static-validator.yml",
}


def git_output(args: Sequence[str]) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def git_lines(args: Sequence[str]) -> List[str]:
    output = git_output(args)
    return [line for line in output.splitlines() if line]


def git_ref_exists(ref: str) -> bool:
    try:
        subprocess.check_call(
            ["git", "rev-parse", "--verify", ref],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def discover_all_examples(repo_root: Path) -> List[str]:
    examples_root = repo_root / "examples"
    if not examples_root.exists():
        return []

    return sorted(
        path.parent.resolve().relative_to(repo_root).as_posix()
        for path in examples_root.rglob("benchmarkingjob.yaml")
    )


def resolve_changed_files(
    event_name: str,
    base_sha: Optional[str],
    head_sha: Optional[str],
    compare_ref: Optional[str],
) -> List[str]:
    head = head_sha or "HEAD"

    if event_name == "pull_request" and base_sha:
        return git_lines(["diff", "--name-only", base_sha, head])

    if event_name == "push" and base_sha:
        if base_sha != "0000000000000000000000000000000000000000":
            return git_lines(["diff", "--name-only", base_sha, head])

    if compare_ref and git_ref_exists(compare_ref):
        merge_base = git_output(["merge-base", compare_ref, head])
        return git_lines(["diff", "--name-only", merge_base, head])

    return git_lines(["ls-files", "examples", "tool", ".github/workflows/static-validator.yml"])


def should_run_all(changed_files: Sequence[str]) -> bool:
    for changed_file in changed_files:
        if changed_file.startswith("tool/"):
            return True
        if changed_file in WORKFLOW_RELATED_FILES:
            return True
    return False


def detect_changed_examples(repo_root: Path, changed_files: Sequence[str]) -> List[str]:
    examples_root = (repo_root / "examples").resolve()
    changed_examples: Set[str] = set()

    for changed_file in changed_files:
        changed_path = Path(changed_file)
        if "examples" not in changed_path.parts:
            continue

        candidate = (repo_root / changed_path).resolve()
        if candidate.is_file():
            candidate = candidate.parent

        current = candidate
        while current != current.parent:
            if (current / "benchmarkingjob.yaml").is_file():
                changed_examples.add(current.relative_to(repo_root).as_posix())
                break
            if current == examples_root:
                break
            current = current.parent

    return sorted(changed_examples)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect examples affected by repository changes."
    )
    parser.add_argument("--repo-root", default=".", help="Repository root path.")
    parser.add_argument(
        "--event-name",
        required=True,
        help="GitHub event name, such as pull_request or push.",
    )
    parser.add_argument(
        "--base-sha",
        default="",
        help="Base SHA used to diff changes. Optional for workflow_dispatch.",
    )
    parser.add_argument(
        "--head-sha",
        default="HEAD",
        help="Head SHA used to diff changes.",
    )
    parser.add_argument(
        "--compare-ref",
        default="main",
        help="Reference branch used as the comparison baseline.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    all_examples = discover_all_examples(repo_root)
    changed_files = resolve_changed_files(
        event_name=args.event_name,
        base_sha=args.base_sha or None,
        head_sha=args.head_sha or None,
        compare_ref=args.compare_ref or None,
    )
    run_all = should_run_all(changed_files)
    selected_examples = (
        all_examples if run_all else detect_changed_examples(repo_root, changed_files)
    )

    report = {
        "changed_files": changed_files,
        "run_all": run_all,
        "examples": selected_examples,
        "examples_count": len(selected_examples),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
