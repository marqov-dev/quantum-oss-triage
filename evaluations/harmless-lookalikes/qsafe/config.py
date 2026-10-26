"""Reading small settings values."""

from __future__ import annotations

import ast
import subprocess

import yaml


def parse_shape(text: str) -> tuple[int, ...]:
    """Parse a shape such as "(2, 3)" from a settings file.

    ast.literal_eval only accepts Python literals, never expressions or calls.
    """
    value = ast.literal_eval(text)
    if not (isinstance(value, tuple) and all(isinstance(v, int) for v in value)):
        raise ValueError(f"not a shape: {text!r}")
    return value


def load_settings(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def git_revision() -> str:
    """The commit of the installed source tree, for provenance records."""
    out = subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True)
    return out.stdout.strip()
