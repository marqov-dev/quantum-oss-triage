"""A saved model answer is reused only for the inputs it was given."""

from types import SimpleNamespace

from harness.controller.context import RepoContext
from harness.controller.ledger import Ledger
from tests.fakes.adapters import FakeAdapter


def ctx(tmp_path, adapter):
    return SimpleNamespace(ledger=Ledger(tmp_path), spec=SimpleNamespace(name="o/r"), retry_failed=False,
                           log=lambda *_: None, adapters={"fake": adapter}, review_dir=tmp_path,
                           manifest=SimpleNamespace(fail=lambda *_: None))


def ask(c, inputs):
    return RepoContext.call_model(c, "challenge", "QOT-1", "fake", "challenge-test", "p", 1, inputs=inputs)


def test_same_inputs_reuse_and_new_inputs_ask_again(tmp_path):
    a = FakeAdapter("fake")
    c = ctx(tmp_path, a)
    assert ask(c, "t1").ok and ask(c, "t1").ok
    assert len(a.calls) == 1
    assert ask(c, "t2").ok
    assert len(a.calls) == 2


def test_older_answers_without_inputs_are_kept(tmp_path):
    a = FakeAdapter("fake")
    c = ctx(tmp_path, a)
    c.ledger.unit("o/r", "challenge", "QOT-1", "fake").save("done", {"verdict": "valid"})
    assert ask(c, "t1").payload == {"verdict": "valid"} and a.calls == []
