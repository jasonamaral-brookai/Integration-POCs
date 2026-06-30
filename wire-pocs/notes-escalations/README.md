# Notes / Escalations POC — POST and GET Patient Notes in athena

**Pillar:** Notes / Escalations (Phase 5)
**Status:** Not validated against athena sandbox — credentials required.

---

## Athena endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/{practiceid}/patients/{patientid}/notes` | Post a patient note or escalation |
| GET | `/v1/{practiceid}/patients/{patientid}/notes` | Get existing notes |

**All endpoint paths and field names are marked `# TODO: verify endpoint path against athena developer docs`.** The `/notes` endpoint path is based on standard athena REST API patterns but must be confirmed in sandbox.

---

## Greenfield status

From recon (`findings.md` Phase 4 section):
- `AthenaApi.java` has only `sendDocument` — no `/notes` endpoint method exists.
- `AthenaService` does not implement `EmrService.sendPatientNote()` for athena.
- Redox note sending (`sendPatientNote()`) posts base64-encoded PDF via Redox — different protocol entirely.

The build plan's "light add" description is accurate: structurally the same as Phase 1b (POST to athena with Bearer token), but using a different endpoint. The implementation requires a new `AthenaApi.sendNote()` Retrofit method in brook-backend.

---

## Request shape — POST note

```
POST https://api.preview.platform.athenahealth.com/v1/{practiceid}/patients/{patientid}/notes
Authorization: Bearer <access_token>
Content-Type: application/x-www-form-urlencoded
X-Idempotency-Key: <escalation-scoped-key>

notetext=<note text>&notetype=ESCALATION
```

Key fields (approximate — verify in sandbox):
- `notetext` — the note body text (field name may be `text`, `note`, or `notetext`)
- `notetype` — note category (accepted values: confirm in sandbox)

---

## Response shape — POST note

```json
{
  "noteid": "567890",
  "success": true
}
```

Key fields to extract:
- `noteid` — athena note ID; store for audit

---

## Response shape — GET notes

```json
{
  "notes": [
    {
      "noteid": "567890",
      "notetext": "Brook escalation note: ...",
      "notetype": "ESCALATION",
      "notedate": "2026-06-30T14:30:00",
      "createdby": "Brook Health"
    }
  ],
  "totalcount": 1
}
```

Response shape may be a flat list or wrapped object — confirm in sandbox.

---

## Signal-not-noise filtering (build plan Phase 4)

> "Only clinically meaningful escalations surface to athena. This is the governing Brook design principle — only clinically meaningful information should surface to providers across care settings."

This wire POC posts notes regardless of clinical significance. The filtering decision belongs in the mapping layer:

| Brook escalation type | Post to athena? | Rationale |
|----------------------|----------------|-----------|
| BP >= 180/110 (hypertensive urgency) | Yes | Clinically significant |
| A1c >= 10% | Yes | Clinically significant |
| Device connectivity loss | No | Operational, not clinical |
| Missed medication reminder | No | Patient engagement, not clinical |
| Provider-flagged alert | Yes | Always surface |

The mapping config defines the filtering rules per partner. Griffin's config v0 determines which Brook escalation types map to athena note types.

---

## Idempotency

Build plan Phase 4: "Idempotency on escalation ID."

Key derivation: `sha256("note:{persona_id}:{practice_id}:{escalation_id}:{note_type}")`

Same escalation_id + same note_type = same key = idempotent POST. Prevents duplicate notes when the same escalation event is processed multiple times.

---

## Failure modes

| Scenario | athena response |
|----------|----------------|
| Invalid/expired token | HTTP 401 |
| Patient not found | HTTP 404 |
| Missing required fields | HTTP 400 with error detail |
| Note type not accepted | HTTP 400 |
| Duplicate note (if athena detects) | HTTP 409 or 200 — confirm in sandbox |
| Rate limited | HTTP 429 with `Retry-After` |

---

## Running the POC

```bash
# Dry run — shows request shape and note type mapping
python poc.py --dry-run

# Post an escalation note
export ATHENA_CLIENT_ID=your_client_id
export ATHENA_CLIENT_SECRET=your_client_secret
export ATHENA_PRACTICE_ID=your_practice_id
python poc.py --patient-id 12345 \
  --note-text "BP elevated: 178/108. Care team notified. Provider review recommended." \
  --note-type escalation \
  --escalation-id "esc-abc123"

# GET existing notes
python poc.py --patient-id 12345 --get-notes
```

---

## Assumptions requiring sandbox validation

1. Endpoint path: `/v1/{practiceid}/patients/{patientid}/notes` — confirm in sandbox.
2. Field names: `notetext` and `notetype` — confirm athena-accepted field names.
3. Accepted `notetype` values — what values does athena accept? (ESCALATION, CLINICAL, VISIT, etc.)
4. Whether `departmentid` is required on the POST.
5. GET response shape: list vs. `{"notes": [...]}` — confirm in sandbox.
6. Whether athena requires a provider/author field on the note.
7. Physician acknowledgment path: the build plan describes "physician acknowledgment via patient case closure (escalation path)." Confirm in sandbox whether athena supports case closure as a note acknowledgment mechanism.
