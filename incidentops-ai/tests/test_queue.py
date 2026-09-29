import pytest

from incidentops.db import IncidentRepository
from incidentops.queue import IncidentEvent, InMemoryIncidentQueue, idempotent_consumer


@pytest.fixture
def repo(tmp_path):
    return IncidentRepository(db_path=str(tmp_path / "queue_test.db"))


class RecordingOrchestrator:
    def __init__(self):
        self.calls = []

    def handle_new_incident(self, raw_request):
        self.calls.append(raw_request)


def test_publish_and_consume(repo):
    q = InMemoryIncidentQueue()
    orchestrator = RecordingOrchestrator()
    handler = idempotent_consumer(repo, orchestrator)

    event = IncidentEvent.new("payment-service latency spike", tenant_id="payments-team")
    q.publish(event)
    processed = q.consume(handler)

    assert processed == 1
    assert orchestrator.calls == ["payment-service latency spike"]


def test_duplicate_kafka_style_redelivery_is_a_no_op(repo):
    """The exact scenario named in the syllabus capstone: a duplicated
    event must not trigger a second incident pipeline run."""
    q = InMemoryIncidentQueue()
    orchestrator = RecordingOrchestrator()
    handler = idempotent_consumer(repo, orchestrator)

    event = IncidentEvent.new("payment-service latency spike", tenant_id="payments-team")
    q.publish(event)
    q.consume(handler)

    q.redeliver(event)  # same event_id, simulating an at-least-once redelivery
    processed = q.consume(handler)

    assert processed == 1  # the queue delivered it again...
    assert orchestrator.calls == ["payment-service latency spike"]  # ...but only ONE incident was created
