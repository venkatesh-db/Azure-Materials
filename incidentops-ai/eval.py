"""Evaluation harness for IncidentOps AI's actual orchestrator.

Unlike azure-agent-demo-setup/day3/lab2_evaluation.py's LLM-as-judge
pattern, this uses DETERMINISTIC STRUCTURAL CHECKS where possible: "did
the diagnosis cite a document that was actually in the retrieved
evidence set" is a factual, checkable fact, not a subjective judgment —
so it doesn't need a second LLM call to verify. This makes the gate
faster, cheaper, and more rigorous than LLM-as-judge for this specific
system. State-correctness (AWAITING_APPROVAL vs ESCALATED) is likewise a
direct comparison against Incident.state, not an opinion.

Runs the REAL orchestrator against REAL Azure agents/retrieval — the
executor is stubbed (nothing should actually execute during evaluation).
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "src")

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential

load_dotenv(Path(__file__).parent.parent / "azure-agent-demo-setup" / ".env")

from incidentops.agents.azure import AzureAgentSuite
from incidentops.db import IncidentRepository
from incidentops.executor import StubActionExecutor
from incidentops.orchestrator import Orchestrator
from incidentops.retrieval import AzureSearchRetriever

EVAL_DATASET_PATH = Path(__file__).parent / "eval_dataset.json"
RESULTS_PATH = Path(__file__).parent / "eval_results.json"


def build_orchestrator():
    endpoint = os.environ["FOUNDRY_ENDPOINT"]
    model = os.environ["MODEL_DEPLOYMENT_NAME"]
    embedding_model = os.environ["EMBEDDING_DEPLOYMENT_NAME"]
    search_endpoint = os.environ["SEARCH_ENDPOINT"]
    credential = DefaultAzureCredential()

    sys.path.insert(0, str(Path(__file__).parent.parent / "azure-agent-demo-setup" / "day1"))
    import config as day1_config  # noqa: E402

    repo = IncidentRepository(db_path="incidentops_eval.db")
    agents = AzureAgentSuite(endpoint=endpoint, model_deployment_name=model, credential=credential)
    retriever = AzureSearchRetriever(
        search_endpoint=search_endpoint, index_name=day1_config.SEARCH_INDEX_NAME,
        credential=credential, embedding_client=day1_config.get_embedding_client(),
        embedding_model=embedding_model,
    )
    orchestrator = Orchestrator(repo=repo, agents=agents, executor=StubActionExecutor(), retriever=retriever)
    return orchestrator, retriever


def main():
    orchestrator, retriever = build_orchestrator()
    cases = json.loads(EVAL_DATASET_PATH.read_text())
    results = []

    for case in cases:
        print(f"[{case['id']}] {case['category']}: ", end="", flush=True)
        try:
            incident = orchestrator.handle_new_incident(case["raw_request"])
        except Exception as exc:
            results.append({**case, "actual_state": None, "state_correct": False,
                              "grounding_correct": None, "error": str(exc)})
            print(f"ERROR: {exc}")
            continue

        actual_state = incident.state.value
        state_correct = actual_state == case["expect_state"]

        grounding_correct = None
        if case["expect_grounded"] and actual_state == "AWAITING_APPROVAL":
            # Deterministic check: every cited doc ID must actually be one
            # of the documents retrieved for this query. Catches
            # hallucinated citations that an LLM judge might miss or
            # rubber-stamp.
            retrieved = retriever.retrieve(case["raw_request"])
            retrieved_ids = {d.id for d in retrieved}
            cited_ids = set(incident.diagnosis.supporting_doc_ids)
            grounding_correct = len(cited_ids) > 0 and cited_ids.issubset(retrieved_ids)

        results.append({
            **case, "actual_state": actual_state, "state_correct": state_correct,
            "grounding_correct": grounding_correct,
            "supporting_doc_ids": list(incident.diagnosis.supporting_doc_ids) if incident.diagnosis else [],
        })
        print(f"state={actual_state} (expected {case['expect_state']}) "
              f"{'OK' if state_correct else 'MISMATCH'}"
              + (f", grounded={grounding_correct}" if grounding_correct is not None else ""))

    RESULTS_PATH.write_text(json.dumps(results, indent=2))

    total = len(results)
    state_correct_count = sum(1 for r in results if r["state_correct"])
    grounding_applicable = [r for r in results if r["grounding_correct"] is not None]
    grounding_correct_count = sum(1 for r in grounding_applicable if r["grounding_correct"])

    print(f"\n{'='*70}\nSummary ({total} cases)")
    print(f"State correctness: {state_correct_count}/{total} = {100*state_correct_count/total:.0f}%")
    if grounding_applicable:
        print(f"Grounding correctness: {grounding_correct_count}/{len(grounding_applicable)} = "
              f"{100*grounding_correct_count/len(grounding_applicable):.0f}%")
    print(f"\nFull results written to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
