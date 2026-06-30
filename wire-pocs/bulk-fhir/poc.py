#!/usr/bin/env python3
"""
Bulk FHIR POC — Initiate bulk FHIR export from athena and poll for completion
=============================================================================
Pillar: Bulk FHIR (Phase 4)
Endpoints:
  POST/GET $export    — Initiate async bulk FHIR export (FHIR R4 Bulk Data Access)
  GET      <poll_url> — Poll export job status
  GET      <file_url> — Download NDJSON result files

athena's Bulk FHIR export follows the FHIR Bulk Data Access IG (v1.0.1/v2.0.0):
  1. Initiate: GET /fhir/r4/Patient/$export  (with headers)
  2. Response: 202 Accepted + Content-Location: <status_url>
  3. Poll: GET <status_url> until 200 (complete) or 4xx (error)
  4. Download: GET each file URL from the manifest's output[]

NOTE: FHIR R4 bulk export is async. This POC demonstrates the full polling pattern.

TODO: Verify athena's FHIR base URL and exact $export endpoint path against
      athena developer docs. athena FHIR R4 API path may differ from standard.

Usage:
  python poc.py --dry-run
  python poc.py --resource-types Patient,Condition,Observation

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

# TODO: verify athena FHIR R4 base URL against athena developer docs
# Standard athena FHIR R4 path is typically:
#   /fhir/r4/{practiceid}/...  or
#   /fhir/r4/...  (tenant-scoped via token)
# Using the practice-scoped form; confirm in sandbox.
FHIR_BASE_TEMPLATE = f"{BASE_URL}/fhir/r4"

# FHIR Bulk Data $export endpoint
# Standard: GET /fhir/r4/Patient/$export  (patient-level export)
# TODO: verify endpoint path against athena developer docs
BULK_EXPORT_ENDPOINT_TEMPLATE = f"{FHIR_BASE_TEMPLATE}/Patient/$export"

# Polling configuration for the async export job
POLL_INTERVAL_SECONDS = 10   # start at 10 seconds
POLL_MAX_SECONDS = 3600      # give up after 1 hour
POLL_BACKOFF_FACTOR = 1.5    # increase interval by 50% each poll
POLL_MAX_INTERVAL_SECONDS = 120  # cap at 2 minutes

# FHIR resource types relevant to Brook patient population
# Filtered to what data-model-gaps.md identifies as needing canonical store
DEFAULT_RESOURCE_TYPES = "Patient,Condition,Observation,AllergyIntolerance,MedicationRequest,Encounter"

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
        print(f"[bulk-fhir] Token request failed: HTTP {resp.status_code}")
        print(f"[bulk-fhir] Body: {resp.text}")
        resp.raise_for_status()
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def request_with_retry(method: str, url: str, max_retries: int = MAX_RETRIES, **kwargs) -> "requests.Response":
    backoff = INITIAL_BACKOFF_SECONDS
    for attempt in range(1, max_retries + 2):
        print(f"[bulk-fhir] Attempt {attempt}: {method} {url}")
        try:
            resp = requests.request(method, url, **kwargs)
        except requests.exceptions.ConnectionError as exc:
            if attempt > max_retries:
                raise
            print(f"[bulk-fhir] Connection error: {exc}. Retrying in {backoff}s ...")
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        if resp.status_code == 429:
            if attempt > max_retries:
                resp.raise_for_status()
                return resp
            retry_after = float(resp.headers.get("Retry-After", backoff))
            wait = max(retry_after, backoff)
            print(f"[bulk-fhir] HTTP 429. Waiting {wait}s ...")
            time.sleep(wait)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        if resp.status_code in {500, 502, 503, 504}:
            if attempt > max_retries:
                resp.raise_for_status()
                return resp
            print(f"[bulk-fhir] HTTP {resp.status_code}. Retrying in {backoff}s ...")
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        return resp

    raise RuntimeError("request_with_retry exhausted without returning")


# ---------------------------------------------------------------------------
# Step 1: Initiate bulk export
# ---------------------------------------------------------------------------

def initiate_bulk_export(
    access_token: str,
    practice_id: str,
    resource_types: str,
    since: str = "",
) -> str:
    """
    Initiate a FHIR R4 bulk export.

    Per FHIR Bulk Data Access IG:
      - Request: GET /fhir/r4/Patient/$export
      - Headers: Accept: application/fhir+json, Prefer: respond-async
      - Query params: _type (comma-separated resource types), _since (ISO8601)
      - Response: 202 Accepted + Content-Location header containing poll URL

    Returns the poll URL from the Content-Location header.
    """
    # TODO: verify endpoint path against athena developer docs
    # Some athena implementations scope the export by practice: /fhir/r4/{practiceid}/Patient/$export
    url = BULK_EXPORT_ENDPOINT_TEMPLATE

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/fhir+json",
        "Prefer": "respond-async",
    }
    params = {"_type": resource_types}
    if since:
        params["_since"] = since

    resp = request_with_retry("GET", url, headers=headers, params=params, timeout=30)

    if resp.status_code == 202:
        poll_url = resp.headers.get("Content-Location", "")
        if not poll_url:
            raise ValueError(
                "athena returned 202 but no Content-Location header. "
                "Cannot poll for export status."
            )
        print(f"[bulk-fhir] Export initiated. Poll URL: {poll_url}")
        return poll_url

    if not resp.ok:
        print(f"[bulk-fhir] Export initiation failed: HTTP {resp.status_code}")
        print(f"[bulk-fhir] Response: {resp.text}")
        resp.raise_for_status()

    # Unexpected: some implementations return 200 synchronously for small datasets
    print(f"[bulk-fhir] Unexpected status {resp.status_code}. Treating as complete.")
    return ""


# ---------------------------------------------------------------------------
# Step 2: Poll export status
# ---------------------------------------------------------------------------

def poll_export_status(access_token: str, poll_url: str) -> dict:
    """
    Poll the export job status URL until complete (200) or failed (4xx/5xx).

    Per FHIR Bulk Data Access IG:
      - While in progress: 202 Accepted (+ optional X-Progress header)
      - On complete: 200 OK with JSON manifest
      - On error: 4xx/5xx

    The manifest JSON (on 200) contains:
      {
        "transactionTime": "...",
        "request": "...",
        "requiresAccessToken": true,
        "output": [
          {"type": "Patient", "url": "https://..."},
          {"type": "Condition", "url": "https://..."},
          ...
        ],
        "error": []
      }
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    elapsed = 0
    interval = POLL_INTERVAL_SECONDS

    while elapsed < POLL_MAX_SECONDS:
        print(f"[bulk-fhir] Polling export status (elapsed: {elapsed}s, interval: {interval}s) ...")
        resp = request_with_retry("GET", poll_url, headers=headers, timeout=30)

        if resp.status_code == 202:
            progress = resp.headers.get("X-Progress", "in progress")
            print(f"[bulk-fhir] Export in progress: {progress}")
            time.sleep(interval)
            elapsed += interval
            interval = min(interval * POLL_BACKOFF_FACTOR, POLL_MAX_INTERVAL_SECONDS)
            continue

        if resp.status_code == 200:
            print(f"[bulk-fhir] Export complete.")
            return resp.json()

        # Terminal failure
        print(f"[bulk-fhir] Export failed: HTTP {resp.status_code}")
        print(f"[bulk-fhir] Response: {resp.text}")
        resp.raise_for_status()

    raise TimeoutError(f"Bulk export did not complete within {POLL_MAX_SECONDS}s")


# ---------------------------------------------------------------------------
# Step 3: Download NDJSON files
# ---------------------------------------------------------------------------

def download_ndjson_file(access_token: str, file_url: str, output_path: str) -> int:
    """
    Download one NDJSON export file from the manifest.
    Returns the number of FHIR resources downloaded (line count).

    Per FHIR Bulk Data Access IG, each line is a JSON FHIR resource.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/fhir+ndjson",
    }

    resp = request_with_retry("GET", file_url, headers=headers, timeout=300, stream=True)
    if not resp.ok:
        print(f"[bulk-fhir] File download failed: HTTP {resp.status_code}")
        print(f"[bulk-fhir] URL: {file_url}")
        resp.raise_for_status()

    line_count = 0
    with open(output_path, "wb") as f:
        for line in resp.iter_lines():
            if line:
                f.write(line + b"\n")
                line_count += 1

    return line_count


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

def dry_run(practice_id: str, resource_types: str) -> None:
    print("\n[DRY RUN] Bulk FHIR Export — Request Shape")
    print("=" * 60)
    print("athena FHIR R4 Bulk Data Access IG — async three-step pattern")
    print()
    print("Step 1 — Initiate export:")
    print(f"  Method : GET")
    print(f"  URL    : {BULK_EXPORT_ENDPOINT_TEMPLATE}")
    print(f"  # TODO: verify endpoint path against athena developer docs")
    print(f"  # Alternative: /fhir/r4/{practice_id or '{practice_id}'}/Patient/$export")
    print(f"  Headers:")
    print(f"    Authorization : Bearer <access_token>")
    print(f"    Accept        : application/fhir+json")
    print(f"    Prefer        : respond-async")
    print(f"  Query params:")
    print(f"    _type   : {resource_types}")
    print(f"    _since  : {{ISO8601 timestamp}}  (optional; for incremental exports)")
    print(f"  Expected response: 202 Accepted + Content-Location: <poll_url>")
    print()
    print("Step 2 — Poll status (repeat until 200):")
    print(f"  Method : GET")
    print(f"  URL    : <poll_url from Content-Location header>")
    print(f"  Headers:")
    print(f"    Authorization : Bearer <access_token>")
    print(f"    Accept        : application/json")
    print(f"  202 response: in progress (+ optional X-Progress header)")
    print(f"  200 response: export manifest JSON")
    print(f"  Poll strategy: start at {POLL_INTERVAL_SECONDS}s, backoff x{POLL_BACKOFF_FACTOR}, cap at {POLL_MAX_INTERVAL_SECONDS}s")
    print()
    print("Step 3 — Download NDJSON files:")
    print(f"  Method : GET")
    print(f"  URL    : each output[].url from the manifest")
    print(f"  Headers:")
    print(f"    Authorization : Bearer <access_token>")
    print(f"    Accept        : application/fhir+ndjson")
    print(f"  Format: one FHIR resource JSON per line")
    print()
    print("Manifest response shape (Step 2, 200 OK):")
    print(json.dumps({
        "transactionTime": "2026-06-30T00:00:00Z",
        "request": f"{BULK_EXPORT_ENDPOINT_TEMPLATE}?_type={resource_types}",
        "requiresAccessToken": True,
        "output": [
            {"type": "Patient", "url": "https://api.preview.platform.athenahealth.com/fhir/r4/bulk/files/Patient-0001.ndjson"},
            {"type": "Condition", "url": "https://api.preview.platform.athenahealth.com/fhir/r4/bulk/files/Condition-0001.ndjson"},
        ],
        "error": []
    }, indent=2))
    print()
    print("Eligibility filtering (build plan Phase 4 scope):")
    print("  Global exclusions (always): deceased, inactive, under-18")
    print("  Partner-configurable: additional toggles per partner config")
    print("  Applied: after download, during NDJSON -> Brook canonical model upsert")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk FHIR POC: Initiate and poll athena bulk export")
    parser.add_argument(
        "--resource-types",
        default=DEFAULT_RESOURCE_TYPES,
        help=f"Comma-separated FHIR resource types (default: {DEFAULT_RESOURCE_TYPES})",
    )
    parser.add_argument(
        "--since",
        default="",
        help="ISO8601 timestamp for incremental export (_since parameter)",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory to write downloaded NDJSON files",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client_id = os.environ.get("ATHENA_CLIENT_ID", "")
    client_secret = os.environ.get("ATHENA_CLIENT_SECRET", "")
    practice_id = os.environ.get("ATHENA_PRACTICE_ID", "")

    if args.dry_run:
        dry_run(practice_id, args.resource_types)
        return

    if not client_id or not client_secret or not practice_id:
        sys.exit("ATHENA_CLIENT_ID, ATHENA_CLIENT_SECRET, ATHENA_PRACTICE_ID required. Use --dry-run.")

    print(f"[bulk-fhir] Acquiring token ...")
    access_token = acquire_token(client_id, client_secret)

    # Step 1: Initiate
    poll_url = initiate_bulk_export(
        access_token=access_token,
        practice_id=practice_id,
        resource_types=args.resource_types,
        since=args.since,
    )

    if not poll_url:
        print("[bulk-fhir] No poll URL — export may have completed synchronously. Check response.")
        return

    # Step 2: Poll
    manifest = poll_export_status(access_token, poll_url)
    print(f"\n[bulk-fhir] Manifest:")
    print(json.dumps(manifest, indent=2))

    # Step 3: Download each file
    output_files = manifest.get("output", [])
    print(f"\n[bulk-fhir] Downloading {len(output_files)} NDJSON file(s) ...")
    for i, file_entry in enumerate(output_files):
        resource_type = file_entry.get("type", f"unknown_{i}")
        file_url = file_entry.get("url", "")
        if not file_url:
            print(f"[bulk-fhir] Skipping entry {i}: no URL")
            continue

        output_path = os.path.join(args.output_dir, f"{resource_type}_{i:04d}.ndjson")
        print(f"[bulk-fhir] Downloading {resource_type} -> {output_path}")
        count = download_ndjson_file(access_token, file_url, output_path)
        print(f"[bulk-fhir]   {count} resources written.")

    errors = manifest.get("error", [])
    if errors:
        print(f"\n[bulk-fhir] WARNING: {len(errors)} error(s) in manifest:")
        for err in errors:
            print(f"  {err}")

    print(f"\n[bulk-fhir] Bulk export complete.")


if __name__ == "__main__":
    main()
