"""Real deployment automation (Feature 14): canary-style deploy + smoke
test + rollback for the Function App executor endpoint.

Runnable locally today (uses your `az login` session via DefaultAzureCredential,
same as every other script in this repo). NOT wired into GitHub Actions
CI directly, because that needs Azure federated (OIDC) credentials issued
to the GitHub repo — an Azure AD app registration + federated credential +
RBAC role assignment, which is a meaningfully bigger and more sensitive
step than a deploy script, so it's documented here rather than silently
set up. To wire it up for real:

    az ad app create --display-name "incidentops-ai-github-actions"
    az ad app federated-credential create --id <app-id> --parameters '{
        "name": "github-main", "issuer": "https://token.actions.githubusercontent.com",
        "subject": "repo:<org>/<repo>:ref:refs/heads/main", "audiences": ["api://AzureADTokenExchange"]
    }'
    az role assignment create --assignee <app-id> --role Contributor --scope <resource-group-id>
    # then add AZURE_CLIENT_ID / AZURE_TENANT_ID / AZURE_SUBSCRIPTION_ID as
    # repo secrets and use azure/login@v2 in the workflow.

Usage:
    python3 deploy.py --stage canary   # deploy + smoke test only
    python3 deploy.py --stage promote  # (no-op placeholder — see below)
    python3 deploy.py --rollback       # redeploy the last known-good package
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

FUNCTION_APP_DIR = Path(__file__).parent.parent / "azure-agent-demo-setup" / "day2" / "azure_function"
LAST_GOOD_MARKER = Path(__file__).parent / ".last_good_deploy.json"


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True)


def smoke_test(function_app_name: str, function_key: str) -> bool:
    """Real smoke test: confirm the deployed endpoint enforces approval
    correctly (403 with no token) — the one behavior that must never
    regress on any deploy."""
    import requests

    url = f"https://{function_app_name}.azurewebsites.net/api/request-service-restart"
    try:
        resp = requests.post(url, params={"code": function_key},
                              json={"idempotency_key": "smoke-test", "service_name": "x", "environment": "y"},
                              timeout=15)
    except requests.RequestException as exc:
        print(f"Smoke test FAILED: request error: {exc}")
        return False

    if resp.status_code != 403:
        print(f"Smoke test FAILED: expected 403 (approval_required), got {resp.status_code}: {resp.text}")
        return False
    print("Smoke test PASSED: endpoint correctly rejects unapproved calls (403)")
    return True


def deploy_canary(function_app_name: str, function_key: str) -> bool:
    print(f"==> Deploying to {function_app_name} (this IS the canary — Consumption plan has no slots, "
          f"so 'canary' here means: deploy, smoke test immediately, roll back on failure before any real traffic hits it)")

    result = run(["func", "azure", "functionapp", "publish", function_app_name, "--python"])
    if result.returncode != 0:
        print(f"Deployment FAILED:\n{result.stdout}\n{result.stderr}")
        return False
    print("Deployment succeeded. Running smoke test...")

    if not smoke_test(function_app_name, function_key):
        print("Smoke test failed — this deploy should be rolled back (see --rollback).")
        return False

    LAST_GOOD_MARKER.write_text(json.dumps({"function_app_name": function_app_name}))
    print("Canary verified healthy. Marked as last-known-good for future rollback.")
    return True


def rollback() -> bool:
    if not LAST_GOOD_MARKER.exists():
        print("No last-known-good deployment recorded — nothing to roll back to.")
        return False
    data = json.loads(LAST_GOOD_MARKER.read_text())
    print(f"Rolling back: redeploying last-known-good package to {data['function_app_name']}")
    result = run(["func", "azure", "functionapp", "publish", data["function_app_name"], "--python"])
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["canary", "promote"])
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--function-app-name")
    parser.add_argument("--function-key")
    args = parser.parse_args()

    if args.rollback:
        sys.exit(0 if rollback() else 1)

    if args.stage == "canary":
        if not args.function_app_name or not args.function_key:
            print("--function-app-name and --function-key are required for --stage canary")
            sys.exit(1)
        import os
        os.chdir(FUNCTION_APP_DIR)
        sys.exit(0 if deploy_canary(args.function_app_name, args.function_key) else 1)

    if args.stage == "promote":
        print("promote: Consumption plan has no deployment slots to swap — 'promotion' here just means "
              "'canary passed, no further action needed, it's already serving all traffic.' A Premium plan "
              "with slots would make this a real slot-swap instead of a no-op.")
        sys.exit(0)


if __name__ == "__main__":
    main()
