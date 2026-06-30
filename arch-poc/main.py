"""
main.py — Entry point: runs the full CCDA inbound vertical slice.

Demonstrates the three-layer integration architecture end-to-end:
  Layer 1: AthenaAdapter (integration layer) — retrieves CCDA XML from athena
  Layer 2: CCDAMapper (mapping layer) — translates CCDA to Brook entity shapes
  Layer 3: ClinicalStore + EventPublisher (platform layer) — persists and emits events

Run: pip install -r requirements.txt && python main.py
"""

import logging
import sys
import os

# Ensure arch-poc root is on the path
sys.path.insert(0, os.path.dirname(__file__))

from integration_layer.auth import AthenaOAuth2Client
from integration_layer.athena_adapter import AthenaAdapter
from mapping_layer.ccda_mapper import CCDAMapper
from platform_layer.clinical_store import ClinicalStore
from platform_layer.event_publisher import EventPublisher, InMemoryEventBus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


def run_ccda_inbound_slice(
    patient_id: str,
    practice_id: str,
    provider_office_id: str,
    store: ClinicalStore,
    publisher: EventPublisher,
) -> dict:
    """
    Execute the full CCDA inbound vertical slice for one patient.

    Returns a summary dict with counts for observability.
    """

    logger.info("=" * 60)
    logger.info("CCDA INBOUND SLICE: patient=%s practice=%s", patient_id, practice_id)
    logger.info("=" * 60)

    # ──────────────────────────────────────────────────────────────
    # Layer 1 — Integration layer: retrieve CCDA from athena
    # ──────────────────────────────────────────────────────────────
    logger.info("[Layer 1] AthenaAdapter: acquiring bearer token...")
    auth_client = AthenaOAuth2Client(
        client_id=os.environ.get("ATHENA_CLIENT_ID", "mock-client-id"),
        client_secret=os.environ.get("ATHENA_CLIENT_SECRET", "mock-client-secret"),
        practice_id=practice_id,
    )
    adapter = AthenaAdapter(
        practice_id=practice_id,
        auth_client=auth_client,
        max_retries=3,
    )

    logger.info("[Layer 1] AthenaAdapter: fetching CCDA for patient %s...", patient_id)
    ccda_result = adapter.get_ccda(patient_id=patient_id)

    logger.info(
        "[Layer 1] Retrieved CCDA XML (%d chars), idempotency_key=%s",
        len(ccda_result["xml"]),
        ccda_result["idempotency_key"],
    )

    # ──────────────────────────────────────────────────────────────
    # Layer 2 — Mapping layer: parse CCDA and extract clinical entities
    # ──────────────────────────────────────────────────────────────
    logger.info("[Layer 2] CCDAMapper: parsing CCDA sections...")
    mapper = CCDAMapper(partner_key="athena")
    entities = mapper.map(
        ccda_xml=ccda_result["xml"],
        patient_id=patient_id,
        provider_office_id=provider_office_id,
        idempotency_key=ccda_result["idempotency_key"],
    )

    by_type: dict = {}
    for entity in entities:
        t = entity["_entity_type"]
        by_type[t] = by_type.get(t, 0) + 1

    logger.info(
        "[Layer 2] Extracted %d entities: %s",
        len(entities),
        ", ".join(f"{t}={n}" for t, n in sorted(by_type.items())),
    )

    for entity in entities:
        t = entity["_entity_type"]
        if t == "PersonaProblem":
            logger.info(
                "  > Problem: %s (%s)",
                entity.get("display_name"), entity.get("icd10_code"),
            )
        elif t == "PersonaMedication":
            logger.info(
                "  > Medication: %s [RxNorm: %s]",
                entity.get("medication_name"), entity.get("rx_norm_code"),
            )
        elif t == "PersonaEncounter":
            logger.info(
                "  > Encounter: %s on %s at %s",
                entity.get("encounter_type"),
                entity.get("period_start"),
                entity.get("location_name"),
            )
        elif t == "PersonaAllergy":
            logger.info(
                "  > Allergy: %s (status=%s)",
                entity.get("allergen_name"), entity.get("clinical_status"),
            )

    # ──────────────────────────────────────────────────────────────
    # Layer 3 — Platform layer: persist entities and emit events
    # ──────────────────────────────────────────────────────────────
    logger.info("[Layer 3] ClinicalStore: writing %d entities...", len(entities))
    written_ids, dup_ids = store.write_batch(entities)

    logger.info(
        "[Layer 3] Store result: written=%d, duplicates=%d",
        len(written_ids), len(dup_ids),
    )

    logger.info("[Layer 3] EventPublisher: emitting integration events...")
    event_results = publisher.emit_batch(entities, duplicate_ids=dup_ids)
    emitted = [r for r in event_results if r is not None]
    suppressed = [r for r in event_results if r is None]

    logger.info(
        "[Layer 3] Events: emitted=%d, suppressed (replay)=%d",
        len(emitted), len(suppressed),
    )

    logger.info("=" * 60)
    logger.info("CCDA INBOUND SLICE COMPLETE")
    logger.info("=" * 60)

    return {
        "patient_id": patient_id,
        "entities_extracted": len(entities),
        "entities_written": len(written_ids),
        "entities_duplicated": len(dup_ids),
        "events_emitted": len(emitted),
        "events_suppressed": len(suppressed),
        "by_type": by_type,
    }


def main():
    """
    Entry point: runs the CCDA inbound slice once, then again to demonstrate idempotency.
    """
    bus = InMemoryEventBus()
    store = ClinicalStore()
    publisher = EventPublisher(bus=bus)

    practice_id = "195900"   # Griffin Faculty Practice (example)
    provider_office_id = "PO-GRIFFIN-001"

    # ──────────────────────────────────────────────────────────────
    # Run 1: first ingest — all entities written, all events emitted
    # ──────────────────────────────────────────────────────────────
    print("\n--- RUN 1: Initial CCDA ingest ---")
    summary1 = run_ccda_inbound_slice(
        patient_id="PAT-DEMO-001",
        practice_id=practice_id,
        provider_office_id=provider_office_id,
        store=store,
        publisher=publisher,
    )

    print(f"\nRun 1 summary:")
    print(f"  Entities extracted : {summary1['entities_extracted']}")
    print(f"  Entities written   : {summary1['entities_written']}")
    print(f"  Entities duplicated: {summary1['entities_duplicated']}")
    print(f"  Events emitted     : {summary1['events_emitted']}")
    print(f"  Events suppressed  : {summary1['events_suppressed']}")

    # ──────────────────────────────────────────────────────────────
    # Run 2: replay — same CCDA, same patient — idempotent
    # Expected: 0 writes, 0 events emitted (all suppressed)
    # ──────────────────────────────────────────────────────────────
    print("\n--- RUN 2: Replay (same CCDA, same patient — idempotency test) ---")
    summary2 = run_ccda_inbound_slice(
        patient_id="PAT-DEMO-001",
        practice_id=practice_id,
        provider_office_id=provider_office_id,
        store=store,
        publisher=publisher,
    )

    print(f"\nRun 2 summary (expected: 0 writes, 0 events emitted):")
    print(f"  Entities extracted : {summary2['entities_extracted']}")
    print(f"  Entities written   : {summary2['entities_written']}")
    print(f"  Entities duplicated: {summary2['entities_duplicated']}")
    print(f"  Events emitted     : {summary2['events_emitted']}")
    print(f"  Events suppressed  : {summary2['events_suppressed']}")

    # Verify idempotency
    assert summary2["entities_written"] == 0, (
        "Idempotency FAILED: duplicate entities were written on replay"
    )
    assert summary2["events_emitted"] == 0, (
        "Idempotency FAILED: events were emitted on replay"
    )

    print("\nIdempotency verified: no duplicate writes, no duplicate events on replay.")
    print(
        f"\nTotal events in bus (across both runs): {len(bus.get_events())}"
    )
    print(
        f"Total entities in store: {store.count()}"
    )


if __name__ == "__main__":
    main()
