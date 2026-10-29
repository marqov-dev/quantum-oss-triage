import json
import os
import subprocess

import pytest
import yaml

from harness.controller import pipeline, schema
from harness.controller.config import Config, RepoSpec
from harness.workers.local import LocalWorker
from tests.fakes.adapters import FakeAdapter, finding

REPRO = {
    "expected_behaviour_source": "the function name and docstring",
    "claimed_failure": "add(2, 3) returns -1",
    "test_code": "import sys, os\nsys.path.insert(0, os.getcwd())\nfrom m import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    "control_code": "import sys, os\nsys.path.insert(0, os.getcwd())\nfrom m import add\n\ndef test_zero():\n    assert add(0, 0) == 0\n",
}
FIX = [{"path": "m.py", "old": "    return a - b\n", "new": "    return a + b\n"}]


@pytest.fixture
def repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "m.py").write_text('def add(a, b):\n    """Return a + b."""\n    return a - b\n')
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", *args], cwd=src, env=env, check=True)
    return RepoSpec("test/m", str(src))


@pytest.fixture
def config():
    return Config(models={"claude": {}, "codex": {}}, review_skills=["review-correctness", "review-security"],
                  worker={"image": "none"}, timeouts={"review_s": 10, "verify_s": 10, "fix_s": 10}, parallel=1,
                  reviewer="Test Reviewer")


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.setenv("QOT_ALLOW_LOCAL_WORKER", "1")
    return LocalWorker()


def two_models(**claude_kw):
    # Claude is first in the configured order, so it proposes fixes; codex verifies.
    return {"claude": FakeAdapter("claude", reviews={"review-correctness": [finding()]}, fix_edits=FIX, **claude_kw),
            "codex": FakeAdapter("codex", reproduction=REPRO)}


def test_end_to_end_with_fakes(tmp_path, repo, config, worker):
    fakes = two_models()
    summary = pipeline.run(config, tmp_path / "run", [repo], adapters=fakes, worker=worker, log=lambda *_: None)
    d = tmp_path / "run" / "test__m"
    findings = json.loads((d / "findings.json").read_text())
    assert len(findings) == 1
    f = findings[0]
    assert schema.validate("finding", f) == []
    assert f["corroboration"]["verifications"][0]["verifier"] == "codex"
    assert f["corroboration"]["status"] == "confirmed"
    assert f["validation"]["status"] == "reproduced", f["validation"]
    assert f["disposition"]["queue"] == "main" and f["disposition"]["decision"] == "pending"
    assert f["severity"]["final"] is None  # a person sets it
    assert (d / "triage.md").exists() and (d / "decisions.yaml").exists()
    manifest = json.loads((d / "manifest.json").read_text())
    assert schema.validate("run", manifest) == []
    assert manifest["tokens"]["claude"]["units"] >= 2
    # Scanners are recorded as unavailable (no worker image), never as a pass.
    assert all(s["status"] in ("unavailable", "not_applicable") for s in manifest["scanners"])
    assert summary["repos"]["test/m"]["status"] == "incomplete"


def test_resume_skips_completed_units(tmp_path, repo, config, worker):
    pipeline.run(config, tmp_path / "run", [repo], adapters=two_models(), worker=worker, log=lambda *_: None)
    again = two_models()
    pipeline.run(config, tmp_path / "run", [repo], adapters=again, worker=worker, log=lambda *_: None)
    assert again["claude"].calls == [] and again["codex"].calls == []


def test_usage_limit_pauses_repo_and_resumes(tmp_path, repo, config, worker):
    limited = two_models(limit_after=1)
    other = RepoSpec("test/next", repo.source)
    s = pipeline.run(config, tmp_path / "run", [repo, other], adapters=limited, worker=worker, log=lambda *_: None)
    assert s["stopped"] and s["repos"]["test/m"]["status"] == "paused"
    assert "test/next" not in s["repos"]  # one repository at a time
    resumed = two_models()
    s2 = pipeline.run(config, tmp_path / "run", [repo], adapters=resumed, worker=worker, log=lambda *_: None)
    assert not s2["stopped"]
    # The unit that finished before the limit is not repeated.
    assert len(resumed["claude"].calls) < len(limited["claude"].calls) + 3


def test_units_refused_for_capacity_run_again_on_resume(tmp_path, repo, config, worker):
    busy = {"claude": two_models()["claude"], "codex": FakeAdapter("codex", reproduction=REPRO, capacity_refused=True)}
    s = pipeline.run(config, tmp_path / "run", [repo], adapters=busy, worker=worker, log=lambda *_: None)
    assert not s["stopped"]  # not a usage limit: the run carries on
    manifest = json.loads((tmp_path / "run" / "test__m" / "manifest.json").read_text())
    assert any("at capacity" in f["error"] for f in manifest["failures"])
    again = two_models()
    pipeline.run(config, tmp_path / "run", [repo], adapters=again, worker=worker, log=lambda *_: None)
    assert again["codex"].calls and again["claude"].calls == []  # only the refused units are repeated
    manifest = json.loads((tmp_path / "run" / "test__m" / "manifest.json").read_text())
    assert not any("at capacity" in f["error"] for f in manifest["failures"])


def test_single_model_self_check_does_not_reach_main_queue(tmp_path, repo, config, worker):
    config.models = {"claude": {}}
    only = {"claude": FakeAdapter("claude", reviews={"review-correctness": [finding()]})}
    pipeline.run(config, tmp_path / "run", [repo], adapters=only, worker=worker, log=lambda *_: None)
    f = json.loads((tmp_path / "run" / "test__m" / "findings.json").read_text())[0]
    assert f["corroboration"]["verifications"][0]["independence"] == "same_model"
    assert f["disposition"]["queue"] == "low"


def test_refuted_finding_goes_to_low_queue(tmp_path, repo, config, worker):
    fakes = {"claude": FakeAdapter("claude", reviews={"review-correctness": [finding()]}),
             "codex": FakeAdapter("codex", verdict="refute")}
    pipeline.run(config, tmp_path / "run", [repo], adapters=fakes, worker=worker, log=lambda *_: None)
    f = json.loads((tmp_path / "run" / "test__m" / "findings.json").read_text())[0]
    assert f["corroboration"]["status"] == "refuted" and f["disposition"]["queue"] == "low"


def test_fix_only_after_acceptance(tmp_path, repo, config, worker):
    run_dir = tmp_path / "run"
    fakes = two_models()
    pipeline.run(config, run_dir, [repo], adapters=fakes, worker=worker, log=lambda *_: None)
    d = run_dir / "test__m"
    assert json.loads((d / "findings.json").read_text())[0]["fix"] is None  # not accepted yet
    doc = yaml.safe_load((d / "decisions.yaml").read_text())
    fid = next(iter(doc["findings"]))
    doc["findings"][fid].update(decision="accept", severity="high")
    (d / "decisions.yaml").write_text(yaml.safe_dump(doc))
    pipeline.run(config, run_dir, [repo], stages=("pin", "triage", "fix"), adapters=two_models(), worker=worker,
                 log=lambda *_: None)
    f = json.loads((d / "findings.json").read_text())[0]
    assert f["disposition"] == {**f["disposition"], "decision": "accept", "decided_by": "Test Reviewer"}
    assert f["severity"]["final"] == "high"
    fx = f["fix"]
    assert fx["worker_check"]["applied"] and fx["worker_check"]["repro_passes"], fx
    assert fx["status"] == "validated"
    assert fx["delivery"] == {"kind": "fork_branch", "branch": f"review/2026-10/{fid}",
                              "status": "awaiting explicit approval to publish", "pushed": False}


def test_behaviour_change_objection_is_kept_as_a_caveat(tmp_path, repo, config, worker):
    run_dir = tmp_path / "run"
    pipeline.run(config, run_dir, [repo], adapters=two_models(), worker=worker, log=lambda *_: None)
    d = run_dir / "test__m"
    doc = yaml.safe_load((d / "decisions.yaml").read_text())
    fid = next(iter(doc["findings"]))
    doc["findings"][fid].update(decision="accept", severity="high")
    (d / "decisions.yaml").write_text(yaml.safe_dump(doc))
    wire = "Existing pickle-encoded results become unreadable."
    objector = {"claude": two_models()["claude"],
                "codex": FakeAdapter("codex", reproduction=REPRO, verdict="refute",
                                     fix_assessment={"fixes_cause": "yes", "keeps_behaviour": "no",
                                                     "regression_risk": wire})}
    pipeline.run(config, run_dir, [repo], stages=("pin", "triage", "fix"), adapters=objector, worker=worker,
                 log=lambda *_: None)
    fx = json.loads((d / "findings.json").read_text())[0]["fix"]
    assert fx["status"] == "pending_objections" and fx["caveats"] == [{"by": "codex", "text": wire}]


def test_build_adapters_records_missing_and_unattested(tmp_path, monkeypatch):
    from harness.controller import cleanenv

    monkeypatch.setattr(cleanenv, "CONFIG_ROOT", tmp_path)
    cfg = Config(models={"claude": {"binary": "definitely-missing-qot"}, "codex": {"sandbox": {"docker": "definitely-missing-qot"}}},
                 review_skills=[], worker={}, timeouts={})
    usable, rows = pipeline.build_adapters(cfg)
    assert usable == {}
    assert all(not r["available"] and "not installed" in r["reason"] for r in rows)


def test_unattested_cli_is_refused(tmp_path, monkeypatch):
    from harness.controller import cleanenv

    monkeypatch.setattr(cleanenv, "CONFIG_ROOT", tmp_path)
    fake_bin = tmp_path / "claude"
    fake_bin.write_text("#!/bin/sh\necho '9.9.9 (Claude Code)'\n")
    fake_bin.chmod(0o755)
    cfg = Config(models={"claude": {"binary": str(fake_bin), "config_dir": "default"}}, review_skills=[], worker={}, timeouts={})
    usable, rows = pipeline.build_adapters(cfg)
    assert usable == {} and "isolation not verified" in rows[0]["reason"]
    usable, _ = pipeline.build_adapters(cfg, require_attestation=False)
    assert "claude" in usable


def test_fix_edits_must_match_exactly_once_and_stay_inside(tmp_path, repo, config, worker):
    from harness.stages import fix as fix_stage

    run_dir = tmp_path / "run"
    pipeline.run(config, run_dir, [repo], stages=("pin",), adapters=two_models(), worker=worker, log=lambda *_: None)
    from harness.controller.context import RepoContext
    from harness.controller.ledger import Ledger
    from harness.controller.manifest import Manifest

    m = Manifest.open(run_dir / repo.slug / "manifest.json", run_id="r", repo={})
    ctx = RepoContext(repo, "r", run_dir, config, Ledger(run_dir), m, worker, {})
    diff = fix_stage.build_diff(ctx, "QOT-x", FIX + [{"path": "tests/test_m.py", "old": "", "new": "def test_a():\n    pass\n"}])
    assert "-    return a - b" in diff and "+    return a + b" in diff and "b/tests/test_m.py" in diff
    for bad in ([{"path": "m.py", "old": "nope", "new": "x"}],
                [{"path": "../escape.py", "old": "", "new": "x"}],
                [{"path": ".git/config", "old": "", "new": "x"}],
                [{"path": "m.py", "old": "a", "new": "b"}]):  # 'a' occurs several times
        with pytest.raises(fix_stage.EditError):
            fix_stage.build_diff(ctx, "QOT-x", bad)
    assert not (tmp_path / "escape.py").exists()
