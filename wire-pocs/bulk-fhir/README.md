# Bulk FHIR POC — Async Export from athena

**Pillar:** Bulk FHIR (Phase 4)
**Status:** Not validated against athena sandbox — credentials required.

---

## Athena endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/fhir/r4/Patient/$export` | Initiate async bulk export |
| GET | `<Content-Location URL>` | Poll export job status |
| GET | `<manifest output[].url>` | Download NDJSON result files |

**All endpoint paths are marked `# TODO: verify endpoint path against athena developer docs`.** The FHIR base URL and `$export` path may include the practice ID (e.g., `/fhir/r4/{practiceid}/Patient/$export`) — confirm in sandbox.

---

## Async three-step pattern

FHIR R4 Bulk Data Access IG (v1.0.1) defines an async pattern. This is not optional — athena's bulk export is always async.

### Step 1 — Initiate

```
GET https://api.preview.platform.athenahealth.com/fhir/r4/Patient/$export?_type=Patient,Condition,...
Authorization: Bearer <access_token>
Accept: application/fhir+json
Prefer: respond-async
```

Response:
```
HTTP/1.1 202 Accepted
Content-Location: https://.../<poll_url>
```

The `Prefer: respond-async` header is required by the FHIR spec to trigger async mode. `Content-Location` is the poll URL.

### Step 2 — Poll

```
GET <poll_url>
Authorization: Bearer <access_token>
Accept: application/json
```

While in progress:
```
HTTP/1.1 202 Accepted
X-Progress: "50% complete"   (optional)
```

When complete:
```
HTTP/1.1 200 OK
Content-Type: application/json

{
  "transactionTime": "2026-06-30T00:00:00Z",
  "request": "https://.../$export?_type=...",
  "requiresAccessToken": true,
  "output": [
    {"type": "Patient", "url": "https://.../Patient-0001.ndjson"},
    {"type": "Condition", "url": "https://.../Condition-0001.ndjson"}
  ],
  "error": []
}
```

Key fields from manifest:
- `output[].type` — FHIR resource type
- `output[].url` — download URL for that resource type's NDJSON file
- `error[]` — partial failures (some resources failed to export)
- `requiresAccessToken` — if true, Authorization header required on download

### Step 3 — Download

```
GET <output[].url>
Authorization: Bearer <access_token>
Accept: application/fhir+ndjson
```

Response: NDJSON (newline-delimited JSON), one FHIR resource per line.
```
{"resourceType":"Patient","id":"12345",...}
{"resourceType":"Patient","id":"12346",...}
```

---

## Resource types relevant to Brook

| FHIR Type | Brook model target | Data model status |
|-----------|-------------------|------------------|
| Patient | Persona | EXISTS — needs ATHENA_BULK_FHIR source |
| Condition | PersonaDiagnosis (`persona.diagnoses[]`) | EXISTS — needs `ATHENA_BULK_FHIR` in DiagnosisSource enum |
| Observation | PersonaLab / activity collection | PARTIAL — see data-model-gaps.md |
| AllergyIntolerance | PersonaAllergy | PARTIAL — free text only |
| MedicationRequest | PersonaMedication | PARTIAL — no RxNorm |
| Encounter | PersonaEncounter | MISSING — new collection required |

---

## Eligibility filtering

Build plan Phase 4 scope — filtering at the Brook ingest layer (after download, before upsert):

**Global exclusions (always apply):**
- Deceased patients
- Inactive patients
- Patients under 18

**Partner-configurable toggles:** additional filters per partner mapping config (e.g., specific diagnosis inclusion criteria, enrollment status).

---

## Failure modes

| Scenario | athena response |
|----------|----------------|
| Invalid/expired token | HTTP 401 |
| Export not supported | HTTP 404 or 405 |
| Rate limited on initiation | HTTP 429 with `Retry-After` |
| Export job failed | HTTP 4xx/5xx on poll URL |
| Partial file failure | HTTP 200 manifest with non-empty `error[]` |
| File download auth failure | HTTP 401 (if `requiresAccessToken: true`) |

---

## Polling strategy

The POC implements progressive backoff:
- Start: poll every 10 seconds
- Backoff: multiply interval by 1.5 each poll
- Cap: 120 seconds maximum interval
- Timeout: give up after 3600 seconds (1 hour)

Production cadence: build plan specifies "start daily, tune from there." Nightly export should fit within a 1-hour window for a typical Griffin patient population.

---

## Running the POC

```bash
# Dry run — shows full three-step request shape
python poc.py --dry-run

# Live run
export ATHENA_CLIENT_ID=your_client_id
export ATHENA_CLIENT_SECRET=your_client_secret
export ATHENA_PRACTICE_ID=your_practice_id
python poc.py --resource-types Patient,Condition,Observation --output-dir /tmp/fhir-export

# Incremental (since last export)
python poc.py --resource-types Patient --since 2026-06-29T00:00:00Z
```

---

## Assumptions requiring sandbox validation

1. FHIR base URL path — `/fhir/r4/Patient/$export` vs. `/fhir/r4/{practiceid}/Patient/$export`.
2. Whether `requiresAccessToken: true` in the manifest (download URLs need Bearer token).
3. Poll URL persistence — how long does athena keep the poll URL active after completion?
4. File size range for a full Griffin patient roster export.
5. Whether athena returns partial results (some resources failed) vs. all-or-nothing.
6. `_since` parameter support — does athena support incremental exports?
7. FHIR Subscriptions availability: build plan notes "alpha-only" for real-time signed-order signals. Confirm in sandbox.

---

## Blockers preventing end-to-end testing

- Athena sandbox credentials not available in this environment.
- FHIR base URL and `$export` path must be confirmed with athena developer documentation.
