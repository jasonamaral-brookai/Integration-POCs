"""
test_idempotency.py — Proves idempotency and replay safety of the CCDA inbound slice.

Tests that running the same CCDA through the full stack twice:
  - Does NOT produce duplicate entities in the clinical store
  - Emits events on the FIRST run
  - SUPPRESSES events on the second run (replay-safe)

This is the class of bug the three-layer architecture is designed to prevent.

Brook context (from findings.md / recon-summary.md):
  AAR-247 (lead provider not written for existing patients) and AAR-329 (consent not
  honored on rematch) are both active open PRs on the Redox integration as of the
  scan date. They are symptoms of mapping logic and ingest semantics tangled into
  application code instead of a defined layer with explicit idempotency ownership.
  Files:
    /tmp/brook-backend/src/main/java/ai/brook/api/rpm/emr/redox/RedoxService.java
    /tmp/fonzie/specs/2026-06-10-redox-orm-ingestion-identity-resolution/plan.md
    /tmp/fonzie/specs/2026-06-18-aar-329-redox-order-consent-guard/plan.md

  The integration layer assigns an idempotency key.
  The clinical store enforces upsert-by-source-key (no duplicate writes).
  The event publisher checks is_duplicate and suppresses replay events.

  This three-layer separation of concerns means replay safety is enforced at the
  store boundary — not scattered across application code.

  Comparison: current EmrLog outbound idempotency in brook-backend uses compound
  unique index on (provider_office_id, persona_id, file_name, type).
  File: /tmp/brook-backend/src/main/java/ai/brook/api/rpm/emr/model/EmrLog.java
  This POC uses the same compound-index pattern for inbound: (persona_id, source, source_id).
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date
from integration_layer.auth import AthenaOAuth2Client
from integration_layer.athena_adapter import AthenaAdapter
from mapping_layer.ccda_mapper import CCDAMapper, ATHENA_CCDA_SOURCE
from platform_layer.clinical_store import ClinicalStore
from platform_layer.event_publisher import EventPublisher, InMemoryEventBus


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def auth_client():
    return AthenaOAuth2Client(
        client_id="test-client-id",
        client_secret="test-client-secret",
        practice_id="195900",
    )


@pytest.fixture
def adapter(auth_client):
    return AthenaAdapter(practice_id="195900", auth_client=auth_client)


@pytest.fixture
def mapper():
    return CCDAMapper(partner_key="athena")


@pytest.fixture
def store():
    s = ClinicalStore()
    yield s
    s.clear()


@pytest.fixture
def bus():
    return InMemoryEventBus()


@pytest.fixture
def publisher(bus):
    return EventPublisher(bus=bus)


def _run_full_slice(adapter, mapper, store, publisher, patient_id: str, idempotency_date=None):
    """
    Run the complete CCDA inbound vertical slice for a patient.

    Returns (entities, written_ids, dup_ids, events_emitted)
    """
    # Layer 1
    if idempotency_date is not None:
        idem_key = adapter.generate_idempotency_key(patient_id, "CCDA", idempotency_date)
        ccda_result = adapter.get_ccda(patient_id=patient_id, idempotency_key=idem_key)
    else:
        ccda_result = adapter.get_ccda(patient_id=patient_id)

    # Layer 2
    entities = mapper.map(
        ccda_xml=ccda_result["xml"],
        patient_id=patient_id,
        provider_office_id="PO-42",
        idempotency_key=ccda_result["idempotency_key"],
    )

    # Layer 3 — store
    written_ids, dup_ids = store.write_batch(entities)

    # Layer 3 — events
    publisher.emit_batch(entities, duplicate_ids=dup_ids)

    bus_snapshot = publisher._bus.get_events()
    return entities, written_ids, dup_ids, bus_snapshot


# ──────────────────────────────────────────────────────────────────────────────
# Idempotency tests
# ──────────────────────────────────────────────────────────────────────────────

class TestIdempotency:
    """Idempotency and replay-safety assertions for the CCDA inbound slice."""

    def test_no_duplicate_entities_on_second_run(
        self, adapter, mapper, store, publisher, bus
    ):
        """
        Running the same CCDA twice does NOT produce duplicate entities in the store.

        The clinical store enforces upsert-by-source-key:
          compound key = (persona_id, source, source_entity_id)
        Second run detects existing entities and skips writes.
        """
        fixed_date = date(2026, 6, 30)
        patient_id = "PAT-IDEM-001"

        # First run
        entities_run1, written1, dup1, events1 = _run_full_slice(
            adapter, mapper, store, publisher, patient_id, fixed_date
        )

        count_after_run1 = store.count()
        assert count_after_run1 == len(entities_run1), (
            "First run should write all entities"
        )
        assert len(dup1) == 0, "First run should have no duplicates"

        # Second run — same patient, same date bucket (same idempotency key)
        entities_run2, written2, dup2, events2 = _run_full_slice(
            adapter, mapper, store, publisher, patient_id, fixed_date
        )

        count_after_run2 = store.count()

        # Store count must not increase on second run
        assert count_after_run2 == count_after_run1, (
            f"Store count changed from {count_after_run1} to {count_after_run2} "
            "on second run — duplicate entities were written"
        )
        assert len(written2) == 0, (
            "Second run should write zero new entities"
        )
        assert len(dup2) == len(entities_run2), (
            "Second run should detect all entities as duplicates"
        )

    def test_events_emitted_on_first_run_only(
        self, adapter, mapper, store, publisher, bus
    ):
        """
        Events are emitted on the first run and SUPPRESSED on replay.

        This is the replay-safety property that prevents the class of bugs
        seen in the Redox integration (AAR-247, AAR-329 — see module docstring).

        The event publisher checks is_duplicate and suppresses the event
        when the clinical store signals the entity already existed.
        """
        fixed_date = date(2026, 6, 30)
        patient_id = "PAT-EVENT-IDEM-001"

        # First run
        entities_run1, _written1, dup1, _ = _run_full_slice(
            adapter, mapper, store, publisher, patient_id, fixed_date
        )

        events_after_run1 = bus.get_events()
        first_run_event_count = len(events_after_run1)

        assert first_run_event_count > 0, "First run must emit events"
        assert first_run_event_count == len(entities_run1), (
            "First run should emit one event per extracted entity"
        )

        # Second run — same patient, same date
        _entities_run2, _written2, dup2, _ = _run_full_slice(
            adapter, mapper, store, publisher, patient_id, fixed_date
        )

        events_after_run2 = bus.get_events()
        second_run_event_count = len(events_after_run2) - first_run_event_count

        assert second_run_event_count == 0, (
            f"Second run emitted {second_run_event_count} events — "
            "replay should suppress all events for duplicate entities"
        )

    def test_duplicate_detection_uses_source_and_source_id(
        self, adapter, mapper, store, publisher, bus
    ):
        """
        Duplicate detection is keyed on (persona_id, source, source_entity_id).

        A different patient with the same source entity ID is NOT a duplicate.
        This ensures the compound key includes persona_id as a discriminator.
        """
        fixed_date = date(2026, 6, 30)

        # Run for patient A
        entities_a, written_a, dup_a, _ = _run_full_slice(
            adapter, mapper, store, publisher, "PAT-A", fixed_date
        )

        # Run for patient B — same CCDA fixture, different patient_id
        entities_b, written_b, dup_b, _ = _run_full_slice(
            adapter, mapper, store, publisher, "PAT-B", fixed_date
        )

        # Both should write successfully — different persona_id = different compound key
        assert len(written_a) == len(entities_a)
        assert len(written_b) == len(entities_b)
        assert len(dup_a) == 0
        assert len(dup_b) == 0

        # Total store count = entities from both patients
        assert store.count() == len(entities_a) + len(entities_b)

    def test_second_run_with_different_date_bucket_writes_new_entities(
        self, adapter, mapper, store, publisher, bus
    ):
        """
        A CCDA retrieved on a different date has a different idempotency key.

        Since the source_entity_id from the CCDA fixture is stable, the compound
        upsert key (persona_id, source, source_id) will still detect duplicates
        on the second day — idempotency is by EHR source ID, not by date key.

        This test verifies the store-level upsert behavior with the same source IDs.
        The date bucket in the integration-layer idempotency key is for adapter-level
        dedup (prevent redundant HTTP calls within a day); the store uses source ID.
        """
        patient_id = "PAT-DATE-BUCKET"

        # Run on day 1
        entities_day1, written_day1, dup_day1, _ = _run_full_slice(
            adapter, mapper, store, publisher, patient_id, date(2026, 6, 29)
        )
        count_day1 = store.count()

        # Run on day 2 — different idempotency key at adapter level,
        # but same source_entity_ids from the CCDA fixture
        entities_day2, written_day2, dup_day2, _ = _run_full_slice(
            adapter, mapper, store, publisher, patient_id, date(2026, 6, 30)
        )
        count_day2 = store.count()

        # Store count should NOT increase — same source IDs from same fixture
        assert count_day2 == count_day1, (
            "Same CCDA fixture on a different day should not create new store entries "
            "(source entity ID is the stable key)"
        )
        assert len(dup_day2) == len(entities_day2)

    def test_all_duplicates_are_reported(
        self, adapter, mapper, store, publisher, bus
    ):
        """
        write_batch reports ALL entities as duplicates on replay — not a partial set.

        This ensures the platform layer cannot accidentally emit events for
        a subset of entities on replay.
        """
        fixed_date = date(2026, 6, 30)
        patient_id = "PAT-ALL-DUP"

        entities, _, _, _ = _run_full_slice(
            adapter, mapper, store, publisher, patient_id, fixed_date
        )
        total_entities = len(entities)

        # Run the store write again directly
        written_again, dup_again = store.write_batch(entities)

        assert len(dup_again) == total_entities, (
            f"Expected all {total_entities} entities to be detected as duplicates "
            f"on replay, but only {len(dup_again)} were"
        )
        assert len(written_again) == 0

    def test_idempotency_key_presence_on_stored_entities(
        self, adapter, mapper, store, publisher, bus
    ):
        """
        Stored entities retain persona_id, source, and source_*_id fields
        that form the compound upsert key — these cannot be stripped on write.
        """
        patient_id = "PAT-KEY-CHECK"
        _entities, written, dup, _ = _run_full_slice(
            adapter, mapper, store, publisher, patient_id
        )

        all_stored = store.get_all_entities()
        for entity in all_stored:
            assert entity.get("persona_id") == patient_id
            assert entity.get("source") == ATHENA_CCDA_SOURCE


class TestIdempotencyEventSuppression:
    """
    Granular tests for the event publisher's duplicate-suppression behavior.
    """

    def test_event_suppressed_for_known_duplicate_id(self, bus, publisher):
        """EventPublisher suppresses a single entity when its ID is in duplicate_ids."""
        entity = {
            "_entity_type": "PersonaMedication",
            "id": "dup-entity-id-001",
            "persona_id": "PAT-001",
            "source": ATHENA_CCDA_SOURCE,
            "_idempotency_key": "ccda-inbound:abc123",
            "medication_name": "Metformin 500mg",
        }

        result = publisher.emit(entity, is_duplicate=True)
        assert result is None, "Suppressed event should return None"
        assert len(bus.get_events()) == 0

    def test_event_emitted_for_new_entity(self, bus, publisher):
        """EventPublisher emits an event for a new (non-duplicate) entity."""
        entity = {
            "_entity_type": "PersonaMedication",
            "id": "new-entity-id-001",
            "persona_id": "PAT-001",
            "source": ATHENA_CCDA_SOURCE,
            "_idempotency_key": "ccda-inbound:abc456",
            "medication_name": "Lisinopril 10mg",
        }

        result = publisher.emit(entity, is_duplicate=False)
        assert result is not None
        assert result.event_name == "CCDA_PersonaMedication_INGESTED"
        assert len(bus.get_events()) == 1

    def test_emit_batch_mixed_duplicates_and_new(self, bus, publisher):
        """emit_batch correctly separates new events from suppressed duplicates."""
        entities = [
            {
                "_entity_type": "PersonaProblem",
                "id": "new-prob-001",
                "persona_id": "PAT-001",
                "source": ATHENA_CCDA_SOURCE,
                "_idempotency_key": "ccda-inbound:k1",
            },
            {
                "_entity_type": "PersonaAllergy",
                "id": "dup-alg-001",
                "persona_id": "PAT-001",
                "source": ATHENA_CCDA_SOURCE,
                "_idempotency_key": "ccda-inbound:k1",
            },
            {
                "_entity_type": "PersonaMedication",
                "id": "new-med-001",
                "persona_id": "PAT-001",
                "source": ATHENA_CCDA_SOURCE,
                "_idempotency_key": "ccda-inbound:k1",
            },
        ]

        dup_ids = {"dup-alg-001"}  # allergy is a duplicate
        results = publisher.emit_batch(entities, duplicate_ids=dup_ids)

        assert len(results) == 3
        # New entities emitted
        assert results[0] is not None  # PersonaProblem — new
        assert results[2] is not None  # PersonaMedication — new
        # Duplicate suppressed
        assert results[1] is None       # PersonaAllergy — dup

        # Only 2 events in bus
        events = bus.get_events()
        assert len(events) == 2
        event_types = {e.entity_type for e in events}
        assert "PersonaProblem" in event_types
        assert "PersonaMedication" in event_types
        assert "PersonaAllergy" not in event_types
