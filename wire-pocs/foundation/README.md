# Foundation POC — athena OAuth2 + Rate-Limit-Aware HTTP Client

**Pillar:** Foundation (P0)
**Status:** Not validated against athena sandbox — credentials required.

---

## Athena endpoint

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/oauth2/v1/token` | Acquire OAuth2 access token (client credentials grant) |

---

## Request shape

```
POST https://api.preview.platform.athenahealth.com/oauth2/v1/token
Authorization: Basic base64(CLIENT_ID:CLIENT_SECRET)
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
```

Key fields:
- `Authorization` header — HTTP Basic auth with `base64(client_id:client_secret)`. NOT Bearer.
- `grant_type` — must be exactly `client_credentials`.
- No `scope` required for standard athena API access (confirm with athena sandbox).

---

## Response shape

```json
{
  "access_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

Key fields to extract:
- `access_token` — use as `Authorization: Bearer <token>` on all subsequent API calls
- `expires_in` — seconds until token expires; cache and refresh before expiry
- `token_type` — always `Bearer` for athena

---

## Retry and backoff pattern

This POC demonstrates the retry wiring that Phase 0 requires for the production `AthenaApiService`. From recon findings: `ExponentialBackoffInterceptor.java` exists in brook-backend at `src/main/java/ai/brook/utils/ExponentialBackoffInterceptor.java` but is not wired to the production OkHttp client builders.

The POC implements equivalent semantics in Python:

| Scenario | Behavior |
|----------|----------|
| HTTP 429 | Parse `Retry-After` header; wait that duration (min) then retry with exponential backoff |
| HTTP 5xx (500/502/503/504) | Exponential backoff, retry up to MAX_RETRIES |
| HTTP 4xx (except 429) | Do not retry; raise immediately |
| Connection error | Retry with backoff |

Settings: `MAX_RETRIES=3`, `INITIAL_BACKOFF=2s`, `MAX_BACKOFF=32s`.

---

## Idempotency key generation

The build plan (Section 2.3) specifies idempotency keys of the form `{entity}:{event_type}:{version}`. This POC uses UUID v5 (deterministic, namespace-scoped) to generate them:

```python
make_idempotency_key("persona:abc123", "CarePlanUpdated", "v42")
# => same UUID every time for the same inputs (replay-safe)
```

The token endpoint does not use idempotency keys; the pattern is demonstrated here as a utility for all downstream pillars.

---

## Failure modes

| Scenario | athena response |
|----------|----------------|
| Invalid client_id or client_secret | HTTP 401, body: `{"error":"invalid_client"}` |
| Malformed Basic auth header | HTTP 400, body: `{"error":"invalid_request"}` |
| Missing grant_type | HTTP 400, body: `{"error":"unsupported_grant_type"}` or `{"error":"invalid_request"}` |
| Rate limited | HTTP 429 with `Retry-After` header (seconds) |
| athena service unavailable | HTTP 503 |

---

## Running the POC

```bash
# Dry run — prints request shape, no API call
python poc.py --dry-run

# Live run — requires credentials
export ATHENA_CLIENT_ID=your_client_id
export ATHENA_CLIENT_SECRET=your_client_secret
export ATHENA_PRACTICE_ID=your_practice_id
python poc.py
```

---

## Assumptions requiring sandbox validation

1. **Token endpoint path** — `/oauth2/v1/token` is consistent with athena developer documentation. Confirm exact path in sandbox.
2. **Basic auth format** — athena uses HTTP Basic auth on the token endpoint (not `client_id`/`client_secret` as form fields). Confirm in sandbox.
3. **Token TTL** — assuming 3600 seconds. If shorter, token refresh logic needs tighter scheduling.
4. **Rate limits on token endpoint** — unknown. If athena rate-limits token requests separately from API calls, token caching with proactive refresh is required.
5. **Sandbox vs. preview credentials** — the sandbox (`api.preview.platform.athenahealth.com`) uses separate credentials from the production preview environment Brook will provision. Confirm credential set with athena.

---

## Blockers preventing end-to-end testing

Athena sandbox credentials (`ATHENA_CLIENT_ID`, `ATHENA_CLIENT_SECRET`) are not available in this environment. The POC is written to work correctly when credentials are provided. Use `--dry-run` to inspect the request shape without credentials.

To obtain sandbox credentials: submit an athena developer account request at https://developer.athenahealth.com/.
