# Run Example Validation Locally

Run all commands from the Ianvs repository root. The local CLI uses the same inventory and validator modules as CI.

See [validation rules](validation_rules.md) for what each stage checks and [classification policy](classification_policy.md) for how CI compares base and pull request results.

## Prerequisites

- Python 3.8 or the `python_version` declared by the selected inventory entry
- Git
- A virtual environment for dependency installation and dynamic validation
- Docker and [`act`](https://github.com/nektos/act) only when running GitHub Actions locally

Install the lightweight validator dependency first:

```bash
python -m venv .venv-validator
. .venv-validator/bin/activate
python -m pip install -r .github/workflows/validator/requirements.txt
```

Dynamic smoke execution also needs Ianvs itself:

```bash
python -m pip install -r requirements.txt
python -m pip install resources/third_party/sedna-0.6.0.1-py3-none-any.whl
python -m pip install -e . --no-deps
```

## Common commands

Run T0 static validation for all active inventory entries:

```bash
python .github/workflows/validator/validation_runner.py --static --all
```

Run static validation for one benchmark unit. `--example` accepts its inventory name, example path, or benchmark file:

```bash
python .github/workflows/validator/validation_runner.py \
  --static \
  --example examples/llm_simple_qa
```

Validate dependency declarations without installing them:

```bash
python .github/workflows/validator/validation_runner.py \
  --dependency \
  --example examples/llm_simple_qa
```

Ask pip to resolve the dependencies without installing them:

```bash
python .github/workflows/validator/validation_runner.py \
  --dependency \
  --pip-install-check \
  --example examples/llm_simple_qa
```

Run the dynamic stages used by CI for `llm_simple_qa`:

```bash
python .github/workflows/validator/validation_runner.py \
  --dependency \
  --pip-install \
  --prepare-env \
  --smoke \
  --example examples/llm_simple_qa
```

This command matches the T1/T2/T3 dynamic command in the current workflow and
runs three explicit stages:

1. `--dependency --pip-install` validates and installs the example dependencies into the active environment.
2. `--prepare-env` executes the ordered `prepare_env.steps` declared by the inventory.
3. `--smoke` validates the configured JSONL dataset structure and then executes the runtime smoke test.

The smoke run automatically enables the inventory-declared Mock LLM runtime; no model download, GPU, or API credential is required. The result must be read as `mocked_llm`, not real-model validation. Use a disposable environment because `--pip-install` changes installed packages.

Use the standalone `--jsonl` stage when dataset validation is needed without
runtime smoke execution:

```bash
python .github/workflows/validator/validation_runner.py \
  --prepare-env \
  --jsonl \
  --example examples/llm_simple_qa
```

CLI `--timeout` controls dependency installation or resolution checks and the
runtime smoke command. Each `prepare_env.steps[].timeout` controls only that
preparation step and is not overridden by CLI `--timeout`.

## Inventory preparation contract

The supported environment-preparation schema is:

```yaml
prepare_env:
  working_directory: examples/llm_simple_qa
  steps:
    - name: prepare_dataset
      type: dataset
      script: scripts/02_prepare_dataset.py
      args:
        - --output-dir
        - ../../dataset/llm_simple_qa
      timeout: 300
```

Active, migrated validation targets use ordered `prepare_env.steps`. Legacy,
unvalidated inventory entries may still contain fields such as
`dataset.prepare_script: null` because they have not been migrated. Do not use
that legacy field as the model for new or activated targets. For entries with
no `prepare_env` mapping, smoke validation retains a backward-compatible
fallback to `dataset.prepare_script`.

## Reports and exit codes

Markdown is printed to standard output by default. Save either Markdown or JSON with `--report`:

```bash
python .github/workflows/validator/validation_runner.py \
  --static \
  --example examples/llm_simple_qa \
  --format json \
  --report /tmp/llm-simple-qa-validation.json
```

The command exits `0` when no check has `FAIL` or `ERROR`, and `1` otherwise. `WARNING` and `SKIP` remain visible but do not change the exit code.

## Detect affected examples

Use the inventory loader to reproduce CI's target selection between two Git revisions:

```bash
python .github/workflows/validator/services/inventory_loader.py \
  --mode static \
  --base-ref upstream/main \
  --head-ref HEAD

python .github/workflows/validator/services/inventory_loader.py \
  --mode dynamic \
  --base-ref upstream/main \
  --head-ref HEAD
```

Static detection considers changed `.py`, `.yaml`, and `.yml` files below inventory example paths. It does not currently select README or other Markdown-only changes. Dynamic detection first selects all changed inventory entries, including inactive entries. `validation_runner.py` executes dynamic stages only for entries with `status: active`; each selected inactive entry receives a `Dynamic validation eligibility: SKIP` result.

When invoked directly, `inventory_loader.py` expands dynamic selection to all inventory entries for changes below `core/` or `.github/workflows/`. The GitHub Actions workflow has a narrower event path filter: it triggers for `examples/**`, `core/**`, `.github/workflows/validator/**`, and `.github/workflows/dynamic_code_cicd.yaml`. Changes to other workflow files do not currently start this dynamic workflow.

The proposal's UC-01.1 document-only validation remains planned coverage. The current workflows do not implement Markdown-specific validation, so do not treat a documentation-only change as an implemented T0 runtime path.

The merge-base-to-`HEAD` range answers which files belong to the contributor's change. The rebased validation branch answers a different question: whether those changes work with the latest upstream validation rules and shared core code. Both are needed—use the original merge-base range for ownership and the rebased state for execution.

## Validate against current upstream

The proposal defines a future local wrapper that synchronizes the upstream baseline, creates a temporary rebased validation branch, runs affected-example validation, and cleans up safely. That wrapper is not present in the repository yet. Its workflow-level implementation depends on cross-job artifact handoff in `act`, which is currently blocked by [`nektos/act#6114`](https://github.com/nektos/act/issues/6114). Until the upstream fix is merged and available in an `act` release, use `validation_runner.py` directly. If needed, update and test a disposable branch manually:

```bash
git remote get-url upstream
git fetch upstream main
git merge-base upstream/main HEAD
git switch -c validation/local-<name>
git rebase upstream/main
```

Run affected-example detection and the appropriate validation commands on that branch. If rebase conflicts occur, stop validation and resolve them on your contributor branch first. After returning to your original branch, delete only the temporary branch you created.

If `upstream` is not configured, add the official Ianvs repository before fetching:

```bash
git remote add upstream https://github.com/kubeedge/ianvs.git
```

These commands change local Git branch state, so commit or stash intentional work before using them.

## Run workflow jobs with act

`act` is useful for checking workflow syntax and individual jobs, but it cannot currently run the complete Ianvs validation workflow. The workflows pass validation results between jobs with `actions/upload-artifact@v7` and `actions/download-artifact@v8`; [`nektos/act#6114`](https://github.com/nektos/act/issues/6114) causes this artifact handoff to fail. GitHub-hosted permissions, pull-request metadata, and runner images can also differ locally.

List available jobs:

```bash
act -l -W .github/workflows/static_code_requirement_cicd.yaml
act -l -W .github/workflows/dynamic_code_cicd.yaml
```

Run a job with a pull-request event payload that contains valid base and head SHAs:

```bash
act pull_request \
  -W .github/workflows/static_code_requirement_cicd.yaml \
  -j detect-change-examples \
  -e /path/to/pull-request-event.json
```

The VS Code `github-local-actions` extension can provide a UI for the same `act`-backed workflow. Always confirm the final result in GitHub Actions before merge.

Do not downgrade the production workflows to older artifact actions or add an Ianvs-specific artifact workaround for local execution. After the [corresponding `act` fix](https://github.com/nektos/act/pull/6115) is merged and included in a usable release, the remaining proposal work is to implement:

- complete local workflow orchestration;
- validation artifact handoff between jobs;
- synchronization and fetching of the upstream baseline;
- creation of a temporary local validation branch;
- rebasing contributor changes onto the latest upstream baseline;
- affected-example validation on the rebased temporary branch; and
- safe cleanup of the temporary branch after validation.

## Troubleshooting

- **No inventory examples matched:** check the selector against `name`, `path`, or `benchmark_file` in the inventory.
- **Dynamic validation was skipped:** the selected inventory entry is not `active`.
- **PyYAML unavailable:** install `.github/workflows/validator/requirements.txt` and rerun static validation.
- **Dataset file missing:** run `--prepare-env` before `--jsonl` or `--smoke`, and confirm the inventory dataset layout.
- **Mock Runtime not loaded:** confirm both Mock Runtime directories exist and that the example fixture declares a supported adapter.
- **Dependency installation polluted the environment:** recreate the disposable virtual environment; do not use `--pip-install` in a shared environment.
- **The VS Code workflow view shows raw `${{ ... }}` expressions:** local-action UIs may display the YAML expression instead of its resolved value even when `act` resolves it during execution; verify the job log and command output.
- **Local action differs from CI:** inspect the uploaded JSON/Markdown artifacts in GitHub Actions and reproduce the underlying `validation_runner.py` command directly.
