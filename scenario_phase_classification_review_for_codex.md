# Scenario Phase Classification Review for Codex

## Target File

Please review and update the following proposal file:

```text
docs/proposals/chore/scenario-roadmap-restructuring.md
```

The current phase planning direction is generally reasonable, but some phase descriptions and proposal assignments need refinement to make the classification logic more consistent and easier for maintainers to understand.

## Overall Assessment

The current three-phase structure is reasonable:

- **Phase 1** focuses on examples, datasets, benchmark assets, and low-risk scenario foundations.
- **Phase 2** focuses on evaluation workflows, metrics, test environments, benchmark execution, and automation.
- **Phase 3** focuses on framework-level evolution, orchestration, privacy-preserving collaboration, distributed capabilities, or architecture-level changes.

However, some proposals currently assigned to Phase 1 appear to involve evaluation pipeline or interface-level work, which makes them more suitable for Phase 2.

## Main Issue

The current Phase 1 description is too narrow if it is named only around examples and benchmarks.

In the actual file structure, Phase 1 includes not only example restoration or validation proposals, but also datasets, benchmark assets, domain scenario proposals, and onboarding-oriented scenario materials.

Therefore, the Phase 1 description should be adjusted to better match the actual content.

## Recommended Phase Naming

Please rename or revise the Phase 1 description from:

```text
Phase 1 — Example & Benchmark Foundation
```

To something like:

```text
Phase 1 — Scenario Assets & Example Foundation
```

This better covers:

- example restoration and example validation
- reusable datasets
- benchmark assets
- domain scenario proposals
- low-risk documentation and scenario organization work

## Recommended Classification Rule

Please add or strengthen a rule similar to the following:

```markdown
A proposal belongs to Phase 1 if it mainly introduces examples, datasets, documentation assets, or reusable benchmark materials without changing evaluation execution or framework behavior.

A proposal belongs to Phase 2 if it extends evaluation execution, benchmark workflows, dataset interfaces, metrics, test environments, CI validation, or automation around scenario assessment.

A proposal belongs to Phase 3 if it introduces framework-level collaboration, orchestration, privacy-preserving mechanisms, plugin-like architecture, distributed inference, or other major architectural capabilities.
```

This rule should be placed near the phase definition section or the phase assignment rationale section.

## README Structure Clarification

The proposed roadmap structure should use `README.md` only for roadmap and phase indexing layers.

Recommended rule:

```markdown
Use `docs/proposals/scenarios/README.md` as the top-level roadmap index.

Use `README.md` inside each phase directory such as `phase-1/`, `phase-2/`, and `phase-3/` to summarize the phase goal, included proposals, and the grouping rationale.

Do not require a separate `README.md` inside each proposal folder such as `Cloud-Robotics/` or `llm-benchmarks/`. Proposal folders can retain their existing proposal documents as the primary description.
```

This keeps the indexing structure lightweight and avoids introducing redundant per-folder README files when proposal content already exists in the current documents.

## Proposal-by-Proposal Recommendations

| Proposal / Folder | Current Phase | Recommended Phase | Reason |
|---|---:|---:|---|
| `Example_Restoration/` | Phase 1 | Phase 1 | Mainly example maintenance and restoration. Low-risk and documentation/example-oriented. |
| `example-restoration/` | Phase 1 | Phase 1 | Same as above. Suitable for Phase 1. |
| `Cloud-Robotics/` | Phase 1 | Phase 1 | Mainly dataset and benchmark case material. Suitable as scenario foundation. |
| `Cloud_robotics/` | Phase 1 | Phase 1 | Mainly dataset and benchmark-oriented. Suitable for Phase 1. |
| `cloud-robotics-lifelong-learning-dataset/` | Phase 1 | Phase 1 | Dataset foundation. Suitable for Phase 1. |
| `industrial-defect-detection/` | Phase 1 | Phase 1 | Suitable for Phase 1 if the scope is mainly dataset/example/benchmark material. |
| `government_affairs/` | Phase 1 | Phase 1 or Phase 2 | Keep in Phase 1 if it only provides dataset or scenario material. Move to Phase 2 if it includes evaluation suites, metrics, or benchmark execution workflow. |
| `Smart_Coding/` | Phase 1 | Phase 1 or Phase 2 | Keep in Phase 1 if it is only a benchmark asset. Move to Phase 2 if it defines evaluation execution, metrics, or automation. |
| `llm-benchmark-suite/` | Phase 1 | **Phase 2** | This appears to involve TestEnvManager, TestCaseController, StoryManager, metrics, CI/CD, OpenCompass integration, quantization/sparsity evaluation, and benchmark execution. These are evaluation pipeline concerns, not only benchmark assets. |
| `llm-benchmarks/` | Phase 1 | **Phase 2** | This appears to involve dataset reading, common interfaces, and possibly changes around benchmark framework behavior. This is closer to evaluation infrastructure than basic scenario assets. |
| `GovDoc2Poster/` | Phase 2 | Phase 2 | It defines task pipeline, datasets, evaluation suites, metrics, and baseline evaluation behavior. Phase 2 is appropriate. |
| `cloud-edge-collaborative-inference-for-llm/` | Phase 2 | Phase 1 or Phase 2 | If the current proposal only provides the MMLU 5-shot transformed dataset, Phase 1 may be enough. If the intended scope is collaborative inference assessment workflow, keep it in Phase 2 and explain that rationale clearly. |
| `data-selection-vla-finetuning-eval/` | Phase 2 | Phase 2 | Data selection plus evaluation optimization fits Phase 2. |
| `industrialEI/` | Phase 2 | Phase 2, with clarification | Phase 2 is acceptable if the scope is benchmark suite, datasets, metrics, and evaluation reports. If it later includes robotic workflow orchestration or agent execution, that part should become Phase 3. |
| `industrialEI-intelligent-assembly/` | Phase 3 | Phase 3 | Embodied workflow, intelligent assembly, and orchestration-level work fit Phase 3. |
| `phys-scene-gen/` | Phase 3 | Phase 3 | Simulation and physical scene generation are closer to architecture or advanced workflow capabilities. |
| `privacy-llm-collaboration/` | Phase 3 | Phase 3 | Cloud-edge privacy collaboration is architecture-level work. |
| `PIPL-Compliant.../` | Phase 3 | Phase 3 | Privacy-preserving cloud-edge LLM inference framework is clearly Phase 3. |

## Important Classification Adjustments

### 1. Move `llm-benchmark-suite/` from Phase 1 to Phase 2

Reason:

This proposal is not only a benchmark asset. It appears to involve benchmark execution, test environment management, metrics, CI/CD, dataset integration, and evaluation workflow design.

These are Phase 2 concerns because they affect how scenarios are evaluated, executed, or automated.

### 2. Move `llm-benchmarks/` from Phase 1 to Phase 2

Reason:

This proposal appears to involve dataset reading, common interfaces, and benchmark framework behavior. These are more than simple datasets or examples.

It should be classified as Phase 2 unless its scope is reduced to only adding static benchmark assets.

### 3. Clarify `cloud-edge-collaborative-inference-for-llm/`

Reason:

If the proposal only adds an MMLU 5-shot dataset transformation, it can be Phase 1.

If the proposal is intended to support collaborative inference evaluation, query routing, speculative decoding, or cloud-edge assessment workflows, it should remain Phase 2.

Recommended wording:

```markdown
Although this proposal includes dataset preparation work, it is assigned to Phase 2 because the intended use is to support collaborative inference evaluation workflows rather than only adding static benchmark assets.
```

### 4. Clarify `industrialEI/`

Reason:

The proposal includes benchmark suites and datasets, which fit Phase 2. However, robotics-centric datasets, simulation environments, embodied AI agents, and manipulation workflows may look like Phase 3 work.

Recommended wording:

```markdown
The Phase 2 scope of industrialEI is limited to benchmark suites, datasets, metrics, and reporting. Any future work involving robotic workflow orchestration, embodied agent execution, or framework-level integration should be treated as Phase 3.
```

## Suggested Text to Add to the Proposal

The following section can be added near the phase assignment rationale:

```markdown
### Phase Assignment Criteria

The phase assignment is based on the expected scope and integration depth of each proposal.

- **Phase 1 — Scenario Assets & Example Foundation** includes proposals that mainly introduce examples, datasets, documentation assets, or reusable benchmark materials. These proposals should not require changes to evaluation execution, framework behavior, or core runtime components.
- **Phase 2 — Evaluation Pipeline Enhancement** includes proposals that extend evaluation execution, benchmark workflows, dataset interfaces, metrics, test environments, CI validation, or automation around scenario assessment.
- **Phase 3 — Framework & Architecture Evolution** includes proposals that introduce framework-level collaboration, orchestration, privacy-preserving mechanisms, plugin-like architecture, distributed inference, simulation integration, or other major architectural capabilities.

If a proposal contains both dataset assets and evaluation workflow changes, it should be assigned to Phase 2. If a proposal contains evaluation workflow changes and framework-level orchestration or distributed runtime changes, it should be assigned to Phase 3.
```

## Suggested Final Summary for the Proposal

Please make sure the final rationale communicates the following:

```markdown
This restructuring does not change Ianvs core framework behavior. It only improves the organization and roadmap clarity of existing scenario proposals. The classification is intended to help maintainers and contributors understand which proposals are low-risk scenario assets, which ones require evaluation pipeline work, and which ones may require architecture-level discussion before implementation.

The documentation index should be maintained through `README.md` files at the roadmap and phase levels, while individual proposal folders continue to use their existing proposal documents without requiring extra README files.
```

## Expected Outcome

After the update, the roadmap should make it clearer that:

1. Phase 1 is for low-risk scenario assets, examples, datasets, and reusable benchmark materials.
2. Phase 2 is for evaluation workflow, test environment, metric, CI, and benchmark execution improvements.
3. Phase 3 is for framework-level architecture, orchestration, privacy, distributed inference, or simulation capabilities.
4. LLM benchmark proposals that define execution workflow or interfaces should not be grouped with simple benchmark assets.
5. Ambiguous proposals should include a short rationale explaining why they are placed in their assigned phase.
