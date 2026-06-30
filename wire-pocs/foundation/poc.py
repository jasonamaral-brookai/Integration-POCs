#!/usr/bin/env python3
"""
Foundation POC — athena OAuth2 + Rate-Limit-Aware HTTP Client
=============================================================
Pillar: Foundation (P0)
Endpoint: POST /oauth2/v1/token

Demonstrates:
  1. OAuth2 client credentials grant (Basic auth header)
  2. Retry + exponential backoff on HTTP 429 (rate limit)
  3. Idempotency key generation pattern (deterministic UUID v5)
  4. Dry-run mode that prints request shape without hitting the API

Usage:
  python poc.py                  # live token request
  python poc.py --dry-run        # print request shape only

Environment variables required (skip for --dry-run):
  ATHENA_CLIENT_ID
  ATHENA_CLIENT_SECRET
  ATHENA_PRACTICE_ID
"""

import argparse
import base64
import os
import sys
import time
import uuid
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

# Retry / backoff settings — mirrors ExponentialBackoffInterceptor.java semantics
# that exists in brook-backend but is not yet wired to AthenaApiService.
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 2
MAX_BACKOFF_SECONDS = 32
RATE_LIMIT_STATUS = 429
SERVER_ERROR_STATUSES = {500, 502, 503, 504}


# ---------------------------------------------------------------------------
# Idempotency key generation
# ---------------------------------------------------------------------------

def make_idempotency_key(entity: str, event_type: str, version: str) -> str:
    """
    Deterministic UUID v5 key scoped to a namespace UUID.
    Key format: {entity}:{event_type}:{version}
    This matches the pattern described in the build plan (Section 2.3).

    Example:
      entity     = "persona:abc123"
      event_type = "TokenRequest"
      version    = "2026-06-30T00:00:00Z"
    """
    namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # URL namespace
    name = f"{entity}:{event_type}:{version}"
    key = str(uuid.uuid5(namespace, name))
    return key


# ---------------------------------------------------------------------------
# Rate-limit-aware HTTP client
# ---------------------------------------------------------------------------

def _parse_retry_after(response: "requests.Response") -> float:
    """
    Parse Retry-After header. Supports seconds (integer) and HTTP-date forms.
    Falls back to 0.0 if header is absent or unparseable.
    """
    header = response.headers.get("Retry-After", "")
    if not header:
        return 0.0
    try:
        return float(header)
    except ValueError:
        # HTTP-date format not parsed here — treat as 0 and let backoff take over
        return 0.0


def request_with_retry(
    method: str,
    url: str,
    max_retries: int = MAX_RETRIES,
    initial_backoff: float = INITIAL_BACKOFF_SECONDS,
    **kwargs,
) -> "requests.Response":
    """
    HTTP request with exponential backoff on 429 and 5xx.

    This function demonstrates the wiring task that Phase 0 requires:
    connecting ExponentialBackoffInterceptor.java semantics to the athena
    client. The interceptor class already exists in brook-backend but is not
    wired to AthenaApiService.

    Raises:
        requests.exceptions.HTTPError if all retries are exhausted.
    """
    backoff = initial_backoff
    attempt = 0

    while True:
        attempt += 1
        print(f"[foundation] Attempt {attempt}/{max_retries + 1}: {method} {url}")

        try:
            resp = requests.request(method, url, **kwargs)
        except requests.exceptions.ConnectionError as exc:
            if attempt > max_retries:
                raise
            wait = min(backoff, MAX_BACKOFF_SECONDS)
            print(f"[foundation] Connection error: {exc}. Retrying in {wait}s ...")
            time.sleep(wait)
            backoff *= 2
            continue

        if resp.status_code == RATE_LIMIT_STATUS:
            if attempt > max_retries:
                print(f"[foundation] Rate limited (429) — max retries exhausted.")
                resp.raise_for_status()
                return resp  # unreachable but satisfies type checker

            retry_after = _parse_retry_after(resp)
            wait = max(retry_after, min(backoff, MAX_BACKOFF_SECONDS))
            print(
                f"[foundation] HTTP 429 received. Retry-After={retry_after}s. "
                f"Waiting {wait}s (attempt {attempt}/{max_retries + 1})"
            )
            time.sleep(wait)
            backoff *= 2
            continue

        if resp.status_code in SERVER_ERROR_STATUSES:
            if attempt > max_retries:
                print(f"[foundation] Server error ({resp.status_code}) — max retries exhausted.")
                resp.raise_for_status()
                return resp

            wait = min(backoff, MAX_BACKOFF_SECONDS)
            print(
                f"[foundation] HTTP {resp.status_code}. Retrying in {wait}s "
                f"(attempt {attempt}/{max_retries + 1})"
            )
            time.sleep(wait)
            backoff *= 2
            continue

        # Success (2xx) or non-retryable error (4xx except 429)
        return resp


# ---------------------------------------------------------------------------
# Token acquisition
# ---------------------------------------------------------------------------

def build_basic_auth_header(client_id: str, client_secret: str) -> str:
    """
    athena OAuth2 uses HTTP Basic auth on the token endpoint.
    Credential string: base64(client_id:client_secret)
    """
    raw = f"{client_id}:{client_secret}"
    encoded = base64.b64encode(raw.encode()).decode()
    return f"Basic {encoded}"


def request_token(client_id: str, client_secret: str) -> dict:
    """
    POST /oauth2/v1/token — client credentials grant.
    Returns the parsed JSON response (contains access_token, expires_in, token_type).
    Raises on non-2xx.
    """
    idempotency_key = make_idempotency_key(
        entity="system",
        event_type="TokenRequest",
        version=datetime.utcnow().strftime("%Y-%m-%dT%H:00:00Z"),  # hourly bucket
    )

    headers = {
        "Authorization": build_basic_auth_header(client_id, client_secret),
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Idempotency-Key": idempotency_key,  # informational; token endpoint may ignore
    }
    data = {"grant_type": "client_credentials"}

    resp = request_with_retry("POST", TOKEN_ENDPOINT, headers=headers, data=data)

    if not resp.ok:
        print(f"[foundation] Token request failed: HTTP {resp.status_code}")
        print(f"[foundation] Response body: {resp.text}")
        resp.raise_for_status()

    return resp.json()


# ---------------------------------------------------------------------------
# Dry-run: print request shape
# ---------------------------------------------------------------------------

def dry_run(client_id: str, client_secret: str) -> None:
    """
    Print the exact request shape that would be sent, without making the call.
    Credential values are masked.
    """
    idempotency_key = make_idempotency_key(
        entity="system",
        event_type="TokenRequest",
        version="2026-06-30T00:00:00Z",
    )

    masked_id = client_id[:4] + "****" if len(client_id) > 4 else "****"
    masked_secret = "****"
    raw_cred = f"{masked_id}:{masked_secret}"
    encoded = base64.b64encode(raw_cred.encode()).decode()

    print("\n[DRY RUN] Foundation — Token Request Shape")
    print("=" * 60)
    print(f"Method : POST")
    print(f"URL    : {TOKEN_ENDPOINT}")
    print(f"Headers:")
    print(f"  Authorization : Basic {encoded}  (base64 of client_id:client_secret)")
    print(f"  Content-Type  : application/x-www-form-urlencoded")
    print(f"  X-Idempotency-Key : {idempotency_key}")
    print(f"Body (form-encoded):")
    print(f"  grant_type=client_credentials")
    print()
    print("[DRY RUN] Retry configuration:")
    print(f"  MAX_RETRIES          : {MAX_RETRIES}")
    print(f"  INITIAL_BACKOFF_SEC  : {INITIAL_BACKOFF_SECONDS}")
    print(f"  MAX_BACKOFF_SEC      : {MAX_BACKOFF_SECONDS}")
    print(f"  Rate-limit status    : {RATE_LIMIT_STATUS} (reads Retry-After header)")
    print(f"  Server-error retry   : {SERVER_ERROR_STATUSES}")
    print()
    print("[DRY RUN] Sample idempotency key derivation:")
    test_key = make_idempotency_key("persona:abc123", "CarePlanUpdated", "v42")
    print(f"  make_idempotency_key('persona:abc123', 'CarePlanUpdated', 'v42')")
    print(f"  => {test_key}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Foundation POC: athena OAuth2 + retry/backoff"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print request shape without hitting the API",
    )
    args = parser.parse_args()

    client_id = os.environ.get("ATHENA_CLIENT_ID", "")
    client_secret = os.environ.get("ATHENA_CLIENT_SECRET", "")
    practice_id = os.environ.get("ATHENA_PRACTICE_ID", "")

    if args.dry_run:
        dry_run(client_id or "YOUR_CLIENT_ID", client_secret or "YOUR_CLIENT_SECRET")
        return

    if not client_id or not client_secret:
        sys.exit(
            "ATHENA_CLIENT_ID and ATHENA_CLIENT_SECRET must be set. "
            "Use --dry-run to print request shape without credentials."
        )

    print(f"[foundation] Requesting token for client_id={client_id[:4]}****")
    print(f"[foundation] Practice ID: {practice_id or '(not used for token endpoint)'}")

    token_data = request_token(client_id, client_secret)

    print("\n[foundation] Token acquired successfully.")
    print(f"  token_type  : {token_data.get('token_type', '?')}")
    print(f"  expires_in  : {token_data.get('expires_in', '?')} seconds")
    # Do not print the access_token value itself — treat as a secret
    access_token = token_data.get("access_token", "")
    if access_token:
        print(f"  access_token: {access_token[:8]}... (truncated)")

    print("\n[foundation] Idempotency key demo:")
    for entity, event, ver in [
        ("persona:abc123", "CarePlanUpdated", "v42"),
        ("persona:abc123", "CarePlanUpdated", "v42"),  # same -> same key
        ("persona:abc123", "CarePlanUpdated", "v43"),  # different version -> different key
    ]:
        key = make_idempotency_key(entity, event, ver)
        print(f"  ({entity}, {event}, {ver}) => {key}")


if __name__ == "__main__":
    main()
