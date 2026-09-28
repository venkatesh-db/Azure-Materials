"""Configuration for the Enterprise Runbook Knowledge Agent.

Reuses the .env written by ../setup.sh. Nothing here is a secret: every
Azure call authenticates with DefaultAzureCredential (your az login locally,
a managed identity in Azure).
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

FOUNDRY_ENDPOINT = os.environ["FOUNDRY_ENDPOINT"]
MODEL_DEPLOYMENT_NAME = os.environ["MODEL_DEPLOYMENT_NAME"]
EMBEDDING_DEPLOYMENT_NAME = os.environ["EMBEDDING_DEPLOYMENT_NAME"]
SEARCH_ENDPOINT = os.environ["SEARCH_ENDPOINT"]
SEARCH_INDEX_NAME = "runbooks"

# Embeddings must go to the raw Cognitive Services endpoint: the
# project-scoped OpenAI client proxies chat/agent calls but not /embeddings.
_RESOURCE_NAME = FOUNDRY_ENDPOINT.split("//")[1].split(".")[0]
COGNITIVE_SERVICES_ENDPOINT = f"https://{_RESOURCE_NAME}.cognitiveservices.azure.com/"


def get_embedding_client() -> AzureOpenAI:
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
    )
    return AzureOpenAI(
        azure_endpoint=COGNITIVE_SERVICES_ENDPOINT,
        azure_ad_token_provider=token_provider,
        api_version="2024-10-21",
    )
