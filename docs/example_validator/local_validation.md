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
  --jsonl \
  --smoke \
  --example examples/llm_simple_qa \
  --timeout 600
```

This command installs example dependencies into the active environment, prepares the smoke dataset, validates JSONL, and executes Ianvs. The smoke run automatically enables the inventory-declared Mock LLM runtime; no model download, GPU, or API credential is required. The result must be read as `mocked_llm`, not real-model validation.

To validate preparation and smoke inputs without starting Ianvs:

```bash
python .github/workflows/validator/validation_runner.py \
  --prepare-env \
  --jsonl \
  --smoke \
  --no-execute-smoke \
  --example examples/llm_simple_qa
```

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

Static detection considers changed `.py`, `.yaml`, and `.yml` files below inventory example paths. Dynamic detection selects changed examples and selects every active entry when `core/` or `.github/workflows/` changes.

## Validate against current upstream

The proposal defines a future local wrapper that creates and cleans up a temporary rebased validation branch. That wrapper is not present in the repository yet. Until it is implemented, update and test a disposable branch manually:

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

`act` is useful for checking workflow syntax and individual jobs, but GitHub-hosted permissions, artifact behavior, pull-request metadata, and runner images can differ locally.

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

## Troubleshooting

- **No inventory examples matched:** check the selector against `name`, `path`, or `benchmark_file` in the inventory.
- **Dynamic validation was skipped:** the selected inventory entry is not `active`.
- **PyYAML unavailable:** install `.github/workflows/validator/requirements.txt` and rerun static validation.
- **Dataset file missing:** run `--prepare-env` before `--jsonl` or `--smoke`, and confirm the inventory dataset layout.
- **Mock Runtime not loaded:** confirm both Mock Runtime directories exist and that the example fixture declares a supported adapter.
- **Dependency installation polluted the environment:** recreate the disposable virtual environment; do not use `--pip-install` in a shared environment.
- **Local action differs from CI:** inspect the uploaded JSON/Markdown artifacts in GitHub Actions and reproduce the underlying `validation_runner.py` command directly.
