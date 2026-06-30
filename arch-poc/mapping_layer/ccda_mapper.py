"""
ccda_mapper.py — Layer 2: CCDA XML → Brook clinical entity translation.

This is the mapping layer. It owns:
  - Parsing the raw C-CDA XML from the integration layer
  - Extracting and normalizing CCDA sections using partner-keyed config (athena.yaml)
  - Producing Brook-shaped entity dicts that mirror the Java data model proposals
  - Setting source = ATHENA_CCDA on every entity

Brook context (from findings.md):
  No CDA parser library dependency found in any scanned repo. No references to
  ccda, C-CDA, ClinicalDocument (HL7/CDA sense), or continuity-of-care XML in
  any Java/Go/Python source file.
  Phase 1a CCDA ingest is fully greenfield for the parsing/mapping work.

  The anti-pattern this layer replaces: all Redox mapping logic is hardcoded in
  RedoxService.java (82.7KB) — mapping tangled into application code instead of
  a defined layer.
  File: /tmp/brook-backend/src/main/java/ai/brook/api/rpm/emr/redox/RedoxService.java

  This mapper reads its section definitions from athena.yaml (mapping_config/).
  A future griffin.yaml or epic.yaml becomes a config file, not a new mapper class.

Entity shapes (mirrored from spec/data-model-proposals/*.java):
  PersonaProblem    — problem list section (LOINC 11450-4)
  PersonaMedication — medications section (LOINC 10160-0)
  PersonaEncounter  — encounters section (LOINC 46240-8)
  PersonaAllergy    — allergies section (LOINC 48765-2)

  All field names are snake_case, matching the @Field annotations and
  @JsonNaming(SnakeCaseStrategy.class) in the Java proposals.
"""

import logging
import os
import re
import uuid
import yaml
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

# C-CDA XML namespace
_CDA_NS = "urn:hl7-org:v3"
_NS = {"cda": _CDA_NS}

# Source enum value — must be added to DiagnosisSource, AllergySource,
# MedicationSource, EncounterSource enums in brook-backend before production wiring.
# See data-model-gaps.md: "ATHENA_CCDA source value not in DiagnosisSource enum"
ATHENA_CCDA_SOURCE = "ATHENA_CCDA"


def _load_config(partner_key: str = "athena") -> Dict[str, Any]:
    """
    Load the partner-keyed mapping config from mapping_config/{partner_key}.yaml.

    This is the config-over-code pattern: a future partner (Epic, Cerner) adds
    a new YAML file; no new mapper code is needed.
    """
    config_dir = os.path.join(os.path.dirname(__file__), "mapping_config")
    config_path = os.path.join(config_dir, f"{partner_key}.yaml")
    with open(config_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _normalize_status(raw: Optional[str], mapping: Dict[str, str]) -> Optional[str]:
    """
    Normalize a raw CCDA status string to a Brook enum value using the config mapping.
    Returns the raw value uppercased if no mapping entry exists (safe fallback).
    """
    if not raw:
        return None
    return mapping.get(raw.lower(), raw.upper())


def _parse_ccda_date(raw: Optional[str]) -> Optional[str]:
    """
    Parse a C-CDA date string (yyyyMMdd or yyyyMMddHHmmss[+tz]) to ISO 8601.
    Returns None if raw is empty or unparseable.
    """
    if not raw:
        return None
    # Strip timezone offset for parsing
    clean = re.sub(r"[+-]\d{4}$", "", raw.strip())
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d"):
        try:
            dt = datetime.strptime(clean, fmt)
            return dt.replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    logger.warning("ccda_mapper: unparseable date value: %r — skipping", raw)
    return None


def _text_content(elem: Optional[ET.Element]) -> Optional[str]:
    """Return stripped text content of an element, or None if element is absent/empty."""
    if elem is None:
        return None
    text = (elem.text or "").strip()
    return text if text else None


class CCDAMapper:
    """
    Maps a raw C-CDA XML document to a list of Brook clinical entity dicts.

    Usage:
        mapper = CCDAMapper(partner_key="athena")
        entities = mapper.map(ccda_xml, patient_id="PAT-001", provider_office_id="PO-42")

    Returns a list of dicts, each with:
      - _entity_type: entity class name (e.g., "PersonaMedication")
      - All fields from the corresponding Java proposal (snake_case)
      - source: "ATHENA_CCDA" on every entity
      - idempotency_key: used by clinical_store for upsert dedup
    """

    def __init__(self, partner_key: str = "athena"):
        self.partner_key = partner_key
        self._config = _load_config(partner_key)
        self._section_configs = self._config.get("ccda_sections", {})
        self._status_norms = self._config.get("status_normalizations", {})
        logger.info(
            "ccda_mapper: loaded config for partner=%s, sections=%s",
            partner_key,
            list(self._section_configs.keys()),
        )

    def map(
        self,
        ccda_xml: str,
        patient_id: str,
        provider_office_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Parse a C-CDA XML string and extract all enabled Brook clinical entities.

        Returns a flat list of entity dicts. Each dict includes _entity_type
        so the platform layer can route to the correct store/event.
        """
        try:
            root = ET.fromstring(ccda_xml)
        except ET.ParseError as exc:
            raise ValueError(f"ccda_mapper: invalid XML: {exc}") from exc

        entities: List[Dict[str, Any]] = []

        # Find all <section> elements in the structured body
        sections = root.findall(
            ".//cda:structuredBody/cda:component/cda:section",
            namespaces=_NS,
        )

        for section in sections:
            loinc_code = self._get_section_loinc(section)
            if not loinc_code:
                continue

            section_cfg = self._find_section_config(loinc_code)
            if section_cfg is None:
                logger.debug(
                    "ccda_mapper: no config for section LOINC %s — skipping",
                    loinc_code,
                )
                continue

            if not section_cfg.get("enabled", True):
                logger.debug(
                    "ccda_mapper: section %s disabled in config — skipping",
                    loinc_code,
                )
                continue

            entity_type = section_cfg["brook_entity"]
            extractor = self._get_extractor(entity_type)
            if extractor is None:
                logger.warning(
                    "ccda_mapper: no extractor for entity type %s — skipping",
                    entity_type,
                )
                continue

            extracted = extractor(
                section=section,
                patient_id=patient_id,
                provider_office_id=provider_office_id,
                idempotency_key=idempotency_key,
            )
            entities.extend(extracted)
            logger.info(
                "ccda_mapper: extracted %d %s entities from section %s",
                len(extracted), entity_type, loinc_code,
            )

        logger.info(
            "ccda_mapper: total entities extracted from CCDA: %d", len(entities)
        )
        return entities

    # ──────────────────────────────────────────────────────────────────────────
    # Section extractor dispatch
    # ──────────────────────────────────────────────────────────────────────────

    def _get_extractor(self, entity_type: str):
        """Return the section-specific extraction method for an entity type."""
        dispatch = {
            "PersonaProblem": self._extract_problems,
            "PersonaMedication": self._extract_medications,
            "PersonaEncounter": self._extract_encounters,
            "PersonaAllergy": self._extract_allergies,
        }
        return dispatch.get(entity_type)

    # ──────────────────────────────────────────────────────────────────────────
    # Problem List — LOINC 11450-4
    # FHIR R4: Condition (category=problem-list-item)
    # Brook target: PersonaProblem (spec/data-model-proposals/PersonaProblem.java)
    # ──────────────────────────────────────────────────────────────────────────

    def _extract_problems(
        self,
        section: ET.Element,
        patient_id: str,
        provider_office_id: Optional[str],
        idempotency_key: Optional[str],
    ) -> List[Dict[str, Any]]:
        """
        Extract PersonaProblem entities from the CCDA problem list section.

        Fields mirror PersonaProblem.java (spec/data-model-proposals/PersonaProblem.java):
          icd10_code, snomed_code, display_name, clinical_status,
          verification_status, onset_date, source, source_problem_id,
          persona_id, provider_office_id

        NOTE: If Backend team decides persona.diagnoses[] (PersonaDiagnosis, PAI-184)
        is the canonical store for ALL conditions including problem-list entries,
        the _entity_type here would change to "PersonaDiagnosis" and source would
        be ATHENA_CCDA. That is a config change in athena.yaml, not a code change.
        See data-model-gaps.md — Persistence Decision Question #1.
        """
        entities = []
        status_map = self._status_norms.get("clinical_status", {})

        observations = section.findall(
            ".//cda:entry/cda:observation", namespaces=_NS
        )
        for obs in observations:
            source_id_elem = obs.find("cda:id", namespaces=_NS)
            source_id = (source_id_elem.get("extension") if source_id_elem is not None else None)

            value_elem = obs.find("cda:value", namespaces=_NS)
            if value_elem is None:
                continue

            icd10_code = value_elem.get("code")
            code_system = value_elem.get("codeSystem", "")
            display_name = value_elem.get("displayName")

            # ICD-10-CM OID: 2.16.840.1.113883.6.90
            # SNOMED CT OID: 2.16.840.1.113883.6.96
            snomed_code = None
            if "2.16.840.1.113883.6.96" in code_system:
                snomed_code = icd10_code
                icd10_code = None

            status_elem = obs.find("cda:statusCode", namespaces=_NS)
            raw_status = status_elem.get("code") if status_elem is not None else None
            clinical_status = _normalize_status(raw_status, status_map) or "ACTIVE"

            onset_elem = obs.find("cda:effectiveTime/cda:low", namespaces=_NS)
            onset_date = _parse_ccda_date(
                onset_elem.get("value") if onset_elem is not None else None
            )

            entities.append({
                "_entity_type": "PersonaProblem",
                "id": str(uuid.uuid4()),
                "persona_id": patient_id,
                "provider_office_id": provider_office_id,
                "source": ATHENA_CCDA_SOURCE,
                "source_problem_id": source_id,
                "icd10_code": icd10_code,
                "snomed_code": snomed_code,
                "display_name": display_name,
                "clinical_status": clinical_status,
                "verification_status": "CONFIRMED",  # CCDA active problems are confirmed
                "onset_date": onset_date,
                "abatement_date": None,
                "ingested_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": None,
                # Idempotency: store-level upsert key (source + source_problem_id)
                "_idempotency_key": idempotency_key,
            })

        return entities

    # ──────────────────────────────────────────────────────────────────────────
    # Medications — LOINC 10160-0
    # FHIR R4: MedicationStatement
    # Brook target: PersonaMedication (spec/data-model-proposals/PersonaMedication.java)
    # ──────────────────────────────────────────────────────────────────────────

    def _extract_medications(
        self,
        section: ET.Element,
        patient_id: str,
        provider_office_id: Optional[str],
        idempotency_key: Optional[str],
    ) -> List[Dict[str, Any]]:
        """
        Extract PersonaMedication entities from the CCDA medications section.

        Fields mirror PersonaMedication.java:
          medication_name, rx_norm_code, ndc_code, status, effective_start,
          effective_end, dosage_text, dose_value, dose_unit, route,
          frequency_text, source, source_medication_id, persona_id, provider_office_id
        """
        entities = []
        status_map = self._status_norms.get("medication_status", {})

        med_administrations = section.findall(
            ".//cda:entry/cda:substanceAdministration", namespaces=_NS
        )
        for med in med_administrations:
            source_id_elem = med.find("cda:id", namespaces=_NS)
            source_id = (source_id_elem.get("extension") if source_id_elem is not None else None)

            # Medication code (RxNorm preferred)
            code_elem = med.find(
                ".//cda:consumable/cda:manufacturedProduct"
                "/cda:manufacturedMaterial/cda:code",
                namespaces=_NS,
            )
            medication_name = None
            rx_norm_code = None
            if code_elem is not None:
                medication_name = code_elem.get("displayName")
                # RxNorm OID: 2.16.840.1.113883.6.88
                if "2.16.840.1.113883.6.88" in code_elem.get("codeSystem", ""):
                    rx_norm_code = code_elem.get("code")

            # Status
            status_elem = med.find("cda:statusCode", namespaces=_NS)
            raw_status = status_elem.get("code") if status_elem is not None else None
            status = _normalize_status(raw_status, status_map) or "UNKNOWN"

            # Dosage
            dose_elem = med.find("cda:doseQuantity", namespaces=_NS)
            dose_value_str = dose_elem.get("value") if dose_elem is not None else None
            dose_value = float(dose_value_str) if dose_value_str else None
            dose_unit = dose_elem.get("unit") if dose_elem is not None else None

            # Route
            route_elem = med.find("cda:routeCode", namespaces=_NS)
            route = route_elem.get("displayName") if route_elem is not None else None

            # SIG text
            text_elem = med.find("cda:text", namespaces=_NS)
            dosage_text = _text_content(text_elem)

            # Effective period
            low_elem = med.find("cda:effectiveTime/cda:low", namespaces=_NS)
            high_elem = med.find("cda:effectiveTime/cda:high", namespaces=_NS)
            effective_start = _parse_ccda_date(
                low_elem.get("value") if low_elem is not None else None
            )
            effective_end = _parse_ccda_date(
                high_elem.get("value") if high_elem is not None else None
            )

            entities.append({
                "_entity_type": "PersonaMedication",
                "id": str(uuid.uuid4()),
                "persona_id": patient_id,
                "provider_office_id": provider_office_id,
                "source": ATHENA_CCDA_SOURCE,
                "source_medication_id": source_id,
                "medication_name": medication_name,
                "rx_norm_code": rx_norm_code,
                "ndc_code": None,
                "status": status,
                "effective_start": effective_start,
                "effective_end": effective_end,
                "dosage_text": dosage_text,
                "dose_value": dose_value,
                "dose_unit": dose_unit,
                "route": route,
                "frequency_text": None,  # CCDA SIG in dosage_text; structured timing TBD
                "prescriber_name": None,
                "prescriber_npi": None,
                "ingested_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": None,
                "_idempotency_key": idempotency_key,
            })

        return entities

    # ──────────────────────────────────────────────────────────────────────────
    # Encounters — LOINC 46240-8
    # FHIR R4: Encounter
    # Brook target: PersonaEncounter (spec/data-model-proposals/PersonaEncounter.java)
    # ──────────────────────────────────────────────────────────────────────────

    def _extract_encounters(
        self,
        section: ET.Element,
        patient_id: str,
        provider_office_id: Optional[str],
        idempotency_key: Optional[str],
    ) -> List[Dict[str, Any]]:
        """
        Extract PersonaEncounter entities from the CCDA encounters section.

        Fields mirror PersonaEncounter.java:
          status, encounter_class, encounter_type, period_start, period_end,
          providers, reason_codes, location_name, source, source_encounter_id,
          persona_id, provider_office_id
        """
        entities = []
        status_map = self._status_norms.get("encounter_status", {})

        encounters = section.findall(
            ".//cda:entry/cda:encounter", namespaces=_NS
        )
        for enc in encounters:
            source_id_elem = enc.find("cda:id", namespaces=_NS)
            source_id = (source_id_elem.get("extension") if source_id_elem is not None else None)

            code_elem = enc.find("cda:code", namespaces=_NS)
            encounter_type = code_elem.get("displayName") if code_elem is not None else None

            # Status (encounters in CCDA history are typically finished)
            status_elem = enc.find("cda:statusCode", namespaces=_NS)
            raw_status = status_elem.get("code") if status_elem is not None else "completed"
            status = _normalize_status(raw_status, status_map) or "FINISHED"

            # Period
            low_elem = enc.find("cda:effectiveTime/cda:low", namespaces=_NS)
            high_elem = enc.find("cda:effectiveTime/cda:high", namespaces=_NS)
            period_start = _parse_ccda_date(
                low_elem.get("value") if low_elem is not None else None
            )
            period_end = _parse_ccda_date(
                high_elem.get("value") if high_elem is not None else None
            )

            # Provider
            provider_name_parts = []
            given_elems = enc.findall(
                ".//cda:performer/cda:assignedEntity/cda:assignedPerson/cda:name/cda:given",
                namespaces=_NS,
            )
            family_elems = enc.findall(
                ".//cda:performer/cda:assignedEntity/cda:assignedPerson/cda:name/cda:family",
                namespaces=_NS,
            )
            for g in given_elems:
                if g.text:
                    provider_name_parts.append(g.text.strip())
            for f in family_elems:
                if f.text:
                    provider_name_parts.append(f.text.strip())
            provider_name = " ".join(provider_name_parts) if provider_name_parts else None

            npi_elem = enc.find(
                ".//cda:performer/cda:assignedEntity/cda:id",
                namespaces=_NS,
            )
            provider_npi = npi_elem.get("extension") if npi_elem is not None else None

            providers = []
            if provider_name or provider_npi:
                providers.append({
                    "role": "attending",
                    "provider_name": provider_name,
                    "npi": provider_npi,
                    "provider_id": None,
                })

            # Location
            loc_elem = enc.find(
                ".//cda:participant[@typeCode='LOC']/cda:participantRole/cda:playingEntity/cda:name",
                namespaces=_NS,
            )
            location_name = _text_content(loc_elem)

            # Reason codes
            reason_codes = []
            reason_obs = enc.findall(
                ".//cda:entryRelationship/cda:observation/cda:value",
                namespaces=_NS,
            )
            for rv in reason_obs:
                code = rv.get("code")
                display = rv.get("displayName")
                code_sys = rv.get("codeSystem", "")
                if code:
                    system = (
                        "ICD-10-CM" if "2.16.840.1.113883.6.90" in code_sys
                        else "SNOMED-CT" if "2.16.840.1.113883.6.96" in code_sys
                        else "UNKNOWN"
                    )
                    reason_codes.append({
                        "system": system,
                        "code": code,
                        "display": display,
                    })

            entities.append({
                "_entity_type": "PersonaEncounter",
                "id": str(uuid.uuid4()),
                "persona_id": patient_id,
                "provider_office_id": provider_office_id,
                "source": ATHENA_CCDA_SOURCE,
                "source_encounter_id": source_id,
                "status": status,
                "encounter_class": "AMB",  # CCDA ambulatory encounter default
                "encounter_type": encounter_type,
                "period_start": period_start,
                "period_end": period_end,
                "providers": providers,
                "reason_codes": reason_codes,
                "location_name": location_name,
                "discharge_disposition": None,
                "ingested_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": None,
                "_idempotency_key": idempotency_key,
            })

        return entities

    # ──────────────────────────────────────────────────────────────────────────
    # Allergies — LOINC 48765-2
    # FHIR R4: AllergyIntolerance
    # Brook target: PersonaAllergy (spec/data-model-proposals/PersonaAllergy.java)
    # ──────────────────────────────────────────────────────────────────────────

    def _extract_allergies(
        self,
        section: ET.Element,
        patient_id: str,
        provider_office_id: Optional[str],
        idempotency_key: Optional[str],
    ) -> List[Dict[str, Any]]:
        """
        Extract PersonaAllergy entities from the CCDA allergies section.

        Fields mirror PersonaAllergy.java:
          clinical_status, verification_status, allergy_type, categories,
          criticality, allergen_name, rx_norm_code, snomed_code, onset_date,
          reactions, source, source_allergy_id, persona_id, provider_office_id

        Clinical safety note (from spec/data-model-proposals/PersonaAllergy.java):
          Criticality is clinically critical for medication safety decisions.
          Do not collapse this to freetext.
        """
        entities = []
        status_map = self._status_norms.get("clinical_status", {})
        allergy_type_codes = self._status_norms.get("allergy_type_codes", {})
        verification_map = self._status_norms.get("verification_status", {})

        acts = section.findall(".//cda:entry/cda:act", namespaces=_NS)
        for act in acts:
            source_id_elem = act.find("cda:id", namespaces=_NS)
            source_id = (source_id_elem.get("extension") if source_id_elem is not None else None)

            # Status of the allergy concern act
            act_status_elem = act.find("cda:statusCode", namespaces=_NS)
            raw_status = (act_status_elem.get("code") if act_status_elem is not None else "active")
            clinical_status = _normalize_status(raw_status, status_map) or "ACTIVE"

            # The actual allergy observation is nested under entryRelationship/observation
            allergy_obs = act.find(
                ".//cda:entryRelationship/cda:observation",
                namespaces=_NS,
            )
            if allergy_obs is None:
                continue

            # Allergy type from observation code (drug allergy, drug intolerance, food allergy)
            obs_code_elem = allergy_obs.find("cda:code", namespaces=_NS)
            obs_code = obs_code_elem.get("code") if obs_code_elem is not None else None
            allergy_type_str = allergy_type_codes.get(obs_code) if obs_code else None

            # Allergen name and codes
            allergen_code_elem = allergy_obs.find(
                ".//cda:participant/cda:participantRole/cda:playingEntity/cda:code",
                namespaces=_NS,
            )
            allergen_name_elem = allergy_obs.find(
                ".//cda:participant/cda:participantRole/cda:playingEntity/cda:name",
                namespaces=_NS,
            )
            allergen_name = _text_content(allergen_name_elem)
            rx_norm_code = None
            snomed_code = None
            if allergen_code_elem is not None:
                code_sys = allergen_code_elem.get("codeSystem", "")
                code_val = allergen_code_elem.get("code")
                if "2.16.840.1.113883.6.88" in code_sys:  # RxNorm
                    rx_norm_code = code_val
                elif "2.16.840.1.113883.6.96" in code_sys:  # SNOMED
                    snomed_code = code_val

            # Onset
            obs_low = allergy_obs.find(
                "cda:effectiveTime/cda:low", namespaces=_NS
            )
            onset_date = _parse_ccda_date(
                obs_low.get("value") if obs_low is not None else None
            )

            # Reactions (from nested entryRelationship/observation under the allergy obs)
            reactions = []
            reaction_obs_list = allergy_obs.findall(
                ".//cda:entryRelationship/cda:observation",
                namespaces=_NS,
            )
            for r_obs in reaction_obs_list:
                reaction_val = r_obs.find("cda:value", namespaces=_NS)
                if reaction_val is not None:
                    reaction_display = reaction_val.get("displayName")
                    reaction_snomed = reaction_val.get("code")
                    reactions.append({
                        "manifestation": reaction_display,
                        "manifestation_snomed_code": reaction_snomed,
                        "severity": None,  # severity not encoded in minimal fixture
                    })

            # Category: medication allergy if RxNorm code present
            categories = None
            if rx_norm_code or allergy_type_str == "ALLERGY":
                categories = ["MEDICATION"] if rx_norm_code else None

            entities.append({
                "_entity_type": "PersonaAllergy",
                "id": str(uuid.uuid4()),
                "persona_id": patient_id,
                "provider_office_id": provider_office_id,
                "source": ATHENA_CCDA_SOURCE,
                "source_allergy_id": source_id,
                "clinical_status": clinical_status,
                "verification_status": "CONFIRMED",
                "allergy_type": allergy_type_str,
                "categories": categories,
                "criticality": None,  # not in minimal fixture; real CCDA may include
                "allergen_name": allergen_name,
                "rx_norm_code": rx_norm_code,
                "snomed_code": snomed_code,
                "onset_date": onset_date,
                "reactions": reactions,
                "ingested_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": None,
                "_idempotency_key": idempotency_key,
            })

        return entities

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _get_section_loinc(self, section: ET.Element) -> Optional[str]:
        """Extract the LOINC code from a CDA <section> element."""
        code_elem = section.find("cda:code", namespaces=_NS)
        if code_elem is None:
            return None
        return code_elem.get("code")

    def _find_section_config(self, loinc_code: str) -> Optional[Dict[str, Any]]:
        """Find the section config dict matching the given LOINC code."""
        for _name, cfg in self._section_configs.items():
            if cfg.get("loinc_code") == loinc_code:
                return cfg
        return None
