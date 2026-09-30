"""Pinned Vue v1 CircuitVerse checkout for canonical projects."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import V1_REV, BuildError

REPOSITORY = "https://github.com/CircuitVerse/cv-frontend-vue.git"


def directory() -> Path:
    override = os.environ.get("CVGEN_V1_DIR")
    if override:
        return Path(override).resolve()
    cache = Path(os.environ.get("CVGEN_CACHE", Path.home() / ".cache" / "cv-gen"))
    return cache / "v1" / V1_REV


def ready() -> bool:
    path = directory()
    marker = (path / ".cv-gen-v1-ready").is_file()
    override = "CVGEN_V1_DIR" in os.environ
    return (marker or override) and (path / "node_modules" / ".bin" / "vitest").is_file()


def _run(command: list[str], cwd: Path) -> None:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        tail = "\n".join((result.stderr or result.stdout).splitlines()[-20:])
        raise BuildError(f"{' '.join(command[:2])} failed:\n{tail}")


def install() -> Path:
    path = directory()
    if ready():
        return path
    if "CVGEN_V1_DIR" in os.environ:
        raise BuildError(f"CVGEN_V1_DIR={path} is not a prepared Vue v1 checkout")
    if shutil.which("node") is None or shutil.which("npm") is None or shutil.which("git") is None:
        raise BuildError("Node, npm, and git are required for canonical-v1 engine install")
    staging = path.with_name(path.name + ".partial")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        _run(["git", "init", "-q"], staging)
        _run(["git", "fetch", "-q", "--depth", "1", REPOSITORY, V1_REV], staging)
        _run(["git", "checkout", "-q", "FETCH_HEAD"], staging)
        _run(["npm", "ci", "--ignore-scripts"], staging)
        (staging / ".cv-gen-v1-ready").write_text(V1_REV + "\n")
        if path.exists():
            shutil.rmtree(path)
        staging.rename(path)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return path


def converter_directory() -> Path:
    cache = Path(os.environ.get("CVGEN_CACHE", Path.home() / ".cache" / "cv-gen"))
    return cache / "converter" / "yosys2digitaljs-0.10.3"


def converter_ready() -> bool:
    path = converter_directory()
    local = Path(__file__).parent / "node" / "node_modules" / "yosys2digitaljs"
    return (path / "node_modules" / "yosys2digitaljs").is_dir() or local.is_dir()


def install_converter() -> Path:
    path = converter_directory()
    if (path / "node_modules" / "yosys2digitaljs").is_dir():
        return path
    if shutil.which("npm") is None:
        raise BuildError("npm is required to install yosys2digitaljs")
    path.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).parent / "node"
    shutil.copyfile(source / "package.json", path / "package.json")
    shutil.copyfile(source / "package-lock.json", path / "package-lock.json")
    _run(["npm", "ci", "--ignore-scripts"], path)
    return path
