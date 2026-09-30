"""Pull and guarded push.

Push never uploads the local file. It fetches the live document, regenerates the tests
against it, changes nothing but ``testbenchData``, backs up, uploads, and refetches to
verify. The server offers no conditional write, so a stale-copy check narrows (but
cannot close) the window in which a browser edit could be overwritten.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..config import Config
from ..oracles import Registry
from ..pipeline import Build, Calibrator, build
from ..project import (
    Document,
    canonical_hash,
    load,
    non_testbench_view,
    save,
    scopes,
    testbench_view,
)
from .client import CircuitVerseClient, project_ref


class SyncError(RuntimeError):
    pass


class StaleError(SyncError):
    pass


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _state_path(config: Config) -> Path:
    return config.state_dir / "state.json"


def read_state(config: Config) -> dict:
    path = _state_path(config)
    return json.loads(path.read_text()) if path.is_file() else {}


def _record(config: Config, ref: str, document: Document) -> None:
    state = read_state(config)
    state[f"{config.server} {ref}"] = {
        "hash": canonical_hash(document),
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    config.state_dir.mkdir(parents=True, exist_ok=True)
    _state_path(config).write_text(json.dumps(state, indent=2) + "\n")


def _backup(config: Config, document: Document, label: str) -> Path:
    path = config.state_dir / "backups" / f"{label}.{_timestamp()}.cv"
    save(document, path)
    return path


def _require_project(config: Config) -> tuple[str, Path]:
    if not config.project_id:
        raise SyncError("set [project] id in cvgen-tests.toml to pull or push")
    if not config.project_file:
        raise SyncError("set [project] file in cvgen-tests.toml")
    return project_ref(config.project_id), config.project_file


def pull(client: CircuitVerseClient, config: Config) -> tuple[Path, Path | None]:
    """Download the live document into ``project.file``; back up what was there."""
    ref, path = _require_project(config)
    document = client.circuit_data(ref)
    backup = None
    if path.is_file():
        backup = _backup(config, load(path), f"local-{ref}")
    save(document, path)
    _record(config, ref, document)
    return path, backup


@dataclass(frozen=True, slots=True)
class PushPlan:
    ref: str
    name: str
    remote: Document
    build: Build
    changed: tuple[str, ...]  # scope names whose testbench changes

    @property
    def request_bytes(self) -> int:
        return len(json.dumps(self.build.document, separators=(",", ":")))


def plan_push(
    client: CircuitVerseClient,
    config: Config,
    registry: Registry,
    calibrate: Calibrator | None,
    *,
    force: bool = False,
) -> PushPlan:
    ref, _ = _require_project(config)
    if not client.check_edit_access(ref):
        raise SyncError(f"no edit access to project {ref!r} (must be author or collaborator)")
    metadata = client.project(ref)
    remote = client.circuit_data(ref)

    recorded = read_state(config).get(f"{config.server} {ref}")
    if recorded is None and not force:
        raise StaleError("no record of a pull for this project; run `cv-gen pull` first")
    if recorded and recorded["hash"] != canonical_hash(remote) and not force:
        raise StaleError(
            "the project changed on CircuitVerse since your last pull (edited in the "
            "browser?). Run `cv-gen pull` and `cv-gen check`, then push again."
        )

    result = build(config, remote, registry, calibrate)
    if non_testbench_view(result.document) != non_testbench_view(remote):
        raise SyncError("internal error: push would change more than testbench data")
    before, after = testbench_view(remote), testbench_view(result.document)
    names = {info.id: info.name for info in scopes(remote)}
    changed = tuple(names[i] for i in after if after[i] != before.get(i))
    return PushPlan(ref, metadata.get("name") or remote.get("name", ""), remote, result, changed)


def execute_push(
    client: CircuitVerseClient, config: Config, plan: PushPlan, *, image: str
) -> Path:
    """Upload ``plan``; return the backup path. Raises SyncError if verification fails."""
    backup = _backup(config, plan.remote, f"remote-{plan.ref}")
    client.update_circuit(plan.ref, name=plan.name, document=plan.build.document, image=image)

    after = client.circuit_data(plan.ref)
    # Compare only testbenches: the server may rewrite other fields (e.g. assignment
    # restrictions) on save.
    if testbench_view(after) != testbench_view(plan.build.document):
        raise SyncError(
            f"upload verification failed: the tests on CircuitVerse do not match what was "
            f"sent. The pre-push document is backed up at {backup}"
        )
    _record(config, plan.ref, after)
    if config.project_file:
        save(after, config.project_file)
    return backup
