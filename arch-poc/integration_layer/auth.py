"""
auth.py — OAuth2 token management stub for the athena integration layer.

Brook context (from findings.md):
  The production athena integration uses OAuth2 client credentials.
  Auth flow: Basic auth (client_id:client_secret) to token endpoint,
  then Bearer token for all API calls.
  File: /tmp/brook-backend/src/main/java/ai/brook/api/rpm/emr/athena/api/AthenaApiService.java:40-43, 110

  Secrets injection: athena.client-id and athena.client-secret are injected
  via Spring @Value annotations in the Java service. In a K8s deployment
  these come from a Kubernetes Secret. The Redox integration uses a different
  pattern — RSA private key mounted from filesystem (volume mount from K8s Secret).
  File: /tmp/brook-backend/src/main/java/ai/brook/api/rpm/emr/redox/api/RedoxApiService.java:53-56, 115-135

  This Python stub demonstrates the OAuth2 client credentials flow. In production,
  client_id and client_secret would be read from environment variables or a secrets
  manager (Kubernetes Secret → env injection pattern, same as the Java service).
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TokenCache:
    """
    In-memory token cache. Production would add distributed caching
    (Redis or similar) to share tokens across multiple integration layer instances.
    """
    access_token: Optional[str] = None
    expires_at: float = 0.0  # Unix timestamp

    def is_valid(self) -> bool:
        """Return True if the cached token is still valid with a 60-second buffer."""
        return (
            self.access_token is not None
            and time.time() < (self.expires_at - 60)
        )


class AthenaOAuth2Client:
    """
    OAuth2 client credentials token manager for the athena integration.

    Mirrors the token-acquisition logic in AthenaApiService.java (brook-backend):
      - POST to token endpoint with Basic auth (client_id:client_secret)
      - Cache the bearer token; refresh when nearing expiry
      - All athena API calls use the cached bearer token

    In production this would hit the real athena OAuth2 token endpoint.
    This stub returns a mock token to enable integration layer POC testing
    without live credentials.
    """

    # Athena OAuth2 token endpoint (from AthenaApiService.java context)
    # Production: https://api.platform.athenahealth.com/oauth2/v1/token
    TOKEN_ENDPOINT = "https://api.platform.athenahealth.com/oauth2/v1/token"

    def __init__(self, client_id: str, client_secret: str, practice_id: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.practice_id = practice_id
        self._cache = TokenCache()

    def get_bearer_token(self) -> str:
        """
        Return a valid bearer token, refreshing if needed.

        Production behavior: POST to TOKEN_ENDPOINT with:
          Authorization: Basic base64(client_id:client_secret)
          Content-Type: application/x-www-form-urlencoded
          Body: grant_type=client_credentials

        Response: {"access_token": "...", "expires_in": 3600, "token_type": "Bearer"}
        """
        if self._cache.is_valid():
            logger.debug("auth: returning cached bearer token (still valid)")
            return self._cache.access_token

        logger.info(
            "auth: acquiring new bearer token from athena OAuth2 endpoint "
            "(MOCKED — no real HTTP call in POC)"
        )

        # TODO: In production, make the real HTTP POST here.
        # import base64, requests
        # credentials = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        # resp = requests.post(
        #     self.TOKEN_ENDPOINT,
        #     headers={"Authorization": f"Basic {credentials}"},
        #     data={"grant_type": "client_credentials"},
        #     timeout=30,
        # )
        # resp.raise_for_status()
        # data = resp.json()
        # token = data["access_token"]
        # expires_in = data.get("expires_in", 3600)

        # Mock token for POC
        token = f"mock-bearer-token-{self.practice_id}-{int(time.time())}"
        expires_in = 3600  # 1 hour (typical athena token lifetime)

        self._cache.access_token = token
        self._cache.expires_at = time.time() + expires_in

        logger.info(
            "auth: token acquired, valid for %d seconds", expires_in
        )
        return token

    def invalidate(self) -> None:
        """Force token refresh on next call (e.g., after a 401 response)."""
        self._cache.access_token = None
        self._cache.expires_at = 0.0
        logger.info("auth: token cache invalidated")
