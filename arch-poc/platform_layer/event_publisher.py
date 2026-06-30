"""
event_publisher.py — Layer 3: Brook integration event emission.

This is the platform layer's event publisher. It owns:
  - Emitting a Brook integration event for each extracted clinical entity
  - Event schema: entity_type, entity_id, patient_id, source, event_name, payload
  - In-memory event bus for POC (production would wire to a real Brook event substrate)

Brook event substrate decision (from findings.md / recon-summary.md):

  THREE different event substrates are running in production — the plan's claim
  that "the existing SQS-backed worker pattern is the substrate" applies only to
  device data:

  1. AWS SQS — device data path (services-data → brook-backend via QueueAlias.BROOK,
     BROOK_PLUS, NOTIFICATIONS).
     File: /tmp/services-data/src/main/java/health/brook/servicesdata/common/SQSSender.java
     and /tmp/brook-backend/src/main/java/ai/brook/channels/queue/GenericQueueProcessor.java

  2. MongoDB Change Data Capture (CDC) — care-nexus path. A Go service watches MongoDB
     change streams and writes derived patient_features to PostgreSQL.
     File: /tmp/care-nexus/services/cdc-consumer/internal/config/config.go

  3. Redis Streams (Valkey) — data-platform CIO service path for webhook queuing
     between receipt and processing.
     File: /tmp/data-platform/services/cio/queue/manager.go

  The "Integration Event Worker (Go)" and "Integration Past Event Worker (Go)"
  referenced in the build plan are NOT found as source-level repos in the Brookai org.
  This decision must be made before production wiring.

TODO: wire to real Brook event substrate — see findings.md for the three candidates.
  The choice has infrastructure implications. The athena integration layer needs
  an explicit decision on which substrate it targets before any production code ships.
"""

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class IntegrationEvent:
    """
    A Brook integration event representing the ingest of a single clinical entity
    from an EHR source.

    Event schema mirrors what a real SQS message, MongoDB CDC event, or Redis
    Streams record would carry. The _event_id provides a stable correlation ID
    for tracing in the Integration Health Dashboard pipeline.
    (See reference/brook-integration-platform-athena-griffin-v1.md section 3,
    Phase 0 observability requirements: IDEA-36 integration monitoring prototype.)
    """

    def __init__(
        self,
        event_name: str,
        entity_type: str,
        entity_id: str,
        patient_id: str,
        source: str,
        idempotency_key: Optional[str],
        payload: Dict[str, Any],
    ):
        self.event_id = str(uuid.uuid4())
        self.event_name = event_name
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.patient_id = patient_id
        self.source = source
        self.idempotency_key = idempotency_key
        self.emitted_at = datetime.now(timezone.utc).isoformat()
        self.payload = payload

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "patient_id": self.patient_id,
            "source": self.source,
            "idempotency_key": self.idempotency_key,
            "emitted_at": self.emitted_at,
            "payload": self.payload,
        }

    def __repr__(self) -> str:
        return (
            f"IntegrationEvent(event_id={self.event_id!r}, "
            f"event_name={self.event_name!r}, "
            f"entity_type={self.entity_type!r}, "
            f"patient_id={self.patient_id!r})"
        )


class InMemoryEventBus:
    """
    Thread-safe in-memory event bus for POC testing.

    Stores emitted events and supports subscriber callbacks.
    In production this would be replaced by:
      - SQS: boto3.client('sqs').send_message(...)
      - MongoDB CDC: The platform layer writes to MongoDB; CDC consumer picks up
      - Redis Streams: redis.xadd(stream_key, event_dict)

    TODO: wire to real Brook event substrate — see findings.md
    """

    def __init__(self):
        self._events: List[IntegrationEvent] = []
        self._subscribers: List[Callable[[IntegrationEvent], None]] = []
        self._lock = threading.Lock()

    def publish(self, event: IntegrationEvent) -> None:
        """Publish an event to the bus and notify all subscribers."""
        with self._lock:
            self._events.append(event)
            subscribers = list(self._subscribers)

        logger.debug(
            "event_bus: published %s (event_id=%s)",
            event.event_name, event.event_id,
        )

        for callback in subscribers:
            try:
                callback(event)
            except Exception as exc:
                logger.error(
                    "event_bus: subscriber %r raised exception: %s",
                    callback, exc,
                )

    def subscribe(self, callback: Callable[[IntegrationEvent], None]) -> None:
        """Register a subscriber callback."""
        with self._lock:
            self._subscribers.append(callback)

    def get_events(self) -> List[IntegrationEvent]:
        """Return a snapshot of all emitted events (for testing)."""
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        """Clear all stored events (useful between test runs)."""
        with self._lock:
            self._events.clear()


# Global in-memory bus instance (shared across the POC)
_default_bus = InMemoryEventBus()


def get_default_bus() -> InMemoryEventBus:
    return _default_bus


class EventPublisher:
    """
    Emits Brook integration events for each extracted clinical entity.

    One event per entity, fired immediately after the entity is written to
    the clinical store. The event carries the full entity payload so downstream
    consumers (care-nexus CDC, data-platform, analytics) can act without reading
    back from MongoDB.

    Event naming: CCDA_{EntityType}_INGESTED
      e.g., CCDA_PersonaMedication_INGESTED, CCDA_PersonaAllergy_INGESTED

    Idempotency: if the clinical_store signals that this entity was a duplicate
    (already stored on a prior ingest), the event is SUPPRESSED — not emitted again.
    This is the replay-safety property that the Redox seam-bugs violated:
      AAR-247 (lead provider not written for existing patients) and
      AAR-329 (consent not honored on rematch) both stem from the absence of a
      defined layer that owns replay semantics.
    Files: findings.md — "AAR-247, AAR-329 are actively in-flight fixes on open PRs"
    """

    def __init__(self, bus: Optional[InMemoryEventBus] = None):
        self._bus = bus or _default_bus

    def emit(
        self,
        entity: Dict[str, Any],
        is_duplicate: bool = False,
    ) -> Optional[IntegrationEvent]:
        """
        Emit a Brook integration event for the given entity dict.

        Args:
            entity: entity dict from the mapping layer (includes _entity_type, source, etc.)
            is_duplicate: if True, the entity already existed in the store — suppress event

        Returns:
            The emitted IntegrationEvent, or None if suppressed (is_duplicate=True).
        """
        entity_type = entity.get("_entity_type", "UNKNOWN")
        entity_id = entity.get("id", "UNKNOWN")
        patient_id = entity.get("persona_id", "UNKNOWN")
        source = entity.get("source", "UNKNOWN")
        idempotency_key = entity.get("_idempotency_key")

        if is_duplicate:
            logger.info(
                "event_publisher: SUPPRESSED duplicate event for %s entity_id=%s "
                "(idempotency_key=%s) — replay-safe",
                entity_type, entity_id, idempotency_key,
            )
            return None

        event_name = f"CCDA_{entity_type}_INGESTED"

        # Strip internal POC fields before including in payload
        payload = {k: v for k, v in entity.items() if not k.startswith("_")}

        event = IntegrationEvent(
            event_name=event_name,
            entity_type=entity_type,
            entity_id=entity_id,
            patient_id=patient_id,
            source=source,
            idempotency_key=idempotency_key,
            payload=payload,
        )

        self._bus.publish(event)

        logger.info(
            "event_publisher: emitted %s for patient=%s entity=%s",
            event_name, patient_id, entity_id,
        )

        return event

    def emit_batch(
        self,
        entities: List[Dict[str, Any]],
        duplicate_ids: Optional[set] = None,
    ) -> List[Optional[IntegrationEvent]]:
        """
        Emit events for a batch of entities, suppressing duplicates by entity id.

        Args:
            entities: list of entity dicts from the mapping layer
            duplicate_ids: set of entity ids that already exist in the store

        Returns:
            List of IntegrationEvent (or None for suppressed duplicates).
        """
        if duplicate_ids is None:
            duplicate_ids = set()

        results = []
        for entity in entities:
            entity_id = entity.get("id")
            is_dup = entity_id in duplicate_ids
            results.append(self.emit(entity, is_duplicate=is_dup))
        return results
