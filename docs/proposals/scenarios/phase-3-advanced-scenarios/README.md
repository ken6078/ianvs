# Phase 3: Advanced Scenarios and Vertical Applications

## Purpose

Phase 3 extends Ianvs planning into advanced, vertical, and application-specific scenarios that benefit from the maintainability baseline in Phase 1 and the reusable benchmark capabilities in Phase 2.

## Scope

This phase groups proposals that are more application-oriented, scenario-specific, or research-oriented. These proposals often require stable benchmark execution, clearer dataset handling, and mature evaluation metrics from earlier phases.

## Included Proposals

| Proposal | Role in This Phase | Reason |
| --- | --- | --- |
| `Cloud-Robotics` | Advanced robotics scenario | It represents a robotics-oriented cloud-edge scenario that is more specialized than the shared benchmark foundation. |
| `Cloud_robotics` | Related robotics scenario | It appears to cover a similar robotics direction and should be reviewed together with `Cloud-Robotics` for overlap or consolidation. |
| `cloud-robotics-lifelong-learning-dataset` | Robotics dataset scenario | It adds dataset-centered evaluation work for cloud robotics and lifelong learning use cases. |
| `data-selection-vla-finetuning-eval` | VLA evaluation scenario | It focuses on more advanced fine-tuning and evaluation workflows for VLA-related tasks. |
| `phys-scene-gen` | Physical scene generation scenario | It represents a specialized generation and evaluation scenario that goes beyond core benchmark infrastructure. |
| `Industrial manufacturing` | Industrial vertical scenario | It applies Ianvs concepts to a manufacturing-focused scenario with vertical workflow requirements. |
| `industrial-defect-detection` | Industrial vision benchmark | It provides a concrete industrial inspection scenario that is more application-specific than a generic benchmark layer. |
| `industrialEI` | Industrial edge intelligence scenario | It extends Ianvs toward industrial edge intelligence use cases. |
| `industrialEI-intelligent-assembly` | Industrial assembly scenario | It narrows the industrial direction into a more specific assembly-oriented application scenario. |
| `GovDoc2Poster` | Government GenAI application | It represents a concrete application workflow rather than a shared benchmark interface. |
| `privacy-llm-collaboration` | Privacy-preserving LLM scenario | It adds privacy-aware collaboration requirements that depend on stronger benchmark and validation foundations. |
| `PIPL-Compliant Cloud-Edge Collaborative Privacy-Preserving Prompt Processing Framework` | Compliance and privacy scenario | It extends privacy-preserving cloud-edge collaboration toward compliance-aware workflow design. |

## Expected Deliverables

- Robotics and cloud-robotics benchmark planning
- Lifelong learning dataset evaluation direction for robotics scenarios
- Industrial intelligence and defect detection benchmark planning
- Privacy-preserving cloud-edge LLM collaboration workflows
- VLA fine-tuning and evaluation workflow planning
- Physical scene generation benchmark scenarios
- Government document generation application planning
- Clear dependency mapping back to the maintainability and benchmark capabilities established in earlier phases

## Relationship to Other Phases

Phase 3 depends on Phase 1 for more reliable example and maintenance practices, and on Phase 2 for reusable benchmark interfaces, metrics, and execution workflows.

The proposals in this phase are the most likely to diverge in datasets, objectives, and evaluation logic, so they benefit from not having to solve maintainability and benchmark infrastructure from scratch.

## Notes and Constraints

Several proposal names suggest overlapping directions, especially `Cloud-Robotics` and `Cloud_robotics`, as well as the broader `industrialEI` and the more specific `industrialEI-intelligent-assembly`. Those overlaps should be reviewed during planning rather than assumed to be fully distinct.

Where a proposal name is broad or partially ambiguous, the classification is based on the folder name and the apparent scenario direction of the existing proposal document.
