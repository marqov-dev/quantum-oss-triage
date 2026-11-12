"""Stage 1b: install the project's dependencies, so its tests and our
reproductions do not fail at import.

The plan is read from the snapshot's files (a uv.lock, requirements files,
pyproject.toml extras and dependency groups, setup.py or setup.cfg); nothing
from the repository runs on the host. When the repository ships a uv.lock,
its pinned versions are installed as locked (exported by uv, then installed
by pip without resolving again); if that fails the step falls back to
resolving from the project metadata. The install runs in a worker whose only
network is the package registries (DockerWorker.install_deps). Dependencies go
into a virtual environment in the repository's run folder, which later
workers mount read-only at /deps. The project itself stays installed, for its
metadata and entry points (PennyLane finds its devices through them); later
workers put the copy under review first on the path (PYTHONPATH=/work/src:/work),
so the code that runs is the copy's.

The resolved versions (pip freeze) are kept as evidence, so a rerun can use
the same ones.
"""

from __future__ import annotations

import re
import shlex
import tomllib
from pathlib import Path, PurePosixPath

from harness import secrets
from harness.controller.context import RepoContext
from harness.stages import prefetch
from harness.workers.base import venv_installed

PIP_VERSION = "25.2"  # first release line with --group (PEP 735)
TEST_EXTRAS = ("test", "tests", "testing", "dev")
TIMEOUT_S = 1800


def requirement_files(src: Path) -> list[str]:
    names = set()
    for pattern in ("requirements*.txt", "*-requirements.txt", "*_requirements.txt", "requirements/*.txt"):
        names.update(str(p.relative_to(src)) for p in Path(src).glob(pattern) if p.is_file() and not p.is_symlink())
    return sorted(n for n in names if "doc" not in Path(n).name.lower())


_PKG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def local_package(entry: str) -> tuple[str, str]:
    """("src/openqaoa-core", "[tests]") from "src/openqaoa-core[tests]"; refuses paths outside the copy."""
    m = re.fullmatch(r"([^\[\]]+?)(\[[A-Za-z0-9_,.-]+\])?", entry.strip())
    if not m:
        raise ValueError(f"local package {entry!r}: expected a path with optional [extras]")
    path = PurePosixPath(m[1])
    if path.is_absolute() or ".." in path.parts or not path.parts or str(path) == ".":
        raise ValueError(f"local package {entry!r}: must be a relative path inside the repository")
    return str(path), m[2] or ""


def locked_versions(src: Path) -> dict[str, str]:
    """Normalised package name -> version, from the snapshot's uv.lock (read as data)."""
    try:
        lock = tomllib.loads((Path(src) / "uv.lock").read_text())
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return {}
    return {_norm(x["name"]): str(x.get("version", "")) for x in lock.get("package", []) if x.get("name")}


def plan(src: Path, install_extras: list[str] | tuple = (), *, local_packages: list[str] | tuple = (),
         omit: list[dict] | tuple = (), source_builds: list[dict] | tuple = ()) -> dict:
    """What to install. local_packages, omit and source_builds come from config/repos.yaml
    and appear in the plan only when set."""
    src = Path(src)
    out = {"requirements": requirement_files(src), "project": False, "extras": [], "groups": [],
           "lock": None, "workspace": False}
    pyproject = src / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text())
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            data = {}
        # A root with only [build-system] or a uv workspace (no [project]) is not
        # an installable project; pip would fail on its metadata. Poetry keeps
        # its metadata in [tool.poetry] instead.
        if "project" in data or "poetry" in (data.get("tool") or {}):
            out["project"] = True
        out["workspace"] = bool(((data.get("tool") or {}).get("uv") or {}).get("workspace"))
        extras = (data.get("project") or {}).get("optional-dependencies") or {}
        out["extras"] = [e for e in (*TEST_EXTRAS, *install_extras) if e in extras]
        groups = data.get("dependency-groups") or {}
        out["groups"] = [g for g in TEST_EXTRAS if g in groups]
    if (src / "setup.py").is_file() or (src / "setup.cfg").is_file():
        out["project"] = True
    lock = src / "uv.lock"
    if lock.is_file() and not lock.is_symlink():
        try:
            tomllib.loads(lock.read_text())
            out["lock"] = "uv.lock"
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            pass
    if local_packages:
        out["local_packages"] = []
        for entry in local_packages:
            path, extras = local_package(entry)
            if not (src / path).is_dir() or (src / path).is_symlink():
                raise ValueError(f"local package {path}: not a directory in the snapshot")
            out["local_packages"].append(path + extras)
    versions = locked_versions(src) if source_builds else {}
    for key, items in (("omit", omit), ("source_builds", source_builds)):
        if not items:
            continue
        if not out["lock"]:
            raise ValueError(f"deps.{key} needs a uv.lock: without one there is no locked set to change")
        rows = []
        for x in items:
            name = str(x.get("package", ""))
            if not _PKG.fullmatch(name) or not str(x.get("reason", "")).strip():
                raise ValueError(f"deps.{key}: each entry needs a package name and a reason")
            row = {"package": name, "reason": str(x["reason"]).strip()}
            if key == "source_builds":
                row["prefetch"] = str(x.get("prefetch", ""))
                row["version"] = versions.get(_norm(name))
                if not row["version"]:
                    raise ValueError(f"deps.source_builds: {name} is not in the snapshot's uv.lock")
            rows.append(row)
        out[key] = rows
    return out


def python_path(src: Path, p: dict) -> list[str]:
    """Package roots of the local packages inside the copy (their src/ folder when they have
    one), to go first on PYTHONPATH so later workers run the copy's code."""
    roots = []
    for entry in p.get("local_packages", []):
        path, _ = local_package(entry)
        roots.append(f"{path}/src" if (Path(src) / path / "src").is_dir() else path)
    return roots


# Run in the install worker after the install. For each distribution installed from the copy
# (/work), any file it installed that the copy lacks (a compiled extension such as
# pymatching/_cpp_pymatching*.so, a native library the build placed in the tree, a version
# file) is kept under /deps/generated at its path in the copy. Later workers add these to
# their copy where missing (docker.py's wrapper), since the copy comes first on the path
# and would otherwise hide the built files. Nothing in the copy is replaced.
_BUILT_FILES = r"""
import importlib.metadata as m, json, os, shutil, sys
roots = sys.argv[1:]
for d in m.distributions():
    try:
        url = json.loads(d.read_text('direct_url.json') or '{}').get('url', '')
    except ValueError:
        continue
    if not url.startswith('file:///work'):
        continue
    for f in d.files or []:
        s = str(f)
        if s.startswith('..') or '.dist-info/' in s or '__pycache__' in s or s.endswith('.pyc'):
            continue
        top = s.split('/')[0]
        for root in roots:
            if os.path.isdir(os.path.join(root, top)):
                rel = os.path.relpath(os.path.join(root, s), '/work')
                # Compared with the snapshot (/src): the build may have written the file into
                # this worker's own copy (setuptools-scm's write_to does).
                if not os.path.lexists(os.path.join('/src', rel)):
                    out = os.path.join('/deps/generated', rel)
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    shutil.copy2(str(f.locate()), out)
                    print('QOT-GENERATED', rel)
                break
"""


def _copy_roots(p: dict) -> list[str]:
    """Package roots inside the copy for local packages (src/ layout or flat)."""
    out = []
    for entry in p.get("local_packages", []):
        path, _ = local_package(entry)
        out += [f"{path}/src", path]
    return out


def script(p: dict, prefetched: list[dict] | tuple = ()) -> str:
    q = shlex.quote
    # An isolated environment: the worker image's own tools (semgrep, PyYAML,
    # ...) must not satisfy the project's requirements by accident. pytest is
    # added at the image's version so the suite runs the same way.
    lines = ["pt=$(python -c 'import pytest; print(pytest.__version__)')",
             "rm -rf /deps/generated",
             "python -m venv /deps/venv || exit 90",
             ". /deps/venv/bin/activate",
             f"pip install -q pip=={PIP_VERSION} \"pytest==$pt\" || {{ echo 'QOT-FAIL tooling'; exit 91; }}",
             "rc=0", "locked=0"]
    # Host-fetched source archives (checked by sha256), unpacked here, never on the host.
    lines += prefetch.script_lines(list(prefetched))
    unpacked = {e["name"]: prefetch.unpack_dir(e) for e in prefetched}
    local = [f"./{x}" for x in p.get("local_packages", [])]
    # Built first, from their prefetched trees, so that the locked set below (which leaves
    # them out) finds them installed. Each must build exactly the locked version.
    check = "import importlib.metadata as m,sys; v=m.version(sys.argv[1]); sys.exit(0 if v==sys.argv[2] else 'built '+v)"
    for b in p.get("source_builds", []):
        if b["prefetch"] not in unpacked:
            raise ValueError(f"source build {b['package']}: no prefetch entry named {b['prefetch']!r}")
        lines.append(f"echo 'QOT-STEP source-build {b['package']}'; "
                     f"pip install --no-deps {q(unpacked[b['prefetch']])} && "
                     f"python -c {q(check)} {q(b['package'])} {q(b['version'])} "
                     f"|| {{ echo 'QOT-FAIL source-build {b['package']}'; rc=1; }}")
    if p.get("lock"):
        # The lock's own versions, workspace members left out (their code comes
        # from the copy). uv only reads the lock here; it never resolves.
        # Packages omitted or built from source on purpose are left out too.
        sel = " ".join([f"--extra {q(e)}" for e in p["extras"]] + [f"--group {q(g)}" for g in p["groups"]]
                       + [f"--no-emit-package {q(x['package'])}"
                          for x in [*p.get("omit", []), *p.get("source_builds", [])]])
        lines += ["echo 'QOT-STEP lock uv.lock'",
                  f"if UV_OFFLINE=1 uv export --frozen --format requirements-txt --no-header --no-emit-workspace "
                  f"{'--all-packages ' if p.get('workspace') else ''}{sel} -o /tmp/lock-req.txt "
                  "&& pip install --no-deps -r /tmp/lock-req.txt"
                  + (f" && pip install --no-deps {' '.join(q(x) for x in local)}" if local else "")
                  + (" && pip install --no-deps ." if p["project"] else "")
                  + "; then locked=1; "
                  "else echo 'QOT-FAIL lock (falling back to resolving)'; fi"]
        lines.append('if [ "$locked" = 0 ]; then :')
    for f in p["requirements"]:
        lines.append(f"echo 'QOT-STEP requirements {f}'; pip install -r {q(f)} || {{ echo 'QOT-FAIL requirements'; rc=1; }}")
    if p["project"]:
        spec = "." + (f"[{','.join(p['extras'])}]" if p["extras"] else "")
        groups = " ".join(f"--group {q(g)}" for g in p["groups"])
        # Local packages go in the same resolve, so pip takes them from the copy and not
        # the registry (a monorepo root that pins its own subpackages by version).
        locals_ = "".join(f"{q(x)} " for x in local)
        lines.append(f"echo 'QOT-STEP project'; pip install --report /tmp/report.json {groups} {locals_}{q(spec)} "
                     "|| { echo 'QOT-FAIL project'; rc=1; }")
        # The project stays installed (metadata, entry points); its code is
        # still taken from the copy, which comes first on the path.
        lines.append("own=$(python -c \"import json;r=json.load(open('/tmp/report.json'));"
                     "print(' '.join(i['metadata']['name'] for i in r.get('install',[]) "
                     "if i.get('download_info',{}).get('url','').startswith('file:///work')))\" 2>/dev/null)")
        lines.append('echo "QOT-PROJECT-INSTALLED $own"')
    elif p["groups"]:
        lines.append(f"pip install {' '.join(f'--group {q(g)}' for g in p['groups'])} || rc=1")
    if p.get("lock"):
        lines.append("fi")
    roots = " ".join(q(f"/work/{r}") for r in _copy_roots(p))
    lines.append(f"python -c {q(_BUILT_FILES)} {roots} /work/src /work || echo 'QOT-FAIL generated files'")
    lines += ["pip freeze > /deps/freeze.txt", "exit $rc"]
    return "\n".join(lines)


def environment_problem(ctx: RepoContext) -> str | None:
    """Why the project's code cannot be run here, or None. Stages that run project code
    (validate, gates, blind fix, fix) check this; scanners do not need the environment."""
    rec = ctx.ledger.unit(ctx.spec.name, "deps", None, None).load()
    if rec and (rec.get("payload") or {}).get("status") == "failed":
        return "the project's dependencies failed to install (details in the private run record)"
    return None


def _submodule_commit(src: Path, path: str) -> str | None:
    """The commit the snapshot's tree records for a submodule (a gitlink), read with git."""
    from harness.stages.pin import git
    try:
        out = git(["ls-tree", "HEAD", "--", path], cwd=src)
    except RuntimeError:
        return None
    parts = out.split()
    return parts[2] if len(parts) >= 3 and parts[1] == "commit" else None


def _plan_for(ctx: RepoContext) -> dict:
    s = ctx.spec
    return plan(ctx.source_dir, s.install_extras, local_packages=s.local_packages, omit=s.omit,
                source_builds=s.source_builds)


def _deviation_notes(ctx: RepoContext, p: dict) -> None:
    """Configured departures from the project's own dependency set, shown in the manifest."""
    for x in p.get("omit", []):
        ctx.manifest.incomplete(f"dependencies: {x['package']} left out by configuration ({x['reason']})")
    for x in p.get("source_builds", []):
        ctx.manifest.incomplete(f"dependencies: {x['package']} {x['version']} built from a prefetched source "
                                f"tree instead of the registry ({x['reason']})")


def run(ctx: RepoContext) -> None:
    deps_dir = ctx.repo_dir / "deps"
    unit = ctx.ledger.unit(ctx.spec.name, "deps", None, None)
    if unit.done():
        payload = unit.payload()
        ctx.manifest.data["dependencies"] = payload
        if payload.get("status") == "partial":
            ctx.manifest.incomplete("dependencies: some failed to install (details in the private run record)")
        _deviation_notes(ctx, payload)
        ctx.worker = ctx.worker.with_deps(deps_dir, python_path(ctx.source_dir, payload))
        return
    p = _plan_for(ctx)
    if not p["requirements"] and not p["project"] and not p["groups"] and not p.get("lock"):
        result = {"status": "not_applicable", **p, "note": "no requirements files or Python project metadata"}
        unit.save("done", result)
        ctx.manifest.data["dependencies"] = result
        return
    ok, why = ctx.worker.available() if ctx.worker else (False, "no worker configured")
    if not ok:
        ctx.manifest.incomplete(f"dependencies: not installed (worker unavailable: {why})")
        unit.save("skipped", {"status": "unavailable", **p})
        return
    prefetched: list[dict] = []
    kwargs = {}
    if ctx.spec.prefetch:
        # On the host: downloads only, checked by sha256; nothing is unpacked or run here.
        prefetch.check_declared(ctx.spec.prefetch, ctx.source_dir, submodule_commit=_submodule_commit)
        prefetched = prefetch.fetch(ctx.spec.prefetch, ctx.repo_dir / "prefetch", log=ctx.log)
        kwargs["prefetch_dir"] = ctx.repo_dir / "prefetch"
    ctx.log(f"  deps: installing ({len(p['requirements'])} requirements files, project={p['project']}) ...")
    r = ctx.worker.install_deps(script(p, prefetched), ctx.source_dir, deps_dir, timeout_s=TIMEOUT_S, **kwargs)
    evidence = ctx.repo_dir / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "deps.log").write_text(secrets.redact(r.stdout + "\n--- stderr ---\n" + r.stderr))
    freeze = deps_dir / "freeze.txt"
    packages = [x for x in freeze.read_text().splitlines() if x.strip()] if freeze.exists() else []
    tooling = {"pytest", "pluggy", "iniconfig", "packaging", "pygments"}
    project_packages = [x for x in packages if x.split("==")[0].lower() not in tooling]
    venv = venv_installed(deps_dir)
    status = "ok" if r.ok else ("partial" if venv and r.exit_code not in (90, 91, 92) else "failed")
    # Nothing of the project installed (no project packages, and the project step failed):
    # tests would only measure the missing environment, so this is a failure, not partial.
    if status == "partial" and not project_packages and "QOT-FAIL project" in r.stdout:
        status = "failed"
    denied = sorted({d.get("request", "")[:120] for d in r.proxy_log if d.get("decision") == "deny"})
    installed_from = ("uv.lock" if "QOT-STEP lock" in r.stdout and "QOT-FAIL lock" not in r.stdout
                      else "resolved from project metadata")
    result = {"status": status, **p, "installed_from": installed_from,
              "registries": list(getattr(ctx.worker, "registries", ()) or ()),
              "packages": len(project_packages), "exit_code": r.exit_code, "timed_out": r.timed_out,
              "duration_s": round(r.duration_s, 1),
              "registry_hosts_used": sorted({d["host"] for d in r.proxy_log if d.get("decision") == "allow"}),
              "denied_requests": denied, "freeze_ref": "deps/freeze.txt" if freeze.exists() else None}
    # The interpreter and platform the environment was built for: later workers must match.
    image = ctx.worker.describe() if hasattr(ctx.worker, "describe") else {}
    if isinstance(image, dict) and image.get("tag"):
        result["worker_image"] = {k: image[k] for k in ("tag", "digest", "platform", "python") if k in image}
    built = sorted({x.split(" ", 1)[1].strip() for x in r.stdout.splitlines() if x.startswith("QOT-GENERATED ")})
    if built:
        result["built_files"] = built  # added to later workers' copies: see _BUILT_FILES
    if prefetched:
        keep = ("name", "url", "commit", "sha256", "bytes", "file", "extract_to", "fetchcontent", "declared_in")
        result["prefetched"] = [{k: e[k] for k in keep if k in e} for e in prefetched]
    if status != "ok":
        ctx.manifest.incomplete(f"dependencies: {'some failed' if status == 'partial' else 'failed'} to install "
                                "(details in the private run record)")
    _deviation_notes(ctx, p)
    unit.save("done" if status in ("ok", "partial") else "failed", result)
    ctx.manifest.data["dependencies"] = result
    ctx.worker = ctx.worker.with_deps(deps_dir, python_path(ctx.source_dir, p))
