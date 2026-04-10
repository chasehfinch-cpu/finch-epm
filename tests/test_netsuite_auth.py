"""Tests for NetSuite OAuth 2.0 certificate authentication.

Tests the JWT construction and credential handling without hitting
a real NetSuite instance. Integration tests require live credentials.
"""

from __future__ import annotations

import json
import time

import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)

from finch_epm.connectors.base import ConnectorAuthError
from finch_epm.connectors.netsuite.auth import (
    AccessToken,
    NetSuiteAuthenticator,
    NetSuiteCredentials,
)


@pytest.fixture
def test_private_key_pem() -> str:
    """Generate a throwaway RSA private key for testing."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    ).decode("utf-8")


@pytest.fixture
def test_credentials() -> NetSuiteCredentials:
    return NetSuiteCredentials(
        account_id="TSTDRV1234567",
        client_id="abc123def456",
        certificate_id="cert-id-789",
    )


class TestNetSuiteCredentials:
    def test_dataclass_fields(self) -> None:
        creds = NetSuiteCredentials("acct", "client", "cert")
        assert creds.account_id == "acct"
        assert creds.client_id == "client"
        assert creds.certificate_id == "cert"


class TestAccessToken:
    def test_not_expired_when_fresh(self) -> None:
        token = AccessToken(
            token="test",
            token_type="Bearer",
            expires_at=time.monotonic() + 3600,
        )
        assert not token.is_expired

    def test_expired_when_past(self) -> None:
        token = AccessToken(
            token="test",
            token_type="Bearer",
            expires_at=time.monotonic() - 100,
        )
        assert token.is_expired

    def test_authorization_header(self) -> None:
        token = AccessToken(
            token="my_token",
            token_type="Bearer",
            expires_at=time.monotonic() + 3600,
        )
        assert token.authorization_header == "Bearer my_token"


class TestAuthenticator:
    def test_init_loads_key(
        self, test_credentials: NetSuiteCredentials, test_private_key_pem: str
    ) -> None:
        auth = NetSuiteAuthenticator(test_credentials, test_private_key_pem)
        assert auth._private_key is not None
        auth.close()

    def test_invalid_key_raises(self, test_credentials: NetSuiteCredentials) -> None:
        with pytest.raises(ConnectorAuthError, match="Failed to load private key"):
            NetSuiteAuthenticator(test_credentials, "not-a-valid-key")

    def test_jwt_assertion_is_valid_rsa(
        self, test_credentials: NetSuiteCredentials, test_private_key_pem: str
    ) -> None:
        """Verify the JWT assertion has the right structure with RSA key."""
        import jwt as pyjwt

        auth = NetSuiteAuthenticator(test_credentials, test_private_key_pem)
        assert auth._jwt_algorithm == "PS256"
        assertion = auth._build_jwt_assertion()

        header = pyjwt.get_unverified_header(assertion)
        assert header["alg"] == "PS256"
        assert header["kid"] == test_credentials.certificate_id
        assert header["typ"] == "JWT"

        payload = pyjwt.decode(assertion, options={"verify_signature": False})
        assert payload["iss"] == test_credentials.client_id
        assert payload["scope"] == "rest_webservices"
        assert "aud" in payload
        assert "exp" in payload
        assert "iat" in payload
        assert "jti" in payload

        auth.close()

    def test_jwt_assertion_ec_key(self, test_credentials: NetSuiteCredentials) -> None:
        """Verify EC keys use ES256 algorithm."""
        import jwt as pyjwt

        ec_key = ec.generate_private_key(ec.SECP256R1())
        ec_pem = ec_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        ).decode("utf-8")

        auth = NetSuiteAuthenticator(test_credentials, ec_pem)
        assert auth._jwt_algorithm == "ES256"

        assertion = auth._build_jwt_assertion()
        header = pyjwt.get_unverified_header(assertion)
        assert header["alg"] == "ES256"

        auth.close()

    def test_token_url_format(
        self, test_credentials: NetSuiteCredentials, test_private_key_pem: str
    ) -> None:
        auth = NetSuiteAuthenticator(test_credentials, test_private_key_pem)
        url = auth._token_url
        # Account ID with uppercase/dashes should be lowercased/underscored
        assert "tstdrv1234567" in url
        assert "suitetalk.api.netsuite.com" in url
        auth.close()

    def test_close_clears_state(
        self, test_credentials: NetSuiteCredentials, test_private_key_pem: str
    ) -> None:
        auth = NetSuiteAuthenticator(test_credentials, test_private_key_pem)
        auth.close()
        assert auth._current_token is None
        assert auth._http_client is None
