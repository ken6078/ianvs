import sys
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


VALIDATOR_DIR = Path(__file__).resolve().parents[1]
if str(VALIDATOR_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATOR_DIR))

from services import inventory_loader


def inventory_entry(name, path):
    return {
        "name": name,
        "path": path,
        "benchmark_file": "{}/benchmarkingjob.yaml".format(path),
        "python_version": "3.8",
        "status": "active",
    }


class InventoryLoaderRevisionSelectionTest(unittest.TestCase):
    @mock.patch.object(inventory_loader, "git_lines")
    @mock.patch.object(inventory_loader, "load_inventory_examples_at_ref")
    @mock.patch.object(inventory_loader, "load_inventory_examples")
    def test_tier2_uses_complete_base_and_head_target_sets(
        self,
        load_head,
        load_base,
        git_lines,
    ):
        base = [
            inventory_entry("a", "examples/a"),
            inventory_entry("b", "examples/b"),
            inventory_entry("c", "examples/c"),
        ]
        head = base + [inventory_entry("d", "examples/d")]
        load_head.return_value = head
        load_base.return_value = base
        git_lines.return_value = ["core/common.py"]

        report = inventory_loader.detect_changes(
            base_ref="base-sha",
            head_ref="HEAD",
            mode=inventory_loader.MODE_DYNAMIC,
            inventory_path=Path(".github/workflows/validator/data/example_inventory.yaml"),
            base_inventory_ref="base-sha",
        )

        self.assertTrue(report["run_all"])
        self.assertEqual(3, len(report["base_validation_matrix"]))
        self.assertEqual(4, len(report["head_validation_matrix"]))
        self.assertEqual(3, len(report["base_changed_examples"]))
        complete_base_reports = ["a.json", "b.json", "c.json"]
        self.assertEqual(
            len(report["base_changed_examples"]),
            len(complete_base_reports),
        )
        self.assertNotEqual(
            len(report["head_changed_examples"]),
            len(complete_base_reports),
        )

    @mock.patch.object(inventory_loader, "git_lines")
    @mock.patch.object(inventory_loader, "load_inventory_examples_at_ref")
    @mock.patch.object(inventory_loader, "load_inventory_examples")
    def test_changed_path_is_selected_only_from_revision_where_it_exists(
        self,
        load_head,
        load_base,
        git_lines,
    ):
        added = inventory_entry("new", "examples/new")
        load_head.return_value = [added]
        load_base.return_value = []
        git_lines.return_value = ["examples/new/benchmarkingjob.yaml"]

        report = inventory_loader.detect_changes(
            base_ref="base-sha",
            head_ref="HEAD",
            mode=inventory_loader.MODE_DYNAMIC,
            inventory_path=Path(".github/workflows/validator/data/example_inventory.yaml"),
            base_inventory_ref="base-sha",
        )

        self.assertFalse(report["base_examples_changed"])
        self.assertTrue(report["head_examples_changed"])
        self.assertEqual([], report["base_validation_matrix"])
        self.assertEqual(
            ["examples/new/benchmarkingjob.yaml"],
            report["head_changed_examples"],
        )

        load_head.return_value = []
        load_base.return_value = [added]
        report = inventory_loader.detect_changes(
            base_ref="base-sha",
            head_ref="HEAD",
            mode=inventory_loader.MODE_DYNAMIC,
            inventory_path=Path(".github/workflows/validator/data/example_inventory.yaml"),
            base_inventory_ref="base-sha",
        )

        self.assertTrue(report["base_examples_changed"])
        self.assertFalse(report["head_examples_changed"])
        self.assertEqual(
            ["examples/new/benchmarkingjob.yaml"],
            report["base_changed_examples"],
        )
        self.assertEqual([], report["head_validation_matrix"])

    def test_workflow_tier2_completeness_uses_base_targets(self):
        workflow = (
            VALIDATOR_DIR.parent / "dynamic_code_cicd.yaml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "EXPECTED_EXAMPLES: ${{ needs.detect-change-examples.outputs.base_changed_examples }}",
            workflow,
        )
        self.assertNotIn(
            "EXPECTED_EXAMPLES: ${{ needs.detect-change-examples.outputs.head_changed_examples }}",
            workflow,
        )
        self.assertIn('--base-ref "${{ github.event.pull_request.base.sha }}"', workflow)
        self.assertIn('--head-ref HEAD', workflow)

    def test_static_workflow_uses_revision_specific_targets(self):
        workflow = (
            VALIDATOR_DIR.parent / "static_code_requirement_cicd.yaml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            '--base-inventory-ref "${{ github.event.pull_request.base.sha }}"',
            workflow,
        )
        self.assertIn(
            "include: ${{ fromJson(needs.detect-change-examples.outputs.base_validation_matrix) }}",
            workflow,
        )
        self.assertIn(
            "include: ${{ fromJson(needs.detect-change-examples.outputs.head_validation_matrix) }}",
            workflow,
        )
        self.assertIn("--allow-missing-base", workflow)
        self.assertIn("--allow-missing-head", workflow)
        self.assertNotIn("matrix.changed_example", workflow)

    def test_validator_tests_have_a_path_scoped_workflow(self):
        workflow = (
            VALIDATOR_DIR.parent / "validator_test_cicd.yaml"
        ).read_text(encoding="utf-8")
        dynamic_workflow = (
            VALIDATOR_DIR.parent / "dynamic_code_cicd.yaml"
        ).read_text(encoding="utf-8")

        self.assertEqual(2, workflow.count("- '.github/workflows/validator/**'"))
        self.assertEqual(
            2,
            workflow.count("- '.github/workflows/validator_test_cicd.yaml'"),
        )
        self.assertIn(
            "python .github/workflows/validator/tests/run_tests.py",
            workflow,
        )
        self.assertNotIn("validator-unit-tests:", dynamic_workflow)

    def test_fallback_yaml_parser_and_inventory_filtering(self):
        payload = inventory_loader.load_inventory_text_without_pyyaml(
            "examples:\n"
            "- name: active\n  path: examples/active/\n  status: active\n"
            "  dataset:\n    root: dataset\n"
            "- name: waiting\n  path: examples/waiting\n  status: unvalidated\n"
            "- name: missing-path\n  status: active\n"
        )
        self.assertEqual(["active"], [e["name"] for e in inventory_loader.inventory_examples(payload)])
        self.assertEqual(
            ["active", "waiting"],
            [e["name"] for e in inventory_loader.inventory_examples(payload, active_only=False)],
        )
        self.assertEqual("examples/active", inventory_loader.inventory_examples(payload)[0]["path"])

    def test_path_matching_static_filter_and_dynamic_run_all(self):
        self.assertTrue(inventory_loader.file_matches_path("examples/a/x.py", "examples/a"))
        self.assertFalse(inventory_loader.file_matches_path("examples/ab/x.py", "examples/a"))
        self.assertTrue(inventory_loader.is_static_tracked_file("EXAMPLES/A/JOB.YAML"))
        self.assertFalse(inventory_loader.is_static_tracked_file("examples/a/readme.md"))
        self.assertTrue(inventory_loader.should_run_all_dynamic(["core/common.py"]))
        self.assertTrue(inventory_loader.should_run_all_dynamic([".github/workflows/x.yaml"]))
        self.assertFalse(inventory_loader.should_run_all_dynamic(["docs/readme.md"]))

    def test_selection_report_uses_selector_and_default_python(self):
        examples = [
            {"name": "a", "path": "examples/a", "benchmark_file": "a.yaml", "python_version": "3.10"},
            {"name": "b", "path": "examples/b", "python_version": " "},
        ]
        report = inventory_loader.inventory_selection_report("static", examples, False, ["x.py"], "a", "b")
        self.assertEqual(["a.yaml", "b"], report["changed_examples"])
        self.assertEqual("3.10", report["validation_matrix"][0]["python_version"])
        self.assertEqual(inventory_loader.DEFAULT_PYTHON_VERSION, report["validation_matrix"][1]["python_version"])

    def test_utc_health_record_and_metadata_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            readme = root / "README.md"
            readme.write_text(
                '<!-- ianvs-example-health-record {"validated_at":"2026-08-01T00:00:00Z","source_run_id":7,"source_tier":"T3"} -->',
                encoding="utf-8",
            )
            record = inventory_loader.load_health_record(readme)
            self.assertEqual(7, record["source_run_id"])
            self.assertEqual("2026-08-01T00:00:00Z", inventory_loader.format_utc(record["validated_at"]))

            metadata = root / "summary.json"
            metadata.write_text(json.dumps({"validated_at": "2026-08-02T01:00:00", "commit": "abc"}))
            loaded = inventory_loader.load_health_metadata(metadata)
            self.assertEqual("abc", loaded["source_sha"])
            self.assertEqual(timezone.utc, loaded["validated_at"].tzinfo)

            metadata.write_text("{}")
            with self.assertRaises(ValueError):
                inventory_loader.load_health_metadata(metadata)

    def test_pending_tier2_artifact_filters_and_selects_latest(self):
        record = {"validated_at": inventory_loader.parse_utc("2026-08-01T00:00:00Z"), "source_run_id": 10}
        artifacts = [
            {"id": 1, "created_at": "2026-08-02T00:00:00Z", "workflow_run": {"id": 10}},
            {"id": 2, "created_at": "2026-08-03T00:00:00Z", "workflow_run": {"id": 11}, "expired": True},
            {"id": 3, "created_at": "bad", "workflow_run": {}},
            {"id": 4, "created_at": "2026-08-04T00:00:00Z", "workflow_run": {"id": 12}},
            {"id": 5, "created_at": "2026-08-05T00:00:00Z", "workflow_run": {"id": 13}},
        ]
        selected = inventory_loader.select_pending_tier2_artifact(artifacts, record)
        self.assertEqual(5, selected["artifact_id"])
        self.assertEqual(13, selected["run_id"])

    def test_scheduled_plan_covers_publish_run_and_wait(self):
        now = inventory_loader.parse_utc("2026-08-20T00:00:00Z")
        artifact = {"artifact_id": 4, "run_id": 5, "created_at": now}
        publish = inventory_loader.scheduled_validation_plan(now, None, artifact)
        self.assertEqual(inventory_loader.SCHEDULE_ACTION_PUBLISH_TIER2, publish["action"])

        self.assertEqual(
            inventory_loader.SCHEDULE_ACTION_RUN_TIER3,
            inventory_loader.scheduled_validation_plan(now, None, None)["action"],
        )
        recent = {"validated_at": inventory_loader.parse_utc("2026-08-19T00:00:00Z")}
        self.assertEqual(
            inventory_loader.SCHEDULE_ACTION_NONE,
            inventory_loader.scheduled_validation_plan(now, recent, None)["action"],
        )
        old = {"validated_at": inventory_loader.parse_utc("2026-08-01T00:00:00Z")}
        self.assertEqual(
            inventory_loader.SCHEDULE_ACTION_RUN_TIER3,
            inventory_loader.scheduled_validation_plan(now, old, None)["action"],
        )

    def test_export_outputs_are_machine_readable(self):
        report = inventory_loader.inventory_selection_report(
            "static", [inventory_entry("a", "examples/a")], False, ["examples/a/x.py"]
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "github-output"
            inventory_loader.export_github_outputs(report, str(output))
            text = output.read_text()
            self.assertIn("examples_changed=true", text)
            self.assertIn('changed_examples=["examples/a/benchmarkingjob.yaml"]', text)

            plan = inventory_loader.scheduled_validation_plan(
                datetime(2026, 8, 20, tzinfo=timezone.utc), None, None
            )
            inventory_loader.export_schedule_outputs(plan, str(output))
            self.assertIn("action=run_tier3", output.read_text())

    @mock.patch.object(inventory_loader.subprocess, "check_output")
    @mock.patch.object(inventory_loader.subprocess, "run")
    def test_inventory_at_ref_handles_present_and_new_inventory(self, run, check_output):
        path = Path("inventory.yaml")
        run.return_value.returncode = 0
        check_output.return_value = "examples:\n- name: a\n  path: examples/a\n"
        self.assertEqual("a", inventory_loader.load_inventory_examples_at_ref(path, "base")[0]["name"])

        run.return_value.returncode = 1
        check_output.return_value = "base\n"
        self.assertEqual([], inventory_loader.load_inventory_examples_at_ref(path, "base"))


if __name__ == "__main__":
    unittest.main()
