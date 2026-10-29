"""Stage 1b: install the project's dependencies, so its tests and our
reproductions do not fail at import.

The plan is read from the snapshot's files (requirements files, pyproject.toml
extras and dependency groups, setup.py or setup.cfg); nothing from the
repository runs on the host. The install runs in a worker whose only network
is the package registry (DockerWorker.install_deps). Dependencies go into a
virtual environment in the repository's run folder, which later workers mount
read-only at /deps. The project itself is uninstalled again, so the code under
review always comes from the worker's copy of the snapshot.

The resolved versions (pip freeze) are kept as evidence, so a rerun can use
the same ones.
"""

from __future__ import annotations

import shlex
import tomllib
from pathlib import Path

from harness import secrets
from harness.controller.context import RepoContext

PIP_VERSION = "25.2"  # first release line with --group (PEP 735)
TEST_EXTRAS = ("test", "tests", "testing", "dev")
TIMEOUT_S = 1800


def requirement_files(src: Path) -> list[str]:
    names = set()
    for pattern in ("requirements*.txt", "*-requirements.txt", "*_requirements.txt", "requirements/*.txt"):
        names.update(str(p.relative_to(src)) for p in Path(src).glob(pattern) if p.is_file() and not p.is_symlink())
    return sorted(n for n in names if "doc" not in Path(n).name.lower())


def plan(src: Path) -> dict:
    src = Path(src)
    out = {"requirements": requirement_files(src), "project": False, "extras": [], "groups": []}
    pyproject = src / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text())
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            data = {}
        if "project" in data or "build-system" in data:
            out["project"] = True
        extras = (data.get("project") or {}).get("optional-dependencies") or {}
        out["extras"] = [e for e in TEST_EXTRAS if e in extras]
        groups = data.get("dependency-groups") or {}
        out["groups"] = [g for g in TEST_EXTRAS if g in groups]
    if (src / "setup.py").is_file() or (src / "setup.cfg").is_file():
        out["project"] = True
    return out


def script(p: dict) -> str:
    q = shlex.quote
    # An isolated environment: the worker image's own tools (semgrep, PyYAML,
    # ...) must not satisfy the project's requirements by accident. pytest is
    # added at the image's version so the suite runs the same way.
    lines = ["pt=$(python -c 'import pytest; print(pytest.__version__)')",
             "python -m venv /deps/venv || exit 90",
             ". /deps/venv/bin/activate",
             f"pip install -q pip=={PIP_VERSION} \"pytest==$pt\" || {{ echo 'QOT-FAIL tooling'; exit 91; }}",
             "rc=0"]
    for f in p["requirements"]:
        lines.append(f"echo 'QOT-STEP requirements {f}'; pip install -r {q(f)} || {{ echo 'QOT-FAIL requirements'; rc=1; }}")
    if p["project"]:
        spec = "." + (f"[{','.join(p['extras'])}]" if p["extras"] else "")
        groups = " ".join(f"--group {q(g)}" for g in p["groups"])
        lines.append(f"echo 'QOT-STEP project'; pip install --report /tmp/report.json {groups} {q(spec)} "
                     "|| { echo 'QOT-FAIL project'; rc=1; }")
        # Keep the dependencies, drop the project: its code must come from the copy under review.
        lines.append("own=$(python -c \"import json;r=json.load(open('/tmp/report.json'));"
                     "print(' '.join(i['metadata']['name'] for i in r.get('install',[]) "
                     "if i.get('download_info',{}).get('url','').startswith('file:///work')))\" 2>/dev/null)")
        lines.append('[ -n "$own" ] && pip uninstall -y $own >/dev/null')
    elif p["groups"]:
        lines.append(f"pip install {' '.join(f'--group {q(g)}' for g in p['groups'])} || rc=1")
    lines += ["pip freeze > /deps/freeze.txt", "exit $rc"]
    return "\n".join(lines)


def run(ctx: RepoContext) -> None:
    deps_dir = ctx.repo_dir / "deps"
    unit = ctx.ledger.unit(ctx.spec.name, "deps", None, None)
    if unit.done():
        ctx.manifest.data["dependencies"] = unit.payload()
        if unit.payload().get("status") == "partial":
            ctx.manifest.incomplete("dependencies: some failed to install (details in the private run record)")
        ctx.worker = ctx.worker.with_deps(deps_dir)
        return
    p = plan(ctx.source_dir)
    if not p["requirements"] and not p["project"] and not p["groups"]:
        result = {"status": "not_applicable", **p, "note": "no requirements files or Python project metadata"}
        unit.save("done", result)
        ctx.manifest.data["dependencies"] = result
        return
    ok, why = ctx.worker.available() if ctx.worker else (False, "no worker configured")
    if not ok:
        ctx.manifest.incomplete(f"dependencies: not installed (worker unavailable: {why})")
        unit.save("skipped", {"status": "unavailable", **p})
        return
    ctx.log(f"  deps: installing ({len(p['requirements'])} requirements files, project={p['project']}) ...")
    r = ctx.worker.install_deps(script(p), ctx.source_dir, deps_dir, timeout_s=TIMEOUT_S)
    evidence = ctx.repo_dir / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "deps.log").write_text(secrets.redact(r.stdout + "\n--- stderr ---\n" + r.stderr))
    freeze = deps_dir / "freeze.txt"
    packages = [x for x in freeze.read_text().splitlines() if x.strip()] if freeze.exists() else []
    tooling = {"pytest", "pluggy", "iniconfig", "packaging", "pygments"}
    project_packages = [x for x in packages if x.split("==")[0].lower() not in tooling]
    venv = (deps_dir / "venv" / "bin" / "python").exists()
    status = "ok" if r.ok else ("partial" if venv and r.exit_code not in (90, 91) else "failed")
    denied = sorted({d.get("request", "")[:120] for d in r.proxy_log if d.get("decision") == "deny"})
    result = {"status": status, **p, "packages": len(project_packages), "exit_code": r.exit_code, "timed_out": r.timed_out,
              "duration_s": round(r.duration_s, 1),
              "registry_hosts_used": sorted({d["host"] for d in r.proxy_log if d.get("decision") == "allow"}),
              "denied_requests": denied, "freeze_ref": "deps/freeze.txt" if freeze.exists() else None}
    if status != "ok":
        ctx.manifest.incomplete(f"dependencies: {'some failed' if status == 'partial' else 'failed'} to install "
                                "(details in the private run record)")
    unit.save("done" if status in ("ok", "partial") else "failed", result)
    ctx.manifest.data["dependencies"] = result
    ctx.worker = ctx.worker.with_deps(deps_dir)
