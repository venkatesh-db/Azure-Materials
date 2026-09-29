"""Security hardening (Feature 10) — Key Vault wiring.

Only the Function key currently sits in a plaintext .env file
(azure-agent-demo-setup/.env's FUNCTION_KEY) — everything else already
uses DefaultAzureCredential with zero secrets. This module replaces that
one remaining plaintext secret with a Key Vault reference, the same
pattern Managed Identity already uses for the Function App itself.

Private endpoints / VNet integration are NOT implemented here — that's a
network-topology change (subnets, private DNS zones, NSGs) that needs its
own resource-group-level planning, not a code change. Documented as the
remaining item in ROADMAP.md rather than half-implemented.
"""


class SecretProvider:
    """Protocol-shaped, but written as a plain class since there's only
    one real implementation worth having here — a stub would just be
    'return a hardcoded string', which doesn't test anything meaningful."""

    def __init__(self, vault_url: str, credential):
        from azure.keyvault.secrets import SecretClient

        self.client = SecretClient(vault_url=vault_url, credential=credential)

    def get_secret(self, name: str) -> str:
        return self.client.get_secret(name).value


def migrate_function_key_to_key_vault(vault_url: str, function_key: str, credential) -> None:
    """One-time migration helper: writes the Function key (currently
    plaintext in .env) into Key Vault as a secret, so future reads go
    through SecretProvider instead of os.environ. Idempotent — setting
    the same secret value again just creates a new version, does not
    error."""
    from azure.keyvault.secrets import SecretClient

    client = SecretClient(vault_url=vault_url, credential=credential)
    client.set_secret("incidentops-function-key", function_key)
