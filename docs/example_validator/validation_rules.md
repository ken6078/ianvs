# Example Validator Rules

This document describes the checks implemented by the Ianvs example validator. The inventory at [`.github/workflows/validator/data/example_inventory.yaml`](../../.github/workflows/validator/data/example_inventory.yaml) is the source of truth for validation targets and example-specific metadata.

See also:

- [Classification policy](classification_policy.md)
- [Local validation](local_validation.md)
- [Example status directions](status_directions.md)

## Result levels

Each validator emits one of the following check results:

| Result | Meaning | Directly fails a validator run |
| --- | --- | --- |
| `PASS` | The check completed and found no issue. | No |
| `FAIL` | An execution or validation requirement failed. | Yes |
| `ERROR` | A required file, configuration, or structural rule failed. | Yes |
| `WARNING` | A portability or maintenance risk was found. | No |
| `SKIP` | The check was not applicable or could not run. | No |

`FAIL` and `ERROR` are blocking results inside a single validation report. Whether they block a pull request is decided separately by the regression policy.

## Inventory rules

Every benchmark unit is represented by an inventory entry. An entry should declare:

- a unique benchmark `name` and its top-level `example` group;
- `path`, `benchmark_file`, and `readme_file` when available;
- `requirements_file` when the example has specific dependencies;
- `python_version` for active dynamic validation targets;
- an inventory lifecycle `status`;
- dataset metadata, including `root` and `structure` when JSONL validation is supported;
- optional ordered `prepare_env.steps`;
- optional Mock LLM runtime paths.

The validation unit is a benchmark job, normally identified by one benchmarking YAML file. A top-level example may therefore have several inventory entries and several matrix rows. Do not collapse multiple jobs into one result merely because they share an example directory: their configurations and health can differ.

Dynamic validation only runs entries whose inventory status is `active`. Static validation may inspect explicitly selected inactive entries so maintainers can triage them.

`prepare_env.steps` is the supported environment-preparation schema for active,
migrated targets. Legacy, unvalidated entries may still contain fields such as
`dataset.prepare_script: null` while awaiting migration; that legacy field is
not the recommended schema for new or activated targets.

## Static validation

Static checks do not execute the example. They inspect the entry, YAML, and Python files under the example path.

| Check | Rule | Failure level |
| --- | --- | --- |
| Example and benchmark paths | The example directory and declared benchmark file must exist. | `ERROR` |
| Requirements and preparation paths | Declared files and scripts must exist. | `ERROR` |
| YAML syntax | Every `.yaml` and `.yml` file must parse with PyYAML. | `ERROR`; `SKIP` if PyYAML is unavailable |
| Repository-local references | Referenced repository Python/YAML paths must resolve. | `ERROR` |
| Other repository path parents | Parent directories for non-code references should exist. | `WARNING` |
| Hardcoded local paths | Contributor-specific absolute POSIX or Windows paths should not appear in Python or YAML. | `WARNING` |
| Local model paths | Model settings should use a portable model ID or a documented override, not `/home/...`, `/Users/...`, or a local `models/` path. | `WARNING` |
| Device selection | Code that selects CUDA must also provide an availability check and CPU fallback. | `WARNING` |
| Metric safety | Metrics that divide by a collection length should guard an empty collection. | `WARNING`; `SKIP` when no metric file exists |

The current static scanner covers `.py`, `.yaml`, and `.yml` files. README requirements in the proposal remain a review requirement until Markdown-specific checks are implemented.

### Why a check is an error or a warning

The primary boundary is whether the detected condition is sufficient to prevent the configured validation path from running:

- use `ERROR` or `FAIL` for a missing required file, invalid configuration, failed preparation/install command, failed runtime, or another condition that directly prevents execution;
- use `WARNING` for a portability, maintainability, security, or heuristic finding that may still allow execution;
- do not promote a heuristic to an error merely because the pattern is undesirable. A false positive must not block a pull request.

Warnings should normally be addressed during review. If a change is urgent and the example remains runnable, maintainers may accept a warning with a follow-up issue. The report must still retain the warning and its consequence.

| Warning | Why it matters | Expected response |
| --- | --- | --- |
| Missing non-code path parent | A dataset or generated resource may not have been prepared yet. | Confirm the preparation contract or document an external resource. |
| Hardcoded local path | The example may work only on the contributor's machine. | Use a repository-relative path, portable default, or explicit override. |
| Local model path | The example may be non-portable and can encourage committing large model weights. | Use a model ID or configurable local override; do not commit weights. |
| CUDA-only pattern | CPU runners may fail, but a regex can miss or misread nearby fallback logic. | Verify CUDA/MPS/CPU selection and treat a confirmed fallback as a false positive. |
| Metric empty-pair pattern | Empty results may cause division by zero, but the static pattern is heuristic. | Add an explicit empty-pair result such as `0.0`; a reproduced crash is a runtime `FAIL`. |

### Environment preparation contract

If `prepare_env` is present, it must contain a valid `working_directory` and a non-empty ordered `steps` list. Every step requires:

```yaml
- name: prepare_dataset
  type: dataset
  script: scripts/02_prepare_dataset.py
  args:
    - --output-dir
    - ../../dataset/llm_simple_qa
  timeout: 300
```

`args` must be an array of strings, `timeout` must be a positive integer, and the script must exist below the working directory. The environment preparation validator executes steps in order, without `shell=True`, stops at the first failure, and reports the step name and type.

### Mock Runtime contract

When `mock_runtime.enabled` is `true`, both `shared_pythonpath` and `example_pythonpath` must be non-empty path arrays whose directories exist inside the repository. Adapter selection and semantic responses belong to the example fixture, not the inventory.

## Dependency validation

Dependency validation checks the declared requirements file independently of environment preparation. It verifies:

- the declared file exists and is not empty;
- requirement lines are syntactically valid;
- environment markers are compatible with the current Python interpreter;
- imports used by the example runtime are covered by dependency declarations;
- optionally, pip can resolve or install the requirements.

The install modes are:

| CLI option | Behavior |
| --- | --- |
| no install option | Validate declarations only. |
| `--pip-install-check` | Run pip's dry-run resolution check. |
| `--pip-install` | Install the declared requirements into the current environment. |

Use a disposable virtual environment with `--pip-install`; it changes that environment.

## Dataset and JSONL validation

The validator discovers JSONL files from inventory `dataset.root` plus `dataset.structure`, falling back to the test environment configuration when necessary.

The implemented JSONL rules are:

- every declared file must exist;
- test data must not be empty;
- blank rows are invalid;
- each physical line must contain one complete JSON value;
- every row must decode to a JSON object;
- an empty training file is allowed for examples that do not train.

Field-level schema validation, such as requiring `question` and `answer`, is not currently enforced by the shared validator. Examples should document their schema, and a future validator change may make these fields machine-enforced.

For `llm_simple_qa`, the expected layout is:

```text
dataset/llm_simple_qa/
├── train_data/data.jsonl
└── test_data/data.jsonl
```

## Smoke validation

The default smoke command is:

```bash
python benchmarking.py -f <benchmark-file>
```

Before execution, the validator verifies the benchmark file and JSONL structure. A non-zero exit status or timeout is a `FAIL`.

For an inventory entry with Mock LLM enabled, the smoke subprocess receives `IANVS_LLM_MOCK=1` and a composed `PYTHONPATH`. Python loads the shared `sitecustomize.py`, which installs the adapters declared by the example fixture. The report labels this check `Runtime smoke test (mocked_llm)`.

A mocked run proves that the unchanged inference integration and benchmark flow execute with deterministic substitute responses. It does not prove model quality, model availability, provider availability, network access, GPU behavior, or benchmark accuracy.

Examples that require an external API key and do not have a supported Mock Runtime cannot run a meaningful credential-free smoke test. Classify that limitation explicitly; do not publish a real-provider passing status from a substituted response.

## Validation reports

Human-readable reports are summaries of structured JSON results. Diagnostics use the form:

```text
path/to/file -> (Line 31): offending value
```

The file and line identify where maintainers should look; the value and message explain what triggered the check and why it matters. Regression details show at most the first ten diagnostics in Markdown and report how many more exist. Use the JSON artifact when the summary is truncated.

The regression summary separates current, pre-existing, new, and fixed issues. A heading such as `Collected Result Files` refers to validator JSON artifacts for selected inventory benchmark jobs/YAML files. It does not mean that one result is generated for every source file changed by the contributor.

Direct base and PR validation jobs preserve their result artifacts even when an individual validator exits non-zero. This is intentional: the regression comparison is the job that decides whether a newly introduced blocking issue fails the pull request.

## CI coverage

The repository uses these validation levels:

| Tier | Selection | Checks |
| --- | --- | --- |
| T0 | Inventory examples with changed `.py`, `.yaml`, or `.yml` files below their example path | Static checks |
| T1 | Example changed by a pull request | Dependencies, preparation, dataset, and smoke validation for that example |
| T2 | Shared `core/` or workflow/validator changes | Dynamic validation for all active inventory targets |
| T3 | Scheduled or main-branch broad run | Dynamic validation for all active inventory targets and health snapshot publication |

The static workflow currently triggers for changed example Python or YAML files. The dynamic workflow triggers for changes below `examples/`, `core/`, the validator, or its workflow. Scheduled planning runs daily and uses a seven-day broad-validation cadence. Generated reports and status snapshots are the evidence for classification; a passing mocked check must retain its `mocked_llm` label.

T0 intentionally focuses on inexpensive code/configuration checks for the changed example. Documentation-only change detection, Markdown-specific validation, deeper parsing of GPU declarations such as runtime configuration fields, and broader static semantic analysis are future extensions. T2/T3 status must be based on dynamic evidence rather than inferred from a T0 pass.
