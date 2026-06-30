#!/usr/bin/env python3
"""
Billing POC — Check patient eligibility and post charge/procedure in athena
===========================================================================
Pillar: Billing (Phase 5)
Endpoints:
  GET  /v1/{practiceid}/patients/{patientid}/insurances    — List patient insurance/eligibility
  POST /v1/{practiceid}/patients/{patientid}/procedures    — Post CPT procedure charge (real-time billing)

Build plan Phase 5 scope:
  - POCAR "ready for billing" state -> ChargePosted event -> POST /procedure
  - Correct CPT codes per program:
      RPM: 99457/99458
      CCM: 99490/99439
      APCM: 99490 + addendums
  - Idempotent posting
  - Parallel-run with existing batch monthly bundled reports
  - Eligibility verification (not full claims submission)

NOTE: Fully greenfield. No athena billing endpoint (/procedure) implemented in
brook-backend. Current path: monthly PDF bundle report as clinical document
(AthenaService.sendBundleReport()). Phase 5 adds real-time charge posting as
a parallel path, not a replacement until finance team signs off.

TODO: verify all endpoint paths against athena developer docs.
      athena billing/procedure endpoint path may differ.

Usage:
  python poc.py --dry-run
  python poc.py --patient-id 12345 --check-eligibility
  python poc.py --patient-id 12345 --post-charge --cpt-code 99457 --program rpm

Environment variables:
  ATHENA_CLIENT_ID
  ATHENA_CLIENT_SECRET
  ATHENA_PRACTICE_ID
"""

import argparse
import base64
import hashlib
import json
import os
import sys
import time
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

# TODO: verify endpoint paths against athena developer docs
# Eligibility / insurance check
INSURANCE_ENDPOINT_TEMPLATE = (
    f"{BASE_URL}/v1/{{practice_id}}/patients/{{patient_id}}/insurances"
)

# Real-time charge / procedure posting
# TODO: verify - athena may use /charges or /encounters/{id}/procedures
PROCEDURE_ENDPOINT_TEMPLATE = (
    f"{BASE_URL}/v1/{{practice_id}}/patients/{{patient_id}}/procedures"
)

MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 2
MAX_BACKOFF_SECONDS = 32

# CPT code mapping per Brook program (from build plan Phase 5)
CPT_CODES_BY_PROGRAM = {
    "rpm": {
        "primary": "99457",    # RPM, first 20 minutes/month
        "additional": "99458", # RPM, each additional 20 minutes
        "description": "Remote Physiologic Monitoring (RPM)",
    },
    "ccm": {
        "primary": "99490",    # CCM, 20 minutes/month
        "additional": "99439", # CCM, each additional 20 minutes
        "description": "Chronic Care Management (CCM)",
    },
    "apcm": {
        "primary": "99490",    # APCM (Advanced Primary Care Management) — uses CCM base code
        "additional": "99439",
        "description": "Advanced Primary Care Management (APCM)",
        "note": "APCM uses 99490 + addendums per build plan",
    },
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
        print(f"[billing] Token request failed: HTTP {resp.status_code}")
        print(f"[billing] Body: {resp.text}")
        resp.raise_for_status()
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def request_with_retry(method: str, url: str, max_retries: int = MAX_RETRIES, **kwargs) -> "requests.Response":
    backoff = INITIAL_BACKOFF_SECONDS
    for attempt in range(1, max_retries + 2):
        print(f"[billing] Attempt {attempt}: {method} {url}")
        try:
            resp = requests.request(method, url, **kwargs)
        except requests.exceptions.ConnectionError as exc:
            if attempt > max_retries:
                raise
            print(f"[billing] Connection error: {exc}. Retrying in {backoff}s ...")
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        if resp.status_code == 429:
            if attempt > max_retries:
                resp.raise_for_status()
                return resp
            retry_after = float(resp.headers.get("Retry-After", backoff))
            wait = max(retry_after, backoff)
            print(f"[billing] HTTP 429. Waiting {wait}s ...")
            time.sleep(wait)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        if resp.status_code in {500, 502, 503, 504}:
            if attempt > max_retries:
                resp.raise_for_status()
                return resp
            print(f"[billing] HTTP {resp.status_code}. Retrying in {backoff}s ...")
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        return resp

    raise RuntimeError("request_with_retry exhausted without returning")


# ---------------------------------------------------------------------------
# Idempotency for charge posting
# ---------------------------------------------------------------------------

def make_charge_idempotency_key(
    persona_id: str,
    practice_id: str,
    cpt_code: str,
    service_date: str,  # YYYY-MM-DD
    charge_event_id: str,  # Brook ChargePosted event ID
) -> str:
    """
    Build plan Phase 5: "Idempotent posting"
    Key: hash of (persona_id, practice_id, cpt_code, service_date, charge_event_id)
    Prevents duplicate charge submissions for the same billing event.
    """
    compound = f"charge:{persona_id}:{practice_id}:{cpt_code}:{service_date}:{charge_event_id}"
    digest = hashlib.sha256(compound.encode()).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


# ---------------------------------------------------------------------------
# Eligibility check
# ---------------------------------------------------------------------------

def check_patient_eligibility(
    access_token: str,
    practice_id: str,
    patient_id: str,
) -> dict:
    """
    GET patient insurance/eligibility from athena.

    Build plan Phase 5 scope: "eligibility verification, not full claims submission."
    This endpoint returns the patient's insurance records stored in athena.
    Real-time eligibility verification may require a separate endpoint.

    TODO: verify endpoint path and response shape against athena developer docs.
    athena may have a dedicated eligibility check endpoint separate from /insurances.
    """
    url = INSURANCE_ENDPOINT_TEMPLATE.format(
        practice_id=practice_id,
        patient_id=patient_id,
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    resp = request_with_retry("GET", url, headers=headers, timeout=30)

    if not resp.ok:
        print(f"[billing] Eligibility check failed: HTTP {resp.status_code}")
        print(f"[billing] Response: {resp.text}")
        resp.raise_for_status()

    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


# ---------------------------------------------------------------------------
# Post procedure / charge
# ---------------------------------------------------------------------------

def post_procedure_charge(
    access_token: str,
    practice_id: str,
    patient_id: str,
    cpt_code: str,
    service_date: str,
    department_id: str,
    provider_id: str,
    idempotency_key: str,
) -> dict:
    """
    POST a CPT procedure charge to athena.

    Build plan Phase 5: POST /procedure for real-time CPT charge posting.
    Parallel-run with existing batch monthly bundled reports.

    Request shape is approximate — verify required fields in sandbox.
    athena charge/procedure posting typically requires:
      - procedurecode (CPT code)
      - servicedate
      - departmentid
      - providerid
      - diagnosiscode (ICD-10, for medical necessity)

    TODO: verify endpoint path and all field names against athena developer docs.
    athena may route charge posting through /encounters or a different path.
    """
    url = PROCEDURE_ENDPOINT_TEMPLATE.format(
        practice_id=practice_id,
        patient_id=patient_id,
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Idempotency-Key": idempotency_key,
    }

    # TODO: verify all field names and required fields against athena developer docs
    data = {
        "procedurecode": cpt_code,       # CPT code
        "servicedate": service_date,      # Date of service (MM/DD/YYYY or YYYY-MM-DD — confirm)
        "departmentid": department_id,
        "providerid": provider_id,
        # "diagnosiscode": "",            # ICD-10 for medical necessity — may be required
        # "quantity": "1",                # Units — may be required
    }

    resp = request_with_retry("POST", url, headers=headers, data=data, timeout=30)

    if resp.status_code == 409:
        print(f"[billing] HTTP 409 Conflict — charge already posted (idempotent).")
        return {"status": "duplicate", "idempotency_key": idempotency_key}

    if not resp.ok:
        print(f"[billing] Charge POST failed: HTTP {resp.status_code}")
        print(f"[billing] Response: {resp.text}")
        resp.raise_for_status()

    result = {}
    try:
        result = resp.json()
    except Exception:
        pass

    return {
        "status": "posted",
        "http_status": resp.status_code,
        "cpt_code": cpt_code,
        "service_date": service_date,
        "idempotency_key": idempotency_key,
        "athena_response": result,
    }


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

def dry_run(practice_id: str, patient_id: str) -> None:
    eligibility_url = INSURANCE_ENDPOINT_TEMPLATE.format(
        practice_id=practice_id or "{practice_id}",
        patient_id=patient_id or "{patient_id}",
    )
    procedure_url = PROCEDURE_ENDPOINT_TEMPLATE.format(
        practice_id=practice_id or "{practice_id}",
        patient_id=patient_id or "{patient_id}",
    )
    service_date = datetime.utcnow().strftime("%Y-%m-%d")
    idempotency_key = make_charge_idempotency_key(
        persona_id=patient_id or "persona_id",
        practice_id=practice_id or "practice_id",
        cpt_code="99457",
        service_date=service_date,
        charge_event_id="ChargePosted-event-id",
    )

    print("\n[DRY RUN] Billing — Request Shape")
    print("=" * 60)
    print("Phase 5 scope: eligibility verification + real-time charge posting")
    print("Parallel-run with existing batch monthly bundled reports (AthenaService.sendBundleReport())")
    print()
    print("Step 1 — Eligibility check:")
    print(f"  Method : GET")
    print(f"  URL    : {eligibility_url}")
    print(f"  # TODO: verify endpoint path against athena developer docs")
    print(f"  Headers: Authorization: Bearer <access_token>")
    print()
    print("Step 2 — Post charge (real-time CPT billing):")
    print(f"  Method : POST")
    print(f"  URL    : {procedure_url}")
    print(f"  # TODO: verify endpoint path against athena developer docs")
    print(f"  # athena may route charges through /encounters or a different path")
    print(f"  Headers:")
    print(f"    Authorization    : Bearer <access_token>")
    print(f"    Content-Type     : application/x-www-form-urlencoded")
    print(f"    X-Idempotency-Key: {idempotency_key}")
    print(f"  Body (form-encoded):")
    print(f"    procedurecode : 99457       # CPT code")
    print(f"    servicedate   : {service_date}")
    print(f"    departmentid  : {{dept_id}}")
    print(f"    providerid    : {{provider_id}}")
    print(f"    # diagnosiscode TBD — may be required for medical necessity")
    print()
    print("CPT code mapping (from build plan Phase 5):")
    for program, codes in CPT_CODES_BY_PROGRAM.items():
        print(f"  {program.upper():6s}: {codes['primary']} (primary) / {codes['additional']} (additional)")
        print(f"         {codes['description']}")
    print()
    print("Idempotency key derivation:")
    print(f"  compound = charge:{patient_id or 'persona_id'}:{practice_id or 'practice_id'}:99457:{service_date}:ChargePosted-event-id")
    print(f"  key      = {idempotency_key}")
    print()
    print("Reconciliation logging: per-charge audit log required before finance sign-off.")
    print("Parallel-run exit criterion: finance team sign-off concludes the parallel window.")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Billing POC: Eligibility check + real-time charge posting")
    parser.add_argument("--patient-id", default=os.environ.get("ATHENA_PATIENT_ID", ""))
    parser.add_argument("--check-eligibility", action="store_true", help="Check patient eligibility only")
    parser.add_argument("--post-charge", action="store_true", help="Post a procedure charge")
    parser.add_argument(
        "--cpt-code",
        default="99457",
        help="CPT code to post (default: 99457)",
    )
    parser.add_argument(
        "--program",
        choices=list(CPT_CODES_BY_PROGRAM.keys()),
        default="rpm",
        help="Brook program (used to validate CPT code mapping)",
    )
    parser.add_argument(
        "--service-date",
        default=datetime.utcnow().strftime("%Y-%m-%d"),
        help="Service date (YYYY-MM-DD, default: today)",
    )
    parser.add_argument("--department-id", default=os.environ.get("ATHENA_DEPARTMENT_ID", ""))
    parser.add_argument("--provider-id", default=os.environ.get("ATHENA_PROVIDER_ID", ""))
    parser.add_argument("--charge-event-id", default="", help="Brook ChargePosted event ID for idempotency")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client_id = os.environ.get("ATHENA_CLIENT_ID", "")
    client_secret = os.environ.get("ATHENA_CLIENT_SECRET", "")
    practice_id = os.environ.get("ATHENA_PRACTICE_ID", "")

    if args.dry_run:
        dry_run(practice_id, args.patient_id)
        return

    if not client_id or not client_secret or not practice_id:
        sys.exit("ATHENA_CLIENT_ID, ATHENA_CLIENT_SECRET, ATHENA_PRACTICE_ID required. Use --dry-run.")

    if not args.patient_id:
        sys.exit("--patient-id required")

    print(f"[billing] Acquiring token ...")
    access_token = acquire_token(client_id, client_secret)

    if args.check_eligibility:
        print(f"[billing] Checking eligibility for patient {args.patient_id} ...")
        result = check_patient_eligibility(access_token, practice_id, args.patient_id)
        print(f"[billing] Eligibility data:")
        print(json.dumps(result, indent=2))

    if args.post_charge:
        program_codes = CPT_CODES_BY_PROGRAM.get(args.program, {})
        valid_cpt = [program_codes.get("primary", ""), program_codes.get("additional", "")]
        if args.cpt_code not in [c for c in valid_cpt if c]:
            print(f"[billing] WARNING: CPT code {args.cpt_code} may not match program {args.program}")
            print(f"[billing] Expected: {valid_cpt}")

        charge_event_id = args.charge_event_id or f"ChargePosted-{args.patient_id}-{args.service_date}"
        idempotency_key = make_charge_idempotency_key(
            persona_id=args.patient_id,
            practice_id=practice_id,
            cpt_code=args.cpt_code,
            service_date=args.service_date,
            charge_event_id=charge_event_id,
        )

        print(f"[billing] Posting charge ...")
        print(f"  patient_id      : {args.patient_id}")
        print(f"  cpt_code        : {args.cpt_code} ({args.program.upper()})")
        print(f"  service_date    : {args.service_date}")
        print(f"  charge_event_id : {charge_event_id}")
        print(f"  idempotency_key : {idempotency_key}")

        result = post_procedure_charge(
            access_token=access_token,
            practice_id=practice_id,
            patient_id=args.patient_id,
            cpt_code=args.cpt_code,
            service_date=args.service_date,
            department_id=args.department_id or "UNKNOWN",
            provider_id=args.provider_id or "UNKNOWN",
            idempotency_key=idempotency_key,
        )
        print(f"\n[billing] Result: {json.dumps(result, indent=2)}")

    if not args.check_eligibility and not args.post_charge:
        print("[billing] No action specified. Use --check-eligibility or --post-charge.")
        print("[billing] Use --dry-run to see request shapes.")


if __name__ == "__main__":
    main()
