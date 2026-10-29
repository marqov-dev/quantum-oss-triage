"""The evaluation fixtures behave as their expected.yaml says."""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from harness.paths import REPO_ROOT

EVAL = REPO_ROOT / "evaluations"


def git_repo(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
    subprocess.run(git + ["init", "-q"], cwd=path, check=True)
    (path / "marker").write_text(path.name)
    subprocess.run(git + ["add", "."], cwd=path, check=True)
    subprocess.run(git + ["commit", "-qm", path.name], cwd=path, check=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True,
                          text=True).stdout.strip()


def load(path: Path):
    spec = importlib.util.spec_from_file_location(f"fixture_{path.stem}_{abs(hash(path))}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def installed_and_caller(tmp_path, monkeypatch):
    """A package checkout and an unrelated repository the caller runs from."""
    if not shutil.which("git"):
        pytest.skip("git not installed")
    installed, caller = tmp_path / "installed", tmp_path / "caller"
    installed_head, caller_head = git_repo(installed), git_repo(caller)
    monkeypatch.chdir(caller)
    return installed, installed_head, caller_head


def test_p12_git_revision_reports_the_callers_repository(installed_and_caller):
    installed, installed_head, caller_head = installed_and_caller
    shutil.copy(EVAL / "planted-bugs" / "qtoy" / "provenance.py", installed / "provenance.py")
    assert load(installed / "provenance.py").git_revision() == caller_head != installed_head


def test_h2_git_revision_reports_its_own_checkout(installed_and_caller):
    installed, installed_head, _ = installed_and_caller
    shutil.copy(EVAL / "harmless-lookalikes" / "qsafe" / "config.py", installed / "config.py")
    assert load(installed / "config.py").git_revision() == installed_head


@pytest.mark.parametrize("case,key", [("planted-bugs", "planted"), ("harmless-lookalikes", "harmless")])
def test_expected_line_ranges_point_at_the_code(case, key):
    names = {"P12": "def git_revision", "H1": "def parse_shape", "H2": "def git_revision"}
    for entry in yaml.safe_load((EVAL / case / "expected.yaml").read_text())[key]:
        if entry["id"] not in names:
            continue
        lines = (EVAL / case / entry["file"]).read_text().splitlines()
        start, end = entry["lines"]
        assert lines[start - 1].startswith(names[entry["id"]]), entry["id"]
        assert end <= len(lines) + 1 and "return" in "\n".join(lines[start - 1:end]), entry["id"]
