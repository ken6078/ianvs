# Scenario Roadmap Organization

## Summary

As the number of scenario proposals in Ianvs continues to grow, it becomes increasingly difficult for contributors and maintainers to understand implementation order, proposal dependencies, and the overall development direction.

This proposal introduces a roadmap-based organization strategy for scenario proposals. Existing and future proposals will be categorized into three development phases according to their scope, complexity, and impact on the Ianvs ecosystem.

The objective is to provide a clearer project development direction without introducing any changes to the Ianvs core framework.

---

## Motivation

Currently, scenario proposals are maintained independently under:

```text
docs/proposals/scenarios/
```

While this structure is sufficient for storing proposals, it does not clearly communicate:

* Which proposals depend on previous work
* Which proposals affect framework architecture
* Long-term development direction

A phased roadmap helps contributors understand the project's development direction and enables mentorship programs such as LFX and GSoC to align project milestones with community goals.

---

## Goals

### Phase 1 — Example & Benchmark Foundation

Focus on improving example quality, maintainability, and validation.

Potential proposals:

* Example Restoration
* Example Restoration CI
* Example Validation
* Documentation Validation

Objectives:

* Ensure examples remain executable
* Improve contributor experience
* Provide continuous example health monitoring

---

### Phase 2 — Evaluation Pipeline Enhancement

Focus on extending evaluation capabilities.

Potential proposals:

* Benchmark Integration
* Evaluator Enhancement
* Dataset Validation
* Dataset Management

Objectives:

* Improve evaluation coverage
* Support more benchmarks and metrics
* Enhance evaluation reliability

---

### Phase 3 — Framework & Architecture Evolution

Focus on future framework expansion.

Potential proposals:

* Agent Evaluation
* Workflow Evaluation
* Distributed Evaluation
* Plugin Architecture

Objectives:

* Expand Ianvs capabilities
* Support emerging AI evaluation scenarios
* Improve framework extensibility

---

## Non-Goals

This proposal does not:

* Modify Ianvs core code
* Modify evaluation pipelines
* Introduce new benchmarks
* Change existing APIs
* Change existing example behavior

The proposal only provides roadmap organization and documentation improvements.

---

## Proposed File Structure

```text
docs/
└── proposals/
    └── scenarios/
        ├── README.md
        ├── phase-1/
        │   ├── README.md
        │   ├── Cloud-Robotics/
        │   ├── Cloud_robotics/
        │   ├── Example_Restoration/
        │   ├── Smart_Coding/
        │   ├── cloud-robotics-lifelong-learning-dataset/
        │   ├── example-restoration/
        │   ├── government_affairs/
        │   ├── industrial-defect-detection/
        │   ├── Industrial manufacturing/
        │   ├── llm-benchmark-suite/
        │   └── llm-benchmarks/
        │
        ├── phase-2/
        │   ├── README.md
        │   ├── GovDoc2Poster/
        │   ├── cloud-edge-collaborative-inference-for-llm/
        │   ├── data-selection-vla-finetuning-eval/
        │   └── industrialEI/
        │
        └── phase-3/
            ├── README.md
            ├── PIPL-Compliant Cloud-Edge Collaborative Privacy-Preserving Prompt Processing Framework/
            ├── industrialEI-intelligent-assembly/
            ├── phys-scene-gen/
            └── privacy-llm-collaboration/
```

The top-level `README.md` serves as the roadmap index. Each phase directory also includes a `README.md` summarizing the phase goal, included proposals, and why they belong together. Proposal folders themselves can retain their existing proposal documents without adding a separate `README.md`.

Alternatively, existing proposal locations may remain unchanged while introducing a `README.md`-based index:

```text
docs/
└── proposals/
    └── scenarios/
        ├── README.md
        ├── Cloud-Robotics/
        ├── example-restoration/
        ├── llm-benchmarks/
        ├── ...
```

The final structure should be discussed with maintainers.

### Phase Assignment Rationale

#### Phase 1 — Example & Benchmark Foundation

This phase groups proposals that primarily contribute reusable examples, benchmark suites, or datasets that can be adopted without major framework changes.

Included folders:

* `Cloud-Robotics/` and `Cloud_robotics/`: dataset-oriented cloud robotics proposals that provide baseline evaluation assets
* `Example_Restoration/` and `example-restoration/`: example maintenance and restoration work that improves contributor onboarding and example usability
* `Smart_Coding/`, `llm-benchmark-suite/`, and `llm-benchmarks/`: benchmark-oriented proposals that expand scenario coverage with relatively direct integration paths
* `cloud-robotics-lifelong-learning-dataset/` and `industrial-defect-detection/`: domain datasets that strengthen the evaluation foundation
* `government_affairs/`: a domain-specific benchmarking proposal that fits the initial scenario and benchmark accumulation stage
* `Industrial manufacturing/`: an applied scenario proposal that is closer to a benchmarkable example than to a framework-level capability

#### Phase 2 — Evaluation Pipeline Enhancement

This phase groups proposals that build on the Phase 1 foundation by extending evaluators, data workflows, or scenario-specific assessment pipelines.

Included folders:

* `GovDoc2Poster/`: focuses on a concrete task pipeline and evaluation flow rather than only introducing a raw benchmark asset
* `cloud-edge-collaborative-inference-for-llm/`: introduces an LLM evaluation dataset and workflow intended for collaborative inference assessment
* `data-selection-vla-finetuning-eval/`: centers on data selection and evaluation optimization, which is naturally a pipeline capability
* `industrialEI/`: introduces embodied intelligence benchmarking methods that go beyond simple dataset publication

#### Phase 3 — Framework & Architecture Evolution

This phase groups proposals that introduce broader system capabilities, cloud-edge coordination strategies, or advanced scenario orchestration that are more likely to affect framework direction.

Included folders:

* `PIPL-Compliant Cloud-Edge Collaborative Privacy-Preserving Prompt Processing Framework/` and `privacy-llm-collaboration/`: both focus on privacy-aware cloud-edge collaboration and imply architecture-level design choices
* `industrialEI-intelligent-assembly/`: moves from benchmark definition toward embodied workflow execution and scenario orchestration
* `phys-scene-gen/`: introduces simulation scene generation and interaction capabilities that are closer to future framework expansion than to a standalone benchmark

Some proposals may span multiple phases in practice. The grouping above reflects the most likely implementation sequence, starting from reusable evaluation assets, then extending evaluation workflows, and finally addressing broader framework evolution.

---

## Expected Impact

### Contributors

Benefits:

* Better understanding of implementation order
* Easier onboarding for new contributors
* Clearer project development direction

### Maintainers

Benefits:

* Easier proposal planning
* Better milestone management
* Improved mentorship project organization

### End Users

No direct impact.

---

## Impact on Existing Code

### Core Framework

No impact.

No Ianvs core modules will be modified.

### Evaluation Pipeline

No impact.

### Example Execution

No impact.

### CI Workflow

No impact.

---

## Risks

### Documentation Link Changes

If proposal files are reorganized into phase-based directories, some existing links may become invalid.

Potentially affected locations include:

* Proposal cross references
* Documentation hyperlinks
* External references
* GitHub URLs

Before merging any restructuring changes, all affected links should be reviewed and updated.

A final link verification pass should be performed to ensure documentation consistency.
