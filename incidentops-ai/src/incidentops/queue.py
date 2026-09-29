"""Real event/queue integration (Feature 6).

Same Protocol-seam pattern as every other layer: an IncidentQueue
interface, an in-memory implementation for tests, and a real Azure
Service Bus implementation for production. This directly answers the
syllabus capstone's "duplicate Kafka events" scenario — the queue
consumer uses the SAME idempotency_key + db.py mechanism already proven
in executor.py, so a duplicated/redelivered message is a no-op, not a
double-execution.
"""
import json
import queue as _queue
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(frozen=True)
class IncidentEvent:
    event_id: str
    raw_request: str
    tenant_id: str
    received_at: float

    @staticmethod
    def new(raw_request: str, tenant_id: str) -> "IncidentEvent":
        return IncidentEvent(event_id=str(uuid.uuid4()), raw_request=raw_request,
                              tenant_id=tenant_id, received_at=time.time())


class IncidentQueue(Protocol):
    def publish(self, event: IncidentEvent) -> None: ...
    def consume(self, handler: Callable[[IncidentEvent], None], max_messages: int = 10) -> int:
        """Pulls up to max_messages and calls handler on each. Returns the
        count actually processed."""
        ...


class InMemoryIncidentQueue:
    """Local queue for tests and single-process demos — same delivery
    semantics contract as the real one (at-least-once: a message can be
    redelivered, consumers MUST be idempotent)."""

    def __init__(self):
        self._queue: _queue.Queue = _queue.Queue()
        self.published_event_ids: list[str] = []

    def publish(self, event: IncidentEvent) -> None:
        self._queue.put(event)
        self.published_event_ids.append(event.event_id)

    def redeliver(self, event: IncidentEvent) -> None:
        """Test helper: simulates the at-least-once redelivery that a real
        queue can do (consumer crashed before ack, message redelivered)."""
        self._queue.put(event)

    def consume(self, handler: Callable[[IncidentEvent], None], max_messages: int = 10) -> int:
        processed = 0
        while processed < max_messages:
            try:
                event = self._queue.get_nowait()
            except _queue.Empty:
                break
            handler(event)
            processed += 1
        return processed


class AzureServiceBusIncidentQueue:
    """Real Azure Service Bus-backed queue. Imports lazily (like
    retrieval.py's AzureSearchRetriever) so this module stays importable
    without azure-servicebus installed for local-only runs.
    """

    def __init__(self, fully_qualified_namespace: str, queue_name: str, credential):
        from azure.servicebus import ServiceBusClient

        self.client = ServiceBusClient(fully_qualified_namespace=fully_qualified_namespace, credential=credential)
        self.queue_name = queue_name

    def publish(self, event: IncidentEvent) -> None:
        from azure.servicebus import ServiceBusMessage

        with self.client.get_queue_sender(self.queue_name) as sender:
            message = ServiceBusMessage(json.dumps(event.__dict__), message_id=event.event_id)
            sender.send_messages(message)

    def consume(self, handler: Callable[[IncidentEvent], None], max_messages: int = 10) -> int:
        processed = 0
        with self.client.get_queue_receiver(self.queue_name) as receiver:
            for message in receiver.receive_messages(max_message_count=max_messages, max_wait_time=5):
                data = json.loads(str(message))
                handler(IncidentEvent(**data))
                receiver.complete_message(message)
                processed += 1
        return processed


def idempotent_consumer(repo, orchestrator) -> Callable[[IncidentEvent], None]:
    """Wraps orchestrator.handle_new_incident with the queue's event_id as
    the idempotency key — this is the actual fix for 'duplicate Kafka
    events' from the syllabus capstone: a redelivered event is detected
    and skipped BEFORE a second incident/agent pipeline run is triggered,
    reusing db.py's existing idempotency table rather than inventing a
    second mechanism."""

    def handle(event: IncidentEvent) -> None:
        dedup_key = f"queue_event:{event.event_id}"
        if not repo.check_and_record_idempotency_key(dedup_key):
            return  # already processed this exact event_id — no-op, not an error
        orchestrator.handle_new_incident(event.raw_request)

    return handle
