# Orders POC — Create Lab/Referral Order and Check Status in athena

**Pillar:** Orders (Phase 3)
**Status:** Not validated against athena sandbox — credentials required.

---

## Athena endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/{practiceid}/patients/{patientid}/orders/lab` | Create lab order |
| GET | `/v1/{practiceid}/patients/{patientid}/orders/{orderid}` | Check order status |
| POST | `/v1/{practiceid}/patients/{patientid}/orders/referral` | Create referral order |

**All endpoint paths are marked `# TODO: verify endpoint path against athena developer docs`.** The order endpoint paths are based on standard athena REST API patterns but must be validated in sandbox. athena's Orders API is documented under the "Orders" section of the developer portal.

---

## Classical vs. Postmodern orders

The build plan identifies this as a key Phase 2 decision requiring clinician verification:

**Classical:** Physician places the order in athena directly. Brook has no outbound order creation role. Brook receives the signed-order signal (via CCDA pull on next cycle or FHIR subscriptions if available).

**Postmodern (Griffin pattern):** Brook PSMs cultivate the clinic relationship. The provider signs off post-hoc via athena's task queue. Brook drafts the order (POST), the physician reviews and signs in athena. Brook polls for signed status (GET) or receives a FHIR subscription notification.

This POC demonstrates the **Brook-drafts side** (POST order). Whether athena sandbox supports the task-queue signing flow is unverified — this is listed as an open blocker in the build plan (dependency #2: "clinician verification of orders workflow assumption").

---

## Request shape — Create lab order

```
POST https://api.preview.platform.athenahealth.com/v1/{practiceid}/patients/{patientid}/orders/lab
Authorization: Bearer <access_token>
Content-Type: application/x-www-form-urlencoded
X-Idempotency-Key: <compound-key>

diagnosiscode={ICD-10-code}&departmentid={dept_id}&providerid={provider_id}
```

Key fields (approximate — verify in sandbox):
- `diagnosiscode` — ICD-10 diagnosis code (indication for the order)
- `departmentid` — athena department ID (stored in `ProviderOffice.emrDetails.Athena.departmentId` in Brook)
- `providerid` — ordering provider athena ID (stored in `ProviderDetails.leadProviderId`)
- Additional required fields (test code, reference lab facility) — confirm in sandbox

---

## Response shape — Create lab order

```json
{
  "orderid": "789012",
  "status": "UNSIGNED"
}
```

Key fields to extract:
- `orderid` — athena order ID; store for status polling
- `status` — initial status; `UNSIGNED` means awaiting physician sign-off

---

## Response shape — Order status check

```json
{
  "orderid": "789012",
  "status": "SIGNED",
  "signedby": "Dr. Smith",
  "signedatetime": "2026-06-30T14:30:00"
}
```

Key fields:
- `status` — poll until `SIGNED` or `COMPLETE` to trigger Brook patient activation
- `signedby` — provider who signed; used for audit
- Field names (`status`, `orderstatus`, etc.) — verify in sandbox

---

## Failure modes

| Scenario | athena response |
|----------|----------------|
| Invalid/expired token | HTTP 401 |
| Patient not found | HTTP 404 |
| Invalid department ID | HTTP 400 with error detail |
| Missing required fields | HTTP 400 |
| Duplicate order (same idempotency key) | HTTP 409 or 200 depending on athena behavior |
| Rate limited | HTTP 429 with `Retry-After` |
| Order not found (status check) | HTTP 404 |

---

## Greenfield status

From recon (`findings.md` Orders section): NO order ingest implemented in brook-backend for athena. The Redox ORM ingest pattern (inbound webhook → `RedoxOrderQueueItem` → 10-minute scheduled processor) is the correct precedent for the inbound signed-order signal.

Active open PRs as of 2026-06-30:
- AAR-247 (lead provider not written) — PR #1717
- AAR-329 (consent not honored on rematch) — PR #1758

These are Redox ORM bugs but the same patient-matching and consent-handling logic applies to the athena orders path.

---

## Running the POC

```bash
# Dry run — shows request shape and decision points
python poc.py --dry-run

# Live run — create lab order
export ATHENA_CLIENT_ID=your_client_id
export ATHENA_CLIENT_SECRET=your_client_secret
export ATHENA_PRACTICE_ID=your_practice_id
export ATHENA_DEPARTMENT_ID=your_dept_id
export ATHENA_PROVIDER_ID=your_provider_id
python poc.py --patient-id 12345 --order-type lab --diagnosis-icd10 E11.65

# Check order status
python poc.py --patient-id 12345 --check-order-id 789012
```

---

## Assumptions requiring sandbox validation

1. Endpoint paths for lab and referral orders — confirm in sandbox.
2. Required vs. optional fields on the order POST — the field list here is approximate.
3. Whether athena sandbox supports the task-queue signing flow (postmodern pattern).
4. Order status field name (`status` vs. `orderstatus`) — confirm response schema.
5. Dedup behavior — does athena return 409 on duplicate order, or 200 with same order ID?
6. Whether FHIR subscriptions are available in sandbox for real-time signed-order signals (build plan notes "alpha-only").

---

## Blockers preventing end-to-end testing

- Athena sandbox credentials not available in this environment.
- Clinician verification of the orders workflow assumption (Build plan dependency #2) is not complete.
- Andrew Rosenthal's review of orders dedup logic (Build plan dependency #1) is pending.
