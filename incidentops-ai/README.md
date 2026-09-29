# IncidentOps AI — Phase 1

Production evolution of the 3-day course demo (`azure-agent-demo-setup/`),
scoped to **Feature 1 (real persistence)** and **Feature 4 (multi-agent
orchestration)** from `IncidentOps-AI-features.md`. Built and tested
locally — no Azure resources required or deployed in this phase.

## What's real here

| Layer | Old (course demo) | New (this phase) |
|---|---|---|
| State persistence | JSON files (`workflow_state.json`) | SQLite (`db.py`, repository pattern) — survives process restart, verified by test |
| Approval tokens | JSON file (`approval_tokens.json`) | Same SQLite DB, same single-use/scope/expiry checks |
| Idempotency | In-memory dict | SQLite table, survives restart |
| Agent structure | 1 agent does everything | 4 specialists behind one `AgentSuite` interface: Triage → Diagnosis → Remediation → Communication |

## What's intentionally stubbed

`agents/stub.py` implements `AgentSuite` with deterministic, hardcoded
logic — **no LLM calls, no Azure, no network**. This is not a placeholder
to be embarrassed about; it's the point: `orchestrator.py` is fully tested
(13 tests, 98% coverage) without needing a live Foundry deployment.

To wire in real agents later:
1. Write `agents/azure.py` implementing `AgentSuite` (see `agents/base.py`),
   reusing the exact `AgentsClient` patterns from `day1/lab5_grounded_agent.py`
   and `day2/lab7_read_only_tools.py` — one method per specialist, each
   making a real `create_agent` → `threads.create` → `runs.create_and_process`
   call.
2. Change one line in whatever wires up the `Orchestrator`:
   `Orchestrator(repo=repo, agents=AzureAgentSuite(...))` instead of
   `StubAgentSuite()`.
3. `orchestrator.py` and `db.py` need **zero changes** — that's the payoff
   of the `Protocol`-based seam.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install pytest pytest-cov
python3 -m pytest tests/ -v --cov=incidentops    # 13 tests, 98% coverage
python3 demo.py                                   # end-to-end scenario walkthrough
```

## A real bug this TDD process caught

Writing tests first caught a genuine state-sync bug before it ever ran:
the orchestrator's local `Incident` object wasn't updated after calling
`repo.transition()`, so a later `repo.save(incident)` call was silently
overwriting the database's correct state with a stale in-memory value.
`test_confident_diagnosis_reaches_awaiting_approval` failed on first run
with `InvalidTransitionError: RECEIVED -> DIAGNOSED is not a valid
transition` — the state machine correctly refused an impossible jump
caused by that bug. Fixed in `orchestrator.py` by syncing
`incident.state` locally right after every `repo.transition()` call. See
the code comments at each fix site.

## Not built in this phase

Everything else in `IncidentOps-AI-features.md` (real event queue, real
approval UI, multi-tenancy, security hardening, continuous evaluation,
cost governance, compliance, real deployment automation, load testing) —
deliberately out of scope for Phase 1. Pick the next category when ready.
