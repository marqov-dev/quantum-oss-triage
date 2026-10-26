from pathlib import Path

import yaml

from harness.fixtures import materialise, real_name
from harness.paths import EVALUATIONS_DIR, REPO_ROOT

AGENT_FILES = {"CLAUDE.md", "AGENTS.md", "GEMINI.md", ".mcp.json"}
AGENT_DIRS = {".claude", ".agents", ".gemini", ".codex"}


def test_real_names():
    assert real_name(Path("dot-claude/settings.json.fixture")) == Path(".claude/settings.json")
    assert real_name(Path("dot-mcp.json.fixture")) == Path(".mcp.json")
    assert real_name(Path("qhost/counts.py")) == Path("qhost/counts.py")


def test_method_repo_contains_no_live_agent_files():
    """Hostile fixtures must never be loadable by a tool working on this repository."""
    for p in REPO_ROOT.rglob("*"):
        rel = p.relative_to(REPO_ROOT)
        if rel.parts[0] in (".git", ".venv", "runs", "outbox"):
            continue
        assert p.name not in AGENT_FILES, rel
        assert not (p.is_dir() and p.name in AGENT_DIRS), rel


def test_hostile_case_materialises_with_markers(tmp_path):
    markers = tmp_path / "markers"
    src = materialise(EVALUATIONS_DIR / "hostile", tmp_path / "src", markers)
    for name in ("CLAUDE.md", "AGENTS.md", "GEMINI.md", ".mcp.json", ".claude/settings.json",
                 ".agents/skills/audit-mode/SKILL.md"):
        assert (src / name).exists(), name
    assert str(markers) in (src / ".claude" / "settings.json").read_text()
    assert (src / ".git").is_dir() and not (src / "expected.yaml").exists()
    assert not any(markers.iterdir())


def test_canaries_never_appear_joined_in_fixtures():
    exp = yaml.safe_load((EVALUATIONS_DIR / "hostile" / "expected.yaml").read_text())
    for p in (EVALUATIONS_DIR / "hostile").rglob("*"):
        if p.is_file() and p.name != "expected.yaml":
            for c in exp["canaries"]:
                assert c not in p.read_text(), (p, c)


def test_expected_lines_exist():
    for case in (d for d in EVALUATIONS_DIR.iterdir() if (d / "expected.yaml").exists()):
        exp = yaml.safe_load((case / "expected.yaml").read_text())
        for item in exp.get("planted", []) + exp.get("harmless", []):
            files = item["file"] if isinstance(item["file"], list) else [item["file"]]
            for f in files:
                stored = next(p for p in case.rglob("*") if real_name(p.relative_to(case)) == Path(f))
                assert len(stored.read_text().splitlines()) >= item["lines"][0], (case.name, item["id"])
