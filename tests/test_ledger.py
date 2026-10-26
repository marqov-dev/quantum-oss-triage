from harness.controller.ledger import Ledger


def test_unit_roundtrip_and_resume(tmp_path):
    led = Ledger(tmp_path)
    u = led.unit("org/repo", "review", "review-security", "claude")
    assert not u.done()
    u.save("done", {"x": 1}, tokens={"input": 3, "output": 4}, model_id="m")
    again = Ledger(tmp_path).unit("org/repo", "review", "review-security", "claude")
    assert again.done() and again.payload() == {"x": 1}
    assert led.usage()[0]["adapter"] == "claude" and led.usage()[0]["input"] == 3


def test_failed_and_limited_units_are_not_done(tmp_path):
    led = Ledger(tmp_path)
    led.unit("r", "review", "s", "m").save("failed", None, error="bad")
    led.unit("r", "review", "s2", "m").save("usage_limited", None)
    assert not led.unit("r", "review", "s", "m").done()
    assert not led.unit("r", "review", "s2", "m").done()


def test_keys_are_distinct_per_model_and_skill(tmp_path):
    led = Ledger(tmp_path)
    paths = {led.unit("r", "review", s, m).path for s in ("a", "b") for m in ("claude", "codex")}
    assert len(paths) == 4
