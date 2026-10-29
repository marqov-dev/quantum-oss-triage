"""Provenance for result records."""

from __future__ import annotations

import subprocess


def git_revision() -> str:
    """The commit of the installed qtoy source tree, for provenance records."""
    out = subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True)
    return out.stdout.strip()
