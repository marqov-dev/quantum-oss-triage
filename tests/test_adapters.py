import json
import shutil
from pathlib import Path

import pytest

from harness.adapters import AntigravityAdapter, ClaudeAdapter, CodexAdapter
from harness.adapters.base import extract_json
from harness.adapters.claude import ISOLATION_FLAGS
from harness.controller import cleanenv
from tests.test_schemas import GOOD_REVIEW

FAKES = Path(__file__).parent / "fakes"


@pytest.fixture
def fake(tmp_path):
    d = tmp_path / "bin"
    d.mkdir()
    shutil.copy(FAKES / "fakecli", d / "fakecli")
    claude_doc = {"type": "result", "is_error": False, "structured_output": GOOD_REVIEW, "result": "",
                  "usage": {"input_tokens": 5, "output_tokens": 7, "cache_read_input_tokens": 11,
                            "cache_creation_input_tokens": 13},
                  "total_cost_usd": 0.01, "modelUsage": {"claude-test-1": {"outputTokens": 7}}}
    (d / "good.json").write_text(json.dumps(claude_doc))

    def setup(*modes):
        (d / "modes").write_text("\n".join(modes) + "\n")
        return str(d / "fakecli")

    setup.dir = d
    return setup


def make(fake_bin, cls=ClaudeAdapter, **kw):
    return cls(binary=fake_bin, config_dir="default", **kw) if cls is ClaudeAdapter else cls(binary=fake_bin, **kw)


def test_valid_output_is_parsed(fake, tmp_path):
    a = make(fake("good"))
    r = a.run("review", "sys", "review-output", tmp_path)
    assert r.ok and r.attempts == 1
    assert r.data == GOOD_REVIEW
    assert r.model_id == "claude-test-1"
    assert r.tokens["output"] == 7 and r.tokens["cache_read"] == 11


def test_adapter_retries_once_then_fails(fake, tmp_path):
    a = make(fake("bad", "bad"))
    r = a.run("review", "sys", "review-output", tmp_path)
    assert not r.ok and r.attempts == 2
    assert (fake.dir / "count").read_text().strip() == "2"
    assert "rejected by the harness" in (fake.dir / "args.2").read_text()


def test_retry_can_succeed(fake, tmp_path):
    r = make(fake("bad", "good")).run("review", "sys", "review-output", tmp_path)
    assert r.ok and r.attempts == 2


def test_schema_invalid_output_is_retried(fake, tmp_path):
    doc = json.loads((fake.dir / "good.json").read_text())
    doc["structured_output"] = {"findings": [{"title": "x"}], "coverage": {}}
    (fake.dir / "good.json").write_text(json.dumps(doc))
    r = make(fake("good")).run("review", "sys", "review-output", tmp_path)
    assert not r.ok and r.attempts == 2 and "schema errors" in r.error


def test_usage_limit_is_detected_without_retry(fake, tmp_path):
    r = make(fake("limit")).run("review", "sys", "review-output", tmp_path)
    assert not r.ok and r.usage_limited and r.attempts == 1


def test_signed_out_is_detected(fake, tmp_path):
    r = make(fake("signedout")).run("review", "sys", "review-output", tmp_path)
    assert not r.ok and r.not_signed_in and not r.usage_limited


def test_hard_timeout_kills_process(fake, tmp_path):
    r = make(fake("hang")).run("review", "sys", "review-output", tmp_path, timeout_s=2)
    assert not r.ok and "timed out" in r.error
    assert r.duration_s < 10


def test_missing_binary_is_unavailable(tmp_path):
    a = ClaudeAdapter(binary="definitely-not-installed-qot")
    ok, reason = a.available()
    assert not ok and "not installed" in reason
    r = a.run("x", "y", "review-output", tmp_path)
    assert not r.ok and "not installed" in r.error


def test_claude_command_has_every_isolation_flag(tmp_path):
    cmd = ClaudeAdapter(binary="claude", config_dir="default").build_command("p", "s", "review-output", tmp_path, tmp_path / "o")
    joined = "\x00".join(cmd)
    assert "\x00".join(ISOLATION_FLAGS) in joined
    assert cmd[cmd.index("--tools") + 1] == "Read,Grep,Glob"
    schema_arg = json.loads(cmd[cmd.index("--json-schema") + 1])
    assert "$schema" not in schema_arg


def test_env_passed_to_cli_has_no_credentials(fake, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-pass")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_should_not_pass")
    monkeypatch.setenv("CLAUDE_CODE_USER_EMAIL", "someone@example.com")
    monkeypatch.setenv("MARQOV_API_KEY", "mq_should_not_pass")
    make(fake("good")).run("review", "sys", "review-output", tmp_path)
    env_seen = (fake.dir / "env.1").read_text()
    for leaked in ("sk-should-not-pass", "ghp_should_not_pass", "someone@example.com", "mq_should_not_pass"):
        assert leaked not in env_seen
    for cls in (ClaudeAdapter, CodexAdapter, AntigravityAdapter):
        env = cls().env()
        assert cleanenv.forbidden_keys(env, allowed=("CLAUDE_CONFIG_DIR", "CODEX_HOME")) == [], cls


def test_codex_command_is_read_only_with_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(cleanenv, "CONFIG_ROOT", tmp_path / "cfg")
    cmd = CodexAdapter(binary="codex").build_command("p", "s", "verdict", tmp_path, tmp_path / "out.json")
    assert cmd[1:3] == ["exec", "--json"]
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert json.loads(Path(cmd[cmd.index("--output-schema") + 1]).read_text())["title"] == "Verifier verdict"
    assert "project_doc_max_bytes=0" in cmd
    home = cleanenv.codex_home()
    assert "mcp_servers" in (home / "config.toml").read_text()


def test_antigravity_command_and_hard_timeout():
    a = AntigravityAdapter(binary="agy")
    cmd = a.build_command("p", "s", "verdict", Path("."), Path("o"))
    for flag in ("--output-format", "--mode", "--sandbox", "--print-timeout"):
        assert flag in cmd
    assert cmd[cmd.index("--mode") + 1] == "plan"
    assert a.max_timeout_s == 25 * 60


def test_codex_parse_reads_output_file_and_usage():
    from harness.adapters.base import Invocation

    events = "\n".join([json.dumps({"type": "thread.started"}),
                        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 3, "cached_input_tokens": 1, "output_tokens": 4}})])
    p = CodexAdapter().parse(Invocation(0, events, "", False, 1.0, json.dumps(GOOD_REVIEW)))
    assert p.data == GOOD_REVIEW and p.tokens == {"input": 3, "output": 4, "cache_read": 1}


def test_antigravity_parse_reads_response_and_stats():
    from harness.adapters.base import Invocation

    doc = {"response": "```json\n" + json.dumps(GOOD_REVIEW) + "\n```",
           "stats": {"models": {"gemini-x": {"tokens": {"prompt": 9, "candidates": 2, "cached": 1}}}}}
    p = AntigravityAdapter().parse(Invocation(0, json.dumps(doc), "", False, 1.0))
    assert p.data == GOOD_REVIEW and p.model_id == "gemini-x" and p.tokens["input"] == 9


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('text\n```json\n{"a": 2}\n```\n') == {"a": 2}
    assert extract_json('prefix {"a": 3} suffix') == {"a": 3}
    assert extract_json("nothing") is None
