# IncidentOps AI — Step-by-Step Execution Guide

Every command below was actually run this session and the output shown
is real (not illustrative). Follow in order.

---

## Part A — Local only (no Azure, no cost, ~2 minutes)

Proves the orchestration logic works using `StubAgentSuite` — no
credentials needed.

### A1. Set up the Python environment

```bash
cd incidentops-ai
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### A2. Run the full test suite

```bash
python3 -m pytest tests/ -v --cov=incidentops --cov-report=term-missing
```

Expect: **44 passed**, ~80% coverage. This covers all 15 feature
categories (persistence, orchestration, executor, retrieval, tenancy,
queue, ingestion, cost, audit, approval server) — all pure-local, no
network calls.

### A3. Run the local end-to-end demo

```bash
python3 demo.py
```

Expect 3 scenarios printed: a confident diagnosis reaching
`AWAITING_APPROVAL` → approved → `COMPLETED`; a vague request escalating
without proposing an action; and a process-restart durability check
(state survives a fresh `IncidentRepository` instance pointed at the same
DB file).

**Stop here if you just want to see the architecture work.** Everything
below needs a live Azure subscription and will incur small charges
(~$2.50/day, mainly Azure AI Search).

---

## Part B — Go live (real Azure Foundry agents + real Function App)

### B1. Sign in

```bash
az login
```

Confirm you're on the right account:

```bash
az account show --query "{user:user.name, subscription:name}" -o table
```

### B2. Provision Azure resources

This project reuses `azure-agent-demo-setup`'s provisioning script — it
builds Foundry (+ `gpt-5-mini` + `text-embedding-3-small` deployments),
Azure AI Search, Storage, App Insights, and a Function App.

```bash
cd ../azure-agent-demo-setup
./setup.sh
```

Takes 5–10 minutes. **Known issue, low but real probability**: Azure AI
Search sometimes returns `InsufficientResourcesAvailable` in `eastus2`.
If that happens, create Search manually in `eastus` instead:

```bash
az search service create --name srch-agent-demo-$RANDOM \
  --resource-group rg-ai-agent-demo --location eastus \
  --sku Basic --partition-count 1 --replica-count 1 \
  --auth-options aadOrApiKey --aad-auth-failure-mode http401WithBearerChallenge
```

then re-run the rest of `setup.sh`'s remaining steps manually (Storage,
App Insights, Function App, RBAC, `.env` generation) — see
`azure-agent-demo-setup/SETUP_LOG.md` for the exact commands used when
this happened live.

### B3. Populate the RAG search index

A fresh Search service starts **empty** — the Diagnosis agent has nothing
to retrieve until you build the index:

```bash
cd ../azure-agent-demo-setup/day1
source ../.venv/bin/activate
python3 lab4_build_search_index.py
```

Expect: `Indexed 8/8 documents.`

### B4. Deploy the Function App code

A fresh Function App also starts **empty** — the executor has nothing to
call until you publish the code:

```bash
cd ../day2/azure_function
func azure functionapp publish <your-function-app-name> --python
```

(Get `<your-function-app-name>` from `azure-agent-demo-setup/.env`'s
`FUNCTION_APP_NAME`.) Not sure if `func` CLI is installed:

```bash
func --version   # if missing:
brew tap azure/functions && brew install azure-functions-core-tools@4
# if brew refuses the tap as "untrusted": brew trust --tap azure/functions
```

### B5. Get the Function key and add it to `.env`

```bash
FKEY=$(az functionapp keys list -g rg-ai-agent-demo -n <your-function-app-name> \
  --query "functionKeys.default" -o tsv)
echo "FUNCTION_KEY=$FKEY" >> ../../.env
```

### B6. Install incidentops-ai's own dependencies (into the same venv or a fresh one)

```bash
cd ../../../incidentops-ai
source .venv/bin/activate
pip install -r requirements.txt
pip install azure-search-documents openai requests   # if not already present
```

### B7. Run the live end-to-end demo

```bash
python3 demo_live.py
```

Real output you should see (this exact shape, wording will vary):

```
LIVE Scenario 1: confident case -> propose -> approve -> execute -> communicate
  state: AWAITING_APPROVAL
  diagnosis: ...confidence='high', supporting_doc_ids=('rb-001', 'rb-002', 'rb-006')
  Final state: COMPLETED

LIVE Scenario 2: vague request -> should escalate, not propose an action
  state: ESCALATED
  diagnosis: ...confidence='low', supporting_doc_ids=()
```

If Scenario 2 does NOT escalate (goes to `AWAITING_APPROVAL` instead),
see `ROADMAP.md`'s Feature 7 section — this was a real regression found
and fixed once already; if it recurs, the fix is in
`src/incidentops/agents/azure.py`'s `diagnose()` instructions.

---

## Part C — Verification suite (proves it, doesn't just run it)

### C1. Run the evaluation harness

```bash
rm -f incidentops_eval.db eval_results.json
python3 eval.py
```

Expect: `State correctness: 9/9 = 100%`, `Grounding correctness: 3/3 = 100%`.

### C2. Check the release gate

```bash
python3 check_gate.py
```

Expect: `RELEASE GATE PASSED.` (exits 0). This is the same script CI runs.

### C3. Run the security attack simulation

```bash
python3 attack_test_live.py
```

5 attacks run (false authority, false urgency, fabricated confidence,
malicious-document surfacing, prompt injection). Expect every one to end
in `ESCALATED` or a safely-rejected exception, `OK: no malicious document
text found in output` and `OK: rb-008 not cited` on every line.

### C4. Run a real load test against the deployed Function App

```bash
python3 load_test.py --function-app-name <your-function-app-name> \
  --function-key "<the FUNCTION_KEY from your .env>" \
  --total-requests 50 --concurrency 10
```

Expect all 403s (no approval token sent — that's the correct response),
0 unexpected errors, and an honest throughput/latency report.

---

## Part D — Optional extras

### D1. Try the human-approval HTTP server

```bash
python3 -c "
import sys; sys.path.insert(0, 'src')
from incidentops.db import IncidentRepository
from incidentops.approval_server import run_approval_server
repo = IncidentRepository(db_path='incidentops_manual_test.db')
server = run_approval_server(repo, port=8765)
print('Approval server running on http://127.0.0.1:8765')
server.serve_forever()
"
```

In another terminal, `POST /approve` with `{"correlation_id": "...", "scope": "..."}`.

### D2. Verify the audit log's tamper-detection

```bash
python3 -c "
import sys; sys.path.insert(0, 'src')
from incidentops.audit import AuditLog
audit = AuditLog(db_path='incidentops_audit_demo.db')
audit.record('corr-1', 'incident_received', {'raw_request': 'test'})
audit.record('corr-1', 'triaged', {'category': 'database'})
print(audit.history_for('corr-1'))
print('Chain valid:', audit.verify_chain())
"
```

---

## Part E — Tear down (stop billing)

```bash
cd ../azure-agent-demo-setup
./teardown.sh
```

Type `rg-ai-agent-demo` to confirm. Deletes everything in that resource
group. Verify it's actually gone:

```bash
az group exists --name rg-ai-agent-demo   # should print: false
```

---

## Quick reference — what each file does

| File | Run it to see... |
|---|---|
| `demo.py` | Full pipeline, local stub agents, no Azure |
| `demo_live.py` | Full pipeline, real Foundry agents + real Function App |
| `eval.py` + `check_gate.py` | Automated correctness/grounding scoring + pass/fail gate |
| `attack_test_live.py` | Security resistance against 5 live adversarial inputs |
| `load_test.py` | Real throughput/latency numbers against the deployed endpoint |
| `deploy.py` | Canary-style deploy + smoke test + rollback for the Function App |
| `.github/workflows/ci.yml` | What runs automatically on every push to GitHub |
