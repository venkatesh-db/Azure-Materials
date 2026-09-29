"""Enterprise RAG at scale (Feature 9): real document ingestion, ACLs,
and staleness detection — extends retrieval.py's static 8-document JSON
file toward something an ingestion pipeline could actually populate.
"""
import time
from dataclasses import dataclass, replace
from pathlib import Path

from incidentops.retrieval import Document

STALENESS_THRESHOLD_SECONDS = 180 * 24 * 60 * 60  # ~6 months


@dataclass(frozen=True)
class IngestedDocument(Document):
    allowed_tenant_ids: tuple[str, ...] = ()  # empty tuple = visible to all tenants
    last_updated_at: float = 0.0
    source_path: str = ""


def load_markdown_directory(directory: Path) -> list[IngestedDocument]:
    """Real ingestion source: a directory of markdown runbooks, each with
    a tiny frontmatter-style header. This is what a scheduled sync job
    (Confluence/SharePoint export -> this directory -> re-index) would
    feed into the search index build step (day1/lab4_build_search_index.py's
    pattern, extended with ACL + timestamp fields).

    Expected format per file:
        ---
        id: rb-001
        title: Payment Service Runbook
        status: approved
        tenants: payments-team
        ---
        <markdown body>
    """
    docs = []
    for path in sorted(directory.glob("*.md")):
        text = path.read_text()
        if not text.startswith("---"):
            continue
        _, frontmatter, body = text.split("---", 2)
        fields = {}
        for line in frontmatter.strip().splitlines():
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()

        tenants = tuple(t.strip() for t in fields.get("tenants", "").split(",") if t.strip())
        docs.append(IngestedDocument(
            id=fields["id"], title=fields["title"], status=fields.get("status", "approved"),
            content=body.strip(), allowed_tenant_ids=tenants,
            last_updated_at=path.stat().st_mtime, source_path=str(path),
        ))
    return docs


def filter_by_tenant_access(docs: list[IngestedDocument], tenant_id: str) -> list[IngestedDocument]:
    """ACL enforcement: a document with a non-empty allowed_tenant_ids list
    is only visible to those tenants. Called by the retriever before
    results reach the Diagnosis agent — same 'filter before the prompt'
    principle as the malicious-document quarantine in retrieval.py."""
    return [d for d in docs if not d.allowed_tenant_ids or tenant_id in d.allowed_tenant_ids]


def flag_stale_documents(docs: list[IngestedDocument], now: float | None = None) -> list[IngestedDocument]:
    """Returns documents whose last_updated_at exceeds the staleness
    threshold — these should be surfaced to the runbook owner for review,
    same idea as Day 1's 'obsolete' status but detected automatically
    instead of relying on someone manually re-flagging a document."""
    now = now if now is not None else time.time()
    return [d for d in docs if (now - d.last_updated_at) > STALENESS_THRESHOLD_SECONDS]
