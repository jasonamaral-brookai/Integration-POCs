#!/usr/bin/env python3
"""
Orders POC — Create lab/referral order and check order status in athena
=======================================================================
Pillar: Orders (Phase 3)
Endpoints:
  POST /v1/{practiceid}/patients/{patientid}/orders/lab         (lab order)
  GET  /v1/{practiceid}/patients/{patientid}/orders/{orderid}   (order status)
  POST /v1/{practiceid}/patients/{patientid}/orders/referral    (referral order, if supported)

Classical vs. Postmodern Order Pattern:
  The build plan notes "classical vs. postmodern orders" as a key decision.
  - Classical: Physician places an order in athena directly.
  - Postmodern (Griffin): Brook PSMs cultivate the clinic relationship; physicians
    sign off post-hoc via athena's task queue. Brook drafts the order, the physician
    signs in athena.
  This POC demonstrates the outbound order creation (Brook drafts). Whether the
  athena sandbox supports task-queue-based signing is unverified — documented below.

NOTE: Athena orders path is fully greenfield from Brook side. No existing athena
orders endpoint implemented in brook-backend. The Redox ORM ingest pattern
(webhook -> queue -> 10-minute processor) is the precedent for inbound order signals.

Usage:
  python poc.py --dry-run
  python poc.py --patient-id 12345 --order-type lab --diagnosis-icd10 E11.65

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
# Lab order endpoint — standard athena REST API form
LAB_ORDER_ENDPOINT_TEMPLATE = (
    f"{BASE_URL}/v1/{{practice_id}}/patients/{{patient_id}}/orders/lab"
)
# Referral order endpoint — TODO: confirm if /orders/referral is the correct path
REFERRAL_ORDER_ENDPOINT_TEMPLATE = (
    f"{BASE_URL}/v1/{{practice_id}}/patients/{{patient_id}}/orders/referral"
)
# Order status endpoint
ORDER_STATUS_ENDPOINT_TEMPLATE = (
    f"{BASE_URL}/v1/{{practice_id}}/patients/{{patient_id}}/orders/{{order_id}}"
)

MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 2
MAX_BACKOFF_SECONDS = 32


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
        print(f"[orders] Token request failed: HTTP {resp.status_code}")
        print(f"[orders] Body: {resp.text}")
        resp.raise_for_status()
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def request_with_retry(method: str, url: str, max_retries: int = MAX_RETRIES, **kwargs) -> "requests.Response":
    backoff = INITIAL_BACKOFF_SECONDS
    for attempt in range(1, max_retries + 2):
        print(f"[orders] Attempt {attempt}: {method} {url}")
        try:
            resp = requests.request(method, url, **kwargs)
        except requests.exceptions.ConnectionError as exc:
            if attempt > max_retries:
                raise
            print(f"[orders] Connection error: {exc}. Retrying in {backoff}s ...")
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        if resp.status_code == 429:
            if attempt > max_retries:
                resp.raise_for_status()
                return resp
            retry_after = float(resp.headers.get("Retry-After", backoff))
            wait = max(retry_after, backoff)
            print(f"[orders] HTTP 429. Waiting {wait}s ...")
            time.sleep(wait)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        if resp.status_code in {500, 502, 503, 504}:
            if attempt > max_retries:
                resp.raise_for_status()
                return resp
            print(f"[orders] HTTP {resp.status_code}. Retrying in {backoff}s ...")
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        return resp

    raise RuntimeError("request_with_retry exhausted without returning")


# ---------------------------------------------------------------------------
# Lab order creation
# ---------------------------------------------------------------------------

def create_lab_order(
    access_token: str,
    practice_id: str,
    patient_id: str,
    diagnosis_icd10: str,
    department_id: str,
    provider_id: str,
    idempotency_key: str,
) -> dict:
    """
    POST a lab order to athena.

    Request shape is approximate — exact required fields must be validated
    in sandbox. athena lab orders typically require:
      - diagnosisid or diagnosiscode (ICD-10)
      - departmentid
      - providerid (ordering provider)
      - ordertype or facilityid (reference lab)

    TODO: verify required fields against athena developer docs.
    """
    url = LAB_ORDER_ENDPOINT_TEMPLATE.format(
        practice_id=practice_id, patient_id=patient_id
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Idempotency-Key": idempotency_key,
    }

    # TODO: verify all required fields against athena developer docs
    # These are approximate based on standard athena Orders API patterns
    data = {
        "diagnosiscode": diagnosis_icd10,     # ICD-10 code for the order indication
        "departmentid": department_id,         # athena department ID
        "providerid": provider_id,             # ordering provider ID
        # "facilityid": "",                    # TODO: reference lab facility ID
        # "ordertype": "",                     # TODO: specific order type / test code
    }

    resp = request_with_retry("POST", url, headers=headers, data=data, timeout=30)

    if not resp.ok:
        print(f"[orders] Lab order creation failed: HTTP {resp.status_code}")
        print(f"[orders] Response: {resp.text}")
        resp.raise_for_status()

    result = {}
    try:
        result = resp.json()
    except Exception:
        pass

    return {"status": "created", "http_status": resp.status_code, "athena_response": result}


# ---------------------------------------------------------------------------
# Order status check
# ---------------------------------------------------------------------------

def get_order_status(
    access_token: str,
    practice_id: str,
    patient_id: str,
    order_id: str,
) -> dict:
    """
    GET order status from athena.

    TODO: verify endpoint path against athena developer docs.
    The status endpoint may be at a different path depending on order type.
    """
    url = ORDER_STATUS_ENDPOINT_TEMPLATE.format(
        practice_id=practice_id,
        patient_id=patient_id,
        order_id=order_id,
    )
    headers = {"Authorization": f"Bearer {access_token}"}

    resp = request_with_retry("GET", url, headers=headers, timeout=30)

    if not resp.ok:
        print(f"[orders] Order status check failed: HTTP {resp.status_code}")
        print(f"[orders] Response: {resp.text}")
        resp.raise_for_status()

    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

def dry_run(practice_id: str, patient_id: str, order_type: str, diagnosis_icd10: str) -> None:
    if order_type == "lab":
        url = LAB_ORDER_ENDPOINT_TEMPLATE.format(
            practice_id=practice_id or "{practice_id}",
            patient_id=patient_id or "{patient_id}",
        )
    else:
        url = REFERRAL_ORDER_ENDPOINT_TEMPLATE.format(
            practice_id=practice_id or "{practice_id}",
            patient_id=patient_id or "{patient_id}",
        )

    status_url = ORDER_STATUS_ENDPOINT_TEMPLATE.format(
        practice_id=practice_id or "{practice_id}",
        patient_id=patient_id or "{patient_id}",
        order_id="{order_id}",
    )

    print("\n[DRY RUN] Orders — Request Shape")
    print("=" * 60)
    print(f"Order type: {order_type}")
    print()
    print(f"Step 1 — Create order:")
    print(f"  Method : POST")
    print(f"  URL    : {url}")
    print(f"  # TODO: verify endpoint path against athena developer docs")
    print(f"  Headers:")
    print(f"    Authorization    : Bearer <access_token>")
    print(f"    Content-Type     : application/x-www-form-urlencoded")
    print(f"    X-Idempotency-Key: <compound-key>")
    print(f"  Body (form-encoded):")
    print(f"    diagnosiscode : {diagnosis_icd10}")
    print(f"    departmentid  : {{department_id}}  # TODO: from ProviderOffice.emrDetails.Athena.departmentId")
    print(f"    providerid    : {{provider_id}}    # TODO: from ProviderDetails.leadProviderId")
    print(f"    # Additional required fields TBD — verify in sandbox")
    print()
    print(f"Step 2 — Check order status:")
    print(f"  Method : GET")
    print(f"  URL    : {status_url}")
    print(f"  # TODO: verify endpoint path against athena developer docs")
    print()
    print("Classical vs. Postmodern Order Decision:")
    print("  Classical  : Physician places order in athena directly — Brook has no outbound role")
    print("  Postmodern : Brook drafts order, physician signs in athena task queue")
    print("               This POC demonstrates the Brook-drafts side.")
    print("               Whether athena sandbox supports task-queue signing is UNVERIFIED.")
    print()
    print("Athena orders path is fully greenfield in brook-backend.")
    print("Precedent: Redox ORM ingest (webhook -> queue -> 10-min processor)")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Orders POC: Create athena order and check status")
    parser.add_argument("--patient-id", default=os.environ.get("ATHENA_PATIENT_ID", ""))
    parser.add_argument(
        "--order-type",
        choices=["lab", "referral"],
        default="lab",
        help="Order type to create (default: lab)",
    )
    parser.add_argument(
        "--diagnosis-icd10",
        default="E11.65",
        help="ICD-10 diagnosis code for order indication (default: E11.65 = T2DM with hyperglycemia)",
    )
    parser.add_argument(
        "--department-id",
        default=os.environ.get("ATHENA_DEPARTMENT_ID", ""),
        help="athena department ID (or set ATHENA_DEPARTMENT_ID)",
    )
    parser.add_argument(
        "--provider-id",
        default=os.environ.get("ATHENA_PROVIDER_ID", ""),
        help="athena provider ID (or set ATHENA_PROVIDER_ID)",
    )
    parser.add_argument("--check-order-id", default="", help="If set, check status of this order ID")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client_id = os.environ.get("ATHENA_CLIENT_ID", "")
    client_secret = os.environ.get("ATHENA_CLIENT_SECRET", "")
    practice_id = os.environ.get("ATHENA_PRACTICE_ID", "")

    if args.dry_run:
        dry_run(practice_id, args.patient_id, args.order_type, args.diagnosis_icd10)
        return

    if not client_id or not client_secret or not practice_id:
        sys.exit("ATHENA_CLIENT_ID, ATHENA_CLIENT_SECRET, ATHENA_PRACTICE_ID required. Use --dry-run.")

    if not args.patient_id:
        sys.exit("--patient-id required")

    import hashlib
    compound = f"orders:{args.patient_id}:{practice_id}:{args.order_type}:{args.diagnosis_icd10}:{datetime.utcnow().strftime('%Y-%m-%dT%H')}"
    idempotency_key = hashlib.sha256(compound.encode()).hexdigest()[:32]

    print(f"[orders] Acquiring token ...")
    access_token = acquire_token(client_id, client_secret)

    if args.check_order_id:
        print(f"[orders] Checking order status for order {args.check_order_id} ...")
        status = get_order_status(access_token, practice_id, args.patient_id, args.check_order_id)
        print(f"[orders] Order status: {json.dumps(status, indent=2)}")
        return

    print(f"[orders] Creating {args.order_type} order for patient {args.patient_id} ...")
    if args.order_type == "lab":
        result = create_lab_order(
            access_token=access_token,
            practice_id=practice_id,
            patient_id=args.patient_id,
            diagnosis_icd10=args.diagnosis_icd10,
            department_id=args.department_id or "UNKNOWN",
            provider_id=args.provider_id or "UNKNOWN",
            idempotency_key=idempotency_key,
        )
    else:
        print(f"[orders] Referral order: endpoint TBD — see TODO in code.")
        sys.exit("Referral order creation not yet implemented — verify endpoint with athena docs.")

    print(f"[orders] Result: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    main()
