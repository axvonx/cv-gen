"""Exercise the router without installing either CircuitVerse frontend."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_schematic_router_obstacles_junctions_fanout_and_feedback():
    result = subprocess.run(
        ["node", "--test", str(Path(__file__).with_name("schematic.test.cjs"))],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
