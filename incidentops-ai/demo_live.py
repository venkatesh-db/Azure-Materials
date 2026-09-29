"""Run the full multi-agent pipeline against REAL Azure Foundry agents.

Same scenarios as demo.py, but agents=AzureAgentSuite(...) instead of
StubAgentSuite() — proves the Protocol-based seam actually works: zero
changes to orchestrator.py or db.py were needed to go from stub to live.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, "src")

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential

load_dotenv(Path(__file__).parent.parent / "azure-agent-demo-setup" / ".env")

from incidentops.agents.azure import AzureAgentSuite
from incidentops.db import IncidentRepository
from incidentops.executor import AzureFunctionActionExecutor
from incidentops.orchestrator import Orchestrator
from incidentops.retrieval import AzureSearchRetriever


def main():
    endpoint = os.environ["FOUNDRY_ENDPOINT"]
    model = os.environ["MODEL_DEPLOYMENT_NAME"]
    embedding_model = os.environ["EMBEDDING_DEPLOYMENT_NAME"]
    search_endpoint = os.environ["SEARCH_ENDPOINT"]
    function_app_name = os.environ["FUNCTION_APP_NAME"]
    function_key = os.environ["FUNCTION_KEY"]
    print(f"Foundry endpoint: {endpoint}")
    print(f"Model deployment: {model}")
    print(f"Search endpoint: {search_endpoint}")
    print(f"Function App: {function_app_name}\n")

    credential = DefaultAzureCredential()
    repo = IncidentRepository(db_path="incidentops_live.db")
    agents = AzureAgentSuite(endpoint=endpoint, model_deployment_name=model, credential=credential)
    executor = AzureFunctionActionExecutor(
        function_app_base_url=f"https://{function_app_name}.azurewebsites.net", function_key=function_key,
    )

    # Reuses azure-agent-demo-setup/day1's embedding client + the same
    # "runbooks" index built by day1/lab4_build_search_index.py — that
    # script must have been run against the current Search service for
    # this retriever to find anything.
    sys.path.insert(0, str(Path(__file__).parent.parent / "azure-agent-demo-setup" / "day1"))
    import config as day1_config  # noqa: E402

    retriever = AzureSearchRetriever(
        search_endpoint=search_endpoint, index_name=day1_config.SEARCH_INDEX_NAME,
        credential=credential, embedding_client=day1_config.get_embedding_client(),
        embedding_model=embedding_model,
    )

    orchestrator = Orchestrator(repo=repo, agents=agents, executor=executor, retriever=retriever)

    print("=" * 70)
    print("LIVE Scenario 1: confident case -> propose -> approve -> execute -> communicate")
    incident = orchestrator.handle_new_incident(
        "payment-service p95 latency climbing, database connection pool acquisition "
        "time exceeding 5 seconds in production"
    )
    print(f"  correlation_id: {incident.correlation_id}")
    print(f"  state: {incident.state.value}")
    print(f"  triage: {incident.triage}")
    print(f"  diagnosis: {incident.diagnosis}")
    print(f"  remediation: {incident.remediation}")

    if incident.state.value == "AWAITING_APPROVAL":
        token = repo.issue_approval(correlation_id=incident.correlation_id, scope=incident.remediation.scope)
        completed = orchestrator.approve_and_execute(incident.correlation_id, token)
        print(f"\n  Final state: {completed.state.value}")
        print(f"  Communication: {completed.communication.message}")
    else:
        print(f"\n  Incident went to {incident.state.value} instead of AWAITING_APPROVAL "
              f"(e.g. low confidence) — remediation: {incident.remediation}")

    print("\n" + "=" * 70)
    print("LIVE Scenario 2: vague request -> should escalate, not propose an action")
    vague = orchestrator.handle_new_incident("something seems off, not sure what")
    print(f"  state: {vague.state.value}")
    print(f"  diagnosis: {vague.diagnosis}")
    print(f"  remediation: {vague.remediation}")


if __name__ == "__main__":
    main()
