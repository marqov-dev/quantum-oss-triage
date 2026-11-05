"""The test challenge: who attacks a test, and how verdicts become an outcome."""

import json
from types import SimpleNamespace

from harness.controller.ledger import Ledger
from harness.stages import challenge
from harness.controller.context import ModelCall

CITE = [{"file": "m.py", "line_start": 1, "line_end": 2, "says": "documents a - b"}]


def v(verdict, citations=()):
    return {"verdict": verdict, "problem": "none", "reason": "r", "citations": list(citations), "lines_read": []}


def test_outcome_rule():
    assert challenge.outcome([v("valid"), v("valid")])[0] == "upheld"
    assert challenge.outcome([v("valid"), v("invalid", CITE)])[0] == "refuted"
    # An invalid verdict without a citation does not refute; it counts as unsure.
    assert challenge.outcome([v("valid"), v("invalid")])[0] == "unsettled"
    assert challenge.outcome([v("valid"), v("unsure")])[0] == "unsettled"
    assert challenge.outcome([])[0] == "unsettled"
    # A weak control weakens the evidence but does not show the defect is false.
    weak = {**v("invalid", CITE), "problem": "weak_control"}
    assert challenge.outcome([v("valid"), weak])[0] == "unsettled"
    assert challenge.outcome([weak, v("invalid", CITE)])[0] == "refuted"


def _ctx(tmp_path, calls, fail=(), available=("claude", "codex", "antigravity")):
    run_dir = tmp_path / "run"
    repo = run_dir / "o__r"
    attempt = repo / "evidence" / "repro" / "QOT-1" / "1"
    attempt.mkdir(parents=True)
    (attempt / "test_qot_repro.py").write_text("def test_r(): assert 1 == 2\n")
    (attempt / "test_qot_control.py").write_text("def test_c(): assert 1 == 1\n")
    (attempt / "output.txt").write_text("QOT_CONTROL_RC=0\nQOT_REPRO_RC=1\n---REPRO---\nE   assert 1 == 2\n--- stderr ---\n")
    rp = {"expected_behaviour_source": "docs", "claimed_failure": "1 != 2", "test_code": "", "control_code": ""}
    (repo / "groups.json").write_text(json.dumps([{
        "id": "QOT-1", "verifications": [{"verifier": "codex", "reason": "SECRET-VERIFIER-REASON"}],
        "candidates": [{"tool": "claude", "title": "t", "area": "correctness", "file": "m.py", "line_start": 1,
                        "line_end": 1, "claim": "c", "evidence": "SECRET-FINDER-EVIDENCE", "why_it_matters": "w",
                        "proposed_severity": "high", "confidence": "high"}],
        "reproductions": [{"by": "antigravity", **rp}, {"by": "codex", **rp}]}]))
    (repo / "gates.json").write_text(json.dumps({"findings": [
        {"id": "QOT-1", "verdict": "passed", "evidence_ref": "o__r/evidence/repro/QOT-1/1"},
        {"id": "QOT-2", "verdict": "failed", "evidence_ref": None}]}))
    written = {}

    def call_model(stage, fid, model, skill, prompt, timeout):
        calls.append((stage, fid, model, prompt))
        if model in fail:
            return ModelCall(False, None, None, "u", "boom")
        return ModelCall(True, v("valid"), f"{model}-1", "u")

    ctx = SimpleNamespace(
        spec=SimpleNamespace(name="o/r"), commit="abc", run_dir=run_dir, ledger=Ledger(tmp_path),
        model_order=lambda: list(available),
        config=SimpleNamespace(models={"claude": {}, "codex": {}, "antigravity": {}}, parallel=1, timeouts={"verify_s": 1}),
        read_json=lambda n, d=None: json.loads((repo / n).read_text()) if (repo / n).exists() else d,
        write_json=lambda n, data: written.__setitem__(n, data), call_model=call_model,
        manifest=SimpleNamespace(incomplete=lambda *_: None, stage=lambda *a, **k: None))
    return ctx, written


def test_the_author_does_not_judge_and_challengers_are_blind(tmp_path):
    calls = []
    ctx, written = _ctx(tmp_path, calls)
    challenge.run(ctx)
    # Attempt 1 was written by codex, so the other two challenge it; QOT-2 failed the gates.
    assert sorted(m for _, _, m, _ in calls) == ["antigravity", "claude"]
    prompt = calls[0][3]
    assert "assert 1 == 2" in prompt and "SECRET-FINDER-EVIDENCE" not in prompt
    assert "SECRET-VERIFIER-REASON" not in prompt and "codex" not in prompt
    r = written["challenge.json"]["findings"][0]
    assert r["author"] == "codex" and r["outcome"] == "upheld"


def test_a_failed_challenge_leaves_the_test_unsettled(tmp_path):
    ctx, written = _ctx(tmp_path, [], fail=("claude",))
    challenge.run(ctx)
    assert written["challenge.json"]["findings"][0]["outcome"] == "unsettled"


def test_an_unavailable_challenger_leaves_the_test_unsettled(tmp_path):
    calls = []
    ctx, written = _ctx(tmp_path, calls, available=("codex", "antigravity"))
    challenge.run(ctx)
    r = written["challenge.json"]["findings"][0]
    assert [m for _, _, m, _ in calls] == ["antigravity"] and r["outcome"] == "unsettled"


def test_an_unavailable_challenger_keeps_its_earlier_verdict(tmp_path):
    calls = []
    ctx, written = _ctx(tmp_path, calls, available=("codex", "antigravity"))
    ctx.ledger.unit("o/r", "challenge", "QOT-1", "claude").save("done", v("valid"))
    challenge.run(ctx)
    assert written["challenge.json"]["findings"][0]["outcome"] == "upheld"
