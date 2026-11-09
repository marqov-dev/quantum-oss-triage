"""A saved validation stands only for the reproductions it saw.

A model that joins later (one that was out of quota, or whose sandbox was down)
can propose a test for a group that was already validated without one. That
test must run; the earlier "no reproduction was proposed" result must not hide it.
"""

from types import SimpleNamespace

from harness.controller.ledger import Ledger
from harness.stages import validate
from harness.workers.base import WorkerResult

PASSING_REPRO = "QOT_CONTROL_RC=0\nQOT_REPRO_RC=1\n---REPRO---\nE   assert 1 == 2\n"
NOT_REPRODUCED = "QOT_CONTROL_RC=0\nQOT_REPRO_RC=0\n"


class Worker:
    def __init__(self, out=PASSING_REPRO):
        self.out, self.runs = out, 0

    def available(self):
        return True, "ok"

    def run(self, script, src, inputs=None, timeout_s=0):
        self.runs += 1
        return WorkerResult(0, self.out, "")


def ctx(tmp_path, worker):
    run_dir = tmp_path / "run"
    return SimpleNamespace(spec=SimpleNamespace(name="o/r"), ledger=Ledger(tmp_path), worker=worker,
                           run_dir=run_dir, repo_dir=run_dir / "o__r", source_dir=tmp_path / "src")


def rp(by, code="def test_r(): assert 1 == 2\n"):
    return {"by": by, "independence": "independent", "test_code": code, "control_code": "def test_c(): pass\n",
            "expected_behaviour_source": "docs", "claimed_failure": "1 != 2"}


def group(*reproductions):
    return {"id": "QOT-1", "verifications": [{"verdict": "confirmed"}],
            "candidates": [{"area": "correctness"}], "reproductions": list(reproductions)}


def test_unchanged_inputs_reuse_the_saved_result(tmp_path):
    w = Worker()
    c = ctx(tmp_path, w)
    assert validate.validate_group(c, group(rp("claude")))["status"] == "reproduced"
    assert validate.validate_group(c, group(rp("claude")))["status"] == "reproduced"
    assert w.runs == 1


def test_a_test_proposed_later_is_run(tmp_path):
    w = Worker()
    c = ctx(tmp_path, w)
    assert validate.validate_group(c, group())["status"] == "unvalidated"
    assert validate.validate_group(c, group(rp("codex")))["status"] == "reproduced"
    assert w.runs == 1


def test_a_changed_test_is_run_again(tmp_path):
    w = Worker(NOT_REPRODUCED)
    c = ctx(tmp_path, w)
    assert validate.validate_group(c, group(rp("claude")))["status"] == "not_reproduced"
    w.out = PASSING_REPRO
    assert validate.validate_group(c, group(rp("claude"), rp("codex")))["status"] == "reproduced"
    assert w.runs == 2  # validated again from the first test, which now reproduces


def test_records_saved_before_this_change(tmp_path):
    """Older records carry no input fingerprint. Keep a reproduced one (rerunning every test of a
    finished run costs hours and proves nothing new); redo one that saw fewer tests than exist now."""
    w = Worker()
    c = ctx(tmp_path, w)
    unit = c.ledger.unit("o/r", "validate", "QOT-1", None)
    unit.save("done", {"status": "reproduced", "method": "reproduction", "evidence_ref": "x", "notes": "n",
                       "reproduction": {"by": "claude", "attempts": [{"by": "claude"}]}})
    assert validate.validate_group(c, group(rp("claude"), rp("codex")))["evidence_ref"] == "x"
    unit.save("done", {"status": "unvalidated", "method": None, "evidence_ref": None,
                       "notes": "no reproduction was proposed", "reproduction": None})
    assert validate.validate_group(c, group(rp("codex")))["status"] == "reproduced"
    assert w.runs == 1
