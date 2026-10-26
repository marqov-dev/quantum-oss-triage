"""manifest.json: what was reviewed, with what, and what finished."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from harness.controller import schema
from harness.controller.ledger import now
from harness.paths import REPO_ROOT

STAGES = ("pin", "scan", "review", "verify", "validate", "triage", "fix", "publish")


def harness_revision() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        return "unknown"
    return (sha or "uncommitted") + ("-dirty" if dirty else "")


class Manifest:
    def __init__(self, path: Path, data: dict):
        self.path, self.data = Path(path), data

    @classmethod
    def open(cls, path: Path, *, run_id: str, repo: dict) -> "Manifest":
        path = Path(path)
        if path.exists():
            m = cls(path, json.loads(path.read_text()))
            m.data["status"] = "running"
            return m
        data = {
            "schema_version": 1, "run_id": run_id, "harness_revision": harness_revision(), "repo": repo,
            "worker_image": {"tag": "", "digest": None}, "adapters": [], "scanners": [], "skills": [],
            "prompts_sha256": "", "started_at": now(), "finished_at": None, "status": "running",
            "stages": {s: {"status": "not_started"} for s in STAGES}, "tokens": {}, "failures": [],
            "coverage": {"reviewed": [], "not_reviewed": [], "incomplete_checks": []},
        }
        return cls(path, data)

    def stage(self, name: str, status: str, **extra) -> None:
        self.data["stages"][name] = {**self.data["stages"].get(name, {}), "status": status, **extra}
        self.save()

    def fail(self, unit: str, error: str) -> None:
        if not any(f["unit"] == unit and f["error"] == error for f in self.data["failures"]):
            self.data["failures"].append({"unit": unit, "error": error[:1000]})

    _PREFIXES = {"models": ("model ",), "pin": ("pin",), "scan": ("scanner ",), "review": ("review",),
                 "verify": ("verification",), "validate": ("validate",)}

    def clear_notes(self, stage: str) -> None:
        """Drop the incomplete-check notes and failures a stage produced last time."""
        prefixes = self._PREFIXES.get(stage, ())
        cov = self.data["coverage"]
        cov["incomplete_checks"] = [c for c in cov["incomplete_checks"] if not c.startswith(prefixes)] if prefixes else cov["incomplete_checks"]
        self.data["failures"] = [f for f in self.data["failures"] if f"/{stage}/" not in f["unit"] and not f["unit"].endswith(f"/{stage}")]

    def incomplete(self, what: str) -> None:
        checks = self.data["coverage"]["incomplete_checks"]
        if what not in checks:
            checks.append(what)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2))

    def finish(self, status: str) -> list[str]:
        self.data["status"] = status
        self.data["finished_at"] = now()
        self.save()
        return schema.validate("run", self.data)
