"""
test_ccda_flow.py — End-to-end test of the CCDA inbound vertical slice.

Tests the full three-layer flow:
  1. Integration layer: AthenaAdapter returns CCDA XML fixture with idempotency key
  2. Mapping layer: CCDAMapper extracts all four clinical entity types
  3. Platform layer: ClinicalStore writes entities, EventPublisher emits events

All assertions are against mocked/in-memory components — no external credentials needed.
"""

import pytest
import sys
import os

# Allow imports from arch-poc root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integration_layer.auth import AthenaOAuth2Client
from integration_layer.athena_adapter import AthenaAdapter
from mapping_layer.ccda_mapper import CCDAMapper, ATHENA_CCDA_SOURCE
from platform_layer.clinical_store import ClinicalStore
from platform_layer.event_publisher import EventPublisher, InMemoryEventBus


@pytest.fixture
def auth_client():
    return AthenaOAuth2Client(
        client_id="test-client-id",
        client_secret="test-client-secret",
        practice_id="195900",
    )


@pytest.fixture
def adapter(auth_client):
    return AthenaAdapter(
        practice_id="195900",
        auth_client=auth_client,
        max_retries=2,
    )


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
    b = InMemoryEventBus()
    return b


@pytest.fixture
def publisher(bus):
    return EventPublisher(bus=bus)


# ──────────────────────────────────────────────────────────────────────────────
# Layer 1 — Integration layer
# ──────────────────────────────────────────────────────────────────────────────

class TestAthenaAdapter:
    """Tests for Layer 1: athena integration adapter."""

    def test_get_ccda_returns_xml(self, adapter):
        """Adapter returns a valid C-CDA XML document."""
        result = adapter.get_ccda(patient_id="PAT-001")
        assert "xml" in result
        assert result["xml"].strip().startswith("<?xml")
        assert "ClinicalDocument" in result["xml"]

    def test_get_ccda_includes_idempotency_key(self, adapter):
        """Adapter attaches an idempotency key to the response."""
        result = adapter.get_ccda(patient_id="PAT-001")
        assert "idempotency_key" in result
        assert result["idempotency_key"].startswith("ccda-inbound:")

    def test_idempotency_key_is_stable(self, adapter):
        """Idempotency key for the same patient+doc_type+date is deterministic."""
        from datetime import date
        key1 = adapter.generate_idempotency_key("PAT-001", "CCDA", date(2026, 6, 30))
        key2 = adapter.generate_idempotency_key("PAT-001", "CCDA", date(2026, 6, 30))
        assert key1 == key2

    def test_idempotency_key_differs_by_patient(self, adapter):
        """Different patient IDs produce different idempotency keys."""
        from datetime import date
        d = date(2026, 6, 30)
        key1 = adapter.generate_idempotency_key("PAT-001", "CCDA", d)
        key2 = adapter.generate_idempotency_key("PAT-002", "CCDA", d)
        assert key1 != key2

    def test_idempotency_key_differs_by_date(self, adapter):
        """Different date buckets produce different idempotency keys."""
        from datetime import date
        key1 = adapter.generate_idempotency_key("PAT-001", "CCDA", date(2026, 6, 29))
        key2 = adapter.generate_idempotency_key("PAT-001", "CCDA", date(2026, 6, 30))
        assert key1 != key2

    def test_get_ccda_includes_patient_and_practice(self, adapter):
        """Adapter echoes patient_id and practice_id in the response."""
        result = adapter.get_ccda(patient_id="PAT-TEST-42")
        assert result["patient_id"] == "PAT-TEST-42"
        assert result["practice_id"] == "195900"

    def test_auth_token_acquired(self, adapter):
        """Adapter calls auth client to acquire a bearer token."""
        result = adapter.get_ccda(patient_id="PAT-001")
        # Adapter succeeds — auth client produced a token
        assert result is not None
        token = adapter.auth_client.get_bearer_token()
        assert "mock-bearer-token" in token


# ──────────────────────────────────────────────────────────────────────────────
# Layer 2 — Mapping layer
# ──────────────────────────────────────────────────────────────────────────────

class TestCCDAMapper:
    """Tests for Layer 2: CCDA → Brook entity mapping."""

    def _run_mapper(self, mapper, adapter):
        ccda_result = adapter.get_ccda(patient_id="PAT-001")
        return mapper.map(
            ccda_xml=ccda_result["xml"],
            patient_id="PAT-001",
            provider_office_id="PO-42",
            idempotency_key=ccda_result["idempotency_key"],
        )

    def test_extracts_all_four_entity_types(self, mapper, adapter):
        """Mapper extracts PersonaProblem, PersonaMedication, PersonaEncounter, PersonaAllergy."""
        entities = self._run_mapper(mapper, adapter)
        entity_types = {e["_entity_type"] for e in entities}
        assert "PersonaProblem" in entity_types
        assert "PersonaMedication" in entity_types
        assert "PersonaEncounter" in entity_types
        assert "PersonaAllergy" in entity_types

    def test_all_entities_have_athena_ccda_source(self, mapper, adapter):
        """Every extracted entity has source=ATHENA_CCDA."""
        entities = self._run_mapper(mapper, adapter)
        assert len(entities) > 0
        for entity in entities:
            assert entity["source"] == ATHENA_CCDA_SOURCE, (
                f"Entity {entity['_entity_type']} has source={entity['source']!r}, "
                f"expected {ATHENA_CCDA_SOURCE!r}"
            )

    def test_all_entities_have_idempotency_key(self, mapper, adapter):
        """Every entity carries the CCDA-level idempotency key from the adapter."""
        entities = self._run_mapper(mapper, adapter)
        for entity in entities:
            assert entity.get("_idempotency_key") is not None, (
                f"Entity {entity['_entity_type']} missing _idempotency_key"
            )

    def test_all_entities_have_persona_id(self, mapper, adapter):
        """Every entity has persona_id set from the calling context."""
        entities = self._run_mapper(mapper, adapter)
        for entity in entities:
            assert entity.get("persona_id") == "PAT-001"

    def test_problem_extraction(self, mapper, adapter):
        """Mapper extracts two problem list entries from the fixture CCDA."""
        entities = self._run_mapper(mapper, adapter)
        problems = [e for e in entities if e["_entity_type"] == "PersonaProblem"]
        assert len(problems) >= 1
        # At least one should have an ICD-10 code
        icd_codes = [p.get("icd10_code") for p in problems if p.get("icd10_code")]
        assert len(icd_codes) >= 1

    def test_problem_has_expected_icd10_codes(self, mapper, adapter):
        """Problems include E11.9 (T2DM) and I10 (Hypertension) from fixture."""
        entities = self._run_mapper(mapper, adapter)
        problems = [e for e in entities if e["_entity_type"] == "PersonaProblem"]
        icd_codes = {p["icd10_code"] for p in problems if p.get("icd10_code")}
        assert "E11.9" in icd_codes
        assert "I10" in icd_codes

    def test_medication_extraction(self, mapper, adapter):
        """Mapper extracts medications with RxNorm codes from the fixture."""
        entities = self._run_mapper(mapper, adapter)
        meds = [e for e in entities if e["_entity_type"] == "PersonaMedication"]
        assert len(meds) >= 1
        rx_codes = [m.get("rx_norm_code") for m in meds if m.get("rx_norm_code")]
        assert len(rx_codes) >= 1

    def test_medication_has_expected_rx_norm_codes(self, mapper, adapter):
        """Medications include Metformin (860975) and Lisinopril (29046) from fixture."""
        entities = self._run_mapper(mapper, adapter)
        meds = [e for e in entities if e["_entity_type"] == "PersonaMedication"]
        rx_codes = {m.get("rx_norm_code") for m in meds if m.get("rx_norm_code")}
        assert "860975" in rx_codes  # Metformin 500mg
        assert "29046" in rx_codes   # Lisinopril 10mg

    def test_medication_has_dosage(self, mapper, adapter):
        """Medications have dosage fields populated."""
        entities = self._run_mapper(mapper, adapter)
        meds = [e for e in entities if e["_entity_type"] == "PersonaMedication"]
        with_dose = [m for m in meds if m.get("dose_value") is not None]
        assert len(with_dose) >= 1

    def test_encounter_extraction(self, mapper, adapter):
        """Mapper extracts encounters with type and location."""
        entities = self._run_mapper(mapper, adapter)
        encounters = [e for e in entities if e["_entity_type"] == "PersonaEncounter"]
        assert len(encounters) >= 1
        enc = encounters[0]
        assert enc.get("encounter_type") is not None
        assert enc.get("period_start") is not None

    def test_encounter_has_provider(self, mapper, adapter):
        """Encounters include provider information."""
        entities = self._run_mapper(mapper, adapter)
        encounters = [e for e in entities if e["_entity_type"] == "PersonaEncounter"]
        enc = encounters[0]
        providers = enc.get("providers", [])
        assert len(providers) >= 1

    def test_encounter_has_reason_codes(self, mapper, adapter):
        """Encounters include ICD-10 reason codes."""
        entities = self._run_mapper(mapper, adapter)
        encounters = [e for e in entities if e["_entity_type"] == "PersonaEncounter"]
        enc = encounters[0]
        reason_codes = enc.get("reason_codes", [])
        assert len(reason_codes) >= 1
        assert reason_codes[0].get("code") == "E11.9"

    def test_allergy_extraction(self, mapper, adapter):
        """Mapper extracts allergy with allergen name and RxNorm code."""
        entities = self._run_mapper(mapper, adapter)
        allergies = [e for e in entities if e["_entity_type"] == "PersonaAllergy"]
        assert len(allergies) >= 1
        alg = allergies[0]
        assert alg.get("allergen_name") is not None

    def test_allergy_has_reactions(self, mapper, adapter):
        """Allergies include reaction information from fixture."""
        entities = self._run_mapper(mapper, adapter)
        allergies = [e for e in entities if e["_entity_type"] == "PersonaAllergy"]
        alg = allergies[0]
        reactions = alg.get("reactions", [])
        assert len(reactions) >= 1
        assert reactions[0].get("manifestation") is not None

    def test_all_entities_have_uuid_ids(self, mapper, adapter):
        """Every entity gets a Brook-generated UUID id."""
        import re
        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        )
        entities = self._run_mapper(mapper, adapter)
        for entity in entities:
            assert uuid_pattern.match(entity.get("id", "")), (
                f"Entity {entity['_entity_type']} id={entity.get('id')!r} "
                "is not a valid UUID"
            )


# ──────────────────────────────────────────────────────────────────────────────
# Layer 3 — Platform layer
# ──────────────────────────────────────────────────────────────────────────────

class TestClinicalStore:
    """Tests for Layer 3: ClinicalStore entity persistence."""

    def _get_entities(self, mapper, adapter):
        ccda_result = adapter.get_ccda(patient_id="PAT-001")
        return mapper.map(
            ccda_xml=ccda_result["xml"],
            patient_id="PAT-001",
            provider_office_id="PO-42",
            idempotency_key=ccda_result["idempotency_key"],
        )

    def test_write_batch_stores_all_entity_types(self, mapper, adapter, store):
        """ClinicalStore writes all four entity types successfully."""
        entities = self._get_entities(mapper, adapter)
        written_ids, dup_ids = store.write_batch(entities)
        assert len(written_ids) > 0
        assert len(dup_ids) == 0

        all_stored = store.get_all_entities()
        stored_types = {e.get("_entity_type") for e in all_stored
                        if "_entity_type" in e}
        # _entity_type is stripped on write — check collection counts instead
        assert store.count("persona_problems") >= 1
        assert store.count("persona_medications") >= 1
        assert store.count("persona_encounters") >= 1
        assert store.count("persona_allergies") >= 1

    def test_stored_entities_have_source_field(self, mapper, adapter, store):
        """All stored entities have source=ATHENA_CCDA."""
        entities = self._get_entities(mapper, adapter)
        store.write_batch(entities)
        all_stored = store.get_all_entities()
        for entity in all_stored:
            assert entity.get("source") == ATHENA_CCDA_SOURCE, (
                f"Stored entity missing source or has wrong value: {entity.get('source')!r}"
            )

    def test_stored_entities_do_not_contain_internal_fields(self, mapper, adapter, store):
        """Internal POC fields (_entity_type, _idempotency_key) are stripped on write."""
        entities = self._get_entities(mapper, adapter)
        store.write_batch(entities)
        all_stored = store.get_all_entities()
        for entity in all_stored:
            for key in entity:
                assert not key.startswith("_"), (
                    f"Internal field {key!r} leaked into stored entity"
                )


class TestEventPublisher:
    """Tests for Layer 3: EventPublisher event emission."""

    def _get_entities(self, mapper, adapter):
        ccda_result = adapter.get_ccda(patient_id="PAT-001")
        return mapper.map(
            ccda_xml=ccda_result["xml"],
            patient_id="PAT-001",
            provider_office_id="PO-42",
            idempotency_key=ccda_result["idempotency_key"],
        )

    def test_events_emitted_for_each_entity(self, mapper, adapter, store, bus, publisher):
        """An integration event is emitted for every new entity written."""
        entities = self._get_entities(mapper, adapter)
        written_ids, dup_ids = store.write_batch(entities)
        publisher.emit_batch(entities, duplicate_ids=dup_ids)

        events = bus.get_events()
        assert len(events) == len(written_ids)

    def test_event_names_follow_naming_convention(self, mapper, adapter, store, bus, publisher):
        """Events follow the CCDA_{EntityType}_INGESTED naming pattern."""
        entities = self._get_entities(mapper, adapter)
        _written, dup_ids = store.write_batch(entities)
        publisher.emit_batch(entities, duplicate_ids=dup_ids)

        for event in bus.get_events():
            assert event.event_name.startswith("CCDA_"), (
                f"Event name {event.event_name!r} does not follow CCDA_ convention"
            )
            assert event.event_name.endswith("_INGESTED"), (
                f"Event name {event.event_name!r} does not end with _INGESTED"
            )

    def test_event_source_is_athena_ccda(self, mapper, adapter, store, bus, publisher):
        """All events carry source=ATHENA_CCDA."""
        entities = self._get_entities(mapper, adapter)
        _written, dup_ids = store.write_batch(entities)
        publisher.emit_batch(entities, duplicate_ids=dup_ids)

        for event in bus.get_events():
            assert event.source == ATHENA_CCDA_SOURCE

    def test_events_have_idempotency_key(self, mapper, adapter, store, bus, publisher):
        """All events carry the CCDA-level idempotency key."""
        entities = self._get_entities(mapper, adapter)
        _written, dup_ids = store.write_batch(entities)
        publisher.emit_batch(entities, duplicate_ids=dup_ids)

        for event in bus.get_events():
            assert event.idempotency_key is not None
            assert event.idempotency_key.startswith("ccda-inbound:")

    def test_events_cover_all_four_entity_types(self, mapper, adapter, store, bus, publisher):
        """Events are emitted for all four entity types extracted from the CCDA."""
        entities = self._get_entities(mapper, adapter)
        _written, dup_ids = store.write_batch(entities)
        publisher.emit_batch(entities, duplicate_ids=dup_ids)

        event_entity_types = {e.entity_type for e in bus.get_events()}
        assert "PersonaProblem" in event_entity_types
        assert "PersonaMedication" in event_entity_types
        assert "PersonaEncounter" in event_entity_types
        assert "PersonaAllergy" in event_entity_types


# ──────────────────────────────────────────────────────────────────────────────
# Full vertical slice — end-to-end
# ──────────────────────────────────────────────────────────────────────────────

class TestCCDAVerticalSlice:
    """End-to-end test of the complete CCDA inbound vertical slice."""

    def test_full_slice_produces_entities_events_and_store_writes(
        self, adapter, mapper, store, bus, publisher
    ):
        """
        Full three-layer vertical slice:
          Layer 1: AthenaAdapter retrieves CCDA XML with idempotency key
          Layer 2: CCDAMapper extracts clinical entities
          Layer 3: ClinicalStore writes entities; EventPublisher emits events

        Assertions:
          - Correct entity types are extracted
          - ATHENA_CCDA source is set on all entities
          - Idempotency key is present on all entities and events
          - Events are emitted for each extracted entity
        """
        # Layer 1
        ccda_result = adapter.get_ccda(patient_id="PAT-FULL-SLICE")
        assert ccda_result["idempotency_key"].startswith("ccda-inbound:")

        # Layer 2
        entities = mapper.map(
            ccda_xml=ccda_result["xml"],
            patient_id="PAT-FULL-SLICE",
            provider_office_id="PO-GRIFFIN",
            idempotency_key=ccda_result["idempotency_key"],
        )
        assert len(entities) > 0
        entity_types = {e["_entity_type"] for e in entities}
        assert {"PersonaProblem", "PersonaMedication", "PersonaEncounter", "PersonaAllergy"}.issubset(
            entity_types
        )
        for entity in entities:
            assert entity["source"] == ATHENA_CCDA_SOURCE
            assert entity.get("_idempotency_key") is not None

        # Layer 3 — store
        written_ids, dup_ids = store.write_batch(entities)
        assert len(written_ids) == len(entities)  # all new on first run
        assert len(dup_ids) == 0

        # Layer 3 — events
        results = publisher.emit_batch(entities, duplicate_ids=dup_ids)
        events = bus.get_events()
        assert len(events) == len(entities)
        for event in events:
            assert event.source == ATHENA_CCDA_SOURCE
            assert event.idempotency_key is not None
