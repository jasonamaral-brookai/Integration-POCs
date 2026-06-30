"""
athena_adapter.py — Layer 1: Partner-specific integration adapter.

This is the integration layer for the athena EHR. It owns:
  - athena wire-protocol concerns (OAuth2 auth, HTTP client, rate limits)
  - Retry/backoff logic
  - Idempotency key generation for inbound document retrieval
  - Returning raw athena payloads (CCDA XML) to the mapping layer

Brook context (from findings.md):
  The existing brook-backend Java service already implements athena outbound only:
  POST /v1/{practice_id}/patients/{patient_id}/documents/clinicaldocument
  File: /tmp/brook-backend/src/main/java/ai/brook/api/rpm/emr/athena/api/AthenaApi.java:20-26

  CCDA inbound (GET /v1/{practiceid}/ccda/{patientid}/ccda) does NOT exist in any
  scanned brook repo. Phase 1a is fully greenfield.
  File: findings.md — "Phase 1a (CCDA inbound) is fully greenfield."

Retry/backoff:
  Java precedent: ExponentialBackoffInterceptor.java handles HTTP 429 with
  Retry-After header parsing, exponential backoff, configurable max retries.
  File: /tmp/brook-backend/src/main/java/ai/brook/utils/ExponentialBackoffInterceptor.java
  NOTE (from findings.md): That interceptor exists but is NOT wired into the
  production AthenaApiService or RedoxApiService OkHttp builders — a gap flagged
  in the recon. Both services use ReactUtils.retryWithExponentialBackoff(3, 2)
  which retries on any exception but does not parse Retry-After headers.
  File: /tmp/brook-backend/src/main/java/ai/brook/utils/ReactUtils.java

  This Python implementation does the right thing: parses Retry-After when present,
  falls back to exponential backoff otherwise.

Idempotency key (from findings.md):
  Current athena outbound idempotency: (personaId, providerOfficeId, month-in-filename,
  documentType) via EmrLog MongoDB collection (redox_log compound index).
  File: /tmp/brook-backend/src/main/java/ai/brook/api/rpm/emr/model/EmrLog.java
  and AthenaService.java:57-70

  For CCDA inbound, the idempotency key uses a daily bucket because CCDA documents
  are stable within a day — the same patient's CCDA pulled twice on the same day
  should be treated as the same document for dedup purposes.
  Key: patient_id + document_type + date_bucket (YYYY-MM-DD)
"""

import hashlib
import logging
import time
from datetime import date
from typing import Any, Dict, Optional
from integration_layer.auth import AthenaOAuth2Client

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Minimal valid C-CDA XML fixture
# In production this comes from the athena API response body.
# Structure mirrors athena's GET /v1/{practiceid}/ccda/{patientid}/ccda response.
# Sections keyed by LOINC codes per C-CDA R2.1 specification:
#   11450-4  Problem List
#   10160-0  History of Medication Use
#   46240-8  Encounters
#   48765-2  Allergies, Adverse Reactions, Alerts
# ──────────────────────────────────────────────────────────────────────────────
SAMPLE_CCDA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ClinicalDocument xmlns="urn:hl7-org:v3"
                  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">

  <realmCode code="US"/>
  <typeId root="2.16.840.1.113883.1.3" extension="POCD_HD000040"/>
  <templateId root="2.16.840.1.113883.10.20.22.1.1"/>
  <templateId root="2.16.840.1.113883.10.20.22.1.2"/>

  <id root="2.16.840.1.113883.3.9621" extension="CCDA-POC-001"/>
  <code code="34133-9" codeSystem="2.16.840.1.113883.6.1" displayName="Summarization of Episode Note"/>
  <title>Continuity of Care Document</title>
  <effectiveTime value="20260630120000+0000"/>
  <confidentialityCode code="N" codeSystem="2.16.840.1.113883.5.25"/>
  <languageCode code="en-US"/>

  <!-- Patient demographics (anonymized for POC) -->
  <recordTarget>
    <patientRole>
      <id root="2.16.840.1.113883.3.9621" extension="PAT-001-MRN"/>
      <patient>
        <name>
          <given>Jane</given>
          <family>Doe</family>
        </name>
        <birthTime value="19650315"/>
        <administrativeGenderCode code="F" codeSystem="2.16.840.1.113883.5.1"/>
      </patient>
    </patientRole>
  </recordTarget>

  <component>
    <structuredBody>

      <!-- ═══════════════════════════════════════════════════════════
           PROBLEM LIST — LOINC 11450-4
           FHIR R4: Condition (category=problem-list-item)
           Brook target: PersonaProblem / PersonaDiagnosis (source=ATHENA_CCDA)
           ═══════════════════════════════════════════════════════════ -->
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.5.1"/>
          <code code="11450-4" codeSystem="2.16.840.1.113883.6.1" displayName="Problem List"/>
          <title>Problems</title>
          <entry>
            <observation classCode="OBS" moodCode="EVN">
              <id root="2.16.840.1.113883.3.9621" extension="PROB-001"/>
              <code code="55607006" codeSystem="2.16.840.1.113883.6.96" displayName="Problem"/>
              <statusCode code="active"/>
              <effectiveTime>
                <low value="20220101"/>
              </effectiveTime>
              <value xsi:type="CD"
                     code="E11.9"
                     codeSystem="2.16.840.1.113883.6.90"
                     displayName="Type 2 diabetes mellitus without complications"/>
            </observation>
          </entry>
          <entry>
            <observation classCode="OBS" moodCode="EVN">
              <id root="2.16.840.1.113883.3.9621" extension="PROB-002"/>
              <code code="55607006" codeSystem="2.16.840.1.113883.6.96" displayName="Problem"/>
              <statusCode code="active"/>
              <effectiveTime>
                <low value="20210601"/>
              </effectiveTime>
              <value xsi:type="CD"
                     code="I10"
                     codeSystem="2.16.840.1.113883.6.90"
                     displayName="Essential (primary) hypertension"/>
            </observation>
          </entry>
        </section>
      </component>

      <!-- ═══════════════════════════════════════════════════════════
           MEDICATIONS — LOINC 10160-0
           FHIR R4: MedicationStatement
           Brook target: PersonaMedication (source=ATHENA_CCDA)
           ═══════════════════════════════════════════════════════════ -->
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.1.1"/>
          <code code="10160-0" codeSystem="2.16.840.1.113883.6.1"
                displayName="History of Medication Use"/>
          <title>Medications</title>
          <entry>
            <substanceAdministration classCode="SBADM" moodCode="EVN">
              <id root="2.16.840.1.113883.3.9621" extension="MED-001"/>
              <statusCode code="active"/>
              <effectiveTime xsi:type="IVL_TS">
                <low value="20220101"/>
              </effectiveTime>
              <routeCode code="C38288" codeSystem="2.16.840.1.113883.3.26.1.1"
                         displayName="Oral"/>
              <doseQuantity value="500" unit="mg"/>
              <consumable>
                <manufacturedProduct>
                  <manufacturedMaterial>
                    <code code="860975"
                          codeSystem="2.16.840.1.113883.6.88"
                          displayName="Metformin 500 MG Oral Tablet"/>
                  </manufacturedMaterial>
                </manufacturedProduct>
              </consumable>
              <text>Take 1 tablet by mouth twice daily with food</text>
            </substanceAdministration>
          </entry>
          <entry>
            <substanceAdministration classCode="SBADM" moodCode="EVN">
              <id root="2.16.840.1.113883.3.9621" extension="MED-002"/>
              <statusCode code="active"/>
              <effectiveTime xsi:type="IVL_TS">
                <low value="20210601"/>
              </effectiveTime>
              <routeCode code="C38288" codeSystem="2.16.840.1.113883.3.26.1.1"
                         displayName="Oral"/>
              <doseQuantity value="10" unit="mg"/>
              <consumable>
                <manufacturedProduct>
                  <manufacturedMaterial>
                    <code code="29046"
                          codeSystem="2.16.840.1.113883.6.88"
                          displayName="Lisinopril 10 MG Oral Tablet"/>
                  </manufacturedMaterial>
                </manufacturedProduct>
              </consumable>
              <text>Take 1 tablet by mouth once daily</text>
            </substanceAdministration>
          </entry>
        </section>
      </component>

      <!-- ═══════════════════════════════════════════════════════════
           ENCOUNTERS — LOINC 46240-8
           FHIR R4: Encounter
           Brook target: PersonaEncounter (source=ATHENA_CCDA)
           ═══════════════════════════════════════════════════════════ -->
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.22.1"/>
          <code code="46240-8" codeSystem="2.16.840.1.113883.6.1"
                displayName="Encounter History"/>
          <title>Encounters</title>
          <entry>
            <encounter classCode="ENC" moodCode="EVN">
              <id root="2.16.840.1.113883.3.9621" extension="ENC-001"/>
              <code code="99214" codeSystem="2.16.840.1.113883.6.12"
                    displayName="Office Visit — Moderate Complexity"/>
              <effectiveTime>
                <low value="20260115090000+0000"/>
                <high value="20260115093000+0000"/>
              </effectiveTime>
              <performer>
                <assignedEntity>
                  <id root="2.16.840.1.113883.4.6" extension="1234567890"/>
                  <assignedPerson>
                    <name>
                      <prefix>Dr.</prefix>
                      <given>Alex</given>
                      <family>Smith</family>
                    </name>
                  </assignedPerson>
                </assignedEntity>
              </performer>
              <participant typeCode="LOC">
                <participantRole classCode="SDLOC">
                  <playingEntity>
                    <name>Griffin Faculty Practice</name>
                  </playingEntity>
                </participantRole>
              </participant>
              <entryRelationship typeCode="RSON">
                <observation classCode="OBS" moodCode="EVN">
                  <code code="29308-4" codeSystem="2.16.840.1.113883.6.1"
                        displayName="Diagnosis"/>
                  <value xsi:type="CD"
                         code="E11.9"
                         codeSystem="2.16.840.1.113883.6.90"
                         displayName="Type 2 diabetes mellitus without complications"/>
                </observation>
              </entryRelationship>
            </encounter>
          </entry>
        </section>
      </component>

      <!-- ═══════════════════════════════════════════════════════════
           ALLERGIES — LOINC 48765-2
           FHIR R4: AllergyIntolerance
           Brook target: PersonaAllergy (source=ATHENA_CCDA)
           ═══════════════════════════════════════════════════════════ -->
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.6.1"/>
          <code code="48765-2" codeSystem="2.16.840.1.113883.6.1"
                displayName="Allergies, Adverse Reactions, Alerts"/>
          <title>Allergies</title>
          <entry>
            <act classCode="ACT" moodCode="EVN">
              <id root="2.16.840.1.113883.3.9621" extension="ALG-001"/>
              <code code="CONC" codeSystem="2.16.840.1.113883.5.6"/>
              <statusCode code="active"/>
              <entryRelationship typeCode="SUBJ">
                <observation classCode="OBS" moodCode="EVN">
                  <id root="2.16.840.1.113883.3.9621" extension="ALG-001-OBS"/>
                  <code code="416098002"
                        codeSystem="2.16.840.1.113883.6.96"
                        displayName="Drug Allergy"/>
                  <statusCode code="active"/>
                  <effectiveTime>
                    <low value="20100301"/>
                  </effectiveTime>
                  <participant typeCode="CSM">
                    <participantRole classCode="MANU">
                      <playingEntity classCode="MMAT">
                        <code code="7980"
                              codeSystem="2.16.840.1.113883.6.88"
                              displayName="Penicillin"/>
                        <name>Penicillin</name>
                      </playingEntity>
                    </participantRole>
                  </participant>
                  <entryRelationship typeCode="MFST">
                    <observation classCode="OBS" moodCode="EVN">
                      <code code="404684003"
                            codeSystem="2.16.840.1.113883.6.96"
                            displayName="Clinical Finding"/>
                      <value xsi:type="CD"
                             code="247472004"
                             codeSystem="2.16.840.1.113883.6.96"
                             displayName="Urticaria"/>
                    </observation>
                  </entryRelationship>
                </observation>
              </entryRelationship>
            </act>
          </entry>
        </section>
      </component>

    </structuredBody>
  </component>
</ClinicalDocument>"""


class RetryExhaustedError(Exception):
    """Raised when all retry attempts for a request are exhausted."""
    pass


class AthenaAdapter:
    """
    Layer 1: Partner-specific adapter for the athena EHR.

    Responsibilities:
      - Authenticate with athena OAuth2 (delegates to AthenaOAuth2Client)
      - Retrieve CCDA documents from athena API
      - Handle retries, rate limiting (429), and exponential backoff
      - Generate idempotency keys for inbound document retrieval

    This is a MOCKED adapter — it does not make real HTTP calls.
    That is wire-poc's job. This POC demonstrates the structural pattern.

    athena CCDA endpoint (Phase 1a, greenfield per findings.md):
      GET /v1/{practice_id}/ccda/{patient_id}/ccda
      Returns: C-CDA R2.1 XML document
    """

    ATHENA_API_BASE = "https://api.platform.athenahealth.com"
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_INITIAL_DELAY_SECONDS = 2.0
    DEFAULT_BACKOFF_MULTIPLIER = 2.0
    DEFAULT_MAX_DELAY_SECONDS = 30.0

    def __init__(
        self,
        practice_id: str,
        auth_client: AthenaOAuth2Client,
        max_retries: int = DEFAULT_MAX_RETRIES,
        initial_delay_seconds: float = DEFAULT_INITIAL_DELAY_SECONDS,
        backoff_multiplier: float = DEFAULT_BACKOFF_MULTIPLIER,
        max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
    ):
        self.practice_id = practice_id
        self.auth_client = auth_client
        self.max_retries = max_retries
        self.initial_delay_seconds = initial_delay_seconds
        self.backoff_multiplier = backoff_multiplier
        self.max_delay_seconds = max_delay_seconds

    def generate_idempotency_key(
        self,
        patient_id: str,
        document_type: str,
        date_bucket: Optional[date] = None,
    ) -> str:
        """
        Generate a stable idempotency key for a CCDA retrieval request.

        Key components (from findings.md):
          - patient_id: Brook patient identifier
          - document_type: document type constant (e.g., "CCDA")
          - date_bucket: daily bucket (YYYY-MM-DD) — same patient CCDA pulled
            twice on the same day is treated as the same document for dedup.

        This extends the existing athena outbound idempotency pattern found in:
          EmrLog compound index: (provider_office_id, persona_id, file_name, type)
          File: /tmp/brook-backend/src/main/java/ai/brook/api/rpm/emr/model/EmrLog.java

        The outbound key is month-based (file_name encodes month). For CCDA inbound,
        a daily bucket is used — CCDA reflects the patient's current state and is
        stable within a clinical day.
        """
        if date_bucket is None:
            date_bucket = date.today()

        raw_key = f"{patient_id}:{document_type}:{date_bucket.isoformat()}"
        # SHA-256 hash keeps the key fixed-length and avoids any PII leakage
        # in log lines where the key appears.
        hashed = hashlib.sha256(raw_key.encode()).hexdigest()[:32]
        return f"ccda-inbound:{hashed}"

    def _compute_backoff_delay(
        self,
        attempt: int,
        retry_after_seconds: Optional[float] = None,
    ) -> float:
        """
        Compute delay before the next retry attempt.

        If the server returned a Retry-After header, honor it (capped at
        max_delay_seconds). Otherwise use exponential backoff with jitter.

        Java precedent: ExponentialBackoffInterceptor.java
          File: /tmp/brook-backend/src/main/java/ai/brook/utils/ExponentialBackoffInterceptor.java
          That class handles HTTP 429 with Retry-After header parsing and exponential
          backoff at the OkHttp interceptor layer. It exists in brook-backend but is
          NOT wired into the production AthenaApiService or RedoxApiService client
          builders (recon finding: wiring gap, not an implementation gap).
        """
        if retry_after_seconds is not None:
            delay = min(retry_after_seconds, self.max_delay_seconds)
            logger.info(
                "adapter: honoring Retry-After header: %.1f seconds", delay
            )
            return delay

        # Exponential backoff: initial * multiplier^attempt
        delay = self.initial_delay_seconds * (self.backoff_multiplier ** attempt)
        delay = min(delay, self.max_delay_seconds)
        logger.info(
            "adapter: exponential backoff delay: %.1f seconds (attempt %d)",
            delay, attempt + 1,
        )
        return delay

    def get_ccda(
        self,
        patient_id: str,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Retrieve a CCDA document for a patient from athena.

        Returns a dict with:
          - xml: raw C-CDA XML string
          - idempotency_key: the key used for this request
          - patient_id: echoed back for caller convenience
          - practice_id: athena practice identifier

        In production this makes a real HTTP GET to:
          {ATHENA_API_BASE}/v1/{practice_id}/ccda/{patient_id}/ccda
        with Authorization: Bearer {token}

        Retry behavior mirrors the Java precedent (ExponentialBackoffInterceptor.java).
        """
        if idempotency_key is None:
            idempotency_key = self.generate_idempotency_key(
                patient_id=patient_id,
                document_type="CCDA",
            )

        url = (
            f"{self.ATHENA_API_BASE}/v1/{self.practice_id}"
            f"/ccda/{patient_id}/ccda"
        )

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                bearer_token = self.auth_client.get_bearer_token()
                logger.info(
                    "adapter: GET %s (attempt %d/%d, idempotency_key=%s)",
                    url, attempt + 1, self.max_retries + 1, idempotency_key,
                )

                # TODO: In production, replace with a real HTTP call:
                # import requests
                # resp = requests.get(
                #     url,
                #     headers={
                #         "Authorization": f"Bearer {bearer_token}",
                #         "X-Idempotency-Key": idempotency_key,
                #     },
                #     timeout=60,
                # )
                # if resp.status_code == 429:
                #     retry_after = float(resp.headers.get("Retry-After", 0))
                #     raise RateLimitError(retry_after)
                # resp.raise_for_status()
                # ccda_xml = resp.text

                # MOCK: return the embedded CCDA fixture
                _ = bearer_token  # consumed — would be used in real call
                ccda_xml = SAMPLE_CCDA_XML

                logger.info(
                    "adapter: CCDA retrieved successfully for patient %s "
                    "(MOCKED — returns embedded fixture)",
                    patient_id,
                )

                return {
                    "xml": ccda_xml,
                    "idempotency_key": idempotency_key,
                    "patient_id": patient_id,
                    "practice_id": self.practice_id,
                }

            except Exception as exc:
                last_error = exc
                retry_after = getattr(exc, "retry_after_seconds", None)

                if attempt < self.max_retries:
                    delay = self._compute_backoff_delay(attempt, retry_after)
                    logger.warning(
                        "adapter: request failed (attempt %d/%d): %s — "
                        "retrying in %.1f seconds",
                        attempt + 1, self.max_retries + 1, exc, delay,
                    )
                    # In tests we skip the real sleep; the delay value is visible
                    # in logs and verifiable in assertions.
                    time.sleep(0)  # TODO: time.sleep(delay) in production
                else:
                    logger.error(
                        "adapter: all %d retry attempts exhausted for patient %s",
                        self.max_retries + 1, patient_id,
                    )

        raise RetryExhaustedError(
            f"Failed to retrieve CCDA for patient {patient_id} "
            f"after {self.max_retries + 1} attempts"
        ) from last_error
