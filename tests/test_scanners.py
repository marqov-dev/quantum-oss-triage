import json
from pathlib import Path

from harness.scanners import Bandit, Gitleaks, Lychee, OsvScanner, Ruff, Scorecard, Semgrep, Zizmor
from harness.scanners.base import ScanResult

FIX = Path(__file__).parent / "fixtures" / "scanners"


def text(name):
    return (FIX / f"{name}.json").read_text()


def test_gitleaks_output_is_redacted():
    r = Gitleaks().parse(text("gitleaks-unredacted"), "", 0)
    blob = json.dumps(r.findings) + r.raw
    assert "qtk_live_9f8e7d6c5b4a39281706f5e4d3c2b1a0" not in blob
    assert "t@t" not in r.raw  # author email dropped
    assert r.findings[0]["file"] == "pkg/io.py" and r.findings[0]["line_start"] == 2
    assert r.findings[0]["security_impact"] is True


def test_semgrep_leads():
    r = Semgrep().parse(text("semgrep"), "", 0)
    assert [f["rule_id"] for f in r.findings] == ["subprocess-shell-true"]
    assert r.findings[0]["area"] == "security" and r.findings[0]["line_start"] == 6


def test_zizmor_keeps_high_and_medium_confidence():
    r = Zizmor().parse(text("zizmor"), "", 14)
    rules = {f["rule_id"] for f in r.findings}
    assert {"template-injection", "dangerous-triggers"} <= rules
    assert "artipacked" not in rules  # low confidence goes to hygiene
    assert all(f["file"] == ".github/workflows/ci.yml" for f in r.findings)


def test_bandit_split_between_leads_and_hygiene():
    r = Bandit().parse(text("bandit"), "", 0)
    assert {f["rule_id"] for f in r.findings} == {"B301", "B602"}
    assert r.hygiene["low"] == 2


def test_ruff_is_hygiene_only():
    r = Ruff().parse(text("ruff"), "", 0)
    assert r.findings == [] and r.hygiene["total"] >= 1


def test_lychee_counts_broken_local_links():
    r = Lychee().parse(text("lychee"), "", 2)
    assert r.findings == [] and r.hygiene["broken_local_links"] == 1
    assert r.hygiene["broken"][0]["url"] == "docs/missing.md"


def test_osv_advisories_are_known_and_kept_separate():
    r = OsvScanner().parse(text("osv"), "", 1)
    assert len(r.findings) == 2
    assert all(f["known_advisory"] and f["security_impact"] for f in r.findings)
    assert r.findings[0]["proposed_severity"] == "critical"
    assert r.database_date.startswith("queried live")


class _NoWorker:
    def run(self, *a, **k):
        raise AssertionError("must not run")


def test_missing_tool_is_unavailable_not_pass(tmp_path):
    r = Semgrep().run(_NoWorker(), tmp_path, versions={"semgrep": "unavailable"})
    assert r.status == "unavailable"
    r = Scorecard().run(_NoWorker(), tmp_path, versions={})
    assert r.status in ("unavailable", "not_applicable")


def test_not_applicable_when_no_workflows(tmp_path):
    r = Zizmor().run(_NoWorker(), tmp_path, versions={"zizmor": "zizmor 1"})
    assert r.status == "not_applicable"


def test_unparseable_output_is_failed(tmp_path):
    class W:
        def run(self, *a, **k):
            from harness.workers.base import WorkerResult
            return WorkerResult(1, "{not json", "boom")
    (tmp_path / "a.py").write_text("x=1\n")
    r = Ruff().run(W(), tmp_path, versions={"ruff": "ruff 1"})
    assert isinstance(r, ScanResult) and r.status == "failed"


def test_osv_falls_back_to_the_installed_environment():
    doc = {"results": [{"source": {"path": "/deps/freeze.txt", "type": "lockfile"}, "packages": [
        {"package": {"name": "pip", "version": "25.2"}, "groups": [{"ids": ["GHSA-pip"], "max_severity": "5"}]},
        {"package": {"name": "pyyaml", "version": "5.3"}, "groups": [{"ids": ["GHSA-yaml"], "max_severity": "9.8"}]}]}]}
    r = OsvScanner().parse(json.dumps(doc), "No package sources found\nQOT-OSV-INSTALLED-ENV\n", 0)
    assert [f["rule_id"] for f in r.findings] == ["GHSA-yaml"]  # the harness's own pip is left out
    assert r.findings[0]["file"] == "pyproject.toml" and "installed environment" in r.note
    assert "QOT-OSV-INSTALLED-ENV" in OsvScanner().script() and "/deps/freeze.txt" in OsvScanner().script()
