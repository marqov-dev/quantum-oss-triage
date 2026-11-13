"""Docker and disk outages stop a run cleanly instead of being recorded as project failures.

Everything here uses fakes: no Docker daemon is stopped or needed.
"""

import json
import subprocess
from pathlib import Path

import pytest

from harness.controller import pipeline
from harness.controller.config import RepoSpec
from harness.controller.context import RepoContext
from harness.controller.ledger import Ledger
from harness.controller.manifest import Manifest
from harness.workers import infra
from harness.workers.docker import DockerWorker
from harness.workers.infra import DiskCheck, InfraGuard, InfrastructureUnavailable
from harness.workers.local import LocalWorker
from tests.test_pipeline import FIX, REPRO, config, repo, two_models  # noqa: F401  (fixtures)
from tests.fakes.adapters import FakeAdapter

GB = 1024 ** 3


class FakeDocker:
    """Answers `docker info` and `docker image inspect` the way the CLI does."""

    def __init__(self, up=True, images=("img:dev",), hang=False):
        self.up, self.images, self.hang = up, set(images), hang
        self.calls: list[list[str]] = []

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        if self.hang:
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 0))
        if not self.up:
            return subprocess.CompletedProcess(cmd, 1, "", "Cannot connect to the Docker daemon at "
                                               "unix:///var/run/docker.sock. Is the docker daemon running?\n")
        if cmd[1] == "info":
            return subprocess.CompletedProcess(cmd, 0, "29.0.1\n", "")
        if cmd[1:3] == ["image", "inspect"]:
            if cmd[-1] in self.images:
                return subprocess.CompletedProcess(cmd, 0, "sha256:abc\n", "")
            return subprocess.CompletedProcess(cmd, 1, "", f"Error: No such image: {cmd[-1]}\n")
        raise AssertionError(f"unexpected docker call {cmd}")

    def info_calls(self):
        return sum(1 for c in self.calls if c[1] == "info")


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def guard(docker=None, disks=(), free=None, clock=None, ttl_s=5.0):
    return InfraGuard(docker="docker", disks=disks, ttl_s=ttl_s, run=docker or FakeDocker(),
                      free_bytes=free or (lambda p: 100 * GB), clock=clock or Clock(), which=lambda _: "/bin/docker")


# --- the guard itself --------------------------------------------------------

def test_daemon_down_raises_infrastructure_error():
    g = guard(FakeDocker(up=False))
    with pytest.raises(InfrastructureUnavailable) as e:
        g.check(image="img:dev")
    assert e.value.kind == "docker" and "daemon" in str(e.value)


def test_daemon_that_does_not_answer_counts_as_down():
    with pytest.raises(InfrastructureUnavailable) as e:
        guard(FakeDocker(hang=True)).check()
    assert e.value.kind == "docker" and "not responding" in str(e.value)


def test_docker_not_installed():
    g = InfraGuard(run=FakeDocker(), which=lambda _: None)
    with pytest.raises(InfrastructureUnavailable) as e:
        g.check()
    assert e.value.kind == "docker"


def test_missing_image_raises():
    with pytest.raises(InfrastructureUnavailable) as e:
        guard().check(image="other:dev")
    assert e.value.kind == "image" and "other:dev" in str(e.value)


def test_check_is_cached_for_a_few_seconds_and_force_bypasses_it():
    d, clock = FakeDocker(), Clock()
    g = guard(d, clock=clock)
    for _ in range(5):
        g.check(image="img:dev")
    assert d.info_calls() == 1
    clock.t = 6.0
    g.check(image="img:dev")
    assert d.info_calls() == 2
    g.check(image="img:dev", force=True)
    assert d.info_calls() == 3


def test_daemon_going_down_is_seen_once_the_cache_expires():
    d, clock = FakeDocker(), Clock()
    g = guard(d, clock=clock)
    g.check()
    d.up = False
    g.check()  # still cached as up
    clock.t = 10.0
    with pytest.raises(InfrastructureUnavailable):
        g.check()


def test_low_disk_raises_with_path_and_threshold(tmp_path):
    data = tmp_path / "docker-data"
    data.mkdir()
    disks = [DiskCheck("run directory", tmp_path, 8), DiskCheck("Docker data", data, 40, must_exist=True)]
    free = {str(tmp_path): 100 * GB, str(data): 12 * GB}
    g = guard(disks=disks, free=lambda p: free[str(p)])
    with pytest.raises(InfrastructureUnavailable) as e:
        g.check(docker=False)
    assert e.value.kind == "disk"
    assert "Docker data" in str(e.value) and "12.0 GB" in str(e.value) and "40" in str(e.value)


def test_unmounted_docker_data_folder_is_reported(tmp_path):
    g = guard(disks=[DiskCheck("Docker data", tmp_path / "gone", 40, must_exist=True)])
    with pytest.raises(InfrastructureUnavailable) as e:
        g.check(docker=False)
    assert e.value.kind == "disk" and "not mounted" in str(e.value)


def test_disk_check_alone_does_not_touch_docker(tmp_path):
    d = FakeDocker(up=False)
    guard(d, disks=[DiskCheck("run directory", tmp_path, 1)]).check(docker=False)
    assert d.calls == []


def test_missing_disk_path_checks_its_nearest_existing_parent(tmp_path):
    seen = []
    g = guard(disks=[DiskCheck("run directory", tmp_path / "not" / "yet", 1)],
              free=lambda p: seen.append(Path(p)) or 100 * GB)
    g.check(docker=False)
    assert seen == [tmp_path]


def test_docker_data_path_comes_from_docker_desktop_settings(tmp_path):
    settings = tmp_path / "settings-store.json"
    settings.write_text(json.dumps({"DataFolder": "/Volumes/ext/docker/DockerDesktop"}))
    assert infra.docker_data_path("auto", settings_files=[settings]) == Path("/Volumes/ext/docker/DockerDesktop")
    assert infra.docker_data_path("auto", settings_files=[tmp_path / "missing.json"]) is None
    assert infra.docker_data_path("/srv/docker") == Path("/srv/docker")
    assert infra.docker_data_path(None) is None


def test_from_config_uses_thresholds(tmp_path):
    g = infra.from_config({"image": "x", "preflight": {"run_dir_min_free_gb": 3, "docker_data_path": str(tmp_path),
                                                       "docker_data_min_free_gb": 7, "cache_s": 2}}, tmp_path / "run")
    assert [(c.label, c.min_free_gb) for c in g.disks] == [("run directory", 3), ("Docker data", 7)]
    assert g.ttl_s == 2
    assert infra.from_config({"image": "x", "preflight": {"enabled": False}}, tmp_path) is None


def test_after_failure_reports_outage_only_when_daemon_is_gone():
    d = FakeDocker()
    g = guard(d)
    assert g.outage_after_failure(1, "AssertionError") is None  # a real test failure
    d.up = False
    reason = g.outage_after_failure(125, "Cannot connect to the Docker daemon")
    assert reason is not None and reason.kind == "docker"


def test_after_failure_reports_missing_image_from_docker_run():
    g = guard(FakeDocker(images=()))
    reason = g.outage_after_failure(125, "Unable to find image 'img:dev' locally", image="img:dev")
    assert reason is not None and reason.kind == "image"


# --- the Docker worker ---------------------------------------------------------

class Runs:
    """Stands in for subprocess.run inside harness.workers.docker."""

    def __init__(self, docker: FakeDocker, container=(0, "ok", "")):
        self.docker, self.container, self.launched = docker, container, []

    def __call__(self, cmd, **kw):
        if cmd[1] in ("info",) or cmd[1:3] == ["image", "inspect"]:
            return self.docker(cmd, **kw)
        if cmd[1] == "run":
            self.launched.append(cmd)
            if callable(self.container):
                return self.container(cmd)
            rc, out, err = self.container
            return subprocess.CompletedProcess(cmd, rc, out, err)
        if cmd[1] == "network" and cmd[2] == "create" and not self.docker.up:
            raise subprocess.CalledProcessError(1, cmd, "", "Cannot connect to the Docker daemon")
        return subprocess.CompletedProcess(cmd, 0, "", "")


def worker_with(monkeypatch, docker, container=(0, "ok", ""), clock=None):
    runs = Runs(docker, container)
    monkeypatch.setattr("harness.workers.docker.subprocess.run", runs)
    monkeypatch.setattr("harness.workers.docker.shutil.which", lambda _: "/bin/docker")
    g = guard(docker, clock=clock)
    return DockerWorker(image="img:dev", guard=g), runs


def test_worker_does_not_launch_when_docker_is_down(tmp_path, monkeypatch):
    w, runs = worker_with(monkeypatch, FakeDocker(up=False))
    with pytest.raises(InfrastructureUnavailable):
        w.run("true", tmp_path)
    assert runs.launched == []


def test_worker_does_not_launch_without_its_image(tmp_path, monkeypatch):
    w, runs = worker_with(monkeypatch, FakeDocker(images=()))
    with pytest.raises(InfrastructureUnavailable) as e:
        w.run("true", tmp_path)
    assert e.value.kind == "image" and runs.launched == []


def test_available_raises_rather_than_reporting_a_degraded_worker(tmp_path, monkeypatch):
    w, _ = worker_with(monkeypatch, FakeDocker(up=False))
    with pytest.raises(InfrastructureUnavailable):
        w.available()


def test_platform_and_deps_copies_share_the_guard(tmp_path, monkeypatch):
    w, _ = worker_with(monkeypatch, FakeDocker())
    assert w.for_platform("linux/amd64").guard is w.guard
    assert w.with_deps(tmp_path).guard is w.guard


def test_launch_error_from_a_vanished_daemon_is_an_infrastructure_failure(tmp_path, monkeypatch):
    d = FakeDocker()

    def dies(cmd):  # the daemon goes away while the container runs
        d.up = False
        return subprocess.CompletedProcess(cmd, 125, "", "error waiting for container: unexpected EOF\n")

    w, _ = worker_with(monkeypatch, d, container=dies)
    with pytest.raises(InfrastructureUnavailable) as e:
        w.run("pytest", tmp_path)
    assert e.value.kind == "docker"


def test_project_failure_with_docker_up_is_returned_as_a_result(tmp_path, monkeypatch):
    w, _ = worker_with(monkeypatch, FakeDocker(), container=(1, "", "1 failed"))
    r = w.run("pytest", tmp_path)
    assert r.exit_code == 1 and not r.ok


def test_timeout_while_daemon_is_gone_is_an_infrastructure_failure(tmp_path, monkeypatch):
    d = FakeDocker()

    def hangs(cmd):
        d.up = False
        raise subprocess.TimeoutExpired(cmd, 1)

    w, _ = worker_with(monkeypatch, d, container=hangs)
    with pytest.raises(InfrastructureUnavailable):
        w.run("pytest", tmp_path, timeout_s=1)


def test_install_deps_setup_error_from_a_vanished_daemon(tmp_path, monkeypatch):
    d = FakeDocker()
    clock = Clock()
    w, runs = worker_with(monkeypatch, d, clock=clock)
    w.guard.check(image="img:dev")  # cached as up
    d.up = False
    with pytest.raises(InfrastructureUnavailable):
        w.install_deps("true", tmp_path, tmp_path / "deps")
    assert runs.launched == []


# --- model calls in a reviewer sandbox ---------------------------------------------

class SandboxedFake(FakeAdapter):
    def __init__(self, name, docker: FakeDocker, **kw):
        super().__init__(name, **kw)
        self.docker = docker
        self.sandbox = type("Sb", (), {"image": "img:dev"})()

    def run(self, prompt, system, schema_name, cwd, timeout_s=0):
        self.calls.append((schema_name, prompt[:80]))
        from harness.adapters.base import AdapterResult
        self.docker.up = False  # the daemon dies while the CLI runs in its container
        return AdapterResult(False, None, "", None, error="docker: Cannot connect to the Docker daemon")


def _ctx(tmp_path, adapters, g):
    spec = RepoSpec("test/m", "x")
    from harness.controller.config import Config
    cfg = Config(models={"codex": {}}, review_skills=[], worker={"image": "none"}, timeouts={})
    manifest = Manifest.open(tmp_path / "run" / "test__m" / "manifest.json", run_id="run", repo={})
    w = type("W", (), {"guard": g})()
    return RepoContext(spec, "run", tmp_path / "run", cfg, Ledger(tmp_path / "run"), manifest, w, adapters,
                       log=lambda *_: None)


def test_sandboxed_model_call_that_loses_docker_saves_no_unit(tmp_path):
    d = FakeDocker()
    ctx = _ctx(tmp_path, {"codex": SandboxedFake("codex", d)}, guard(d))
    with pytest.raises(InfrastructureUnavailable):
        ctx.call_model("review", "review-correctness", "codex", "review-correctness", "p", 10)
    assert not ctx.ledger.unit("test/m", "review", "review-correctness", "codex").path.exists()
    assert ctx.manifest.data["failures"] == []


def test_sandboxed_model_call_is_not_started_while_docker_is_down(tmp_path):
    d = FakeDocker(up=False)
    a = SandboxedFake("codex", d)
    ctx = _ctx(tmp_path, {"codex": a}, guard(d))
    with pytest.raises(InfrastructureUnavailable):
        ctx.call_model("review", "review-correctness", "codex", "review-correctness", "p", 10)
    assert a.calls == []


# --- the pipeline: pause, record why, resume -----------------------------------------

class GuardedLocal(LocalWorker):
    """The local test worker, checked by a guard the way the Docker worker is."""

    def __init__(self, g):
        self.guard = g

    def available(self):
        self.guard.check(image="img:dev")
        return super().available()

    def run(self, *a, **kw):
        self.guard.check(image="img:dev")
        return super().run(*a, **kw)


def test_outage_pauses_the_repo_records_why_and_a_rerun_resumes(tmp_path, repo, config, monkeypatch):
    monkeypatch.setenv("QOT_ALLOW_LOCAL_WORKER", "1")
    d = FakeDocker()
    g = guard(d, ttl_s=0)
    real_stage = pipeline._run_stage

    def stage(ctx, name):
        if name == "validate":
            d.up = False  # Docker Desktop stops just as validation starts
        return real_stage(ctx, name)

    monkeypatch.setattr(pipeline, "_run_stage", stage)
    other = RepoSpec("test/next", repo.source)
    first = two_models()
    s = pipeline.run(config, tmp_path / "run", [repo, other], adapters=first, worker=GuardedLocal(g),
                     log=lambda *_: None)
    d_ = tmp_path / "run" / "test__m"
    m = json.loads((d_ / "manifest.json").read_text())
    assert s["repos"]["test/m"]["status"] == "paused" and "test/next" not in s["repos"]
    assert s["stop_kind"] == "infrastructure" and "daemon" in s["stopped"]
    assert m["status"] == "paused"
    assert m["stages"]["validate"]["status"] == "paused"
    assert m["stages"].get("gates", {}).get("status", "not_started") == "not_started"
    assert m["interruption"]["kind"] == "infrastructure" and m["interruption"]["stage"] == "validate"
    assert m["interruption"]["cause"] == "docker"
    assert not list((d_ / "units").glob("validate__*.json"))  # nothing recorded for the outage
    assert not any("validate" in c for c in m["coverage"]["incomplete_checks"])

    # Docker is back: the same command picks up at validation.
    monkeypatch.setattr(pipeline, "_run_stage", real_stage)
    d.up = True
    again = two_models()
    s2 = pipeline.run(config, tmp_path / "run", [repo], adapters=again, worker=GuardedLocal(g), log=lambda *_: None)
    m2 = json.loads((d_ / "manifest.json").read_text())
    assert s2["stopped"] is None and m2["status"] != "paused" and m2.get("interruption") is None
    assert list((d_ / "units").glob("validate__*.json"))
    assert not any(skill == "review-output" for skill, _ in again["claude"].calls)  # review not redone
    f = json.loads((d_ / "findings.json").read_text())[0]
    assert f["validation"]["status"] == "reproduced"


def test_low_disk_at_a_stage_start_pauses_before_it_runs(tmp_path, repo, config, monkeypatch):
    monkeypatch.setenv("QOT_ALLOW_LOCAL_WORKER", "1")
    free = {"v": 100 * GB}
    g = guard(FakeDocker(), disks=[DiskCheck("run directory", tmp_path, 8)], free=lambda p: free["v"], ttl_s=0)
    real_stage = pipeline._run_stage
    ran = []

    def stage(ctx, name):
        ran.append(name)
        real_stage(ctx, name)
        if name == "scan":
            free["v"] = 2 * GB  # something else fills the disk just after the scan

    monkeypatch.setattr(pipeline, "_run_stage", stage)
    s = pipeline.run(config, tmp_path / "run", [repo], stages=("pin", "deps", "scan", "review", "verify"),
                     adapters=two_models(), worker=GuardedLocal(g), log=lambda *_: None)
    m = json.loads((tmp_path / "run" / "test__m" / "manifest.json").read_text())
    assert s["stop_kind"] == "infrastructure" and m["interruption"]["cause"] == "disk"
    assert "review" not in ran and m["stages"]["review"]["status"] == "paused"


def test_cli_exits_4_on_an_infrastructure_stop(monkeypatch):
    from harness import __main__ as cli
    from harness.controller import config as config_mod

    monkeypatch.setattr(config_mod, "load_repos", lambda *_: [RepoSpec("a/b", "x")])
    monkeypatch.setattr(cli, "load_repos", lambda *_: [RepoSpec("a/b", "x")])
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: {"run_dir": "r", "repos": {}, "stopped": "infrastructure: x",
                                                          "stop_kind": "infrastructure"})
    assert cli.main(["run", "--run-dir", "unused"]) == 4
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: {"run_dir": "r", "repos": {}, "stopped": "usage limit: x",
                                                          "stop_kind": "usage_limit"})
    assert cli.main(["run", "--run-dir", "unused"]) == 3


def test_round_two_candidates_file_loads():
    from harness.controller.config import REPO_ROOT, load_repos
    round_one = {r.name for r in load_repos()}
    round_two = load_repos(REPO_ROOT / "config" / "repos-round2.yaml")
    assert len(round_two) == 21
    assert not round_one & {r.name for r in round_two}
    assert all(r.source == f"https://github.com/{r.name}.git" for r in round_two)
