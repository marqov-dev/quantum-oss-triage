from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from harness.paths import REPO_ROOT


@dataclass
class RepoSpec:
    name: str
    source: str
    ref: str | None = None
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    tests_timeout_s: int | None = None   # the project's own suite, when the default is too short

    @property
    def slug(self) -> str:
        return self.name.replace("/", "__")

    @classmethod
    def from_dict(cls, d: dict) -> "RepoSpec":
        scope = d.get("scope") or {}
        tests = d.get("tests") or {}
        return cls(d["name"], str(d["source"]), d.get("ref"), list(scope.get("include") or []),
                   list(scope.get("exclude") or []), tests.get("timeout_s"))


@dataclass
class Config:
    models: dict
    review_skills: list[str]
    worker: dict
    timeouts: dict
    parallel: int = 2
    require_isolation_attestation: bool = True
    reviewer: str = "reviewer"
    fix_branch_prefix: str = "review/2026-10/"
    # Off by default: see Adapter.runs_shell_on_host and docs/METHOD.md.
    allow_host_shell_adapters: bool = False
    # Read by the publisher process itself (harness/publish), not the controller.
    publish: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        data = yaml.safe_load((path or REPO_ROOT / "config" / "harness.yaml").read_text())
        return cls(**data)


def load_repos(path: Path | None = None) -> list[RepoSpec]:
    data = yaml.safe_load((path or REPO_ROOT / "config" / "repos.yaml").read_text()) or {}
    return [RepoSpec.from_dict(r) for r in data.get("repos") or []]
