"""Dependency installation: the plan, the registry-only step and the /deps mount."""

import json
import subprocess

import pytest

from harness.controller.config import Config, RepoSpec
from harness.controller.context import RepoContext
from harness.controller.ledger import Ledger
from harness.controller.manifest import Manifest
from harness.stages import deps
from harness.workers.base import Worker, WorkerResult
from harness.workers.docker import DockerWorker
from tests.test_workers import docker


def fake_venv(deps_dir):
    """What the install container leaves: python is a link to the worker's own interpreter."""
    (deps_dir / "venv" / "bin").mkdir(parents=True, exist_ok=True)
    (deps_dir / "venv" / "pyvenv.cfg").write_text("home = /usr/local/bin\n")
    link = deps_dir / "venv" / "bin" / "python"
    if not link.is_symlink():
        link.symlink_to("/usr/local/bin/python3")  # a container path: dangling on the host


def test_a_venv_whose_python_is_a_container_link_counts_as_installed(tmp_path):
    fake_venv(tmp_path / "deps")
    assert not (tmp_path / "deps" / "venv" / "bin" / "python").exists()  # dangling here, as on a real host
    assert DockerWorker().with_deps(tmp_path / "deps").deps_dir is not None
    assert DockerWorker().with_deps(tmp_path / "missing").deps_dir is None


def test_plan_reads_requirements_extras_and_groups(tmp_path):
    (tmp_path / "requirements.txt").write_text("numpy\n")
    (tmp_path / "requirements-dev.txt").write_text("pytest\n")
    (tmp_path / "docs-requirements.txt").write_text("sphinx\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "q"\n[project.optional-dependencies]\ntest = ["hypothesis"]\nviz = ["matplotlib"]\n'
        '[dependency-groups]\ndev = ["ruff"]\n')
    p = deps.plan(tmp_path)
    assert p == {"requirements": ["requirements-dev.txt", "requirements.txt"], "project": True,
                 "extras": ["test"], "groups": ["dev"], "lock": None, "workspace": False}
    s = deps.script(p)
    assert "pip install --report /tmp/report.json --group dev '.[test]'" in s
    assert "pip install -r requirements.txt" in s and "docs-requirements" not in s
    assert "--system-site-packages" not in s  # the image's tools must not satisfy requirements
    # The project stays installed (entry points); its code still comes from the copy, first on the path.
    assert "pip uninstall" not in s and "QOT-PROJECT-INSTALLED" in s


def test_plan_survives_a_broken_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project\nname=")
    assert deps.plan(tmp_path)["project"] is False


def test_worker_mounts_deps_read_only_only_when_installed(tmp_path):
    w = DockerWorker().with_deps(tmp_path / "deps")
    assert w.deps_dir is None
    fake_venv(tmp_path / "deps")
    w = DockerWorker().with_deps(tmp_path / "deps")
    cmd = w.command("x", tmp_path, inputs=None, network=False, writable_copy=True, name="n")
    assert f"{(tmp_path / 'deps').resolve()}:/deps:ro" in cmd
    envs = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-e"]
    assert "PYTHONPATH=/work/src:/work" in envs and envs[envs.index("PYTHONPATH=/work/src:/work") - 1].startswith("PATH=/deps")
    assert cmd[cmd.index("--network") + 1] == "none"  # tests still run offline


class FakeInstallWorker(Worker):
    name = "fake"

    def __init__(self, rc, venv=True):
        self.rc, self.venv, self.scripts = rc, venv, []

    def available(self):
        return True, "fake"

    def describe(self):
        return {"tag": "fake"}

    def install_deps(self, script, src, deps_dir, *, timeout_s=0):
        self.scripts.append(script)
        if self.venv:
            fake_venv(deps_dir)
            (deps_dir / "freeze.txt").write_text("numpy==2.3.4\npytest==9.1.1\n")
        r = WorkerResult(self.rc, "QOT-STEP requirements\napi_key = 'abcdefgh12345678'\n", "")
        r.proxy_log = [{"decision": "allow", "host": "pypi.org"},
                       {"decision": "deny", "request": "CONNECT evil.example:443 HTTP/1.1"}]
        return r


def _ctx(tmp_path, worker):
    run_dir = tmp_path / "run"
    spec = RepoSpec("org/q", str(tmp_path))
    m = Manifest.open(run_dir / spec.slug / "manifest.json", run_id="r", repo={"name": "org/q", "source": "", "commit": "0" * 40,
                                                                                "scope": {"include": [], "exclude": []}})
    ctx = RepoContext(spec, "r", run_dir, Config(models={}, review_skills=[], worker={}, timeouts={}),
                      Ledger(run_dir), m, worker, {})
    ctx.source_dir.mkdir(parents=True)
    (ctx.source_dir / "requirements.txt").write_text("numpy\n")
    return ctx


@pytest.mark.parametrize("rc,venv,status", [(0, True, "ok"), (1, True, "partial"), (90, False, "failed")])
def test_stage_records_outcome_and_never_hides_a_failure(tmp_path, rc, venv, status):
    ctx = _ctx(tmp_path, FakeInstallWorker(rc, venv))
    deps.run(ctx)
    d = ctx.manifest.data["dependencies"]
    assert d["status"] == status and d["registry_hosts_used"] == ["pypi.org"]
    assert d["denied_requests"] == ["CONNECT evil.example:443 HTTP/1.1"]
    notes = ctx.manifest.data["coverage"]["incomplete_checks"]
    assert (status == "ok") == (not any(n.startswith("dependencies") for n in notes))
    assert "abcdefgh12345678" not in (ctx.repo_dir / "evidence" / "deps.log").read_text()
    if venv:
        assert d["packages"] == 1  # numpy; the harness's pytest is not counted


def test_stage_resumes_without_reinstalling(tmp_path):
    w = FakeInstallWorker(0)
    ctx = _ctx(tmp_path, w)
    deps.run(ctx)
    deps.run(ctx)
    assert len(w.scripts) == 1


@pytest.mark.docker
@docker
def test_registry_only_network_live(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    probe = ("curl -sS -m 10 -o /dev/null --noproxy '*' https://pypi.org/simple/ && echo DIRECT-OPEN || echo DIRECT-BLOCKED\n"
             "curl -sS -m 10 -o /dev/null https://example.com && echo OTHER-OPEN || echo OTHER-BLOCKED\n"
             "curl -sS -m 10 -o /dev/null https://pypi.org/simple/ && echo REGISTRY-OPEN || echo REGISTRY-BLOCKED\n"
             "touch /deps/written && echo DEPS-WRITABLE\n")
    r = DockerWorker().install_deps(probe, src, tmp_path / "deps", timeout_s=120)
    assert "DIRECT-BLOCKED" in r.stdout and "OTHER-BLOCKED" in r.stdout and "REGISTRY-OPEN" in r.stdout, r.stdout + r.stderr
    assert {d.get("decision") for d in r.proxy_log} >= {"allow", "deny"}
    left = subprocess.run(["docker", "network", "ls", "--filter", "name=qot-registry-", "-q"], capture_output=True, text=True)
    assert left.stdout.strip() == ""


def test_a_uv_lock_is_installed_as_locked(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "q"\n[project.optional-dependencies]\ntest = ["x"]\n')
    (tmp_path / "uv.lock").write_text('version = 1\nrequires-python = ">=3.10"\n')
    p = deps.plan(tmp_path)
    assert p["lock"] == "uv.lock" and not p["workspace"]
    s = deps.script(p)
    assert "uv export --frozen --format requirements-txt --no-header --no-emit-workspace --extra test" in s
    assert "pip install --no-deps -r /tmp/lock-req.txt && pip install --no-deps ." in s  # pins, then the project
    assert "UV_OFFLINE=1" in s and "--all-packages" not in s
    # The resolving path is still there, as the fallback.
    assert s.index("QOT-STEP lock") < s.index('if [ "$locked" = 0 ]') < s.index("QOT-STEP project")
    subprocess.run(["sh", "-n", "-c", s], check=True)


def test_a_uv_workspace_root_is_not_a_project(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["impl/py"]\n'
                                            '[dependency-groups]\ntest = ["pytest"]\n')
    (tmp_path / "uv.lock").write_text("version = 1\n")
    p = deps.plan(tmp_path)
    assert p["project"] is False and p["workspace"] and p["groups"] == ["test"]
    assert "--all-packages --group test" in deps.script(p)


def test_a_broken_lock_is_ignored(tmp_path):
    (tmp_path / "uv.lock").write_text("version = [\n")
    assert deps.plan(tmp_path)["lock"] is None


def test_registries_are_named_and_unknown_ones_refused():
    assert DockerWorker().registry_hosts() == ("pypi.org", "files.pythonhosted.org")
    hosts = DockerWorker(registries=("pypi", "crates")).registry_hosts()
    assert "static.crates.io" in hosts and "github.com" not in hosts
    with pytest.raises(ValueError):
        DockerWorker(registries=("pypi", "github"))


@pytest.mark.docker
@docker
def test_install_container_can_run_build_tools_live(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    probe = ("cp /usr/bin/true /tmp/t && /tmp/t && echo TMP-EXEC\n"
             "cp /usr/bin/true /work/t && /work/t && echo WORK-EXEC\n"
             "cmake --version >/dev/null && cc --version >/dev/null && echo BUILD-TOOLS\n"
             "rustc --version && cargo --version && uv --version\n"
             "curl -sS -m 10 -o /dev/null https://static.crates.io/ && echo CRATES-OPEN || echo CRATES-BLOCKED\n"
             "curl -sS -m 10 -o /dev/null https://static.rust-lang.org/ && echo RUSTUP-OPEN || echo RUSTUP-BLOCKED\n")
    image = "quantum-oss-triage-worker:dev"
    r = DockerWorker(image=image).install_deps(probe, src, tmp_path / "deps", timeout_s=120)
    out = r.stdout + r.stderr
    assert "TMP-EXEC" in out and "WORK-EXEC" in out and "BUILD-TOOLS" in out, out
    assert "rustc 1.91.1" in out and "uv 0.11" in out, out
    assert "CRATES-BLOCKED" in out and "RUSTUP-BLOCKED" in out, out  # pypi only by default
    r = DockerWorker(image=image, registries=("pypi", "crates")).install_deps(probe, src, tmp_path / "deps2",
                                                                             timeout_s=120)
    assert "CRATES-OPEN" in r.stdout and "RUSTUP-BLOCKED" in r.stdout, r.stdout + r.stderr
