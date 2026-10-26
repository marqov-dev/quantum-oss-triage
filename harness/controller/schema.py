"""Load the JSON schemas and validate data against them."""

from __future__ import annotations

import json
from functools import cache

from jsonschema import Draft202012Validator

from harness.paths import SCHEMAS_DIR

NAMES = ("finding", "verdict", "run", "review-output", "fix-output")


@cache
def load(name: str) -> dict:
    if name not in NAMES:
        raise KeyError(f"unknown schema {name!r}; expected one of {NAMES}")
    return json.loads((SCHEMAS_DIR / f"{name}.schema.json").read_text())


def path(name: str):
    load(name)
    return SCHEMAS_DIR / f"{name}.schema.json"


@cache
def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(load(name))


def validate(name: str, data) -> list[str]:
    """Return a list of error messages. An empty list means the data is valid."""
    errors = sorted(_validator(name).iter_errors(data), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errors]
