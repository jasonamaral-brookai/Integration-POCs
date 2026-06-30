#!/usr/bin/env python3
"""
CCDA Inbound POC — GET CCDA document for a patient from athena
==============================================================
Pillar: CCDA Inbound (Phase 1a)
Endpoint: GET /v1/{practiceid}/patients/{patientid}/ccda
          (or /v1/{practiceid}/ccda/{patientid} — TODO: verify against athena docs)

Demonstrates:
  1. OAuth2 token acquisition (client credentials)
  2. GET CCDA document for a given patient
  3. Write raw CDA XML to a local file for inspection
  4. Parse minimal structured fields from the CDA envelope (Python stdlib xml only)
  5. Dry-run mode

NOTE: This is fully greenfield. From recon: zero existing CCDA handling in brook-backend.
No CDA parser library exists in any Brook repo. The full mapping work (encounters,
medications, problems, allergies -> Brook canonical model) is out of scope for this
wire POC — this proves the retrieval contract only.

Usage:
  python poc.py --patient-id 12345 --dry-run
  python poc.py --patient-id 12345

Environment variables required:
  ATHENA_CLIENT_ID
  ATHENA_CLIENT_SECRET
  ATHENA_PRACTICE_ID
"""

import argparse
import base64
import os
import sys
import time
import xml.etree.ElementTree as ET
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

# TODO: verify endpoint path against athena developer docs
# The build plan cites: GET /v1/{practiceid}/ccda/{patientid}/ccda
# athena developer docs may use: GET /v1/{practiceid}/patients/{patientid}/ccda
# Using the more standard REST form; sandbox validation required.
CCDA_ENDPOINT_TEMPLATE = (
    f"{BASE_URL}/v1/{{practice_id}}/patients/{{patient_id}}/ccda"
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
        print(f"[ccda-inbound] Token request failed: HTTP {resp.status_code}")
        print(f"[ccda-inbound] Body: {resp.text}")
        resp.raise_for_status()
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Retry helper (same pattern as foundation)
# ---------------------------------------------------------------------------

def request_with_retry(method: str, url: str, max_retries: int = MAX_RETRIES, **kwargs) -> "requests.Response":
    backoff = INITIAL_BACKOFF_SECONDS
    for attempt in range(1, max_retries + 2):
        print(f"[ccda-inbound] Attempt {attempt}: {method} {url}")
        try:
            resp = requests.request(method, url, **kwargs)
        except requests.exceptions.ConnectionError as exc:
            if attempt > max_retries:
                raise
            print(f"[ccda-inbound] Connection error: {exc}. Retrying in {backoff}s ...")
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        if resp.status_code == 429:
            if attempt > max_retries:
                resp.raise_for_status()
                return resp
            retry_after = float(resp.headers.get("Retry-After", backoff))
            wait = max(retry_after, backoff)
            print(f"[ccda-inbound] HTTP 429. Waiting {wait}s ...")
            time.sleep(wait)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        if resp.status_code in {500, 502, 503, 504}:
            if attempt > max_retries:
                resp.raise_for_status()
                return resp
            print(f"[ccda-inbound] HTTP {resp.status_code}. Retrying in {backoff}s ...")
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        return resp

    # Should be unreachable
    raise RuntimeError("request_with_retry: exhausted retries without returning")


# ---------------------------------------------------------------------------
# CCDA retrieval
# ---------------------------------------------------------------------------

def get_ccda(access_token: str, practice_id: str, patient_id: str) -> str:
    """
    GET CCDA for a patient. Returns the raw CDA XML string.
    athena returns Content-Type: text/xml or application/xml.
    """
    url = CCDA_ENDPOINT_TEMPLATE.format(practice_id=practice_id, patient_id=patient_id)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/xml, text/xml",
    }

    resp = request_with_retry("GET", url, headers=headers, timeout=60)

    if resp.status_code == 404:
        print(f"[ccda-inbound] Patient {patient_id} not found in practice {practice_id}.")
        print(f"[ccda-inbound] Response: {resp.text}")
        resp.raise_for_status()

    if resp.status_code == 401:
        print(f"[ccda-inbound] Auth failure — token may be expired. Response: {resp.text}")
        resp.raise_for_status()

    if not resp.ok:
        print(f"[ccda-inbound] CCDA fetch failed: HTTP {resp.status_code}")
        print(f"[ccda-inbound] Response: {resp.text}")
        resp.raise_for_status()

    print(f"[ccda-inbound] CCDA retrieved. Content-Type: {resp.headers.get('Content-Type', '?')}")
    print(f"[ccda-inbound] Document size: {len(resp.content)} bytes")

    return resp.text


# ---------------------------------------------------------------------------
# Minimal CDA envelope parse (stdlib only — no HL7/CDA library)
# ---------------------------------------------------------------------------

# C-CDA namespace
CDA_NS = "urn:hl7-org:v3"


def parse_ccda_envelope(cda_xml: str) -> dict:
    """
    Extract minimal metadata from the CDA envelope using stdlib xml.
    This is NOT a full CDA parser — it proves the XML is parseable and
    demonstrates where key fields live. Full mapping requires a proper
    CDA parser library (e.g., python-ccda, hl7apy, or a Java HAPI CDA parser).

    Fields extracted:
      - document_id: ClinicalDocument/id/@extension
      - effective_time: ClinicalDocument/effectiveTime/@value
      - patient_given_name: ClinicalDocument/recordTarget/patientRole/patient/name/given
      - patient_family_name: ClinicalDocument/recordTarget/patientRole/patient/name/family
      - patient_dob: ClinicalDocument/recordTarget/patientRole/patient/birthTime/@value
      - section_codes: list of section templateId/@root values (template IDs)

    Gaps documented in data-model-gaps.md:
      - encounters -> PersonaEncounter (MISSING model)
      - medications -> PersonaMedication (PARTIAL model)
      - problems -> persona.diagnoses[] / PatientCarePlans.problemList (duality unresolved)
      - allergies -> PersonaAllergy (PARTIAL model)
      - labs -> PersonaLab (MISSING EHR-sourced model)
    """
    try:
        root = ET.fromstring(cda_xml)
    except ET.ParseError as exc:
        return {"parse_error": str(exc)}

    def find_text(elem, path):
        ns = {"c": CDA_NS}
        node = elem.find(path, ns)
        return node.text if node is not None else None

    def find_attr(elem, path, attr):
        ns = {"c": CDA_NS}
        node = elem.find(path, ns)
        return node.get(attr) if node is not None else None

    doc_id = find_attr(root, "c:id", "extension")
    effective_time = find_attr(root, "c:effectiveTime", "value")

    patient_path_base = "c:recordTarget/c:patientRole/c:patient"
    given = find_text(root, f"{patient_path_base}/c:name/c:given")
    family = find_text(root, f"{patient_path_base}/c:name/c:family")
    dob = find_attr(root, f"{patient_path_base}/c:birthTime", "value")

    # Collect section template IDs to show document structure
    ns = {"c": CDA_NS}
    sections = root.findall(".//c:section/c:templateId", ns)
    section_roots = list({s.get("root", "") for s in sections if s.get("root")})

    return {
        "document_id": doc_id,
        "effective_time": effective_time,
        "patient_given_name": given,
        "patient_family_name": family,
        "patient_dob": dob,
        "section_template_ids": section_roots,
    }


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

def dry_run(practice_id: str, patient_id: str) -> None:
    url = CCDA_ENDPOINT_TEMPLATE.format(
        practice_id=practice_id or "{practice_id}",
        patient_id=patient_id or "{patient_id}",
    )
    print("\n[DRY RUN] CCDA Inbound — Request Shape")
    print("=" * 60)
    print(f"Step 1 — Token request:")
    print(f"  POST {TOKEN_ENDPOINT}")
    print(f"  Authorization: Basic base64(CLIENT_ID:CLIENT_SECRET)")
    print(f"  Body: grant_type=client_credentials")
    print()
    print(f"Step 2 — CCDA retrieval:")
    print(f"  Method : GET")
    print(f"  URL    : {url}")
    print(f"  # TODO: verify endpoint path against athena developer docs")
    print(f"  Headers:")
    print(f"    Authorization : Bearer <access_token>")
    print(f"    Accept        : application/xml, text/xml")
    print()
    print(f"Step 3 — Parse CDA envelope (minimal, stdlib xml):")
    print(f"  Extracts: document_id, effective_time, patient name, DOB, section template IDs")
    print(f"  Full mapping (medications, encounters, problems, allergies) requires a CDA parser library")
    print()
    print(f"Step 4 — Save raw XML to: ccda_output_{{patient_id}}.xml")
    print("=" * 60)
    print()
    print("NOTE: Zero existing CCDA handling in brook-backend. This is fully greenfield.")
    print("Data model gaps (from data-model-gaps.md):")
    print("  - PersonaEncounter: MISSING — new collection required for Phase 1a")
    print("  - PersonaMedication: PARTIAL — free-text only, no RxNorm")
    print("  - PersonaAllergy: PARTIAL — free-text only, no coding")
    print("  - PersonaLab: MISSING — no EHR lab store")
    print("  - DiagnosisSource.ATHENA_CCDA: not yet in enum")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="CCDA Inbound POC: GET CCDA from athena")
    parser.add_argument("--patient-id", default=os.environ.get("ATHENA_PATIENT_ID", ""), help="athena patient ID")
    parser.add_argument("--dry-run", action="store_true", help="Print request shape without hitting the API")
    parser.add_argument("--output-dir", default=".", help="Directory to write ccda_output_<patient_id>.xml")
    args = parser.parse_args()

    client_id = os.environ.get("ATHENA_CLIENT_ID", "")
    client_secret = os.environ.get("ATHENA_CLIENT_SECRET", "")
    practice_id = os.environ.get("ATHENA_PRACTICE_ID", "")

    if args.dry_run:
        dry_run(practice_id, args.patient_id)
        return

    if not client_id or not client_secret or not practice_id:
        sys.exit(
            "ATHENA_CLIENT_ID, ATHENA_CLIENT_SECRET, ATHENA_PRACTICE_ID must be set. "
            "Use --dry-run to print request shape."
        )

    if not args.patient_id:
        sys.exit("--patient-id is required (or set ATHENA_PATIENT_ID)")

    print(f"[ccda-inbound] Acquiring token ...")
    access_token = acquire_token(client_id, client_secret)
    print(f"[ccda-inbound] Token acquired.")

    print(f"[ccda-inbound] Fetching CCDA for patient {args.patient_id} in practice {practice_id} ...")
    cda_xml = get_ccda(access_token, practice_id, args.patient_id)

    # Write raw XML for inspection
    output_path = Path(args.output_dir) / f"ccda_output_{args.patient_id}.xml"
    output_path.write_text(cda_xml, encoding="utf-8")
    print(f"[ccda-inbound] Raw CDA XML written to: {output_path}")

    # Parse envelope
    parsed = parse_ccda_envelope(cda_xml)
    print("\n[ccda-inbound] CDA envelope fields:")
    for k, v in parsed.items():
        print(f"  {k}: {v}")

    print("\n[ccda-inbound] POC complete.")
    print("Next step: integrate a full CDA parser library (e.g., python-ccda or HAPI FHIR CDA converter)")
    print("to extract encounters, medications, problems, allergies for mapping to Brook canonical model.")


if __name__ == "__main__":
    main()
