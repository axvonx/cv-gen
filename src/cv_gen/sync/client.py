"""CircuitVerse HTTP API client.

Every wire-protocol detail lives here. Circuit data endpoints (``circuit_data``,
``POST /projects``, ``update_circuit``) are handled here and covered by protocol tests.
"""

import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from ..project import Document

USER_AGENT = "cv-gen (+https://github.com/axvonx/cv-gen)"


class CircuitVerseError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


class AuthenticationError(CircuitVerseError):
    """401: missing, invalid, or expired token (or bad credentials at login)."""


class PermissionDenied(CircuitVerseError):
    """403: only the project author or a collaborator may edit circuit data."""


class NotFound(CircuitVerseError):
    pass


class PayloadTooLarge(CircuitVerseError):
    pass


class RateLimited(CircuitVerseError):
    """429: 300 requests / 5 min per IP; logins 5 / 20 s per IP and per email."""


_ERRORS = {401: AuthenticationError, 403: PermissionDenied, 404: NotFound,
           413: PayloadTooLarge, 429: RateLimited}


def project_ref(value: str) -> str:
    """Accept an id, a slug, or a CircuitVerse project URL; return the id/slug."""
    value = value.strip()
    if "://" in value:
        segments = [s for s in urlparse(value).path.split("/") if s]
        if not segments:
            raise ValueError(f"no project in URL {value!r}")
        value = segments[-1]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError(f"not a project id or slug: {value!r}")
    return value


def _message(response: httpx.Response) -> str:
    """Server error bodies vary (JSON:API errors, {status, errors}, {error}, plain text)."""
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:300] or response.reason_phrase
    if isinstance(body, dict):
        errors = body.get("errors") or body.get("error") or body.get("message")
        if isinstance(errors, list):
            parts = [e.get("detail") or e.get("title") if isinstance(e, dict) else str(e)
                     for e in errors]
            return "; ".join(str(p) for p in parts)[:300]
        if errors:
            return str(errors)[:300]
    return json.dumps(body)[:300]


class CircuitVerseClient:
    def __init__(
        self,
        server: str,
        token: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 60,
    ):
        self.server = server.rstrip("/")
        self._token = token
        self._http = httpx.Client(
            base_url=f"{self.server}/api/v1",
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            transport=transport,
            timeout=timeout,
        )

    def __repr__(self) -> str:  # never show the token
        return f"CircuitVerseClient({self.server!r}, authenticated={self._token is not None})"

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _request(self, method: str, path: str, *, auth: bool = True, **kwargs) -> httpx.Response:
        headers = {}
        if auth and self._token:
            headers["Authorization"] = f"Token {self._token}"  # "Token", not "Bearer"
        response = self._http.request(method, path, headers=headers, **kwargs)
        if response.status_code >= 400:
            error = _ERRORS.get(response.status_code, CircuitVerseError)
            raise error(response.status_code, _message(response))
        return response

    # --- authentication -------------------------------------------------------------

    def login(self, email: str, password: str) -> str:
        response = self._request(
            "POST", "/auth/login", auth=False, json={"email": email, "password": password}
        )
        token = response.json().get("token")
        if not token:
            raise CircuitVerseError(response.status_code, "login response had no token")
        self._token = token
        return token

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/me").json()

    # --- projects -------------------------------------------------------------------

    def project(self, ref: str) -> dict[str, Any]:
        """Project metadata (JSON:API record) with ``id`` merged into its attributes."""
        data = self._request("GET", f"/projects/{project_ref(ref)}").json()["data"]
        return {"id": str(data["id"]), **data.get("attributes", {})}

    def check_edit_access(self, ref: str) -> bool:
        try:
            self._request("GET", f"/projects/{project_ref(ref)}/check_edit_access")
        except (PermissionDenied, NotFound):
            return False
        return True

    def circuit_data(self, ref: str) -> Document:
        body = self._request("GET", f"/projects/{project_ref(ref)}/circuit_data").json()
        if isinstance(body, str):  # tolerate a double-encoded body
            body = json.loads(body)
        if not isinstance(body, dict) or "scopes" not in body:
            raise CircuitVerseError(200, "circuit_data response is not a circuit document")
        return body

    def create_project(self, name: str, document: Document, *, image: str = "") -> dict[str, Any]:
        """New project owned by the caller. The server defaults it to Public."""
        response = self._request("POST", "/projects", json={
            "name": name, "image": image, "data": json.dumps(document, separators=(",", ":")),
        })
        return response.json().get("project", {})

    def set_access(self, ref: str, access: str) -> None:
        if access not in ("Public", "Private", "Limited access"):
            raise ValueError(f"unknown access type {access!r}")
        self._request("PATCH", f"/projects/{project_ref(ref)}",
                      json={"project": {"project_access_type": access}})

    def delete_project(self, ref: str) -> None:
        self._request("DELETE", f"/projects/{project_ref(ref)}")

    def update_circuit(self, ref: str, *, name: str, document: Document, image: str) -> None:
        """Replace the whole circuit document. ``image`` is a JPEG data URL, or "" to
        reset the preview to the server default; the server requires the field.

        Not idempotent-safe to retry blindly: on a timeout, refetch and compare instead.
        """
        self._request("PATCH", "/projects/update_circuit", json={
            "id": project_ref(ref),
            "name": name,
            "image": image,
            # The browser sends the document as a JSON *string* inside the JSON body.
            "data": json.dumps(document, separators=(",", ":")),
        })
