"""
clinical_store.py — Layer 3: Clinical entity persistence.

This is the platform layer's clinical data store. It owns:
  - Writing extracted clinical entities to their respective Brook collections
  - Upsert-by-source-and-source-id idempotency (prevents duplicate writes on replay)
  - In-memory store for POC (production would write to MongoDB)

Brook context (from findings.md / data-model-gaps.md):

  Target MongoDB collections (proposed in spec/data-model-proposals/):
    persona_problems    — PersonaProblem (or persona.diagnoses[] for PersonaDiagnosis)
    persona_medications — PersonaMedication (new collection, parallel to care plan section)
    persona_encounters  — PersonaEncounter (new collection, MISSING from brook-backend)
    persona_allergies   — PersonaAllergy (new collection, current store is freetext in care plan)

  Idempotency pattern (from findings.md):
    Outbound idempotency uses EmrLog (MongoDB collection: redox_log) with compound
    unique index on (provider_office_id, persona_id, file_name, type).
    File: /tmp/brook-backend/src/main/java/ai/brook/api/rpm/emr/model/EmrLog.java
    and AthenaService.java:57-70

    For inbound CCDA, each proposed entity has a compound unique index on
    (persona_id, source, source_*_id) — see PersonaAllergy.java, PersonaEncounter.java,
    PersonaMedication.java. The upsert logic here mirrors that index:
      upsert key = (persona_id, source, source_entity_id)
    If the entity already exists at that key → skip write, signal is_duplicate=True
    to suppress the event in event_publisher.

  PersonaDiagnosis write path (from data-model-gaps.md):
    PersonaDiagnosis.java is confirmed merged (PAI-184) in brook-backend HEAD.
    File: /tmp/brook-backend/src/main/java/ai/brook/data/persona/diagnosis/PersonaDiagnosis.java
    ATHENA_CCDA source value is NOT yet in DiagnosisSource enum — must be added before
    production wiring. This store uses PersonaProblem as a distinct collection pending
    Backend team decision on persona.diagnoses[] as the canonical problem-list target.
    See data-model-gaps.md — Persistence Decision Question #1.
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class ClinicalStore:
    """
    In-memory clinical entity store that mirrors the MongoDB collection structure
    proposed in spec/data-model-proposals/*.java.

    The upsert-by-source-key pattern here maps directly to the @CompoundIndex
    annotations in the Java proposals:
      { 'persona_id': 1, 'source': 1, 'source_*_id': 1 }  unique=true, sparse=true

    Production implementation: replace _collections dict with MongoDB operations.
      write: collection.find_one_and_update(
          filter={"persona_id": ..., "source": ..., "source_X_id": ...},
          update={"$setOnInsert": entity_doc},
          upsert=True,
          return_document=False  # return pre-update doc to detect duplicate
      )
      If return_document is not None → is_duplicate = True (entity already existed)

    TODO: Replace in-memory store with real MongoDB client when wiring to brook-backend.
    """

    # Collection names match the COLLECTION_NAME constants in each Java proposal
    COLLECTIONS = {
        "PersonaProblem": "persona_problems",
        "PersonaMedication": "persona_medications",
        "PersonaEncounter": "persona_encounters",
        "PersonaAllergy": "persona_allergies",
        # PersonaDiagnosis is embedded in persona.diagnoses[] — not a separate collection
        # If Backend routes CCDA problem list to PersonaDiagnosis, update this map.
    }

    def __init__(self):
        # In-memory store: { collection_name: { entity_id: entity_dict } }
        self._collections: Dict[str, Dict[str, Dict[str, Any]]] = {
            name: {} for name in self.COLLECTIONS.values()
        }
        # Upsert key index: { collection_name: { upsert_key_tuple: entity_id } }
        self._key_index: Dict[str, Dict[Tuple, str]] = {
            name: {} for name in self.COLLECTIONS.values()
        }
        self._lock = threading.Lock()

    def write(self, entity: Dict[str, Any]) -> Tuple[bool, bool]:
        """
        Write a single entity to its collection with upsert-by-source-key semantics.

        Returns:
            (written: bool, is_duplicate: bool)
            - (True, False)  → entity is new, written successfully
            - (False, True)  → entity already existed (idempotent replay — no write)

        Upsert key: (persona_id, source, source_*_id)
          The source_*_id field name varies by entity type:
            PersonaProblem    → source_problem_id
            PersonaMedication → source_medication_id
            PersonaEncounter  → source_encounter_id
            PersonaAllergy    → source_allergy_id

        This mirrors the @CompoundIndex(unique=true) defined in each Java proposal.
        """
        entity_type = entity.get("_entity_type")
        collection_name = self.COLLECTIONS.get(entity_type)

        if collection_name is None:
            logger.warning(
                "clinical_store: unknown entity type %r — skipping write",
                entity_type,
            )
            return False, False

        upsert_key = self._build_upsert_key(entity, entity_type)
        entity_id = entity.get("id")

        with self._lock:
            collection = self._collections[collection_name]
            key_index = self._key_index[collection_name]

            if upsert_key in key_index:
                existing_id = key_index[upsert_key]
                logger.info(
                    "clinical_store: DUPLICATE detected — %s source_key=%s "
                    "already stored as entity_id=%s — skipping write (idempotent)",
                    entity_type, upsert_key, existing_id,
                )
                return False, True

            # New entity — write to store
            # Strip internal POC metadata fields before storing
            stored_entity = {k: v for k, v in entity.items() if not k.startswith("_")}
            stored_entity["stored_at"] = datetime.now(timezone.utc).isoformat()

            collection[entity_id] = stored_entity
            if upsert_key[2] is not None:  # only index if source_id is present
                key_index[upsert_key] = entity_id

            logger.info(
                "clinical_store: wrote %s entity_id=%s to %s "
                "(upsert_key=%s)",
                entity_type, entity_id, collection_name, upsert_key,
            )
            return True, False

    def write_batch(
        self, entities: List[Dict[str, Any]]
    ) -> Tuple[List[str], Set[str]]:
        """
        Write a batch of entities, collecting new entity IDs and duplicate IDs.

        Returns:
            (written_ids, duplicate_ids)
        """
        written_ids: List[str] = []
        duplicate_ids: Set[str] = set()

        for entity in entities:
            written, is_dup = self.write(entity)
            entity_id = entity.get("id")
            if written:
                written_ids.append(entity_id)
            elif is_dup:
                duplicate_ids.add(entity_id)

        logger.info(
            "clinical_store: batch write complete — written=%d, duplicates=%d",
            len(written_ids), len(duplicate_ids),
        )
        return written_ids, duplicate_ids

    def get_collection(self, collection_name: str) -> Dict[str, Dict[str, Any]]:
        """Return a snapshot of all entities in a collection (for testing)."""
        with self._lock:
            return dict(self._collections.get(collection_name, {}))

    def get_all_entities(self) -> List[Dict[str, Any]]:
        """Return all stored entities across all collections (for testing)."""
        with self._lock:
            result = []
            for collection in self._collections.values():
                result.extend(collection.values())
            return result

    def count(self, collection_name: Optional[str] = None) -> int:
        """Return entity count for a collection, or total across all collections."""
        with self._lock:
            if collection_name:
                return len(self._collections.get(collection_name, {}))
            return sum(len(c) for c in self._collections.values())

    def clear(self) -> None:
        """Clear all stored entities and key indexes (useful between test runs)."""
        with self._lock:
            for name in self._collections:
                self._collections[name].clear()
                self._key_index[name].clear()
        logger.debug("clinical_store: cleared all collections")

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _build_upsert_key(
        self, entity: Dict[str, Any], entity_type: str
    ) -> Tuple[str, str, Optional[str]]:
        """
        Build the compound upsert key for an entity.

        Key structure: (persona_id, source, source_entity_id)
        Matches the @CompoundIndex annotation in each Java proposal.
        """
        persona_id = entity.get("persona_id", "UNKNOWN")
        source = entity.get("source", "UNKNOWN")

        # Source ID field name varies by entity type (mirrors Java field naming)
        source_id_field_map = {
            "PersonaProblem": "source_problem_id",
            "PersonaMedication": "source_medication_id",
            "PersonaEncounter": "source_encounter_id",
            "PersonaAllergy": "source_allergy_id",
        }
        source_id_field = source_id_field_map.get(entity_type, "source_id")
        source_id = entity.get(source_id_field)

        return (persona_id, source, source_id)
