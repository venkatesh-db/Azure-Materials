import time

from incidentops.ingestion import IngestedDocument, filter_by_tenant_access, flag_stale_documents, load_markdown_directory


def test_load_markdown_directory_parses_frontmatter(tmp_path):
    (tmp_path / "rb-001.md").write_text(
        "---\nid: rb-001\ntitle: Payment Service Runbook\nstatus: approved\ntenants: payments-team\n---\n"
        "If payment-service reports elevated latency, check the connection pool.\n"
    )

    docs = load_markdown_directory(tmp_path)

    assert len(docs) == 1
    assert docs[0].id == "rb-001"
    assert docs[0].allowed_tenant_ids == ("payments-team",)
    assert "connection pool" in docs[0].content


def test_document_with_no_tenants_field_is_visible_to_everyone(tmp_path):
    (tmp_path / "rb-general.md").write_text(
        "---\nid: rb-general\ntitle: General Guide\nstatus: approved\n---\nGeneral content.\n"
    )
    docs = load_markdown_directory(tmp_path)
    assert docs[0].allowed_tenant_ids == ()


def test_filter_by_tenant_access_enforces_acl():
    docs = [
        IngestedDocument(id="a", title="A", status="approved", content="x", allowed_tenant_ids=("payments-team",)),
        IngestedDocument(id="b", title="B", status="approved", content="y", allowed_tenant_ids=()),  # visible to all
        IngestedDocument(id="c", title="C", status="approved", content="z", allowed_tenant_ids=("data-team",)),
    ]

    visible_to_payments = filter_by_tenant_access(docs, "payments-team")

    assert {d.id for d in visible_to_payments} == {"a", "b"}


def test_flag_stale_documents():
    now = time.time()
    fresh = IngestedDocument(id="fresh", title="Fresh", status="approved", content="x", last_updated_at=now - 3600)
    stale = IngestedDocument(id="stale", title="Stale", status="approved", content="y", last_updated_at=now - 200 * 24 * 60 * 60)

    stale_docs = flag_stale_documents([fresh, stale], now=now)

    assert [d.id for d in stale_docs] == ["stale"]
