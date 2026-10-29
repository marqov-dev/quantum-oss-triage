"""Regression tests for defects found in the independent review of v0.1."""

import json
import os

from harness import secrets
from harness.adapters import CodexAdapter
from harness.adapters.base import Invocation
from harness.adapters.claude import ClaudeAdapter
from harness.controller import cleanenv, merge, pipeline, snapshot
from harness.controller.config import Config
from harness.scanners import Bandit
from harness.stages.validate import judge


def test_symlinked_include_root_cannot_pull_in_host_files(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("host file")
    src = tmp_path / "src"
    src.mkdir()
    (src / "ok.py").write_text("x = 1\n")
    os.symlink(outside, src / "docs")
    os.symlink(outside / "secret.txt", src / "link.txt")
    review = snapshot.review_copy(src, tmp_path / "review", include=["docs", "ok.py"])
    assert sorted(p.name for p in review.rglob("*")) == ["ok.py"]
    review2 = snapshot.review_copy(src, tmp_path / "review2")
    assert "host file" not in "".join(p.read_text() for p in review2.rglob("*") if p.is_file())


def test_shell_on_host_adapters_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(cleanenv, "CONFIG_ROOT", tmp_path)
    fake = tmp_path / "codex"
    fake.write_text("#!/bin/sh\necho codex 1.0\n")
    fake.chmod(0o755)
    cfg = Config(models={"codex": {"binary": str(fake), "sandbox": False}}, review_skills=[], worker={}, timeouts={})
    usable, rows = pipeline.build_adapters(cfg, require_attestation=False)
    assert usable == {} and "runs shell commands on the host" in rows[0]["reason"]
    assert CodexAdapter(sandbox=False).runs_shell_on_host and not ClaudeAdapter().runs_shell_on_host
    # The default is the reviewer sandbox, which is not "on the host".
    assert not CodexAdapter().runs_shell_on_host


def test_bandit_password_text_is_redacted():
    doc = {"results": [{"test_id": "B105", "issue_severity": "MEDIUM", "issue_confidence": "MEDIUM",
                        "filename": "./a.py", "line_number": 3, "code": "3 PASSWORD = 'hunter2hunter2'\n",
                        "issue_text": "Possible hardcoded password: 'hunter2hunter2'"}]}
    r = Bandit().parse(json.dumps(doc), "", 0)
    assert "hunter2" not in json.dumps(r.findings) + r.raw


def test_secret_redaction_in_model_text():
    c = {"title": "Token committed", "claim": 'DEFAULT_TOKEN = "qtk_live_7Hq2Vx9Lm4Rt8Wz1Np6Ks3Df5Gb0Jc2Ye"', "evidence": "",
         "why_it_matters": "", "tool": "claude"}
    assert "7Hq2" not in json.dumps(merge.redact_candidate(c))
    assert secrets.redact('api_key = "abcdefgh12345678"') == 'api_key = "REDACTED"'


def test_reproduction_needs_an_assertion_failure():
    base = "QOT_CONTROL_RC=0\nQOT_REPRO_RC=1\n---CONTROL---\n1 passed\n---REPRO---\n"
    assert judge(base + "E       assert -1 == 5\n1 failed", False)[0] == "reproduced"
    assert judge(base + "E       TypeError: add() got an unexpected keyword\n1 failed", False)[0] == "blocked"
    assert judge(base + "ModuleNotFoundError: No module named 'x'", False)[0] == "blocked"
    assert judge("QOT_CONTROL_RC=1\nQOT_REPRO_RC=1\n---REPRO---\nAssertionError", False)[0] == "blocked"


def test_distinct_claims_on_one_line_get_distinct_ids(tmp_path):
    from harness.stages import verify

    (tmp_path / "a.py").write_text("subprocess.call(cmd, shell=True)\n")
    a = {"title": "Bandit B602", "area": "security", "file": "a.py", "line_start": 1, "line_end": 1, "claim": "x",
         "tool": "bandit", "rule_id": "B602", "unit": "u1"}
    b = {**a, "title": "Bandit B604", "rule_id": "B604", "unit": "u1"}

    class Ctx:
        spec = type("S", (), {"name": "r"})()
        source_dir = tmp_path

        def model_order(self):
            return []

    plans = verify.plan(Ctx(), merge.group([a, b]))
    assert len(plans) == 2 and plans[0]["id"] != plans[1]["id"]


def test_different_bugs_on_same_lines_from_two_models_stay_apart():
    a = {"title": "off-by-one in loop bound", "claim": "range stops one short", "area": "correctness", "file": "q.py",
         "line_start": 5, "line_end": 6, "tool": "claude", "unit": "u1"}
    b = {"title": "qubit order reversed in key", "claim": "endianness mismatch with docs", "area": "quantum",
         "file": "q.py", "line_start": 5, "line_end": 6, "tool": "codex", "unit": "u2"}
    assert len(merge.group([a, b])) == 2


def test_usage_limit_not_triggered_by_quoted_repository_text(tmp_path):
    a = ClaudeAdapter(binary="claude", config_dir="default")
    inv = Invocation(1, "the repo says: rate limit 429 quota", "", False, 0.1)
    parsed = a.parse(inv)
    from harness.adapters import base
    assert parsed.failed_call and "429" not in parsed.error
    assert not base.USAGE_LIMIT_PATTERNS.search(parsed.error or inv.stderr)


def test_stored_units_redact_secrets_without_breaking_json(tmp_path):
    from harness.controller.ledger import Ledger

    u = Ledger(tmp_path).unit("r", "review", "s", "claude")
    u.save("done", {"evidence": 'DEFAULT_TOKEN = "qtk_live_7Hq2Vx9Lm4Rt8Wz1Np6Ks3Df5Gb0Jc2Ye"'})
    text = u.path.read_text()
    assert "7Hq2" not in text
    assert json.loads(text)["payload"]["evidence"] == 'DEFAULT_TOKEN = "REDACTED"'


def test_fix_check_runs_existing_tests_when_only_tests_folder_exists(tmp_path):
    import subprocess

    from harness.stages.fix import worker_script

    (tmp_path / "tests").mkdir()
    script = worker_script(False).split("; ", 0)[0]
    probe = script[script.index("if [ -d tests ]"):].replace("python -m pytest", "echo RAN #")
    out = subprocess.run(["sh", "-c", probe], cwd=tmp_path, capture_output=True, text=True).stdout
    assert "QOT_TESTS_RC=none" not in out
