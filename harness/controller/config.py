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
    install_extras: list[str] = field(default_factory=list)   # optional integrations the suite needs
    # Run this repository's workers as another platform, e.g. "linux/amd64" for a project whose
    # dependencies publish x86-only wheels and no source (bqskitrs). Emulated on an arm64 host: slower.
    worker_platform: str | None = None
    # Run this repository's workers with another Python, e.g. "3.10" for a project that declares
    # requires-python <3.11. Uses the image variant "<tag>-py310" (see docker/worker.Dockerfile).
    worker_python: str | None = None
    # Packages inside the repository to install with the project, e.g. a monorepo's
    # "src/openqaoa-core[tests]". Their directories go first on PYTHONPATH in later workers,
    # so the code that runs is the copy's.
    local_packages: list[str] = field(default_factory=list)
    # Source archives fetched on the host, by exact commit and sha256, and mounted read-only
    # into the install worker (git submodules, CMake FetchContent): see harness/stages/prefetch.py.
    prefetch: list[dict] = field(default_factory=list)
    # Locked packages left out on purpose, each with its reason, e.g. one that publishes no
    # distribution for this platform. Recorded in the manifest and marked as incomplete.
    omit: list[dict] = field(default_factory=list)
    # Locked packages built from a prefetched source tree instead of the registry, each
    # {package, prefetch, reason}: for one with no wheel for this platform and no usable sdist.
    source_builds: list[dict] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return self.name.replace("/", "__")

    @classmethod
    def from_dict(cls, d: dict) -> "RepoSpec":
        scope = d.get("scope") or {}
        tests = d.get("tests") or {}
        deps = d.get("deps") or {}
        worker = d.get("worker") or {}
        python = worker.get("python")
        if python is not None and not isinstance(python, str):
            # YAML reads an unquoted 3.10 as the number 3.1.
            raise ValueError(f"{d['name']}: worker.python must be a quoted string such as \"3.10\", not {python!r}")
        return cls(d["name"], str(d["source"]), d.get("ref"), list(scope.get("include") or []),
                   list(scope.get("exclude") or []), tests.get("timeout_s"),
                   list(deps.get("extras") or []), worker.get("platform"),
                   python,
                   [str(x) for x in deps.get("local_packages") or []],
                   [dict(x) for x in deps.get("prefetch") or []],
                   [dict(x) for x in deps.get("omit") or []],
                   [dict(x) for x in deps.get("source_builds") or []])


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
    # Models that verify only what another model raised: see harness/stages/verify.py.
    verify_model_claims_only: list[str] = field(default_factory=list)
    # Read by the publisher process itself (harness/publish), not the controller.
    publish: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        data = yaml.safe_load((path or REPO_ROOT / "config" / "harness.yaml").read_text())
        return cls(**data)


def load_repos(path: Path | None = None) -> list[RepoSpec]:
    data = yaml.safe_load((path or REPO_ROOT / "config" / "repos.yaml").read_text()) or {}
    return [RepoSpec.from_dict(r) for r in data.get("repos") or []]
