# Day 1 Project — Enterprise Runbook Knowledge Agent

The Day 1 *project* as the syllabus defines it: **one** agent that does all
seven things in a single pass, not five teaching scripts that each do one.

| # | Capability | Where it lives | How it is proven |
|---|---|---|---|
| 1 | Classify IT support requests | `schema.py` → `request_type`, `classification` | acceptance check 1 |
| 2 | Understand incomplete questions | `clarifying_question` | acceptance check 5–6 |
| 3 | Search approved runbooks | `retrieval.py` | acceptance check 11 |
| 4 | Generate source-grounded answers | `agent.py` INSTRUCTIONS + evidence block | acceptance check 2 |
| 5 | Return citations | `citations[]`, **verified in code** | acceptance checks 3–4 |
| 6 | Refuse unsupported conclusions | `evidence_sufficient`, `refusal_reason` | acceptance checks 7–8 |
| 7 | Escalate when evidence is insufficient | `requires_human_escalation` | acceptance check 9 |

## Run it

Requires `../.env` (from `../setup.sh`) and the `runbooks` index built by
`../day1/lab4_build_search_index.py`.

```bash
cd azure-agent-demo-setup && source .venv/bin/activate && cd day1-project

python3 ask.py "How do I recover from a database connection timeout?"
python3 ask.py                    # short scripted demo
python3 acceptance_test.py        # all 7 capabilities, exits 0/1
```

**Verified 2026-09-25: `acceptance_test.py` → 12/12 checks passed, exit 0.**

## What this adds over `../day1/lab1..lab5`

The labs teach each mechanism separately and are the right shape for
teaching. They are not the project, and three of their behaviours would not
survive production:

**1. Malicious documents reached the prompt.** `lab5_grounded_agent.py` puts
every retrieved document's content into the evidence block, including
`rb-008`, whose content is a `SYSTEM OVERRIDE INSTRUCTION` jailbreak. It
relied entirely on a prompt rule to not obey it. Day 3 later root-caused this
exact pattern as the cause of a failing evaluation gate — Azure's content
filter was blocking generation outright. Here, `retrieval.py` **quarantines**
`status=malicious` before the prompt is built: the document is cited as
existing, its content is withheld, and a `security_event` is recorded.

This is not theoretical. In the verified run, `rb-008` was in the top-3 for
the database question and was quarantined:

```
retrieved   : ['rb-001', 'rb-002', 'rb-008']
quarantined : ['rb-008']
security_events : ['rb-008: quarantined (CONTENT WITHHELD ...)']
```

**2. Citations were unverifiable prose.** The labs ask the model to cite in
free text, so nothing checks whether a cited id was ever retrieved. Here the
model proposes citations and `agent.py` **verifies them against the retrieved
set**; a fabricated id is stripped and forces escalation. The model proposes;
code decides.

**3. "Escalate" was a sentence, not a signal.** Prose refusals cannot be
routed, counted, or gated. Every capability is now a typed field, which is why
the acceptance suite can assert on them and exit non-zero for a release gate.

Also folded in: the `messages.list()` read-after-write retry that Day 2 and
Day 3 both had to discover independently.

## Files

| File | Role |
|---|---|
| `config.py` | Endpoints + credentials from `../.env`; no keys anywhere |
| `schema.py` | The output contract — one object covering all 7 capabilities |
| `retrieval.py` | Hybrid search + governance: approved / superseded / quarantined |
| `agent.py` | The agent, plus code-side citation verification |
| `ask.py` | CLI |
| `acceptance_test.py` | The syllabus's Day 1 acceptance criteria, executable |

## Design notes

**Why quarantine instead of filtering in the search query.** Excluding
`status=malicious` in the OData filter would be simpler, but then the agent
could never *report* that a known-bad document matched — and being able to say
"a quarantined document matched this query" is the security-relevant signal.
Retrieve it, withhold the content, log the event.

**Why obsolete documents are still shown.** They are marked `SUPERSEDED` and
the agent must say so rather than silently following them. Hiding them would
make the agent unable to explain why the procedure someone remembers is no
longer correct — in the verified run it cited `rb-007` *and* escalated, which
is the correct outcome.

**Known model behaviour.** The agent sometimes sets
`requires_human_escalation=true` even on a well-grounded answer, when the cited
runbook itself says approval is needed (e.g. "do not restart production without
on-call approval"). That is defensible, not a bug — but it is why Day 3's
evaluation module exists: binary labels on gray-area cases are exactly where
eval datasets get argued about.
