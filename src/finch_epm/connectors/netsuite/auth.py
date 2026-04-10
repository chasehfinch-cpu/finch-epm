"""NetSuite OAuth 2.0 Client Credentials authentication with certificate.

Flow:
    1. Load private key from OS keychain (stored there during setup)
    2. Build a JWT assertion signed with the private key
    3. POST the assertion to NetSuite's token endpoint
    4. Receive an access token (valid ~60 minutes)
    5. Use the access token in Authorization: Bearer headers

The private key never touches the filesystem at runtime — it lives
exclusively in the OS credential store.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from finch_epm.connectors.base import ConnectorAuthError

# NetSuite OAuth 2.0 token endpoint template
_TOKEN_URL = "https://{account_id}.suitetalk.api.netsuite.com/services/rest/auth/oauth2/v1/token"

# JWT lifetime in seconds (NetSuite allows up to 60 minutes)
_JWT_LIFETIME_SECONDS = 3600

# Buffer before expiry to trigger proactive refresh (5 minutes)
_REFRESH_BUFFER_SECONDS = 300


@dataclass
class NetSuiteCredentials:
    """Non-secret identifiers needed to build the auth request.

    These come from profiles.json (non-secret config).
    The private key itself is retrieved from keyring separately.
    """

    account_id: str
    client_id: str
    certificate_id: str


@dataclass
class AccessToken:
    """A live NetSuite access token with expiry tracking."""

    token: str
    token_type: str
    expires_at: float  # time.monotonic() timestamp
    raw_response: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """True if the token is expired or within the refresh buffer."""
        return time.monotonic() >= (self.expires_at - _REFRESH_BUFFER_SECONDS)

    @property
    def authorization_header(self) -> str:
        """The value for the Authorization HTTP header."""
        return f"Bearer {self.token}"


class NetSuiteAuthenticator:
    """Handles the OAuth 2.0 Client Credentials + JWT assertion flow.

    Usage::

        auth = NetSuiteAuthenticator(credentials, private_key_pem)
        token = auth.get_token()  # fetches or returns cached token
        headers = auth.get_headers()  # returns dict with Authorization
    """

    def __init__(
        self,
        credentials: NetSuiteCredentials,
        private_key_pem: str,
    ) -> None:
        self._creds = credentials
        self._private_key_pem = private_key_pem
        self._private_key = self._load_private_key(private_key_pem)
        self._jwt_algorithm = self._detect_algorithm(self._private_key)
        self._current_token: AccessToken | None = None
        self._http_client: httpx.Client | None = None

    @staticmethod
    def _load_private_key(pem_data: str) -> Any:
        """Parse a PEM-encoded private key (RSA or EC)."""
        try:
            return load_pem_private_key(
                pem_data.encode("utf-8"),
                password=None,
            )
        except Exception as e:
            raise ConnectorAuthError(
                f"Failed to load private key: {e}. "
                "Ensure the key is a valid PEM-encoded RSA or EC private key."
            ) from e

    @staticmethod
    def _detect_algorithm(private_key: Any) -> str:
        """Detect the JWT signing algorithm based on key type.

        NetSuite supports:
            - PS256 (RSA-PSS with SHA-256) for RSA keys
            - ES256 (ECDSA with P-256 and SHA-256) for EC keys
        """
        if isinstance(private_key, rsa.RSAPrivateKey):
            return "PS256"
        elif isinstance(private_key, ec.EllipticCurvePrivateKey):
            return "ES256"
        else:
            raise ConnectorAuthError(
                f"Unsupported key type: {type(private_key).__name__}. "
                "NetSuite requires RSA or EC (P-256) keys."
            )

    def _build_jwt_assertion(self) -> str:
        """Build and sign a JWT assertion for the token request.

        The JWT contains:
            iss: client_id
            scope: rest_webservices
            aud: token endpoint URL
            iat: current time
            exp: current time + lifetime
            jti: unique ID to prevent replay
        """
        now = int(time.time())
        token_url = self._token_url

        payload = {
            "iss": self._creds.client_id,
            "scope": "rest_webservices",
            "aud": token_url,
            "iat": now,
            "exp": now + _JWT_LIFETIME_SECONDS,
            "jti": str(uuid.uuid4()),
        }

        headers = {
            "typ": "JWT",
            "alg": self._jwt_algorithm,
            "kid": self._creds.certificate_id,
        }

        return jwt.encode(
            payload,
            self._private_key,
            algorithm=self._jwt_algorithm,
            headers=headers,
        )

    @property
    def _token_url(self) -> str:
        """Build the token endpoint URL for this account."""
        # NetSuite account IDs use underscores in URLs where the ID has dashes
        account_slug = self._creds.account_id.replace("-", "_").lower()
        return _TOKEN_URL.format(account_id=account_slug)

    def _request_token(self) -> AccessToken:
        """Exchange a JWT assertion for an access token."""
        assertion = self._build_jwt_assertion()

        if self._http_client is None:
            self._http_client = httpx.Client(timeout=30.0)

        try:
            response = self._http_client.post(
                self._token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_assertion_type": (
                        "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
                    ),
                    "client_assertion": assertion,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as e:
            raise ConnectorAuthError(
                f"Failed to reach NetSuite token endpoint: {e}"
            ) from e

        if response.status_code != 200:
            # Parse error details if available
            try:
                error_body = response.json()
                error_msg = error_body.get("error_description", error_body.get("error", ""))
            except Exception:
                error_msg = response.text[:500]

            raise ConnectorAuthError(
                f"NetSuite token request failed (HTTP {response.status_code}): "
                f"{error_msg}"
            )

        data = response.json()
        expires_in = data.get("expires_in", _JWT_LIFETIME_SECONDS)

        return AccessToken(
            token=data["access_token"],
            token_type=data.get("token_type", "Bearer"),
            expires_at=time.monotonic() + expires_in,
            raw_response=data,
        )

    def get_token(self) -> AccessToken:
        """Get a valid access token, refreshing if expired.

        Returns:
            A non-expired AccessToken.

        Raises:
            ConnectorAuthError: If token request fails.
        """
        if self._current_token is None or self._current_token.is_expired:
            self._current_token = self._request_token()
        return self._current_token

    def get_headers(self) -> dict[str, str]:
        """Get HTTP headers including a valid Authorization header.

        Returns:
            Dict with Authorization and Prefer headers for NetSuite REST API.
        """
        token = self.get_token()
        return {
            "Authorization": token.authorization_header,
            "Prefer": "transient",
            "Content-Type": "application/json",
        }

    def validate(self) -> bool:
        """Test that credentials are valid by requesting a token.

        Returns:
            True if a token was successfully obtained.
        """
        try:
            self.get_token()
            return True
        except ConnectorAuthError:
            return False

    def close(self) -> None:
        """Release HTTP resources."""
        if self._http_client is not None:
            self._http_client.close()
            self._http_client = None
        self._current_token = None
