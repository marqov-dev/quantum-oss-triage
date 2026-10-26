"""Load skills (Agent Skills format: a folder with SKILL.md and YAML front matter).

Inside the harness the skill text is passed to each CLI explicitly; no tool is
allowed to discover skills on its own, because discovery would also find the
repository's and the operator's skills.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import cache

import yaml

from harness.paths import SKILLS_DIR

REVIEW_SKILLS = ("review-security", "review-correctness", "review-docs", "review-quantum")


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    output_schema: str
    body: str
    sha256: str


@cache
def load(name: str) -> Skill:
    text = (SKILLS_DIR / name / "SKILL.md").read_text()
    if not text.startswith("---\n"):
        raise ValueError(f"{name}: SKILL.md has no front matter")
    _, front, body = text.split("---\n", 2)
    meta = yaml.safe_load(front)
    if meta.get("name") != name:
        raise ValueError(f"{name}: front matter name is {meta.get('name')!r}")
    return Skill(name=name, description=meta["description"], output_schema=meta["metadata"]["output_schema"],
                 body=body.strip(), sha256=hashlib.sha256(text.encode()).hexdigest())


def available() -> list[str]:
    return sorted(p.name for p in SKILLS_DIR.iterdir() if (p / "SKILL.md").exists())
