#!/usr/bin/env python3
"""Run pytest from the backend directory with the right PYTHONPATH."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    backend = Path(__file__).resolve().parents[1] / "backend"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend)
    return subprocess.call([sys.executable, "-m", "pytest"], cwd=str(backend), env=env)


if __name__ == "__main__":
    raise SystemExit(main())
