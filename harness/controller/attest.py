"""Isolation attestations: which CLI versions have passed the hostile probe.

The pipeline refuses to use a CLI version that has no passing attestation
(unless explicitly told otherwise for tests). `qot doctor` writes these.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.controller import cleanenv
from harness.controller.ledger import now


def path() -> Path:
    return cleanenv.CONFIG_ROOT / "isolation-attestations.json"


def load() -> dict:
    p = path()
    return json.loads(p.read_text()) if p.exists() else {}


def record(adapter: str, version: str, passed: bool, details: dict) -> None:
    data = load()
    data.setdefault(adapter, {})[version] = {"passed": passed, "at": now(), "details": details}
    path().parent.mkdir(parents=True, exist_ok=True)
    path().write_text(json.dumps(data, indent=2))


def verified(adapter: str, version: str | None, config_mode: str | None = None) -> bool:
    if not version:
        return False
    entry = load().get(adapter, {}).get(version)
    if not entry or not entry.get("passed"):
        return False
    return config_mode is None or entry.get("details", {}).get("config_mode", config_mode) == config_mode
