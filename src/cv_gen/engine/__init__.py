"""Run testbenches headless in a pinned checkout of CircuitVerse's legacy simulator.

The checkout lives in ``~/.cache/cv-gen/engine/<rev>`` (override the cache root with
``CVGEN_CACHE``, or point ``CVGEN_ENGINE_DIR`` at an existing prepared checkout).
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

REPOSITORY = "https://github.com/CircuitVerse/CircuitVerse.git"
RUNNER_NAME = "cv-gen-runner.spec.js"
MARKER = ".cv-gen-engine-ready"
MIN_NODE_MAJOR = 18


class EngineError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EngineStatus:
    path: Path
    rev: str
    ready: bool
    node: str | None


def _cache_root() -> Path:
    return Path(os.environ.get("CVGEN_CACHE", Path.home() / ".cache" / "cv-gen"))


def engine_dir(rev: str) -> Path:
    override = os.environ.get("CVGEN_ENGINE_DIR")
    return Path(override) if override else _cache_root() / "engine" / rev


def node_version() -> str | None:
    node = shutil.which("node")
    if node is None:
        return None
    return subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()


def _require_node() -> None:
    version = node_version()
    if version is None:
        raise EngineError("Node.js is required for the test engine; install Node 22 LTS or newer")
    match = re.match(r"v(\d+)", version)
    if not match or int(match.group(1)) < MIN_NODE_MAJOR:
        raise EngineError(f"Node.js {version} is too old; need v{MIN_NODE_MAJOR}+")


def status(rev: str) -> EngineStatus:
    path = engine_dir(rev)
    ready = (path / MARKER).is_file() or (
        "CVGEN_ENGINE_DIR" in os.environ and (path / "node_modules" / ".bin" / "jest").exists()
    )
    return EngineStatus(path, rev, ready, node_version())


def _run(command: list[str], cwd: Path, what: str) -> None:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = "\n".join((result.stderr or result.stdout).strip().splitlines()[-15:])
        raise EngineError(f"{what} failed ({result.returncode}):\n{tail}")


def install(rev: str, *, log=print) -> EngineStatus:
    """Fetch CircuitVerse at ``rev`` and install its JS dependencies (idempotent)."""
    _require_node()
    if not re.fullmatch(r"[0-9a-f]{40}", rev):
        raise EngineError("engine.circuitverse_rev must be a full 40-character commit SHA")
    path = engine_dir(rev)
    if (path / MARKER).is_file():
        return status(rev)
    if "CVGEN_ENGINE_DIR" in os.environ:
        raise EngineError(f"CVGEN_ENGINE_DIR={path} is not a prepared engine; unset it to install")

    staging = path.with_name(path.name + ".partial")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    log(f"fetching CircuitVerse {rev[:12]} ...")
    _run(["git", "init", "-q"], staging, "git init")
    _run(["git", "fetch", "-q", "--depth", "1", REPOSITORY, rev], staging, "git fetch")
    _run(["git", "checkout", "-q", "FETCH_HEAD"], staging, "git checkout")
    log("installing JavaScript dependencies (yarn 1, scripts disabled) ...")
    _run(
        [
            "npx",
            "-y",
            "yarn@1",
            "install",
            "--frozen-lockfile",
            "--ignore-scripts",
            "--ignore-engines",
            "--non-interactive",
        ],
        staging,
        "yarn install",
    )
    # node-canvas is an optional jsdom peer whose native build was skipped; jsdom
    # crashes if it finds the unbuilt package. The runner stubs canvas instead.
    canvas = staging / "node_modules" / "canvas"
    if canvas.exists():
        canvas.rename(staging / "node_modules" / ".canvas-disabled")
    (staging / MARKER).write_text(rev + "\n")
    shutil.rmtree(path, ignore_errors=True)
    staging.rename(path)
    return status(rev)


def run(
    rev: str,
    project_path: Path,
    *,
    only: list[str] | None = None,
    results_for: list[str] | None = None,
    max_failures: int = 5,
    timeout: float | None = 3600,
) -> dict[str, Any]:
    """Run every embedded testbench in ``project_path``; return the raw JSON report."""
    _require_node()
    engine = status(rev)
    if not engine.ready:
        raise EngineError(
            f"test engine not installed at {engine.path}; run `cv-gen engine install`"
        )
    spec_dir = engine.path / "simulator" / "spec"
    runner = resources.files(__package__).joinpath("runner.spec.js").read_text()
    (spec_dir / RUNNER_NAME).write_text(runner)

    with tempfile.TemporaryDirectory(prefix="cv-gen-") as scratch:
        report_path = Path(scratch) / "report.json"
        env = {
            **os.environ,
            "CV_PROJECT": str(Path(project_path).resolve()),
            "CV_REPORT": str(report_path),
            "CV_MAXFAIL": str(max_failures),
        }
        if only:
            env["CV_ONLY"] = json.dumps(only)
        if results_for:
            env["CV_RESULTS"] = json.dumps(results_for)
        command = [
            str(engine.path / "node_modules" / ".bin" / "jest"),
            f"simulator/spec/{RUNNER_NAME}",
            "--ci",
            "--silent",
            "--testTimeout=3600000",
        ]
        try:
            result = subprocess.run(
                command, cwd=engine.path, env=env, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired as error:
            raise EngineError(f"test engine timed out after {timeout}s") from error
        if not report_path.is_file():
            tail = "\n".join((result.stderr or result.stdout).strip().splitlines()[-20:])
            raise EngineError(f"test engine produced no report (exit {result.returncode}):\n{tail}")
        report = json.loads(report_path.read_text())
    if report.get("loadError"):
        raise EngineError(f"engine could not load {project_path}:\n{report['loadError']}")
    return report
