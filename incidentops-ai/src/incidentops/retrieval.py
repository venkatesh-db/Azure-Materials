"""Retrieval layer that grounds the Diagnosis agent in real runbook
documents, instead of reasoning from the raw request text alone.

Same Protocol-seam pattern as agents/base.py and executor.py:
orchestrator/agents depend on Retriever, not on Azure AI Search directly.

The malicious-document quarantine here is not new invention — it's the
exact fix that azure-agent-demo-setup/day3/lab2_evaluation.py found was
necessary at the retrieval layer (not just a system-prompt instruction)
after a real content-filter root-cause investigation. Applying it here
from day one, rather than rediscovering the same bug again.
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    status: str  # "approved" | "obsolete" | "malicious"
    content: str


class Retriever(Protocol):
    def retrieve(self, query: str, top_k: int = 3) -> list[Document]: ...


class StubRetriever:
    """Deterministic keyword-overlap retriever for tests — no embeddings,
    no network. Excludes malicious documents, same as the real retriever."""

    def __init__(self, documents: list[Document]):
        self.documents = documents

    def retrieve(self, query: str, top_k: int = 3) -> list[Document]:
        query_words = set(query.lower().split())
        scored = []
        for doc in self.documents:
            if doc.status == "malicious":
                continue  # quarantined — never returned, regardless of score
            doc_words = set((doc.title + " " + doc.content).lower().split())
            overlap = len(query_words & doc_words)
            if overlap > 0:
                scored.append((overlap, doc))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [doc for _, doc in scored[:top_k]]


class AzureSearchRetriever:
    """Real retriever backed by Azure AI Search hybrid (keyword + vector)
    search — same pattern as azure-agent-demo-setup/day1/lab5_grounded_agent.py.

    Requires azure-search-documents and an embedding client; imported
    lazily inside __init__ so this module stays importable (and StubRetriever
    usable) without those dependencies installed for local-only test runs.
    """

    def __init__(self, search_endpoint: str, index_name: str, credential, embedding_client, embedding_model: str):
        from azure.search.documents import SearchClient

        self.search_client = SearchClient(endpoint=search_endpoint, index_name=index_name, credential=credential)
        self.embedding_client = embedding_client
        self.embedding_model = embedding_model

    def retrieve(self, query: str, top_k: int = 3) -> list[Document]:
        from azure.search.documents.models import VectorizedQuery

        vector = self.embedding_client.embeddings.create(
            model=self.embedding_model, input=[query]
        ).data[0].embedding

        results = self.search_client.search(
            search_text=query,
            vector_queries=[VectorizedQuery(vector=vector, k_nearest_neighbors=top_k, fields="content_vector")],
            select=["id", "title", "content", "status"],
            top=top_k,
        )

        docs = []
        for r in results:
            if r["status"] == "malicious":
                continue  # quarantined at the source — see module docstring
            docs.append(Document(id=r["id"], title=r["title"], status=r["status"], content=r["content"]))
        return docs
