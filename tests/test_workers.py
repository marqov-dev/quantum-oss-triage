import re
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
def test_writable_copy_leaves_git_objects_in_place_but_git_works(tmp_path):
    # A large .git once overflowed the 1 GB /work and every test reported "No space left".
    g = ["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / ".hidden").write_text("h")
    subprocess.run(g + ["add", "-A"], check=True)
    subprocess.run(g + ["commit", "-qm", "c"], check=True)
    subprocess.run(g + ["gc", "-q"], check=True)  # objects now live in a pack under .git/objects/pack
    head = subprocess.run(g + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    r = DockerWorker().run(
        "cat a.py .hidden; echo; git rev-parse HEAD; git status --porcelain | wc -l; "
        "ls .git/objects/pack | wc -l; cat .git/objects/info/alternates; git show -s --format=%s HEAD",
        tmp_path, timeout_s=120)
    assert r.exit_code == 0, r.stderr
    lines = r.stdout.split()
    assert lines[:3] == ["x", "=", "1"] and "h" in lines
    assert head in lines                       # git reads history from the original
    assert lines[lines.index(head) + 1] == "0"  # the copy is clean
    assert lines[lines.index(head) + 2] == "0"  # no pack files copied
    assert "/src/.git/objects" in lines and lines[-1] == "c"


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
    # Worker containers only (qot-<12 hex>); a reviewer sandbox may be running alongside.
    names = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True).stdout.split()
    assert [n for n in names if re.fullmatch(r"qot-[0-9a-f]{12}", n)] == []
