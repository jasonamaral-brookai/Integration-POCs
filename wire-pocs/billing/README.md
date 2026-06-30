# Billing POC — Eligibility Check and Real-Time Charge Posting in athena

**Pillar:** Billing (Phase 5)
**Status:** Not validated against athena sandbox — credentials required.

---

## Athena endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/{practiceid}/patients/{patientid}/insurances` | Check patient insurance / eligibility |
| POST | `/v1/{practiceid}/patients/{patientid}/procedures` | Post CPT procedure charge |

**All endpoint paths are marked `# TODO: verify endpoint path against athena developer docs`.** athena may route charge posting through `/encounters` or a different billing path. The IS consultant referenced in the build plan has billing component expertise and should validate these paths.

---

## Phase 5 scope (from build plan)

This is narrow-scope billing:
- Eligibility verification (GET)
- Real-time CPT charge posting (POST)
- NOT: full claims submission, remittance handling, ERA processing

The existing batch path (`AthenaService.sendBundleReport()`) posts monthly PDF bundles as clinical documents. Phase 5 adds real-time per-charge posting as a parallel path. Finance team sign-off is required before the batch path retires.

---

## Request shape — Eligibility check

```
GET https://api.preview.platform.athenahealth.com/v1/{practiceid}/patients/{patientid}/insurances
Authorization: Bearer <access_token>
Accept: application/json
```

No request body. Returns the patient's insurance records stored in athena.

---

## Response shape — Eligibility check

```json
{
  "insurances": [
    {
      "insuranceid": "12345",
      "sequencenumber": "1",
      "insurancepolicyid": "ABC123",
      "insuranceplandisplayname": "Medicare Part B",
      "eligibilitystatus": "ACTIVE",
      "eligibilitylastrunavailability": null
    }
  ],
  "totalcount": 1
}
```

Key fields to extract:
- `eligibilitystatus` — is the patient currently eligible? (`ACTIVE`, `INACTIVE`, etc.)
- `sequencenumber` — primary vs. secondary insurance
- `insuranceplandisplayname` — plan name for display and billing routing

---

## Request shape — Post procedure charge

```
POST https://api.preview.platform.athenahealth.com/v1/{practiceid}/patients/{patientid}/procedures
Authorization: Bearer <access_token>
Content-Type: application/x-www-form-urlencoded
X-Idempotency-Key: <charge-scoped-key>

procedurecode=99457&servicedate=2026-06-30&departmentid={dept_id}&providerid={provider_id}
```

Key fields (approximate — verify in sandbox):
- `procedurecode` — CPT code
- `servicedate` — date of service (format: `MM/DD/YYYY` or `YYYY-MM-DD` — confirm in sandbox)
- `departmentid` — athena department ID
- `providerid` — billing provider ID
- `diagnosiscode` — ICD-10 for medical necessity (may be required)

---

## Response shape — Post procedure charge

```json
{
  "chargeid": "987654",
  "claimid": "111222",
  "status": "POSTED"
}
```

Key fields to extract:
- `chargeid` — athena charge ID; store for reconciliation audit log
- `claimid` — associated claim ID if immediately assigned
- `status` — charge status (`POSTED`, `PENDING`, etc.)

---

## CPT code mapping (from build plan Phase 5)

| Program | Primary CPT | Additional CPT | Description |
|---------|------------|----------------|-------------|
| RPM | 99457 | 99458 | Remote Physiologic Monitoring — 20 min increments |
| CCM | 99490 | 99439 | Chronic Care Management — 20 min increments |
| APCM | 99490 | 99439 | Advanced Primary Care Management + addendums |

---

## Idempotency

Build plan Phase 5: "Idempotent posting."

Key derivation: `sha256("charge:{persona_id}:{practice_id}:{cpt_code}:{service_date}:{charge_event_id}")`

Same `charge_event_id` (Brook `ChargePosted` event ID) = same key = same charge, not a duplicate. If athena returns HTTP 409, the charge is already posted — do not retry.

---

## Parallel-run strategy (from build plan)

1. Phase 5 launch: real-time charge posting runs alongside the existing batch monthly bundle reports.
2. Monitoring: reconciliation log compares real-time vs. batch for discrepancies.
3. Exit criterion: finance team sign-off on AR/reconciliation alignment.
4. Retirement: batch path retires after sign-off window.

Griffin finance has workflows built around the current batch reports. Do not retire the batch path without explicit finance team confirmation.

---

## Failure modes

| Scenario | athena response |
|----------|----------------|
| Invalid/expired token | HTTP 401 |
| Patient not found | HTTP 404 |
| Invalid CPT code | HTTP 400 with error detail |
| Missing required fields | HTTP 400 |
| Duplicate charge (same idempotency key) | HTTP 409 (idempotent — not an error) |
| Rate limited | HTTP 429 with `Retry-After` |
| Insurance not on file | HTTP 400 or specific error body |

---

## Running the POC

```bash
# Dry run — shows request shapes and CPT code mapping
python poc.py --dry-run

# Check eligibility
export ATHENA_CLIENT_ID=your_client_id
export ATHENA_CLIENT_SECRET=your_client_secret
export ATHENA_PRACTICE_ID=your_practice_id
python poc.py --patient-id 12345 --check-eligibility

# Post RPM charge
python poc.py --patient-id 12345 --post-charge --cpt-code 99457 --program rpm \
  --charge-event-id "ChargePosted-abc123" \
  --department-id your_dept_id --provider-id your_provider_id
```

---

## Assumptions requiring sandbox validation

1. Procedure endpoint path: `/patients/{patientid}/procedures` vs. `/encounters/{encounterid}/procedures` — confirm with athena developer docs and the IS consultant.
2. Service date format: `MM/DD/YYYY` vs. `YYYY-MM-DD` — confirm in sandbox.
3. Whether `diagnosiscode` is required for medical necessity on the procedure POST.
4. Whether CPT codes 99457/99458/99490/99439 are valid in the athena sandbox for the test practice.
5. Eligibility endpoint: whether `/insurances` returns real-time eligibility or only stored insurance on file.
6. Whether a dedicated real-time eligibility check endpoint exists separate from `/insurances`.
7. Response shape for charge post: `chargeid`, `claimid`, `status` field names — confirm in sandbox.

---

## Blockers preventing end-to-end testing

- Athena sandbox credentials not available in this environment.
- Billing endpoint paths must be confirmed with athena developer documentation.
- The athena IS consultant (referenced in build plan Section 6 dependency #7) has billing expertise — engage when the consultant window is active (70 days from assignment).
