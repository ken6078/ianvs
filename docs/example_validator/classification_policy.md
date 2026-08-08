# Example Classification Policy

Ianvs separates three concepts that answer different questions:

1. A **check result** (`PASS`, `FAIL`, `ERROR`, `WARNING`, or `SKIP`) describes one validator rule.
2. A **PR-impact classification** determines whether a result is newly introduced by a pull request.
3. An **example status** summarizes the maintained health of an example over time.

This separation prevents historical failures from blocking unrelated contributions while keeping maintenance debt visible.

See [validation rules](validation_rules.md) for individual checks and [status directions](status_directions.md) for the badge legend.

## Pull request comparison

CI runs the same selected checks against the pull request base and head revisions. The regression detector compares issues by example, check, file, and diagnostic detail. Line mappings from the Git diff are used so an unchanged issue is not treated as new merely because surrounding lines moved.

| Base | PR head | Classification | Blocks the PR |
| --- | --- | --- | --- |
| No blocking issue | New `FAIL` or `ERROR` issue | `Failed: PR regression` | Yes |
| Same blocking issue | Same `FAIL` or `ERROR` issue | `Failed: Pre-existing failure` | No |
| Blocking issue | Issue removed | `Fixed: Pre-existing failure resolved` | No |
| No blocking issue | `WARNING` only | `Passed` with warning details | No |
| Passing | Passing | `Passed` | No |
| Result cannot be compared | Indeterminate | `Unknown` | Maintainer review |

Only newly introduced `FAIL` or `ERROR` details make the regression job fail. Warnings are reported but do not block a pull request.

If a base report is missing or otherwise cannot be compared reliably, maintainers should inspect the raw artifacts instead of assuming the head failure is historical.

## Failure causes

The reporter assigns a cause from the failed check and its diagnostics. Supported cause labels include:

- `Failed: Dependency drift`
- `Failed: Dataset/resource drift`
- `Failed: Model/resource drift`
- `Failed: Hardware assumption`
- `Failed: Metric edge case`
- `Failed: Known issue`

Cause and PR ownership are independent. For example, a dependency failure can be a new PR regression, pre-existing debt, or a time-based maintenance failure.

## Time-based failures

A failure first found by broad scheduled validation is maintenance evidence rather than proof that an unrelated pull request caused it. Common causes include dependency drift, unavailable datasets or models, provider changes, and runner image changes.

Maintainers should:

1. preserve the report and validation timestamp;
2. reproduce or confirm the failure;
3. choose an accurate inventory status, such as `known issue`, `quarantined`, `requires_external_resource`, or `requires_hardware`;
4. create a follow-up issue when restoration is wanted;
5. return the entry to `active` only after the relevant validation tier passes.

## Example lifecycle statuses

The inventory uses machine-friendly values that the health report maps to display statuses.

| Inventory value | Display status | Intended use |
| --- | --- | --- |
| `active` | `Runnable` after a passing broad result | Included in dynamic validation |
| `unvalidated` | `CI/CD onGoing` | Inventory exists, but dynamic coverage is not active |
| `onGoing` | `Example onGoing` | The example implementation is still in progress |
| `requires_external_resource` or `external` | `Requires external dataset or model download` | Normal CI cannot obtain a required resource |
| `requires_hardware` or `hardware` | `Requires GPU or special hardware` | Normal runners do not provide required hardware |
| `quarantined` | `Quarantined` | Validation is intentionally disabled pending repair |
| `known_issue` or `known issue` | `Known issue` | A triaged defect is accepted temporarily |
| `broken` | `Broken` | Broad validation confirms an unhandled failure |

An active entry is displayed as `Broken` when its published T2/T3 result contains a blocking failure. Passing an individual T0 or T1 run does not by itself establish repository-wide `Runnable` status.

## Status update policy

- Use the inventory as the maintained policy source and generated T2/T3 snapshots as validation evidence.
- Do not label a mocked LLM run as evidence of a real model or provider passing.
- Do not use resource or hardware statuses to hide an ordinary reproducible software defect.
- Record constraints and follow-up references in inventory metadata or the tracking issue.
- Broad repair of examples other than the explicit `llm_simple_qa` restoration target belongs in separate issues or proposals.
- When a failure is fixed, rerun the highest practical tier and keep the resulting report or snapshot as evidence.

## Maintainer triage

When a report fails, first determine whether it is a PR regression. If it is, request a fix or explicitly approve an exception. If it is pre-existing or time-based, keep the pull request unblocked, update the example classification when needed, and track restoration separately.
