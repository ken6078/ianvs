# Phase 2: Core Benchmark Capability

## Purpose

Phase 2 focuses on reusable benchmark infrastructure for Ianvs, especially around LLM evaluation, edge-side execution, and general benchmark interfaces that can support multiple scenario domains.

## Scope

This phase groups proposals that define benchmark mechanisms rather than one-off applications. The emphasis is on dataset interfaces, evaluation metrics, benchmark execution, test environment integration, and report generation.

## Included Proposals

| Proposal | Role in This Phase | Reason |
| --- | --- | --- |
| `llm-benchmarks` | Core LLM benchmark proposal | It defines general LLM benchmark direction, dataset handling, and evaluation interfaces that can be reused across scenarios. |
| `llm-benchmark-suite` | Core edge benchmark suite | It extends benchmark execution and metrics toward edge-side LLM evaluation and is one of the main infrastructure proposals in this phase. |
| `cloud-edge-collaborative-inference-for-llm` | Cloud-edge LLM benchmark bridge | It connects reusable LLM benchmark capabilities with cloud-edge collaborative inference behavior. |
| `government_affairs` | Domain benchmark extension | It appears to build a government-domain benchmark case on top of general LLM benchmark capabilities rather than replacing the shared benchmark foundation. |
| `Smart_Coding` | Domain benchmark extension | It appears to apply the same benchmark direction to coding tasks, making it a suitable extension built on top of the phase's common LLM benchmark base. |

## Expected Deliverables

- Reusable LLM benchmark interfaces
- Dataset mapping or dataset loading mechanisms for benchmark tasks
- Test case and test environment integration for benchmark execution
- Edge-side LLM benchmark suite capabilities
- Metrics for accuracy, latency, throughput, memory, and resource usage
- Benchmark reports for maintainers and users
- Domain benchmark examples built on the shared benchmark layer

## Relationship to Other Phases

Phase 2 depends on the example reliability direction from Phase 1 because reusable benchmarks are difficult to trust without maintainable example inputs and clearer validation expectations.

Phase 2 also supports Phase 3 by providing the benchmark interfaces, execution patterns, and metrics that more advanced scenario proposals can reuse instead of redefining core infrastructure.

## Notes and Constraints

`llm-benchmarks` and `llm-benchmark-suite` are treated as the core proposals of this phase. The other included proposals are classified here because they look like extensions of the benchmark foundation rather than purely standalone applications.

Where proposal intent is partially ambiguous, the classification is based on folder names and the apparent scenario direction of the existing documents.
