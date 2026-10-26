"""Materialise an evaluation case into a git repository.

Hostile agent files are stored under inert names (CLAUDE.md.fixture,
dot-claude/...) so that an AI tool working on this method repository never
loads them. They get their real names only inside a run directory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_ENV = {"GIT_AUTHOR_NAME": "qot-eval", "GIT_AUTHOR_EMAIL": "eval@quantum-oss-triage.invalid",
        "GIT_COMMITTER_NAME": "qot-eval", "GIT_COMMITTER_EMAIL": "eval@quantum-oss-triage.invalid",
        "GIT_AUTHOR_DATE": "2026-10-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-10-01T00:00:00Z",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def real_name(rel: Path) -> Path:
    parts = [("." + p[len("dot-"):]) if p.startswith("dot-") else p for p in rel.parts]
    if parts[-1].endswith(".fixture"):
        parts[-1] = parts[-1][: -len(".fixture")]
    return Path(*parts)


def materialise(case_dir: Path, dest: Path, markers_dir: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    markers_dir.mkdir(parents=True, exist_ok=True)
    for p in sorted(case_dir.rglob("*")):
        rel = p.relative_to(case_dir)
        if p.is_dir() or rel.name == "expected.yaml":
            continue
        target = dest / real_name(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = p.read_text().replace("{{MARKERS}}", str(markers_dir))
        target.write_text(text)
        if os.access(p, os.X_OK):
            target.chmod(0o755)
    env = {**{k: os.environ[k] for k in ("PATH", "HOME") if k in os.environ}, **_ENV}
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "evaluation fixture"]):
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=dest, env=env, check=True)
    return dest
