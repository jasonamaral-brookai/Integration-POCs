# CCDA Inbound POC — GET Patient CCDA from athena

**Pillar:** CCDA Inbound (Phase 1a)
**Status:** Not validated against athena sandbox — credentials required.

---

## Athena endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/oauth2/v1/token` | Acquire access token |
| GET | `/v1/{practiceid}/patients/{patientid}/ccda` | Retrieve CCDA document |

**Endpoint path note:** The build plan cites `/v1/{practiceid}/ccda/{patientid}/ccda`. The more conventional REST form is `/v1/{practiceid}/patients/{patientid}/ccda`. Both are marked `# TODO: verify endpoint path against athena developer docs` in the code. Sandbox validation is required to confirm the exact path.

---

## Request shape

```
GET https://api.preview.platform.athenahealth.com/v1/{practiceid}/patients/{patientid}/ccda
Authorization: Bearer <access_token>
Accept: application/xml, text/xml
```

No request body. `practiceid` and `patientid` are path parameters.

---

## Response shape

athena returns a C-CDA R2.1 XML document (HL7 ClinicalDocument schema). Key envelope fields:

```xml
<ClinicalDocument xmlns="urn:hl7-org:v3">
  <id extension="{document_id}" root="{oid}"/>
  <effectiveTime value="{YYYYMMDDHHMMSS}"/>
  <recordTarget>
    <patientRole>
      <patient>
        <name>
          <given>{first_name}</given>
          <family>{last_name}</family>
        </name>
        <birthTime value="{YYYYMMDD}"/>
      </patient>
    </patientRole>
  </recordTarget>
  <component>
    <structuredBody>
      <!-- Sections: encounters, medications, problems, allergies, results -->
    </structuredBody>
  </component>
</ClinicalDocument>
```

Key sections (by LOINC section code):
| LOINC | Section | Brook target model |
|-------|---------|-------------------|
| 46240-8 | Encounters | PersonaEncounter (MISSING — new collection required) |
| 10160-0 | Medications | PersonaMedication (PARTIAL — no RxNorm in current model) |
| 11450-4 | Problem List | persona.diagnoses[] or PatientCarePlans.problemList (duality unresolved) |
| 48765-2 | Allergies | PersonaAllergy (PARTIAL — free text only) |
| 30954-2 | Lab Results | PersonaLab (MISSING — no EHR lab store) |
| 8716-3 | Vitals | activity collection (PARTIAL — no ATHENA_CCDA source type) |

---

## Failure modes

| Scenario | athena response |
|----------|----------------|
| Invalid/expired token | HTTP 401 |
| Patient not found | HTTP 404 |
| Practice not found or unauthorized | HTTP 403 or 404 |
| CCDA not available (no clinical data) | HTTP 404 or empty document — confirm in sandbox |
| Rate limited | HTTP 429 with `Retry-After` header |

---

## Greenfield status

From recon (`findings.md` Phase 1a section):
- Zero existing CCDA handling anywhere in brook-backend, care-nexus, or data-platform.
- No CDA parser library dependency found in any repo.
- `AthenaApiService` OAuth2 client can be reused for the GET call — no new auth infrastructure.
- POCAR trigger (nurse opens chart → fresh CCDA pull) requires both a new API endpoint in brook-backend AND a UI change in `brook-web-app` (Angular).

The `last_pocar_opened_at` timestamp in care-nexus (`/tmp/care-nexus/services/cdc-consumer/internal/rules/next_eval.go:50`) already propagates on chart open. That is the natural hook for the CCDA pull trigger but nothing downstream of it triggers a data fetch today.

---

## Data model gaps (from data-model-gaps.md)

Before CCDA ingest can write any data to Brook:

1. `DiagnosisSource.ATHENA_CCDA` must be added to the enum (1-2 hours, no migration).
2. `PersonaEncounter` collection must be created (new `@Document` class).
3. Persistence decision: is `persona.diagnoses[]` canonical for problem list? Or do both `diagnoses[]` and `PatientCarePlans.problemList` stay?
4. `PersonaMedication`, `PersonaAllergy`, `PersonaLab` collections or model extensions needed before CCDA mapper can write structured clinical data.

---

## Assumptions requiring sandbox validation

1. Endpoint path: `/v1/{practiceid}/patients/{patientid}/ccda` vs. `/v1/{practiceid}/ccda/{patientid}` — confirm in sandbox.
2. Response content type: `application/xml` or `text/xml` — confirm header.
3. Whether athena returns HTTP 404 or an empty document when no CCDA is available.
4. Document size range for Griffin patients (affects timeout settings).
5. Whether the CCDA endpoint requires a specific `departmentid` query parameter.

---

## Running the POC

```bash
# Dry run
python poc.py --dry-run

# Live run
export ATHENA_CLIENT_ID=your_client_id
export ATHENA_CLIENT_SECRET=your_client_secret
export ATHENA_PRACTICE_ID=your_practice_id
python poc.py --patient-id 12345 --output-dir /tmp/ccda-test
```

---

## Blockers preventing end-to-end testing

Athena sandbox credentials not available in this environment. Use `--dry-run` to inspect request shape.
