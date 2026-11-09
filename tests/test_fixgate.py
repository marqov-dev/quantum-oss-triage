"""The separate-fix gate: blind fixers, how a fix is checked, and how attempts become an outcome."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from harness.controller.context import ModelCall
from harness.controller.ledger import Ledger
from harness.stages import fixgate
from harness.workers.base import WorkerResult
from harness.workers.local import LocalWorker


def a(status, holds="yes"):
    return {"status": status, "claim_holds": holds}


def test_outcome_rule():
    assert fixgate.outcome([a("passes"), a("still_fails")])[0] == "confirmed"
    assert fixgate.outcome([a("passes"), a("passes")])[1].startswith("2 of 2")
    # A dissenting fixer is named in the reason, but one passing fix still confirms.
    r = fixgate.outcome([a("passes"), a("not_a_defect", "no")])
    assert r[0] == "confirmed" and "judged the claim not to hold" in r[1]
    assert fixgate.outcome([a("not_a_defect", "no"), a("not_a_defect", "no")])[0] == "disputed"
    assert fixgate.outcome([a("still_fails"), a("not_a_defect", "no")])[0] == "not_confirmed"
    assert fixgate.outcome([a("regressed"), a("not_feasible", "unsure")])[0] == "not_confirmed"
    # A fix that could not be run leaves the test unsettled, never not_confirmed.
    assert fixgate.outcome([a("still_fails"), a("failed", None)])[0] == "unsettled"
    assert fixgate.outcome([a("still_fails"), a("timed_out")])[0] == "unsettled"
    assert fixgate.outcome([])[0] == "unsettled"


def test_test_paths_and_targets():
    for p in ("tests/test_a.py", "mitiq/zne/tests/helpers.py", "test/x.py", "pkg/test_a.py", "pkg/a_test.py"):
        assert fixgate.is_test_path(p), p
    for p in ("mitiq/zne/inference.py", "contest.py", "pkg/testing.py", "docs/tests.md"):
        assert not fixgate.is_test_path(p), p
    assert fixgate.targets(["mitiq/zne/inference.py", "mitiq/zne/scaling/folding.py", "mitiq/pec/pec.py"]) == \
        ["mitiq/pec", "mitiq/zne"]
    assert fixgate.targets(["setup.py", "mitiq/zne/x.py"]) == ["."]
    assert fixgate.targets(["docs/index.md"]) == []


OUT = """QOT_BEFORE FAILED t/test_a.py::test_old
QOT_APPLY_RC=0
QOT_CONTROL_RC={c}
QOT_REPRO_RC={r}
QOT_AFTER FAILED t/test_a.py::test_old
{extra}"""


def test_judge_attempt():
    j = fixgate.judge_attempt
    assert j(OUT.format(c=0, r=0, extra=""), False)["status"] == "passes"
    assert j(OUT.format(c=0, r=1, extra=""), False)["status"] == "still_fails"
    assert j(OUT.format(c=1, r=0, extra=""), False)["status"] == "control_broken"
    got = j(OUT.format(c=0, r=0, extra="QOT_AFTER ERROR t/test_b.py"), False)
    assert got["status"] == "regressed" and got["new_failures"] == ["ERROR t/test_b.py"]
    assert j("QOT_APPLY_RC=1\nerror: patch failed", False)["status"] == "apply_failed"
    assert j("", True)["status"] == "timed_out"


def test_check_script_in_a_real_worker(tmp_path, monkeypatch):
    """The script compares test ids before and after the fix, and runs the hidden test with the fix applied."""
    monkeypatch.setenv("QOT_ALLOW_LOCAL_WORKER", "1")
    src = tmp_path / "src"
    (src / "pkg" / "tests").mkdir(parents=True)
    (src / "pkg" / "m.py").write_text("def add(a, b):\n    return a - b\n\ndef one():\n    return 1\n")
    (src / "pkg" / "tests" / "test_m.py").write_text(
        "import sys, os\nsys.path.insert(0, os.getcwd())\nfrom pkg.m import one\n\ndef test_one():\n    assert one() == 1\n")
    subprocess.run(["git", "init", "-q"], cwd=src, check=True)
    subprocess.run(["git", "add", "."], cwd=src, check=True)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "test_qot_repro.py").write_text(
        "import sys, os\nsys.path.insert(0, os.getcwd())\nfrom pkg.m import add\n\ndef test_r():\n    assert add(2, 3) == 5\n")
    (inputs / "test_qot_control.py").write_text("def test_c():\n    assert True\n")

    def diff(new_m):
        subprocess.run(["git", "checkout", "-q", "--", "."], cwd=src, check=True)
        (src / "pkg" / "m.py").write_text(new_m)
        d = subprocess.run(["git", "diff"], cwd=src, capture_output=True, text=True, check=True).stdout
        subprocess.run(["git", "checkout", "-q", "--", "."], cwd=src, check=True)
        return d

    w = LocalWorker()
    (inputs / "fix.diff").write_text(diff("def add(a, b):\n    return a + b\n\ndef one():\n    return 1\n"))
    r = w.run(fixgate.check_script(["pkg"]), src, inputs=inputs, timeout_s=120)
    assert fixgate.judge_attempt(r.stdout, r.timed_out)["status"] == "passes", r.stdout + r.stderr
    # Fixing add but breaking one(): the hidden test passes, an existing test newly fails.
    (inputs / "fix.diff").write_text(diff("def add(a, b):\n    return a + b\n\ndef one():\n    return 2\n"))
    r = w.run(fixgate.check_script(["pkg"]), src, inputs=inputs, timeout_s=120)
    got = fixgate.judge_attempt(r.stdout, r.timed_out)
    assert got["status"] == "regressed" and got["new_failures"] == ["FAILED pkg/tests/test_m.py::test_one"], r.stdout


def _ctx(tmp_path, reply, available=("claude", "codex", "antigravity"), worker_out=None):
    run_dir = tmp_path / "run"
    repo = run_dir / "o__r"
    src = repo / "source"
    src.mkdir(parents=True)
    (src / "m.py").write_text("def add(a, b):\n    return a - b\n")
    subprocess.run(["git", "init", "-q"], cwd=src, check=True)
    subprocess.run(["git", "add", "."], cwd=src, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i"], cwd=src, check=True)
    attempt = repo / "evidence" / "repro" / "QOT-1" / "1"
    attempt.mkdir(parents=True)
    (attempt / "test_qot_repro.py").write_text("def test_r(): assert HIDDEN_TEST_BODY\n")
    (attempt / "test_qot_control.py").write_text("def test_c(): assert 1 == 1\n")
    (repo / "groups.json").write_text(json.dumps([{
        "id": "QOT-1", "verifications": [{"verifier": "codex", "reason": "SECRET-VERIFIER-REASON"}],
        "candidates": [{"tool": "claude", "title": "t", "area": "correctness", "file": "m.py", "line_start": 1,
                        "line_end": 2, "claim": "add subtracts", "evidence": "SECRET-FINDER-EVIDENCE",
                        "why_it_matters": "w", "proposed_severity": "high", "confidence": "high"}],
        "reproductions": [{"by": "antigravity"}, {"by": "codex", "claimed_failure": "SECRET-CLAIMED-FAILURE"}]}]))
    (repo / "gates.json").write_text(json.dumps({"findings": [
        {"id": "QOT-1", "verdict": "passed", "evidence_ref": "o__r/evidence/repro/QOT-1/1"},
        {"id": "QOT-2", "verdict": "failed", "evidence_ref": None}]}))
    (repo / "challenge.json").write_text(json.dumps({"findings": [
        {"id": "QOT-1", "outcome": "refuted", "reason": "SECRET-CHALLENGE-REASON"}]}))
    calls, runs, written = [], [], {}

    def call_model(stage, fid, model, skill, prompt, timeout, inputs=None):
        calls.append((fid, model, prompt))
        out = reply(model, fid)
        return ModelCall(True, out, f"{model}-1", "u") if out is not None else ModelCall(False, None, None, "u", "boom")

    def run(script, s, inputs=None, timeout_s=0, **kw):
        runs.append((script, inputs))
        assert not (inputs / "test_qot_repro.py").read_text() == "" and (inputs / "fix.diff").exists()
        return WorkerResult(0, worker_out or OUT.format(c=0, r=0, extra=""), "")

    ctx = SimpleNamespace(
        spec=SimpleNamespace(name="o/r", tests_timeout_s=None), commit="abc", run_dir=run_dir, repo_dir=repo,
        source_dir=src, ledger=Ledger(tmp_path), model_order=lambda: list(available),
        worker=SimpleNamespace(available=lambda: (True, ""), run=run),
        config=SimpleNamespace(models={"claude": {}, "codex": {}, "antigravity": {}}, parallel=1,
                               timeouts={"fix_s": 1}),
        read_json=lambda n, d=None: json.loads((repo / n).read_text()) if (repo / n).exists() else d,
        write_json=lambda n, data: written.__setitem__(n, data), call_model=call_model, log=lambda *_: None,
        manifest=SimpleNamespace(incomplete=lambda *_: None, stage=lambda *a, **k: None))
    return ctx, calls, runs, written


FIX = [{"path": "m.py", "old": "return a - b", "new": "return a + b"}]


def fix(edits=FIX, holds="yes"):
    return {"claim_holds": holds, "feasible": bool(edits), "edits": edits, "summary": "s", "notes": "n"}


def test_both_non_authors_fix_blind_and_refuted_tests_are_included(tmp_path):
    ctx, calls, runs, written = _ctx(tmp_path, lambda m, fid: fix())
    fixgate.run(ctx)
    # codex wrote attempt 1, so claude and antigravity fix it; QOT-2 failed the gates.
    assert sorted(m for _, m, _ in calls) == ["antigravity", "claude"]
    for _, _, prompt in calls:
        assert "add subtracts" in prompt
        for secret in ("HIDDEN_TEST_BODY", "SECRET-FINDER-EVIDENCE", "SECRET-VERIFIER-REASON",
                       "SECRET-CLAIMED-FAILURE", "SECRET-CHALLENGE-REASON", "refuted", "codex"):
            assert secret not in prompt, secret
    assert len(runs) == 2
    assert "pytest -rfE ." in runs[0][0].replace("-q -p no:cacheprovider -o addopts= --no-header ", "")
    r = written["fixgate.json"]["findings"][0]
    assert r["challenge"] == "refuted" and r["outcome"] == "confirmed" and r["author"] == "codex"
    assert {x["fixer"] for x in r["attempts"]} == {"claude", "antigravity"}
    assert all(x["status"] == "passes" and x["files_changed"] == ["m.py"] for x in r["attempts"])


def test_a_fixer_that_says_not_a_defect_writes_no_fix(tmp_path):
    ctx, _, runs, written = _ctx(tmp_path, lambda m, fid: fix([], holds="no"))
    fixgate.run(ctx)
    assert runs == []
    assert written["fixgate.json"]["findings"][0]["outcome"] == "disputed"


def test_edits_to_tests_are_refused_then_retried(tmp_path):
    bad = [{"path": "tests/test_m.py", "old": "", "new": "def test_x(): pass\n"}]

    def reply(model, fid):
        return fix() if fid.endswith("-retry") else fix(bad)

    ctx, calls, runs, written = _ctx(tmp_path, reply)
    fixgate.run(ctx)
    retries = [p for fid, _, p in calls if fid.endswith("-retry")]
    assert len(retries) == 2 and all("tests/test_m.py" in p for p in retries)
    assert written["fixgate.json"]["findings"][0]["outcome"] == "confirmed"


def test_unavailable_or_failed_fixers_leave_it_unsettled(tmp_path):
    ctx, calls, _, written = _ctx(tmp_path, lambda m, fid: None if m == "claude" else fix(),
                                  available=("claude", "codex", "antigravity"), worker_out=OUT.format(c=0, r=1, extra=""))
    fixgate.run(ctx)
    r = written["fixgate.json"]["findings"][0]
    assert r["outcome"] == "unsettled"
    ctx, calls, _, written = _ctx(tmp_path / "b", lambda m, fid: fix(), available=("codex", "antigravity"),
                                  worker_out=OUT.format(c=0, r=1, extra=""))
    fixgate.run(ctx)
    assert [m for _, m, _ in calls] == ["antigravity"]
    assert written["fixgate.json"]["findings"][0]["outcome"] == "unsettled"


def test_a_checked_attempt_is_not_rerun(tmp_path):
    ctx, _, runs, _ = _ctx(tmp_path, lambda m, fid: fix())
    fixgate.run(ctx)
    fixgate.run(ctx)
    assert len(runs) == 2


def test_a_changed_test_is_checked_again(tmp_path):
    ctx, _, runs, _ = _ctx(tmp_path, lambda m, fid: fix())
    fixgate.run(ctx)
    test = ctx.repo_dir / "evidence" / "repro" / "QOT-1" / "1" / "test_qot_repro.py"
    test.write_text("def test_r(): assert A_DIFFERENT_TEST\n")
    fixgate.run(ctx)
    assert len(runs) == 4  # both fixes, checked against the new test
