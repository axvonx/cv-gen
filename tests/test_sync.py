import base64
import json
import time

import httpx
import keyring
import pytest

from cv_gen import project
from cv_gen.config import load_config
from cv_gen.oracles import load_oracles
from cv_gen.sync import auth, push
from cv_gen.sync.client import (
    AuthenticationError,
    CircuitVerseClient,
    CircuitVerseError,
    PermissionDenied,
    RateLimited,
    project_ref,
)


def jwt(claims):
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJSUzI1NiJ9.{body}.sig"


# --- client ------------------------------------------------------------------------


def client_with(handler, token="tok"):
    return CircuitVerseClient("https://cv.example", token, transport=httpx.MockTransport(handler))


def test_uses_token_scheme_not_bearer():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"name": "p", "scopes": []})

    client_with(handler).circuit_data("123")
    assert seen["auth"] == "Token tok"


def test_update_circuit_sends_document_as_json_string():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "success"})

    client_with(handler).update_circuit("slug", name="P", document={"scopes": []}, image="")
    assert seen["path"] == "/api/v1/projects/update_circuit"
    assert seen["body"]["id"] == "slug"
    assert isinstance(seen["body"]["data"], str)
    assert json.loads(seen["body"]["data"]) == {"scopes": []}
    assert seen["body"]["image"] == ""


@pytest.mark.parametrize(
    "status, body, error, fragment",
    [
        (401, {"errors": [{"detail": "invalid credentials"}]}, AuthenticationError, "invalid"),
        (403, {"errors": [{"title": "Forbidden"}]}, PermissionDenied, "Forbidden"),
        (429, "Too many requests, please try again later", RateLimited, "Too many"),
        (422, {"status": "error", "errors": ["Name can't be blank"]}, CircuitVerseError, "blank"),
        (404, {"error": "Circuit data unavailabe for the project!"}, CircuitVerseError, "unavail"),
    ],
)
def test_error_bodies_of_every_shape(status, body, error, fragment):
    def handler(request):
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)

    with pytest.raises(error, match=fragment):
        client_with(handler).circuit_data("1")


def test_login_returns_token_and_repr_hides_it():
    def handler(request):
        assert "authorization" not in request.headers
        return httpx.Response(202, json={"token": "secret-jwt"})

    client = client_with(handler, token=None)
    assert client.login("a@b.c", "pw") == "secret-jwt"
    assert "secret-jwt" not in repr(client)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("123", "123"),
        ("https://circuitverse.org/users/9/projects/my-adder", "my-adder"),
        ("https://circuitverse.org/simulator/edit/my-adder", "my-adder"),
    ],
)
def test_project_ref(value, expected):
    assert project_ref(value) == expected


def test_project_ref_rejects_path_tricks():
    with pytest.raises(ValueError):
        project_ref("../../admin")


# --- auth --------------------------------------------------------------------------


@pytest.fixture
def fake_keyring(monkeypatch):
    store = {}
    monkeypatch.setattr(keyring, "get_password", lambda s, a: store.get((s, a)))
    monkeypatch.setattr(keyring, "set_password", lambda s, a, p: store.__setitem__((s, a), p))

    def delete(s, a):
        if (s, a) not in store:
            raise keyring.errors.PasswordDeleteError()
        del store[(s, a)]

    monkeypatch.setattr(keyring, "delete_password", delete)
    monkeypatch.delenv(auth.ENV_TOKEN, raising=False)
    return store


def test_token_store_round_trip_and_claims(fake_keyring):
    tokens = auth.TokenStore("https://cv.example")
    assert tokens.get() is None
    tokens.save(jwt({"username": "ada", "email": "a@b.c", "exp": int(time.time()) + 3600}))
    info = tokens.info()
    assert (info.source, info.username) == ("keyring", "ada")
    assert info.expires_soon and not info.expired
    assert list(fake_keyring) == [("cv-gen:cv.example", "jwt")]
    assert tokens.delete() and not tokens.delete()


def test_env_token_overrides_keyring(fake_keyring, monkeypatch):
    tokens = auth.TokenStore("https://cv.example")
    tokens.save("from-keyring")
    monkeypatch.setenv(auth.ENV_TOKEN, jwt({"exp": 1}))
    assert tokens.get()[1] == "env"
    assert tokens.info().expired


# --- push --------------------------------------------------------------------------


class FakeServer:
    """Just enough of CircuitVerse for pull/push."""

    def __init__(self, document, *, editable=True, corrupt_on_save=False):
        self.document = json.loads(json.dumps(document))
        self.editable = editable
        self.corrupt_on_save = corrupt_on_save
        self.uploads = []

    def check_edit_access(self, ref):
        return self.editable

    def project(self, ref):
        return {"id": "7", "name": "Demo project"}

    def circuit_data(self, ref):
        return json.loads(json.dumps(self.document))

    def update_circuit(self, ref, *, name, document, image):
        self.uploads.append((name, image))
        self.document = json.loads(json.dumps(document))
        if self.corrupt_on_save:
            self.document["scopes"][0].pop("testbenchData", None)


def no_calibration_needed(scopes, document):
    n = project.find_scope(document, "Reg").testbench.case_count
    return {"scopes": [{"scope": "Reg", "status": "pass", "results": [{"OUT": ["0000"] * n}]}]}


@pytest.fixture
def setup(workspace):
    config = load_config(workspace / "cvgen-tests.toml")
    return config, load_oracles(config.oracles), project.load(config.project_file)


def test_push_requires_pull_then_uploads_only_tests(setup):
    config, registry, document = setup
    server = FakeServer(document)
    with pytest.raises(push.StaleError, match="run `cv-gen pull` first"):
        push.plan_push(server, config, registry, no_calibration_needed)

    push.pull(server, config)
    plan = push.plan_push(server, config, registry, no_calibration_needed)
    assert set(plan.changed) == {"AND", "AND4", "Reg"}
    backup = push.execute_push(server, config, plan, image="")

    assert server.uploads == [("Demo project", "")]
    assert backup.is_file() and json.loads(backup.read_text()) == document
    assert project.non_testbench_view(server.document) == project.non_testbench_view(document)
    # local copy and pull record now match the server, so a second push is not stale
    assert project.load(config.project_file) == server.document
    push.plan_push(server, config, registry, no_calibration_needed)


def test_push_refuses_when_remote_changed_since_pull(setup):
    config, registry, document = setup
    server = FakeServer(document)
    push.pull(server, config)
    server.document["scopes"][0]["name"] = "AND (edited in browser)"
    with pytest.raises(push.StaleError, match="changed on CircuitVerse"):
        push.plan_push(server, config, registry, no_calibration_needed)


def test_push_requires_edit_access(setup):
    config, registry, document = setup
    server = FakeServer(document, editable=False)
    push.pull(server, config)
    with pytest.raises(push.SyncError, match="no edit access"):
        push.plan_push(server, config, registry, no_calibration_needed)


def test_push_verification_failure_keeps_backup(setup):
    config, registry, document = setup
    server = FakeServer(document, corrupt_on_save=True)
    push.pull(server, config)
    plan = push.plan_push(server, config, registry, no_calibration_needed)
    with pytest.raises(push.SyncError, match="verification failed") as error:
        push.execute_push(server, config, plan, image="")
    assert "backed up at" in str(error.value)


def test_pull_backs_up_existing_local_file(setup):
    config, _, document = setup
    server = FakeServer(dict(document, name="Remote"))
    path, backup = push.pull(server, config)
    assert project.load(path)["name"] == "Remote"
    assert project.load(backup)["name"] == "Demo"
