# Lab 5 — Evaluate retrieval and validate the Day 1 agent (70 min)

Day 1 · Module 4 · Project 1

Ten starter cases are provided in [`eval_cases.json`](eval_cases.json), one per syllabus category: correct runbook, multiple relevant documents, no relevant document, obsolete document, incorrect service name, conflicting instructions, restricted document, malicious document, ambiguous question, and unsupported diagnosis.
Participants extend the set in [`extended_cases.json`](extended_cases.json), which has 4 examples.

```bash
python lab05_retrieval_evaluation/evaluate.py                      # live
python lab05_retrieval_evaluation/evaluate.py --mock --include-extended
```

Output: `reports/day1_evaluation_report.md` and `.json`.

| Metric | Definition (in `agentcore/evaluation.py`) | Day 1 target |
|---|---|---|
| Retrieval relevance | share of expected documents present in the evidence set | ≥85% |
| Grounded-response rate | answered cases where every step cites supplied evidence and is lexically supported by it | ≥90% |
| Citation correctness | share of citations in the case's acceptable set | ≥90% |
| Unsupported-claim rate | share of delivered steps failing the grounding check | ≤5% |
| No-answer correctness | cases that must not be answered (refuse/clarify/escalate) that were handled correctly | ≥85% |

Case format: `expected_status` (allowed statuses), `expected_docs` (for retrieval relevance), `acceptable_citations`, `forbidden_docs` (must never be cited: obsolete, malicious, restricted), `expect_escalation`, and optional `user_groups`.

**Deliverables:** the retrieval dataset (`eval_cases.json`, `extended_cases.json`) and the evaluation report.
