"""Resumable units of work, keyed by (repository, stage, skill, model).

A unit is saved when it completes. A run that stops (usage limit, crash,
Ctrl-C) resumes from the last finished unit. Token usage is appended to
usage.jsonl per unit.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from harness import secrets

_LOCK = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe(part: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", part or "-")


@dataclass
class Unit:
    path: Path
    key: str
    ledger: "Ledger"

    def load(self) -> dict | None:
        return json.loads(self.path.read_text()) if self.path.exists() else None

    def done(self) -> bool:
        rec = self.load()
        return bool(rec) and rec.get("status") == "done"

    def payload(self):
        rec = self.load()
        return rec.get("payload") if rec else None

    def save(self, status: str, payload=None, *, tokens: dict | None = None, model_id: str | None = None,
             error: str | None = None, attempts: int = 0, duration_s: float = 0.0, extra: dict | None = None) -> dict:
        rec = {"key": self.key, "status": status, "finished_at": now(), "model_id": model_id, "attempts": attempts,
               "duration_s": round(duration_s, 2), "tokens": tokens or {}, "error": error, "payload": payload,
               **(extra or {})}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        # Secret values are redacted before anything is stored.
        tmp.write_text(json.dumps(secrets.redact_obj(rec), indent=2))
        tmp.replace(self.path)
        if tokens is not None or model_id:
            self.ledger.log_usage(self.key, status, model_id, tokens or {}, attempts, duration_s)
        return rec


class Ledger:
    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def unit(self, repo: str, stage: str, skill: str | None, model: str | None) -> Unit:
        key = "/".join([repo, stage, skill or "-", model or "-"])
        name = "__".join(_safe(p) for p in (stage, skill or "-", model or "-")) + ".json"
        return Unit(self.run_dir / repo.replace("/", "__") / "units" / name, key, self)

    def units(self, repo: str) -> list[dict]:
        d = self.run_dir / repo.replace("/", "__") / "units"
        return [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))] if d.exists() else []

    def log_usage(self, key, status, model_id, tokens, attempts, duration_s) -> None:
        repo, stage, skill, model = key.split("/")[-4:] if key.count("/") >= 3 else (key, "", "", "")
        row = {"ts": now(), "unit": key, "stage": stage, "skill": skill, "adapter": model, "status": status,
               "model_id": model_id, "attempts": attempts, "duration_s": round(duration_s, 2), **tokens}
        with _LOCK, (self.run_dir / "usage.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")

    def usage(self) -> list[dict]:
        p = self.run_dir / "usage.jsonl"
        return [json.loads(line) for line in p.read_text().splitlines() if line.strip()] if p.exists() else []
