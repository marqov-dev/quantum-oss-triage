"""Per-repository run state shared by the stages, and the single place that
calls an AI CLI and records the unit."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from harness import secrets
from harness.adapters.base import Adapter
from harness.controller import prompts, skills
from harness.controller.config import Config, RepoSpec
from harness.controller.ledger import Ledger
from harness.controller.manifest import Manifest
from harness.workers.base import Worker


class UsageLimitReached(Exception):
    def __init__(self, adapter: str, unit: str):
        super().__init__(f"{adapter} reported a usage limit at {unit}")
        self.adapter, self.unit = adapter, unit


@dataclass
class ModelCall:
    ok: bool
    payload: dict | None
    model_id: str | None
    unit: str
    error: str | None = None


@dataclass
class RepoContext:
    spec: RepoSpec
    run_id: str
    run_dir: Path
    config: Config
    ledger: Ledger
    manifest: Manifest
    worker: Worker | None
    adapters: dict[str, Adapter]
    commit: str = ""
    retry_failed: bool = False
    log: Callable[[str], None] = print
    extra: dict = field(default_factory=dict)

    @property
    def repo_dir(self) -> Path:
        return self.run_dir / self.spec.slug

    @property
    def source_dir(self) -> Path:
        return self.repo_dir / "source"

    @property
    def review_dir(self) -> Path:
        return self.repo_dir / "review-copy"

    def model_order(self) -> list[str]:
        return [m for m in self.config.models if m in self.adapters]

    def read_json(self, name: str, default=None):
        p = self.repo_dir / name
        return json.loads(p.read_text()) if p.exists() else default

    def write_json(self, name: str, data) -> Path:
        p = self.repo_dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(secrets.redact_obj(data), indent=2))
        return p

    def call_model(self, stage: str, unit_skill: str, model: str, skill_name: str, prompt: str,
                   timeout_s: int) -> ModelCall:
        unit = self.ledger.unit(self.spec.name, stage, unit_skill, model)
        rec = unit.load()
        if rec and rec["status"] == "done":
            return ModelCall(True, rec["payload"], rec.get("model_id"), unit.key)
        # A unit the provider refused for capacity is always tried again.
        if rec and rec["status"] == "failed" and not self.retry_failed and not rec.get("capacity_refused"):
            return ModelCall(False, None, rec.get("model_id"), unit.key, rec.get("error"))
        skill = skills.load(skill_name)
        self.log(f"  {stage} {unit_skill} on {model} ...")
        r = self.adapters[model].run(prompt, prompts.SYSTEM, skill.output_schema, self.review_dir, timeout_s)
        meta = dict(tokens=r.tokens, model_id=r.model_id, attempts=r.attempts, duration_s=r.duration_s,
                    extra={"command": r.command, "skill_sha256": skill.sha256})
        if r.usage_limited:
            unit.save("usage_limited", {"raw": r.raw[-20000:]}, error=r.error, **meta)
            raise UsageLimitReached(model, unit.key)
        if r.ok:
            unit.save("done", r.data, **meta)
            return ModelCall(True, r.data, r.model_id, unit.key)
        if r.capacity_refused:
            meta["extra"]["capacity_refused"] = True
        unit.save("failed", {"raw": r.raw[-50000:]}, error=r.error, **meta)
        self.manifest.fail(unit.key, r.error or "failed")
        return ModelCall(False, None, r.model_id, unit.key, r.error)
