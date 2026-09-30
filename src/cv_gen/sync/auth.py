"""Token storage. The password is never stored; the JWT lives in the OS keyring.

CircuitVerse issues a 2-week RS256 JWT at login, with no refresh or revocation route.
``CV_TOKEN`` in the environment overrides the keyring (for scripts and CI).
"""

import base64
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import keyring
import keyring.errors

ENV_TOKEN = "CV_TOKEN"
_ACCOUNT = "jwt"


@dataclass(frozen=True, slots=True)
class TokenInfo:
    source: str  # "env" or "keyring"
    username: str | None
    email: str | None
    expires: datetime | None

    @property
    def expired(self) -> bool:
        return self.expires is not None and self.expires <= datetime.now(UTC)

    @property
    def expires_soon(self) -> bool:
        return self.expires is not None and self.expires - datetime.now(UTC) < timedelta(days=1)


def _service(server: str) -> str:
    return f"cv-gen:{urlparse(server).netloc or server}"


def _claims(token: str) -> dict:
    """Unverified JWT payload: for display and expiry warnings only, never for trust."""
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}


class TokenStore:
    def __init__(self, server: str):
        self.server = server
        self._service = _service(server)

    def get(self) -> tuple[str, str] | None:
        """(token, source) or None."""
        token = os.environ.get(ENV_TOKEN)
        if token:
            return token, "env"
        try:
            token = keyring.get_password(self._service, _ACCOUNT)
        except keyring.errors.KeyringError:
            return None
        return (token, "keyring") if token else None

    def save(self, token: str) -> None:
        keyring.set_password(self._service, _ACCOUNT, token)

    def delete(self) -> bool:
        try:
            keyring.delete_password(self._service, _ACCOUNT)
        except keyring.errors.PasswordDeleteError:
            return False
        return True

    def info(self) -> TokenInfo | None:
        found = self.get()
        if found is None:
            return None
        token, source = found
        claims = _claims(token)
        expires = claims.get("exp")
        return TokenInfo(
            source=source,
            username=claims.get("username"),
            email=claims.get("email"),
            expires=datetime.fromtimestamp(expires, UTC) if isinstance(expires, int) else None,
        )
