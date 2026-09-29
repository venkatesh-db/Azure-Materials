# IncidentOps AI — Complete Execution Runbook

**Module 5 · Production Capstone · Payment Platform Incident Response Agent**

Verified on: 2026-09-29 · Python 3.14.4 · macOS Darwin 23.5.0

---

## What This Project Does

A production-grade multi-agent AI system that autonomously handles payment platform incidents. When a payment service reports 12,000 TPS incoming vs 4,000 TPS bank capacity, P95 latency rising from 500ms → 3s, 20% timeout rate, DB pool saturation, Redis pressure, retry amplification, and duplicate Kafka events — this agent:

1. **Classifies** the incident (Triage Agent → category, severity, affected service)
2. **Retrieves** approved runbooks from vector search and **cites** them with `supporting_doc_ids`
3. **Queries** service health via Azure Function tools
4. **Diagnoses** root cause with confidence scoring
5. **Identifies** missing evidence → escalates if confidence is low
6. **Ranks** possible causes and recommends safe actions
7. **Handles tool timeouts** without crashing the workflow (exception → ESCALATED, not crash)
8. **Requests human approval** then creates an incident ticket
9. **Prevents duplicate actions** via idempotency key in SQLite
10. **Generates a tamper-evident audit trail** (SHA-256 hash chain) and complete trace

---

## Project Architecture

```
incidentops-ai/
├── src/incidentops/
│   ├── models.py          # Domain types + WorkflowState state machine (11 states)
│   ├── orchestrator.py    # Multi-agent pipeline: Triage → Diagnosis → Remediation → Execute
│   ├── db.py              # SQLite-backed IncidentRepository + approval tokens + idempotency
│   ├── audit.py           # Append-only SHA-256 hash-chained audit log
│   ├── executor.py        # Action execution (StubActionExecutor | AzureFunctionActionExecutor)
│   ├── retrieval.py       # RAG retriever (StubRetriever | AzureSearchRetriever)
│   ├── queue.py           # Kafka-style dedup queue (prevents duplicate events)
│   ├── ingestion.py       # Markdown runbook ingestion with YAML frontmatter + ACL
│   ├── tenancy.py         # Multi-tenant service registry with cross-tenant isolation
│   ├── cost.py            # Per-tenant LLM budget guard + model routing by severity
│   ├── approval_server.py # HTTP approval server (POST /approve)
│   ├── secrets.py         # Azure Key Vault secret manager
│   └── agents/
│       ├── base.py        # AgentSuite Protocol (interface contract)
│       ├── stub.py        # Deterministic test doubles — no LLM calls, no network
│       └── azure.py       # Real Azure Foundry agents (needs live subscription)
├── tests/                 # 44 pytest tests, 80% coverage, all pure-local
├── demo.py                # Full pipeline, stub agents, NO Azure needed ← START HERE
├── demo_live.py           # Full pipeline, real Foundry + real Function App
├── eval.py                # Evaluation harness (9/9 state, 3/3 grounding)
├── check_gate.py          # Release gate (CI gate, exits non-zero on failure)
├── attack_test_live.py    # Security: 5 adversarial attacks, all safely rejected
├── load_test.py           # Throughput/latency against deployed Function App
└── deploy.py              # Canary deploy + smoke test + rollback
```

### State Machine

```
RECEIVED → TRIAGED → DIAGNOSED → ACTION_PROPOSED → AWAITING_APPROVAL → APPROVED → EXECUTING → COMMUNICATED → COMPLETED
    ↘          ↘          ↘               ↘                  ↘                                      ↘
 ESCALATED  ESCALATED  ESCALATED       ESCALATED           FAILED → ESCALATED               FAILED
```

---

## Part A — Local Demo (No Azure, No Cost, ~3 Minutes)

### A1. Environment Setup

```bash
cd /Users/venkatesh/WorldBank/incidentops-ai
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### A2. Run the Full Demo

```bash
python3 demo.py
```

**Real output (verified 2026-09-29):**

```
======================================================================
Scenario 1: confident diagnosis -> proposes action -> awaits approval
  correlation_id: c14c1d32-66ac-4c2d-90a9-b42d4b181020
  state: AWAITING_APPROVAL
  triage: TriageResult(category='database', affected_service='payment-service',
          severity='SEV-2', evidence=('payment-service latency spike, pool saturation suspected',))
  diagnosis: DiagnosisResult(
          root_cause_hypothesis='See Payment Service Runbook: If payment-service reports
          elevated latency, check database connection pool saturation. Recommended action:
          check for long-running transactions holding connections.',
          supporting_doc_ids=('rb-001',), confidence='high')
  remediation proposed: RemediationProposal(action='restart_service',
          scope='restart:payment-service:production', ...)

  Rejecting execution with a fake approval token...
  Correctly rejected: Approval rejected: token_not_found

  Issuing a REAL approval token and executing...
  Final state: COMPLETED
  Communication drafted: Diagnosis: See Payment Service Runbook: If payment-service
  reports elevated latency, check database connection pool saturation. (confidence=high).
  Proposed action: restart_service (...)

  Trying to execute AGAIN (idempotency/state guard)...
  Correctly rejected: Incident c14c1d32-... is not awaiting approval (state=WorkflowState.COMPLETED)

======================================================================
Scenario 2: vague/low-confidence request -> escalates, no action proposed
  state: ESCALATED
  remediation: RemediationProposal(action='escalate_to_human',
               scope='escalation:unspecified',
               justification='Confidence too low to propose an automated action')

======================================================================
Scenario 3: process-restart durability check
  Reloading incident c14c1d32... from a FRESH repository instance
  State survived restart: COMPLETED (matches: True)
```

**What this proves:**
- ✅ Triage → Diagnosis → Remediation pipeline working
- ✅ Runbook retrieved and cited (`supporting_doc_ids=('rb-001',)`)
- ✅ Fake approval token correctly rejected (`token_not_found`)
- ✅ Real approval token issued and consumed
- ✅ Idempotency guard blocks double-execution
- ✅ Low-confidence incident escalates instead of proposing action
- ✅ State persists across process restart (SQLite durability)

---

## Part B — Test Suite

```bash
python3 -m pytest tests/ -v --cov=incidentops --cov-report=term-missing
```

**Real output (verified 2026-09-29):**

```
============================= test session starts ==============================
platform darwin -- Python 3.14.4, pytest-9.1.1
collected 44 items

tests/test_approval_server.py::test_approve_pending_incident_issues_a_real_token PASSED
tests/test_approval_server.py::test_approve_nonexistent_incident_returns_404 PASSED
tests/test_approval_server.py::test_approve_incident_not_awaiting_approval_returns_409 PASSED
tests/test_audit.py::test_record_and_retrieve_history PASSED
tests/test_audit.py::test_chain_is_valid_after_normal_writes PASSED
tests/test_audit.py::test_tampering_with_a_past_entry_breaks_chain_verification PASSED
tests/test_audit.py::test_empty_log_is_valid PASSED
tests/test_cost.py::test_records_usage_and_allows_calls_under_budget PASSED
tests/test_cost.py::test_raises_when_budget_exceeded PASSED
tests/test_cost.py::test_unknown_tenant_raises PASSED
tests/test_cost.py::test_model_routing_by_severity PASSED
tests/test_db.py::test_save_and_load_round_trip PASSED
tests/test_db.py::test_load_missing_incident_returns_none PASSED
tests/test_db.py::test_valid_transition_persists PASSED
tests/test_db.py::test_invalid_transition_raises_and_does_not_persist PASSED
tests/test_db.py::test_survives_a_fresh_repository_instance PASSED
tests/test_db.py::test_idempotency_store_prevents_duplicate_action PASSED
tests/test_db.py::test_approval_token_single_use PASSED
tests/test_db.py::test_approval_token_scope_mismatch_rejected PASSED
tests/test_executor.py::test_restart_service_action_is_recorded PASSED
tests/test_executor.py::test_duplicate_idempotency_key_returns_cached_result_without_re_executing PASSED
tests/test_executor.py::test_unsupported_action_raises PASSED
tests/test_ingestion.py::test_load_markdown_directory_parses_frontmatter PASSED
tests/test_ingestion.py::test_document_with_no_tenants_field_is_visible_to_everyone PASSED
tests/test_ingestion.py::test_filter_by_tenant_access_enforces_acl PASSED
tests/test_ingestion.py::test_flag_stale_documents PASSED
tests/test_orchestrator.py::test_confident_diagnosis_reaches_awaiting_approval PASSED
tests/test_orchestrator.py::test_low_confidence_diagnosis_escalates_instead_of_proposing_action PASSED
tests/test_orchestrator.py::test_approve_and_execute_reaches_completed PASSED
tests/test_orchestrator.py::test_execution_failure_transitions_to_failed PASSED
tests/test_orchestrator.py::test_approve_and_execute_rejects_invalid_token PASSED
tests/test_orchestrator.py::test_duplicate_execution_is_prevented_by_idempotency_key PASSED
tests/test_orchestrator_resilience.py::test_agent_failure_escalates_instead_of_raising PASSED
tests/test_orchestrator_resilience.py::test_escalate_to_human_action_routes_to_escalated_even_with_medium_confidence PASSED
tests/test_queue.py::test_publish_and_consume PASSED
tests/test_queue.py::test_duplicate_kafka_style_redelivery_is_a_no_op PASSED
tests/test_retrieval.py::test_retrieves_relevant_document PASSED
tests/test_retrieval.py::test_malicious_document_is_excluded_from_results PASSED
tests/test_retrieval.py::test_no_relevant_document_returns_empty PASSED
tests/test_tenancy.py::test_service_lookup PASSED
tests/test_tenancy.py::test_unknown_service_returns_none PASSED
tests/test_tenancy.py::test_services_scoped_to_tenant PASSED
tests/test_tenancy.py::test_cross_tenant_ownership_check_blocks_wrong_tenant PASSED
tests/test_tenancy.py::test_cannot_register_service_for_unknown_tenant PASSED

============================== 44 passed in 1.86s ==============================

Coverage: 80% total
  models.py        100%   orchestrator.py  97%   db.py            97%
  audit.py         98%    cost.py          100%  tenancy.py       100%
  agents/stub.py   100%   agents/base.py   100%
```

---

## Part C — Release Gate (CI)

```bash
python3 check_gate.py
```

**Real output:**

```
State correctness: 100% (threshold: >=90%)
Grounding correctness: 100% (threshold: >=100%)

RELEASE GATE PASSED.
```

This reads `eval_results.json` (pre-run against real Azure in a previous session) and enforces:
- State correctness ≥ 90% (9/9 = 100%)
- Grounding correctness = 100% (zero tolerance for hallucinated citations)

---

## Part D — Audit Trail Demo

```bash
python3 -c "
import sys; sys.path.insert(0, 'src')
from incidentops.audit import AuditLog
audit = AuditLog(db_path='incidentops_audit_demo.db')
audit.record('corr-1', 'incident_received', {'raw_request': 'payment latency spike'})
audit.record('corr-1', 'triaged', {'category': 'database', 'severity': 'SEV-2'})
audit.record('corr-1', 'diagnosed', {'confidence': 'high', 'doc_ids': ['rb-001']})
audit.record('corr-1', 'approved', {'token_scope': 'restart:payment-service:production'})
audit.record('corr-1', 'completed', {'action': 'restart_service'})
import json
for e in audit.history_for('corr-1'):
    print(f\"  [{e['event_type']}] {e['detail']}\")
valid, reason = audit.verify_chain()
print(f'Chain valid: {valid} ({reason})')
"
```

Expected output:
```
  [incident_received] {'raw_request': 'payment latency spike'}
  [triaged] {'category': 'database', 'severity': 'SEV-2'}
  [diagnosed] {'confidence': 'high', 'doc_ids': ['rb-001']}
  [approved] {'token_scope': 'restart:payment-service:production'}
  [completed] {'action': 'restart_service'}
Chain valid: True (ok)
```

---

## Part E — Human Approval HTTP Server

In terminal 1:

```bash
python3 -c "
import sys; sys.path.insert(0, 'src')
from incidentops.db import IncidentRepository
from incidentops.approval_server import run_approval_server
repo = IncidentRepository(db_path='incidentops_manual_test.db')
server = run_approval_server(repo, port=8765)
print('Approval server: http://127.0.0.1:8765')
server.serve_forever()
"
```

In terminal 2:

```bash
curl -X POST http://127.0.0.1:8765/approve \
  -H 'Content-Type: application/json' \
  -d '{"correlation_id": "<your-id>", "scope": "restart:payment-service:production"}'
```

---

## Part F — Go Live with Azure (Needs Subscription, ~$2.50/day)

### F1. Sign in

```bash
az login
az account show --query "{user:user.name, subscription:name}" -o table
```

### F2. Provision Azure Resources

```bash
cd /Users/venkatesh/WorldBank/azure-agent-demo-setup
./setup.sh
```

Provisions: Azure Foundry (`gpt-5-mini` + `text-embedding-3-small`), AI Search, Storage, App Insights, Function App. Takes 5–10 minutes.

**Known issue:** Azure AI Search sometimes returns `InsufficientResourcesAvailable` in `eastus2`. If that happens:

```bash
az search service create --name srch-agent-demo-$RANDOM \
  --resource-group rg-ai-agent-demo --location eastus \
  --sku Basic --partition-count 1 --replica-count 1 \
  --auth-options aadOrApiKey --aad-auth-failure-mode http401WithBearerChallenge
```

### F3. Populate the RAG Search Index

```bash
cd /Users/venkatesh/WorldBank/azure-agent-demo-setup/day1
source ../.venv/bin/activate
python3 lab4_build_search_index.py
# Expect: Indexed 8/8 documents.
```

### F4. Deploy the Function App

```bash
cd /Users/venkatesh/WorldBank/incidentops-ai/src  # check path from azure-agent-demo-setup/.env
func azure functionapp publish <FUNCTION_APP_NAME> --python
```

Get the function app name:
```bash
grep FUNCTION_APP_NAME /Users/venkatesh/WorldBank/azure-agent-demo-setup/.env
```

### F5. Get the Function Key

```bash
FKEY=$(az functionapp keys list -g rg-ai-agent-demo -n <FUNCTION_APP_NAME> \
  --query "functionKeys.default" -o tsv)
echo "FUNCTION_KEY=$FKEY" >> /Users/venkatesh/WorldBank/azure-agent-demo-setup/.env
```

### F6. Run the Live Demo

```bash
cd /Users/venkatesh/WorldBank/incidentops-ai
source .venv/bin/activate
python3 demo_live.py
```

Expected output:
```
LIVE Scenario 1: confident case -> propose -> approve -> execute -> communicate
  state: AWAITING_APPROVAL
  diagnosis: ...confidence='high', supporting_doc_ids=('rb-001', 'rb-002', 'rb-006')
  Final state: COMPLETED

LIVE Scenario 2: vague request -> should escalate, not propose an action
  state: ESCALATED
  diagnosis: ...confidence='low', supporting_doc_ids=()
```

### F7. Run Evaluation Against Live Azure

```bash
rm -f incidentops_eval.db eval_results.json
python3 eval.py
# State correctness: 9/9 = 100%, Grounding correctness: 3/3 = 100%
```

### F8. Security Attack Simulation

```bash
python3 attack_test_live.py
```

5 attacks tested:
1. False authority injection
2. False urgency escalation
3. Fabricated confidence score
4. Malicious document surfacing (rb-008 must never be cited)
5. Prompt injection via incident request

All 5 must end in `ESCALATED` or safe rejection. Expected:
```
OK: no malicious document text found in output
OK: rb-008 not cited
```

### F9. Load Test Against Function App

```bash
python3 load_test.py \
  --function-app-name <FUNCTION_APP_NAME> \
  --function-key "<FUNCTION_KEY>" \
  --total-requests 50 \
  --concurrency 10
```

Expected: all 403s (correct — no approval token sent), 0 unexpected errors, honest throughput/latency report.

---

## Part G — Tear Down (Stop Billing)

```bash
cd /Users/venkatesh/WorldBank/azure-agent-demo-setup
./teardown.sh
# Type: rg-ai-agent-demo

az group exists --name rg-ai-agent-demo   # should print: false
```

---

## How Each Module 5 Requirement Is Satisfied

| # | Requirement | Implementation | File |
|---|---|---|---|
| 9 | Classify the incident | `agents.triage()` → `TriageResult(category, severity, affected_service)` | `agents/stub.py`, `agents/azure.py` |
| 10 | Retrieve approved runbooks and cite them | `Retriever.retrieve()` → `supporting_doc_ids` tuple in `DiagnosisResult` | `retrieval.py` |
| 11 | Query service health + search previous incidents | Azure Function tools in `AzureFunctionActionExecutor` | `executor.py`, `agents/azure.py` |
| 12 | Identify missing evidence | Low-confidence diagnosis → `escalate_to_human` remediation → `ESCALATED` state | `orchestrator.py:70` |
| 13 | Rank possible causes | Diagnosis agent returns `root_cause_hypothesis` + `confidence` | `models.py`, `agents/azure.py` |
| 14 | Recommend safe actions | `RemediationProposal(action, scope, justification)` | `models.py` |
| 15 | Handle tool timeout without failing | `try/except Exception` in `handle_new_incident()` → `ESCALATED` not crash | `orchestrator.py:34-62` |
| 16 | Request approval → create ticket | `repo.issue_approval()` + `approve_and_execute()` + approval HTTP server | `db.py`, `approval_server.py` |
| 17 | Prevent duplicate actions | Idempotency key `execute:<correlation_id>` checked before execution | `orchestrator.py:93`, `db.py` |
| 18 | Audit trail + complete trace | SHA-256 hash-chained append-only `AuditLog` | `audit.py` |

---

## Quick Reference

| Command | What it does |
|---|---|
| `python3 demo.py` | Full pipeline, stub agents, zero Azure |
| `python3 -m pytest tests/ -v` | 44 tests, ~2 seconds |
| `python3 check_gate.py` | Release gate — CI equivalent |
| `python3 demo_live.py` | Real Foundry + Function App |
| `python3 eval.py` | Structured eval: state + grounding correctness |
| `python3 attack_test_live.py` | 5 adversarial security attacks |
| `python3 load_test.py ...` | Throughput/latency test |
| `python3 deploy.py` | Canary deploy + smoke test + rollback |
