"""Who verifies what: the rule that keeps quota-limited models on model claims."""

from types import SimpleNamespace

import pytest

from harness.controller import merge
from harness.controller.ledger import Ledger
from harness.stages import verify


def ctx(tmp_path, limited=("antigravity",)):
    return SimpleNamespace(spec=SimpleNamespace(name="org/q"), source_dir=tmp_path, ledger=Ledger(tmp_path),
                           model_order=lambda: ["claude", "codex", "antigravity"],
                           config=SimpleNamespace(verify_model_claims_only=list(limited)))


def claim(*tools):
    return [{"tool": t, "rule_id": None, "title": "+".join(tools)} for t in tools]


@pytest.fixture(autouse=True)
def group_ids(monkeypatch):
    monkeypatch.setattr(merge, "group_key", lambda repo, g, src: "QOT-" + g[0]["title"])
    monkeypatch.setattr(merge, "representative", lambda g: g[0])


def verifiers(c, *tools):
    return verify.plan(c, [claim(*tools)])[0]["verifiers"]


def test_scanner_and_prior_work_claims_skip_the_limited_model(tmp_path):
    c = ctx(tmp_path)
    assert verifiers(c, "zizmor") == [("claude", "independent"), ("codex", "independent")]
    assert verifiers(c, "prior-work") == [("claude", "independent"), ("codex", "independent")]


def test_model_claims_keep_the_limited_model(tmp_path):
    c = ctx(tmp_path)
    assert verifiers(c, "claude") == [("codex", "independent"), ("antigravity", "independent")]
    assert verifiers(c, "claude", "codex") == [("antigravity", "independent")]  # the only independent check
    assert verifiers(c, "claude", "zizmor") == [("codex", "independent"), ("antigravity", "independent")]


def test_a_verdict_already_given_is_kept(tmp_path):
    c = ctx(tmp_path)
    c.ledger.unit("org/q", "verify", "QOT-zizmor", "antigravity").save("done", {})
    assert ("antigravity", "independent") in verifiers(c, "zizmor")


def test_the_limited_model_stays_when_no_other_can_check(tmp_path):
    c = ctx(tmp_path)
    c.model_order = lambda: ["antigravity"]
    assert verifiers(c, "zizmor") == [("antigravity", "independent")]


def test_no_limit_by_default(tmp_path):
    c = ctx(tmp_path, limited=())
    assert ("antigravity", "independent") in verifiers(c, "zizmor")
