"""Reviewer sandbox: what reaches the container, and nothing personal does."""

import json
import os
from pathlib import Path

from harness.adapters import AntigravityAdapter, CodexAdapter
from harness.adapters.base import Invocation
from harness.adapters.sandbox import ReviewerSandbox, probe_markers
from harness.controller import cleanenv

FAKE_DOCKER = """#!/bin/sh
echo "$@" >> "{log}"
case "$1" in
  image) echo sha256:0123456789abcdef; exit 0 ;;
  kill) exit 0 ;;
esac
sleep 30
"""


def fake_docker(tmp_path: Path) -> tuple[str, Path]:
    log = tmp_path / "docker.log"
    p = tmp_path / "docker"
    p.write_text(FAKE_DOCKER.format(log=log))
    p.chmod(0o755)
    return str(p), log


def sandbox(tmp_path, cli="codex", **kw):
    return ReviewerSandbox(cli, home=tmp_path / "home", **kw)


def test_wrap_mounts_only_review_out_and_harness_home(tmp_path):
    review, out = tmp_path / "review", tmp_path / "out"
    review.mkdir(), out.mkdir()
    sb = sandbox(tmp_path)
    cmd = ["/opt/homebrew/bin/codex", "exec", "-C", str(review), "-o", str(out / "out.json"),
           "--output-schema", str(out / "schema.json"), f"{review} is not a path argument"]
    w = sb.wrap(cmd, review, out, "qot-test")
    vols = [w[i + 1] for i, x in enumerate(w) if x == "-v"]
    assert vols == [f"{review.resolve()}:/review:ro", f"{out.resolve()}:/out:rw", f"{(tmp_path / 'home').resolve()}:/home/qot:rw"]
    envs = [w[i + 1] for i, x in enumerate(w) if x == "-e"]
    assert envs == ["HOME=/home/qot", "TERM=dumb", "NO_COLOR=1"]
    for flag in ("--read-only", "--rm", "no-new-privileges"):
        assert flag in w
    assert w[w.index("--cap-drop") + 1] == "ALL"
    assert any(x.startswith("seccomp=") and x.endswith("reviewer-seccomp.json") for x in w)
    inner = w[w.index(sb.image) + 1:]
    assert inner[:2] == ["codex", "exec"]  # the container's own binary, not the host path
    assert inner[inner.index("-C") + 1] == "/review"
    assert inner[inner.index("-o") + 1] == "/out/out.json"
    assert inner[-1].startswith(str(review))  # prompt text is never rewritten
    # The harness settings are rewritten into the sandbox home on every call.
    assert "project_doc_max_bytes = 0" in (tmp_path / "home" / ".codex" / "config.toml").read_text()


def test_probe_markers_are_visible_at_the_same_path(tmp_path):
    markers = tmp_path / "markers"
    markers.mkdir()
    sb = sandbox(tmp_path)
    with probe_markers(markers):
        assert (str(markers.resolve()), str(markers.resolve()), "rw") in sb.mounts(tmp_path, tmp_path)
    assert len(sb.mounts(tmp_path, tmp_path)) == 3


def test_isolation_report_flags_personal_mounts_and_copies(tmp_path):
    personal = tmp_path / "operator"
    (personal / ".gemini" / "config").mkdir(parents=True)
    rules = personal / ".gemini" / "config" / "config.json"
    rules.write_text(json.dumps({"permissions": ["28 old rules"]}))
    sb = sandbox(tmp_path, cli="agy")
    sb.prepare_home()
    clean = sb.isolation_report(tmp_path / "review", tmp_path / "out", personal_home=personal)
    assert clean["personal_mounts"] == [] and clean["personal_copies"] == [] and clean["symlinks_in_home"] == []
    # A copy of the personal permission rules in the sandbox home is caught.
    (sb.home / ".gemini" / "config").mkdir(parents=True, exist_ok=True)
    (sb.home / ".gemini" / "config" / "config.json").write_text(rules.read_text())
    os.symlink(rules, sb.home / "linked.json")
    bad = sb.isolation_report(tmp_path / "review", tmp_path / "out", personal_home=personal)
    assert bad["personal_copies"] == [{"sandbox": ".gemini/config/config.json", "personal": ".gemini/config/config.json"}]
    assert bad["symlinks_in_home"] == ["linked.json"]
    # So is a mount from inside the personal config.
    with probe_markers(personal / ".gemini"):
        assert bad_mount(sb, tmp_path, personal)


def test_cli_written_defaults_and_inner_links_are_not_flagged(tmp_path):
    personal = tmp_path / "operator"
    default = '{\n  "id":  "default-cli-project",\n  "name":  "CLI Project",\n  "projectResources":  {}\n}'
    for home in (personal, tmp_path / "sbhome"):
        (home / ".gemini" / "config" / "projects").mkdir(parents=True)
        (home / ".gemini" / "config" / "projects" / "default-cli-project.json").write_text(default)
    sb = sandbox(tmp_path, cli="agy")
    sb.home = tmp_path / "sbhome"
    (sb.home / ".gemini" / "antigravity-cli" / "log").mkdir(parents=True)
    (sb.home / ".gemini" / "antigravity-cli" / "log" / "cli-1.log").write_text("x")
    os.symlink("log/cli-1.log", sb.home / ".gemini" / "antigravity-cli" / "cli.log")
    r = sb.isolation_report(tmp_path / "review", tmp_path / "out", personal_home=personal)
    assert r["personal_copies"] == [] and r["symlinks_in_home"] == []
    # Once the operator's project file holds anything personal, a copy is caught again.
    edited = '{"id": "default-cli-project", "name": "CLI Project", "projectResources": {"x": 1}}'
    (personal / ".gemini" / "config" / "projects" / "default-cli-project.json").write_text(edited)
    (sb.home / ".gemini" / "config" / "projects" / "default-cli-project.json").write_text(edited)
    os.symlink("../../../escape", sb.home / ".gemini" / "antigravity-cli" / "up.log")
    os.symlink("/home/qot/.gemini/x", sb.home / ".gemini" / "antigravity-cli" / "abs.log")
    r = sb.isolation_report(tmp_path / "review", tmp_path / "out", personal_home=personal)
    assert len(r["personal_copies"]) == 1
    assert sorted(r["symlinks_in_home"]) == [".gemini/antigravity-cli/abs.log", ".gemini/antigravity-cli/up.log"]


def bad_mount(sb, tmp_path, personal):
    return sb.isolation_report(tmp_path / "review", tmp_path / "out", personal_home=personal)["personal_mounts"]


def test_copy_personal_auth_copies_only_the_sign_in(tmp_path, monkeypatch):
    personal = tmp_path / "operator"
    (personal / ".codex").mkdir(parents=True)
    (personal / ".codex" / "auth.json").write_text('{"tokens": "x"}')
    (personal / ".codex" / "config.toml").write_text('[mcp_servers.mine]\ncommand = "x"\n')
    (personal / ".codex" / "AGENTS.md").write_text("personal instructions")
    monkeypatch.setenv("HOME", str(personal))
    sb = sandbox(tmp_path)
    assert sb.copy_personal_auth() == [".codex/auth.json"]
    files = sorted(str(p.relative_to(sb.home)) for p in sb.home.rglob("*") if p.is_file())
    assert files == [".codex/auth.json", ".codex/config.toml"]
    assert "mcp_servers.mine" not in (sb.home / ".codex" / "config.toml").read_text()
    assert oct((sb.home / ".codex" / "auth.json").stat().st_mode)[-3:] == "600"
    assert sb.isolation_report(tmp_path, tmp_path, personal_home=personal)["personal_copies"] == []


def test_unsigned_sandbox_is_unavailable(tmp_path):
    docker, _ = fake_docker(tmp_path)
    ok, reason = sandbox(tmp_path, docker=docker).available()
    assert not ok and "qot sandbox-login codex" in reason


def test_timeout_kills_the_container(tmp_path, monkeypatch):
    monkeypatch.setattr(cleanenv, "CONFIG_ROOT", tmp_path / "cfg")
    docker, log = fake_docker(tmp_path)
    a = CodexAdapter(sandbox={"docker": docker, "home": tmp_path / "home"})
    (tmp_path / "home" / ".codex").mkdir(parents=True)
    (tmp_path / "home" / ".codex" / "auth.json").write_text("{}")
    r = a.run("p", "s", "verdict", tmp_path, timeout_s=2)
    assert not r.ok and "timed out" in r.error
    calls = log.read_text().splitlines()
    run = next(c for c in calls if c.startswith("run "))
    name = run.split("--name ")[1].split()[0]
    assert f"kill {name}" in calls


def test_codex_sandbox_command_flags(tmp_path):
    cmd = CodexAdapter().build_command("p", "s", "verdict", tmp_path, tmp_path / "out.json")
    for flag in ("--ephemeral", "--ignore-rules", "--strict-config", "--skip-git-repo-check"):
        assert flag in cmd
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert "--strict-config" not in CodexAdapter(sandbox=False).build_command("p", "s", "verdict", tmp_path,
                                                                              tmp_path / "o.json")


def test_antigravity_command_uses_schema_file(tmp_path):
    cmd = AntigravityAdapter().build_command("p", "s", "verdict", tmp_path, tmp_path / "out.json")
    assert json.loads(Path(cmd[cmd.index("--json-schema") + 1]).read_text())["title"] == "Verifier verdict"
    for flag in ("--disable-slash-commands", "--sandbox"):
        assert flag in cmd
    assert cmd[cmd.index("--mode") + 1] == "plan"


def test_antigravity_parse_current_json_format():
    a = AntigravityAdapter()
    ok = {"conversation_id": "c", "status": "SUCCESS", "response": '{"verdict": "confirm"}', "error": "",
          "usage": {"input_tokens": 10, "output_tokens": 3, "thinking_tokens": 2, "cache_read_tokens": 4}}
    p = a.parse(Invocation(0, json.dumps(ok), "", False, 1.0))
    assert p.data == {"verdict": "confirm"} and p.tokens == {"input": 10, "output": 5, "cache_read": 4}
    err = {"conversation_id": "", "status": "ERROR", "response": "", "error": "authentication failed or timed out"}
    p = a.parse(Invocation(1, json.dumps(err), "", False, 1.0))
    assert p.failed_call and "authentication" in p.error
