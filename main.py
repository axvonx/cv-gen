#!/usr/bin/env python3
"""Source-tree entry point for cv-gen."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from cv_gen.app import main

raise SystemExit(main())
