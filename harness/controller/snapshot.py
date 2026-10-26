"""Source snapshots: the pinned checkout, and the read-only copy the AI tools see."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from pathlib import Path

# Never copied into the review copy: VCS internals and bulky build output.
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache", ".tox", "build", "dist"}


def review_copy(src: Path, dest: Path, include: list[str] | None = None, exclude: list[str] | None = None) -> Path:
    """Copy the in-scope tree to dest and make it read-only (files and dirs)."""
    src, dest = Path(src), Path(dest)
    if dest.exists():
        make_writable(dest)
        shutil.rmtree(dest)
    real_src = src.resolve()
    roots = [src / i for i in include] if include else [src]
    for root in roots:
        if not root.exists() or not _inside(root, src, real_src):
            continue
        for path in [root] if root.is_file() else root.rglob("*"):
            if not _inside(path, src, real_src):
                continue
            rel = path.relative_to(src)
            if any(part in _SKIP_DIRS for part in rel.parts):
                continue
            if exclude and any(str(rel) == e or str(rel).startswith(e.rstrip("/") + "/") for e in exclude):
                continue
            target = dest / rel
            if path.is_symlink():
                continue  # a link could point outside the snapshot
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif path.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
    dest.mkdir(parents=True, exist_ok=True)
    make_readonly(dest)
    return dest


def _inside(path: Path, src: Path, real_src: Path) -> bool:
    """True if no component between src and path is a symlink and path resolves inside src."""
    try:
        rel = path.relative_to(src)
    except ValueError:
        return False
    cur = src
    for part in rel.parts:
        cur = cur / part
        if cur.is_symlink():
            return False
    return str(path.resolve()).startswith(str(real_src) + "/") or path.resolve() == real_src


def make_readonly(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        for f in filenames:
            p = Path(dirpath) / f
            p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        d = Path(dirpath)
        d.chmod(d.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def make_writable(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        d.chmod(d.stat().st_mode | stat.S_IWUSR)
        for f in filenames:
            p = Path(dirpath) / f
            if not p.is_symlink():
                p.chmod(p.stat().st_mode | stat.S_IWUSR)


def tree_hash(root: Path) -> str:
    """Hash of every path and file content under root (excluding .git internals)."""
    h = hashlib.sha256()
    root = Path(root)
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] == ".git":
            continue
        h.update(str(rel).encode() + b"\0")
        if path.is_file() and not path.is_symlink():
            h.update(hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()


def listing(root: Path, limit: int = 400) -> list[str]:
    files = sorted(str(p.relative_to(root)) for p in Path(root).rglob("*") if p.is_file())
    return files[:limit] + ([f"... and {len(files) - limit} more"] if len(files) > limit else [])


def read_lines(root: Path, rel: str, start: int, end: int) -> str:
    p = (Path(root) / rel).resolve()
    if not str(p).startswith(str(Path(root).resolve())) or not p.is_file():
        return ""
    lines = p.read_text(errors="replace").splitlines()
    return "\n".join(lines[max(start - 1, 0): max(end, start)])
