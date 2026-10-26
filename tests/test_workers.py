import subprocess

import pytest

from harness.workers.docker import DockerWorker
from harness.workers.local import LocalWorker


def test_docker_command_is_locked_down(tmp_path):
    cmd = DockerWorker().command("echo hi", tmp_path, inputs=None, network=False, writable_copy=True, name="n")
    joined = " ".join(cmd)
    for flag in ("--network none", "--read-only", "--cap-drop ALL", "no-new-privileges", "--pids-limit",
                 "--memory 2g", "--cpus 2", "--user 65534:65534", f"{tmp_path.resolve()}:/src:ro"):
        assert flag in joined, flag
    assert "docker.sock" not in joined
    # Only harness variables are passed; nothing from the host environment.
    envs = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-e"]
    assert {e.split("=")[0] for e in envs} == {"HOME", "QOT_COPY", "QOT_CWD"}
    assert "--env-file" not in cmd


def test_network_only_when_asked(tmp_path):
    cmd = DockerWorker().command("x", tmp_path, inputs=None, network=True, writable_copy=False, name="n")
    assert cmd[cmd.index("--network") + 1] == "bridge"


def test_local_worker_refuses_without_opt_in(tmp_path, monkeypatch):
    monkeypatch.delenv("QOT_ALLOW_LOCAL_WORKER", raising=False)
    with pytest.raises(RuntimeError):
        LocalWorker().run("true", tmp_path)


def _docker_ready():
    ok, _ = DockerWorker().available()
    return ok


docker = pytest.mark.skipif(not _docker_ready(), reason="worker image not built")


@pytest.mark.docker
@docker
def test_container_has_no_network_no_host_env_and_readonly_src(tmp_path, monkeypatch):
    monkeypatch.setenv("QOT_SECRET_CANARY", "should-not-appear")
    (tmp_path / "f.txt").write_text("data")
    r = DockerWorker().run(
        "env; echo ---; (touch /src/x 2>&1 || true); echo ---; "
        "python -c \"import socket; socket.create_connection(('1.1.1.1', 53), 3)\" 2>&1 | tail -n1; "
        "echo ---; touch /work/ok && echo work-writable; id -u; ls /var/run/docker.sock 2>&1",
        tmp_path, timeout_s=120)
    out = r.stdout
    assert "should-not-appear" not in out
    assert "Read-only file system" in out
    assert "Network is unreachable" in out or "OSError" in out
    assert "work-writable" in out and "65534" in out
    assert "No such file" in out


@pytest.mark.docker
@docker
def test_container_output_is_capped(tmp_path):
    r = DockerWorker().run("head -c 7000000 /dev/zero | tr '\\0' a", tmp_path, timeout_s=120)
    assert r.truncated and len(r.stdout) <= 5 * 1024 * 1024


@pytest.mark.docker
@docker
def test_container_timeout_kills(tmp_path):
    r = DockerWorker().run("sleep 60", tmp_path, timeout_s=5)
    assert r.timed_out
    left = subprocess.run(["docker", "ps", "-q", "--filter", "name=qot-"], capture_output=True, text=True).stdout
    assert left.strip() == ""
