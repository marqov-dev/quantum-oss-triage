"""Stage 1: clone at the default branch (or a given ref) and pin the commit."""

from __future__ import annotations

import os
import shutil
import subprocess

from harness.controller import cleanenv, snapshot
from harness.controller.context import RepoContext


def _git_env() -> dict:
    env = cleanenv.base_env()
    # Ignore the operator's git config (credential helpers, hooks paths, aliases).
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"})
    return env


def git(args: list[str], cwd=None) -> str:
    r = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=cwd, env=_git_env(),
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()[-500:]}")
    return r.stdout.strip()


def run(ctx: RepoContext) -> None:
    unit = ctx.ledger.unit(ctx.spec.name, "pin", None, None)
    if unit.done():
        ctx.commit = unit.payload()["commit"]
        if not ctx.review_dir.exists():
            snapshot.review_copy(ctx.source_dir, ctx.review_dir, ctx.spec.include, ctx.spec.exclude)
        return
    if ctx.source_dir.exists():
        snapshot.make_writable(ctx.source_dir)
        shutil.rmtree(ctx.source_dir)
    ctx.repo_dir.mkdir(parents=True, exist_ok=True)
    # Cloning reads data only: no hooks run, submodules are not fetched.
    git(["clone", "--no-recurse-submodules", "--quiet", ctx.spec.source, str(ctx.source_dir)])
    if ctx.spec.ref:
        git(["checkout", "--quiet", "--detach", ctx.spec.ref], cwd=ctx.source_dir)
    ctx.commit = git(["rev-parse", "HEAD"], cwd=ctx.source_dir)
    snapshot.review_copy(ctx.source_dir, ctx.review_dir, ctx.spec.include, ctx.spec.exclude)
    payload = {"commit": ctx.commit, "source": ctx.spec.source, "ref": ctx.spec.ref,
               "source_tree_sha256": snapshot.tree_hash(ctx.source_dir),
               "review_copy_sha256": snapshot.tree_hash(ctx.review_dir)}
    unit.save("done", payload)
    ctx.manifest.data["repo"]["commit"] = ctx.commit
