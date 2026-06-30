#!/usr/bin/env python3
"""
Notes / Escalations POC — POST and GET patient notes in athena
=============================================================
Pillar: Notes / Escalations (Phase 5)
Endpoints:
  POST /v1/{practiceid}/patients/{patientid}/notes   — Post a patient note
  GET  /v1/{practiceid}/patients/{patientid}/notes   — Get existing notes

NOTE: From recon (findings.md Phase 4 section):
  - AthenaApi.java has only sendDocument — NO /note endpoint method
  - AthenaService does NOT implement EmrService.sendPatientNote() for athena
  - Redox note sending (sendPatientNote()) posts base64 PDF via Redox — different protocol
  - This is greenfield for athena: new AthenaApi.sendNote() Retrofit method needed

The build plan's "signal-not-noise filtering" principle:
  Only clinically meaningful escalations surface to athena.
  This POC demonstrates the wire contract; filtering logic is in the mapping layer.

Usage:
  python poc.py --dry-run
  python poc.py --patient-id 12345 --note-text "Patient escalation: BP 180/110. Provider notified."
                --note-type escalation

Environment variables:
  ATHENA_CLIENT_ID
  ATHENA_CLIENT_SECRET
  ATHENA_PRACTICE_ID
"""

import argparse
import base64
import json
import os
import sys
import time
import hashlib
from datetime import datetime

try:
    import requests
except ImportError:
    sys.exit("requests is required: pip install requests")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = "https://api.preview.platform.athenahealth.com"
TOKEN_ENDPOINT = f"{BASE_URL}/oauth2/v1/token"

# TODO: verify endpoint path against athena developer docs
# Standard athena patient notes endpoint
NOTES_ENDPOINT_TEMPLATE = (
    f"{BASE_URL}/v1/{{practice_id}}/patients/{{patient_id}}/notes"
)

MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 2
MAX_BACKOFF_SECONDS = 32

# Note type mapping — from Redox precedent (RedoxService.java DocumentType enum)
# Brook note types -> athena note type param (TODO: verify athena's accepted values)
NOTE_TYPE_MAP = {
    "escalation": "ESCALATION",          # Clinically meaningful escalation
    "clinical": "CLINICAL",              # Clinical observation note
    "interaction": "VISIT",              # Care team interaction note
    "simple_escalation": "ESCALATION",   # Simple escalation (lighter-weight)
}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def acquire_token(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}"
    encoded = base64.b64encode(raw.encode()).decode()
    headers = {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    resp = requests.post(TOKEN_ENDPOINT, headers=headers, data={"grant_type": "client_credentials"})
    if not resp.ok:
        print(f"[notes] Token request failed: HTTP {resp.status_code}")
        print(f"[notes] Body: {resp.text}")
        resp.raise_for_status()
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def request_with_retry(method: str, url: str, max_retries: int = MAX_RETRIES, **kwargs) -> "requests.Response":
    backoff = INITIAL_BACKOFF_SECONDS
    for attempt in range(1, max_retries + 2):
        print(f"[notes] Attempt {attempt}: {method} {url}")
        try:
            resp = requests.request(method, url, **kwargs)
        except requests.exceptions.ConnectionError as exc:
            if attempt > max_retries:
                raise
            print(f"[notes] Connection error: {exc}. Retrying in {backoff}s ...")
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        if resp.status_code == 429:
            if attempt > max_retries:
                resp.raise_for_status()
                return resp
            retry_after = float(resp.headers.get("Retry-After", backoff))
            wait = max(retry_after, backoff)
            print(f"[notes] HTTP 429. Waiting {wait}s ...")
            time.sleep(wait)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        if resp.status_code in {500, 502, 503, 504}:
            if attempt > max_retries:
                resp.raise_for_status()
                return resp
            print(f"[notes] HTTP {resp.status_code}. Retrying in {backoff}s ...")
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        return resp

    raise RuntimeError("request_with_retry exhausted without returning")


# ---------------------------------------------------------------------------
# Idempotency key for notes
# ---------------------------------------------------------------------------

def make_note_idempotency_key(
    persona_id: str,
    practice_id: str,
    escalation_id: str,
    note_type: str,
) -> str:
    """
    Build plan (Phase 4): "Idempotency on escalation ID"
    Key: hash of (persona_id, practice_id, escalation_id, note_type)
    Same escalation_id + same note_type = same key = idempotent POST.
    """
    compound = f"note:{persona_id}:{practice_id}:{escalation_id}:{note_type}"
    digest = hashlib.sha256(compound.encode()).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


# ---------------------------------------------------------------------------
# POST note
# ---------------------------------------------------------------------------

def post_patient_note(
    access_token: str,
    practice_id: str,
    patient_id: str,
    note_text: str,
    note_type: str,
    idempotency_key: str,
) -> dict:
    """
    POST a patient note to athena.

    Request shape is approximate — exact required fields must be validated
    in sandbox. athena patient notes typically accept:
      - notetext or text (the note body)
      - notetype (note category)
      - departmentid (required by some athena endpoints)

    TODO: verify all required fields against athena developer docs.

    Reuses store pattern from Phase 1b (POST /clinicaldocument) but uses
    the /notes endpoint. From findings.md: the plan's "light add" description
    is accurate in spirit — same auth, same retry pattern, new endpoint.
    """
    url = NOTES_ENDPOINT_TEMPLATE.format(
        practice_id=practice_id,
        patient_id=patient_id,
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Idempotency-Key": idempotency_key,
    }

    # TODO: verify field names against athena developer docs
    # "notetext" and "notetype" are approximate; athena may use different field names
    data = {
        "notetext": note_text,
        "notetype": note_type,
        # "departmentid": "",  # TODO: may be required — verify in sandbox
    }

    resp = request_with_retry("POST", url, headers=headers, data=data, timeout=30)

    if not resp.ok:
        print(f"[notes] Note POST failed: HTTP {resp.status_code}")
        print(f"[notes] Response: {resp.text}")
        resp.raise_for_status()

    result = {}
    try:
        result = resp.json()
    except Exception:
        pass

    return {
        "status": "posted",
        "http_status": resp.status_code,
        "idempotency_key": idempotency_key,
        "athena_response": result,
    }


# ---------------------------------------------------------------------------
# GET notes
# ---------------------------------------------------------------------------

def get_patient_notes(
    access_token: str,
    practice_id: str,
    patient_id: str,
) -> list:
    """
    GET existing notes for a patient from athena.

    TODO: verify endpoint path and response shape against athena developer docs.
    Some athena GET /notes endpoints require a departmentid query parameter.
    """
    url = NOTES_ENDPOINT_TEMPLATE.format(
        practice_id=practice_id,
        patient_id=patient_id,
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    resp = request_with_retry("GET", url, headers=headers, timeout=30)

    if not resp.ok:
        print(f"[notes] Notes GET failed: HTTP {resp.status_code}")
        print(f"[notes] Response: {resp.text}")
        resp.raise_for_status()

    try:
        data = resp.json()
    except Exception:
        return [{"raw": resp.text}]

    # athena may return {"notes": [...]} or a direct list
    if isinstance(data, list):
        return data
    return data.get("notes", data.get("patientnotes", [data]))


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

def dry_run(practice_id: str, patient_id: str, note_type: str) -> None:
    post_url = NOTES_ENDPOINT_TEMPLATE.format(
        practice_id=practice_id or "{practice_id}",
        patient_id=patient_id or "{patient_id}",
    )
    idempotency_key = make_note_idempotency_key(
        persona_id=patient_id or "persona_id",
        practice_id=practice_id or "practice_id",
        escalation_id="escalation_id_example",
        note_type=note_type,
    )

    print("\n[DRY RUN] Notes / Escalations — Request Shape")
    print("=" * 60)
    print("From recon: AthenaApi.java has no /notes endpoint — this is greenfield.")
    print("Reuses store pattern from Phase 1b (same auth, same retry, new endpoint).")
    print()
    print("Step 1 — POST note:")
    print(f"  Method : POST")
    print(f"  URL    : {post_url}")
    print(f"  # TODO: verify endpoint path against athena developer docs")
    print(f"  Headers:")
    print(f"    Authorization    : Bearer <access_token>")
    print(f"    Content-Type     : application/x-www-form-urlencoded")
    print(f"    X-Idempotency-Key: {idempotency_key}")
    print(f"  Body (form-encoded):")
    print(f"    notetext : <note text>     # TODO: verify field name")
    print(f"    notetype : {NOTE_TYPE_MAP.get(note_type, note_type)}   # TODO: verify athena accepted values")
    print(f"    # departmentid: TBD — may be required")
    print()
    print("Step 2 — GET existing notes:")
    print(f"  Method : GET")
    print(f"  URL    : {post_url}")
    print(f"  # TODO: verify response shape (list vs nested object)")
    print()
    print("Signal-not-noise filtering (build plan Phase 4):")
    print("  Only clinically meaningful escalations surface to athena.")
    print("  Filtering logic lives in the mapping layer, not in this wire script.")
    print()
    print("Note type mapping (Brook -> athena):")
    for brook_type, athena_type in NOTE_TYPE_MAP.items():
        print(f"  {brook_type:20s} -> {athena_type}")
    print()
    print("Idempotency (build plan Phase 4): idempotency on escalation ID")
    print(f"  key = sha256(note:{patient_id or 'persona_id'}:{practice_id or 'practice_id'}:escalation_id_example:{note_type})")
    print(f"  => {idempotency_key}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Notes/Escalations POC: POST and GET athena patient notes")
    parser.add_argument("--patient-id", default=os.environ.get("ATHENA_PATIENT_ID", ""))
    parser.add_argument("--note-text", default="", help="Note text to post")
    parser.add_argument(
        "--note-type",
        choices=list(NOTE_TYPE_MAP.keys()),
        default="escalation",
        help="Brook note type (default: escalation)",
    )
    parser.add_argument(
        "--escalation-id",
        default="",
        help="Brook escalation ID for idempotency key derivation",
    )
    parser.add_argument("--get-notes", action="store_true", help="Only GET existing notes, don't POST")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client_id = os.environ.get("ATHENA_CLIENT_ID", "")
    client_secret = os.environ.get("ATHENA_CLIENT_SECRET", "")
    practice_id = os.environ.get("ATHENA_PRACTICE_ID", "")

    if args.dry_run:
        dry_run(practice_id, args.patient_id, args.note_type)
        return

    if not client_id or not client_secret or not practice_id:
        sys.exit("ATHENA_CLIENT_ID, ATHENA_CLIENT_SECRET, ATHENA_PRACTICE_ID required. Use --dry-run.")

    if not args.patient_id:
        sys.exit("--patient-id required")

    print(f"[notes] Acquiring token ...")
    access_token = acquire_token(client_id, client_secret)

    if args.get_notes:
        print(f"[notes] Getting existing notes for patient {args.patient_id} ...")
        notes = get_patient_notes(access_token, practice_id, args.patient_id)
        print(f"[notes] Found {len(notes)} note(s):")
        print(json.dumps(notes[:5], indent=2))  # print up to 5
        return

    if not args.note_text:
        sys.exit("--note-text required when posting a note")

    escalation_id = args.escalation_id or f"auto-{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}"
    athena_note_type = NOTE_TYPE_MAP.get(args.note_type, args.note_type)
    idempotency_key = make_note_idempotency_key(
        persona_id=args.patient_id,
        practice_id=practice_id,
        escalation_id=escalation_id,
        note_type=args.note_type,
    )

    print(f"[notes] Posting {args.note_type} note for patient {args.patient_id} ...")
    print(f"  escalation_id   : {escalation_id}")
    print(f"  athena_note_type: {athena_note_type}")
    print(f"  idempotency_key : {idempotency_key}")

    result = post_patient_note(
        access_token=access_token,
        practice_id=practice_id,
        patient_id=args.patient_id,
        note_text=args.note_text,
        note_type=athena_note_type,
        idempotency_key=idempotency_key,
    )

    print(f"\n[notes] Result: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    main()
