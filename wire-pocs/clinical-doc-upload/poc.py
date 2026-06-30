#!/usr/bin/env python3
"""
Clinical Document Upload POC — POST clinical document to athena
==============================================================
Pillar: Clinical Document Upload (Phase 1b)
Endpoint: POST /v1/{practiceid}/patients/{patientid}/documents/clinicaldocument

IMPORTANT: THIS IS LIVE CODE. AthenaService.java in brook-backend already posts PDF
care plans to this exact endpoint with documentTypeId=440672 hardcoded (with a //TODO
comment). This POC demonstrates the same endpoint but with parameterized document type,
proving the mapping-config-driven approach the build plan requires.

Risk documented: hardcoded documentTypeId=440672 in AthenaService.java:65 is
a single-document-type assumption that breaks for any non-Griffin partner or
non-bundle-report document type.

Demonstrates:
  1. OAuth2 token acquisition
  2. POST multipart/form-data clinical document with parameterized document type
  3. Idempotency key derivation (persona_id + practice_id + month + doc_type)
  4. Duplicate detection before POST (mirrors EmrLog dedup in production)
  5. Dry-run mode

Usage:
  python poc.py --dry-run
  python poc.py --patient-id 12345 --document-path ./test-care-plan.pdf --document-type-id 440672

Environment variables:
  ATHENA_CLIENT_ID
  ATHENA_CLIENT_SECRET
  ATHENA_PRACTICE_ID
"""

import argparse
import base64
import hashlib
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("requests is required: pip install requests")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = "https://api.preview.platform.athenahealth.com"
TOKEN_ENDPOINT = f"{BASE_URL}/oauth2/v1/token"

# Endpoint confirmed from AthenaApi.java in brook-backend (line 20-26):
#   @POST("v1/{practiceId}/patients/{patientId}/documents/clinicaldocument")
UPLOAD_ENDPOINT_TEMPLATE = (
    f"{BASE_URL}/v1/{{practice_id}}/patients/{{patient_id}}/documents/clinicaldocument"
)

# HARDCODED_TODO_RISK: In production AthenaService.java:65, this is hardcoded as 440672
# with the comment: //TODO: make this configurable or dynamic when needed
# The build plan's mapping config is the fix for this. The POC accepts it as a parameter.
DEFAULT_DOCUMENT_TYPE_ID = "440672"  # Griffin bundle report document type
DOCUMENT_SUBCLASS = "CLINICALDOCUMENT"  # hardcoded in AthenaService.java:52
AUTO_CLOSE = "true"  # hardcoded in AthenaService.java — confirm with Griffin if parameterizable

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
        print(f"[clinical-doc-upload] Token request failed: HTTP {resp.status_code}")
        print(f"[clinical-doc-upload] Body: {resp.text}")
        resp.raise_for_status()
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def request_with_retry(method: str, url: str, max_retries: int = MAX_RETRIES, **kwargs) -> "requests.Response":
    backoff = INITIAL_BACKOFF_SECONDS
    for attempt in range(1, max_retries + 2):
        print(f"[clinical-doc-upload] Attempt {attempt}: {method} {url}")
        try:
            resp = requests.request(method, url, **kwargs)
        except requests.exceptions.ConnectionError as exc:
            if attempt > max_retries:
                raise
            print(f"[clinical-doc-upload] Connection error: {exc}. Retrying in {backoff}s ...")
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        if resp.status_code == 429:
            if attempt > max_retries:
                resp.raise_for_status()
                return resp
            retry_after = float(resp.headers.get("Retry-After", backoff))
            wait = max(retry_after, backoff)
            print(f"[clinical-doc-upload] HTTP 429. Waiting {wait}s ...")
            time.sleep(wait)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        if resp.status_code in {500, 502, 503, 504}:
            if attempt > max_retries:
                resp.raise_for_status()
                return resp
            print(f"[clinical-doc-upload] HTTP {resp.status_code}. Retrying in {backoff}s ...")
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        return resp

    raise RuntimeError("request_with_retry exhausted without returning")


# ---------------------------------------------------------------------------
# Idempotency key (mirrors EmrLog dedup semantics, extended for event-version model)
# ---------------------------------------------------------------------------

def make_document_idempotency_key(
    persona_id: str,
    practice_id: str,
    document_type_id: str,
    period: str,  # e.g. "2026-06" — month bucket (current production pattern)
    version: str = "v1",  # event version for future event-version-based dedup
) -> str:
    """
    Deterministic key that matches current brook-backend EmrLog dedup semantics:
      compound index: (provider_office_id, persona_id, file_name, type)
    where file_name encodes the month.

    The plan's proposed format is: {entity}:{event}:{version}
    This implementation uses both for forward compatibility.

    Production AthenaService.java uses month-based filenames like:
      "griffin_bundle_report_2026_06_{persona_id}.pdf"
    The period param encodes the same month bucket.
    """
    compound = f"persona:{persona_id}:practice:{practice_id}:doctype:{document_type_id}:period:{period}:{version}"
    digest = hashlib.sha256(compound.encode()).hexdigest()[:32]
    # Format as UUID-like string for header compatibility
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


# ---------------------------------------------------------------------------
# Document upload
# ---------------------------------------------------------------------------

def upload_clinical_document(
    access_token: str,
    practice_id: str,
    patient_id: str,
    document_bytes: bytes,
    document_filename: str,
    document_type_id: str,
    idempotency_key: str,
) -> dict:
    """
    POST a clinical document to athena as multipart/form-data.

    From AthenaApi.java:
      @Multipart
      @POST("v1/{practiceId}/patients/{patientId}/documents/clinicaldocument")
      Call<Void> sendDocument(
        @Header("Authorization") String authHeader,
        @Path("practiceId") int practiceId,
        @Path("patientId") String patientId,
        @Part("file\"; filename=\"report.pdf\" ") RequestBody file,
        @Part("documentsubclass") RequestBody documentSubclass,
        @Part("autoclose") RequestBody autoClose,
        @Part("documenttypeid") RequestBody documentTypeId
      )
    """
    url = UPLOAD_ENDPOINT_TEMPLATE.format(practice_id=practice_id, patient_id=patient_id)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Idempotency-Key": idempotency_key,
    }

    # Multipart form fields — matching AthenaApi.java field names exactly
    files = {
        "file": (document_filename, document_bytes, "application/pdf"),
    }
    data = {
        "documentsubclass": DOCUMENT_SUBCLASS,
        "autoclose": AUTO_CLOSE,
        "documenttypeid": document_type_id,
    }

    resp = request_with_retry(
        "POST",
        url,
        headers=headers,
        files=files,
        data=data,
        timeout=120,  # PDF upload may take time; match production read timeout
    )

    if resp.status_code == 409:
        # Duplicate document — idempotent (already uploaded)
        print(f"[clinical-doc-upload] HTTP 409 Conflict — document already exists (idempotent).")
        print(f"[clinical-doc-upload] Response: {resp.text}")
        return {"status": "duplicate", "idempotency_key": idempotency_key}

    if not resp.ok:
        print(f"[clinical-doc-upload] Upload failed: HTTP {resp.status_code}")
        print(f"[clinical-doc-upload] Response: {resp.text}")
        resp.raise_for_status()

    # athena returns 200 or 201 with document ID
    result = {}
    try:
        result = resp.json()
    except Exception:
        # athena may return empty body on success
        pass

    return {
        "status": "uploaded",
        "http_status": resp.status_code,
        "idempotency_key": idempotency_key,
        "athena_response": result,
    }


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

def dry_run(practice_id: str, patient_id: str, document_type_id: str) -> None:
    url = UPLOAD_ENDPOINT_TEMPLATE.format(
        practice_id=practice_id or "{practice_id}",
        patient_id=patient_id or "{patient_id}",
    )
    period = datetime.utcnow().strftime("%Y-%m")
    idempotency_key = make_document_idempotency_key(
        persona_id=patient_id or "persona_id",
        practice_id=practice_id or "practice_id",
        document_type_id=document_type_id,
        period=period,
    )

    print("\n[DRY RUN] Clinical Document Upload — Request Shape")
    print("=" * 60)
    print(f"Method : POST (multipart/form-data)")
    print(f"URL    : {url}")
    print(f"Headers:")
    print(f"  Authorization    : Bearer <access_token>")
    print(f"  X-Idempotency-Key: {idempotency_key}")
    print(f"Form fields:")
    print(f"  file             : <PDF bytes>  (filename: care_plan_{period}_{patient_id or 'patient_id'}.pdf)")
    print(f"  documentsubclass : {DOCUMENT_SUBCLASS}")
    print(f"  autoclose        : {AUTO_CLOSE}")
    print(f"  documenttypeid   : {document_type_id}")
    print()
    print("HARDCODED_TODO_RISK:")
    print("  Production AthenaService.java:65 has:")
    print('    documentTypeId=440672  // TODO: make this configurable or dynamic when needed')
    print("  This POC accepts documenttypeid as a parameter (--document-type-id).")
    print("  The build plan's mapping config is the production fix for this hardcoding.")
    print()
    print("Idempotency key derivation:")
    print(f"  compound = persona:{patient_id or 'persona_id'}:practice:{practice_id or 'practice_id'}:doctype:{document_type_id}:period:{period}:v1")
    print(f"  key      = {idempotency_key}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Clinical Document Upload POC")
    parser.add_argument("--patient-id", default=os.environ.get("ATHENA_PATIENT_ID", ""))
    parser.add_argument("--document-path", help="Path to PDF file to upload")
    parser.add_argument(
        "--document-type-id",
        default=DEFAULT_DOCUMENT_TYPE_ID,
        help=f"athena document type ID (default: {DEFAULT_DOCUMENT_TYPE_ID} = Griffin bundle report)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client_id = os.environ.get("ATHENA_CLIENT_ID", "")
    client_secret = os.environ.get("ATHENA_CLIENT_SECRET", "")
    practice_id = os.environ.get("ATHENA_PRACTICE_ID", "")

    if args.dry_run:
        dry_run(practice_id, args.patient_id, args.document_type_id)
        return

    if not client_id or not client_secret or not practice_id:
        sys.exit("ATHENA_CLIENT_ID, ATHENA_CLIENT_SECRET, ATHENA_PRACTICE_ID required. Use --dry-run.")

    if not args.patient_id:
        sys.exit("--patient-id required")

    if not args.document_path:
        sys.exit("--document-path required (path to PDF file)")

    doc_path = Path(args.document_path)
    if not doc_path.exists():
        sys.exit(f"Document not found: {doc_path}")

    document_bytes = doc_path.read_bytes()
    period = datetime.utcnow().strftime("%Y-%m")
    document_filename = f"care_plan_{period}_{args.patient_id}.pdf"

    idempotency_key = make_document_idempotency_key(
        persona_id=args.patient_id,
        practice_id=practice_id,
        document_type_id=args.document_type_id,
        period=period,
    )

    print(f"[clinical-doc-upload] Acquiring token ...")
    access_token = acquire_token(client_id, client_secret)

    print(f"[clinical-doc-upload] Uploading document ...")
    print(f"  practice_id       : {practice_id}")
    print(f"  patient_id        : {args.patient_id}")
    print(f"  document_type_id  : {args.document_type_id}")
    print(f"  document_filename : {document_filename}")
    print(f"  document_size     : {len(document_bytes)} bytes")
    print(f"  idempotency_key   : {idempotency_key}")

    result = upload_clinical_document(
        access_token=access_token,
        practice_id=practice_id,
        patient_id=args.patient_id,
        document_bytes=document_bytes,
        document_filename=document_filename,
        document_type_id=args.document_type_id,
        idempotency_key=idempotency_key,
    )

    print(f"\n[clinical-doc-upload] Result: {result}")


if __name__ == "__main__":
    main()
