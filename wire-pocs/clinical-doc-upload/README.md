# Clinical Document Upload POC — POST Clinical Document to athena

**Pillar:** Clinical Document Upload (Phase 1b)
**Status:** Not validated against athena sandbox — credentials required.

**IMPORTANT: This is live code.** `AthenaService.java` and `AthenaApi.java` in brook-backend already post monthly PDF care plan bundles to this exact endpoint for Griffin today. This POC is not greenfield — it is a reference implementation proving the parameterized form of what is already in production.

---

## Athena endpoint

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/{practiceid}/patients/{patientid}/documents/clinicaldocument` | Upload a clinical document (PDF) |

Endpoint confirmed from `AthenaApi.java` in brook-backend:
```java
@POST("v1/{practiceId}/patients/{patientId}/documents/clinicaldocument")
```

---

## Request shape

```
POST https://api.preview.platform.athenahealth.com/v1/{practiceid}/patients/{patientid}/documents/clinicaldocument
Authorization: Bearer <access_token>
Content-Type: multipart/form-data
X-Idempotency-Key: <compound-key>

[multipart body]
  file:             <PDF bytes>   (filename: care_plan_2026-06_{patient_id}.pdf)
  documentsubclass: CLINICALDOCUMENT
  autoclose:        true
  documenttypeid:   440672        (or any valid athena document type ID)
```

Key fields:
- `file` — the PDF document bytes with a content-disposition filename
- `documentsubclass` — must be `CLINICALDOCUMENT` for care plan documents
- `autoclose` — athena-side auto-close behavior; current production value is `true`
- `documenttypeid` — athena document type ID; determines how the document appears in the EHR

---

## HARDCODED_TODO_RISK

In `AthenaService.java` at line 65:
```java
.addFormDataPart("documenttypeid", "440672") // TODO: make this configurable or dynamic when needed
```

And at line 52:
```java
.addFormDataPart("documentsubclass", "CLINICALDOCUMENT")
```

`documentTypeId=440672` is the Griffin-specific bundle report document type. This hardcoding breaks for:
- Any non-Griffin athena partner that uses a different document type
- Any document category other than the monthly bundle report (e.g., escalation notes, individual care plan updates)

The build plan's mapping config schema is the fix: `documenttypeid` and `documentsubclass` should be read from a per-partner config file, not hardcoded. This POC accepts both as parameters to prove the parameterized contract.

---

## Response shape

```json
{
  "documentid": "12345678",
  "status": "OPEN"
}
```

Key fields:
- `documentid` — athena's document ID for the uploaded document (store in `EmrLog` for audit)
- `status` — document processing status in athena

athena may return HTTP 200 or 201 on success. Confirm exact response shape in sandbox.

---

## Idempotency

Current production idempotency: `EmrLog` MongoDB collection with unique compound index on `(provider_office_id, persona_id, file_name, type)` where `file_name` encodes the month.

This POC demonstrates the same pattern with SHA-256 of `persona:{id}:practice:{id}:doctype:{id}:period:{YYYY-MM}:v1`. The build plan's `{entity}:{event}:{version}` key format is more precise and should replace the filename-based key for the event-driven trigger path.

If athena returns HTTP 409, the upload is idempotent — the document was already received. Do not retry on 409.

---

## Failure modes

| Scenario | athena response |
|----------|----------------|
| Invalid/expired token | HTTP 401 |
| Patient not found | HTTP 404 |
| Invalid document type ID | HTTP 400 with error detail |
| File too large | HTTP 413 or 400 — confirm size limit in sandbox |
| Duplicate document | HTTP 409 (idempotent — not an error) |
| Rate limited | HTTP 429 with `Retry-After` |
| malformed multipart | HTTP 400 |

---

## Running the POC

```bash
# Dry run — shows request shape and hardcoded TODO risk
python poc.py --dry-run

# Live run
export ATHENA_CLIENT_ID=your_client_id
export ATHENA_CLIENT_SECRET=your_client_secret
export ATHENA_PRACTICE_ID=your_practice_id
python poc.py --patient-id 12345 --document-path ./test-care-plan.pdf --document-type-id 440672
```

---

## Assumptions requiring sandbox validation

1. `documentsubclass=CLINICALDOCUMENT` — is this the correct subclass for care plans? Confirm in sandbox.
2. `autoclose=true` — does this close the document immediately or trigger a workflow? Confirm with Griffin.
3. Response shape — does athena return a `documentid` field on success? Confirm in sandbox.
4. File size limit — what is the maximum PDF size athena accepts? Unknown; typical is 10MB-50MB.
5. Duplicate handling — HTTP 409 assumed; confirm athena returns 409 (not 200) for duplicates.
6. `documenttypeid=440672` — is this ID valid in the sandbox environment? Document type IDs may differ between sandbox and production.

---

## Blockers preventing end-to-end testing

Athena sandbox credentials not available in this environment. Use `--dry-run` to inspect request shape.
