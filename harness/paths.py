"""Locations of the method files (schemas, skills) shipped with the harness."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_DATA = Path(__file__).resolve().parent / "_data"


def _pick(name: str) -> Path:
    # Running from a checkout uses the top-level folders; an installed wheel
    # carries copies under harness/_data.
    top = REPO_ROOT / name
    return top if top.is_dir() else _DATA / name


SCHEMAS_DIR = _pick("schemas")
SKILLS_DIR = _pick("skills")
EVALUATIONS_DIR = REPO_ROOT / "evaluations"
DOCKERFILE = REPO_ROOT / "docker" / "worker.Dockerfile"
