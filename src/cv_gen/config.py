"""``cvgen-tests.toml``: project bindings and generation settings. Never credentials."""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_NAME = "cvgen-tests.toml"
DEFAULT_SERVER = "https://circuitverse.org"
# Legacy simulator engine covered by native integration tests.
DEFAULT_ENGINE_REV = "6f725c5a924dc0b73527215eb5aa0618e45330e1"
_SECRET_KEY = re.compile(r"token|passw|secret|api[_-]?key|credential", re.IGNORECASE)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Suite:
    scope: str
    oracle: str
    max_cases: int | None = None
    intensity: int | None = None
    seed: int | None = None


@dataclass(frozen=True, slots=True)
class Config:
    root: Path
    project_file: Path | None
    project_id: str | None
    server: str
    engine_rev: str
    oracles: Path | None
    seed: int
    max_cases: int
    intensity: int
    suites: tuple[Suite, ...]

    @property
    def state_dir(self) -> Path:
        return self.root / ".cv-gen"

    @property
    def build_dir(self) -> Path:
        return self.root / "build"


_SCHEMA: dict[str, set[str]] = {
    "project": {"file", "id", "server"},
    "engine": {"circuitverse_rev"},
    "generate": {"oracles", "seed", "max_cases", "intensity"},
}
_SUITE_KEYS = {"scope", "oracle", "max_cases", "intensity", "seed"}


def _reject_secrets(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            where = f"{path}.{key}" if path else key
            if _SECRET_KEY.search(key):
                raise ConfigError(
                    f"{where}: credentials never belong in {CONFIG_NAME}; "
                    "use `cv-gen auth login` (Keychain) or the CV_TOKEN environment variable"
                )
            _reject_secrets(inner, where)
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            _reject_secrets(inner, f"{path}[{index}]")


def _int(table: dict[str, Any], key: str, where: str, lo: int, hi: int) -> int | None:
    value = table.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
        raise ConfigError(f"{where}.{key} must be an integer in {lo}..{hi}")
    return value


def _int_or(table: dict[str, Any], key: str, where: str, default: int, lo: int, hi: int) -> int:
    value = _int(table, key, where, lo, hi)
    return default if value is None else value


def find_config(start: Path | None = None) -> Path:
    directory = (start or Path.cwd()).resolve()
    for candidate in (directory, *directory.parents):
        if (candidate / CONFIG_NAME).is_file():
            return candidate / CONFIG_NAME
    raise ConfigError(f"no {CONFIG_NAME} found in {directory} or its parents")


def load_config(path: str | Path | None = None) -> Config:
    path = Path(path) if path else find_config()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: {error}") from error
    _reject_secrets(raw)

    unknown = set(raw) - {*_SCHEMA, "suite"}
    if unknown:
        raise ConfigError(f"{path}: unknown section(s) {sorted(unknown)}")
    for section, keys in _SCHEMA.items():
        extra = set(raw.get(section, {})) - keys
        if extra:
            raise ConfigError(f"[{section}]: unknown key(s) {sorted(extra)}")

    root = path.resolve().parent
    project = raw.get("project", {})
    generate = raw.get("generate", {})

    suites = []
    seen = set()
    for index, entry in enumerate(raw.get("suite", [])):
        where = f"suite[{index}]"
        extra = set(entry) - _SUITE_KEYS
        if extra:
            raise ConfigError(f"{where}: unknown key(s) {sorted(extra)}")
        for key in ("scope", "oracle"):
            if not isinstance(entry.get(key), str) or not entry[key]:
                raise ConfigError(f"{where}.{key} is required")
        if entry["scope"] in seen:
            raise ConfigError(f"{where}: circuit {entry['scope']!r} is listed twice")
        seen.add(entry["scope"])
        suites.append(
            Suite(
                scope=entry["scope"],
                oracle=entry["oracle"],
                max_cases=_int(entry, "max_cases", where, 1, 1 << 20),
                intensity=_int(entry, "intensity", where, 0, 100),
                seed=_int(entry, "seed", where, 0, (1 << 64) - 1),
            )
        )

    def optional_path(value: Any, key: str) -> Path | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ConfigError(f"{key} must be a path string")
        return (root / value).resolve()

    project_id = project.get("id")
    return Config(
        root=root,
        project_file=optional_path(project.get("file"), "project.file"),
        project_id=str(project_id) if project_id is not None else None,
        server=str(project.get("server", DEFAULT_SERVER)).rstrip("/"),
        engine_rev=str(raw.get("engine", {}).get("circuitverse_rev", DEFAULT_ENGINE_REV)),
        oracles=optional_path(generate.get("oracles"), "generate.oracles"),
        seed=_int_or(generate, "seed", "generate", 0, 0, (1 << 64) - 1),
        max_cases=_int_or(generate, "max_cases", "generate", 256, 1, 1 << 20),
        intensity=_int_or(generate, "intensity", "generate", 100, 0, 100),
        suites=tuple(suites),
    )
