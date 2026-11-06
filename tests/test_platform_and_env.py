"""A repository can run its workers as another platform; a failed install blocks code-running stages."""

from pathlib import Path
from types import SimpleNamespace

from harness.controller.config import RepoSpec
from harness.controller.ledger import Ledger
from harness.stages import deps
from harness.workers.docker import DockerWorker


def test_repo_spec_reads_the_worker_platform():
    s = RepoSpec.from_dict({"name": "o/r", "source": "x", "worker": {"platform": "linux/amd64"}})
    assert s.worker_platform == "linux/amd64"
    assert RepoSpec.from_dict({"name": "o/r", "source": "x"}).worker_platform is None


def test_platform_worker_uses_its_own_image_and_flag(tmp_path):
    w = DockerWorker(image="qot:dev")
    assert w.for_platform(None) is w
    x = w.for_platform("linux/amd64")
    cmd = x.command("true", tmp_path, inputs=None, network=False, writable_copy=True, name="n")
    assert cmd[1:4] == ["run", "--platform", "linux/amd64"] and "qot:dev-amd64" in cmd
    assert w.image == "qot:dev" and "--platform" not in w.command("true", tmp_path, inputs=None, network=False,
                                                                    writable_copy=True, name="n")
    assert x.base_image == "qot:dev"  # the registry proxy stays native


def test_a_failed_install_blocks_code_running_stages(tmp_path):
    ledger = Ledger(tmp_path)
    ctx = SimpleNamespace(spec=SimpleNamespace(name="o/r"), ledger=ledger)
    assert deps.environment_problem(ctx) is None
    ledger.unit("o/r", "deps", None, None).save("failed", {"status": "failed"})
    assert "failed to install" in deps.environment_problem(ctx)
    ledger.unit("o/r", "deps", None, None).save("done", {"status": "partial"})
    assert deps.environment_problem(ctx) is None
