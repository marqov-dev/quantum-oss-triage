import ast
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from harness.paths import REPO_ROOT
from harness.publish import redact, render
from harness.publish.__main__ import publish_repo

MANIFEST = {
    "schema_version": 1, "run_id": "r1", "harness_revision": "abc", "status": "incomplete",
    "repo": {"name": "org/repo", "source": "x", "commit": "a" * 40, "scope": {"include": [], "exclude": []}},
    "adapters": [{"name": "claude", "used": True, "version": "2.1", "model_ids": ["claude-opus-5-5"], "reason": "ok"},
                 {"name": "codex", "used": False, "version": None, "model_ids": [], "reason": "codex not installed"}],
    "scanners": [{"name": "gitleaks", "status": "ok", "version": "8"}, {"name": "scorecard", "status": "unavailable", "version": None}],
    "started_at": "2026-10-26T00:00:00+00:00", "finished_at": "2026-10-26T01:00:00+00:00",
    "coverage": {"reviewed": [], "not_reviewed": [], "incomplete_checks": ["model codex not used: codex not installed"]},
    "stages": {}, "tokens": {},
}


def make(sample, **kw):
    f = copy.deepcopy(sample)
    for k, v in kw.items():
        f[k] = v
    return f


@pytest.fixture
def findings(sample_finding):
    ok = make(sample_finding, id="QOT-aaaaaaaaaa")
    ok["disposition"]["decision"] = "accept"
    ok["severity"]["final"] = "high"
    sec = make(sample_finding, id="QOT-bbbbbbbbbb", title="Unpickling downloaded job results", area="security",
               category="security_vulnerability", file="pkg/remote.py", line_start=28, line_end=28,
               claim="fetch_result calls pickle.loads on bytes from the network.")
    sec["sensitivity"] = {"sensitive": True, "reasons": ["area is security"], "removal_reason": None}
    sec["disposition"]["decision"] = "accept"
    sec["severity"]["final"] = "critical"
    rejected = make(sample_finding, id="QOT-cccccccccc", title="Not a bug")
    rejected["disposition"]["decision"] = "reject"
    return [ok, sec, rejected]


def test_report_has_only_approved_and_security_rows_are_minimal(findings, tmp_path):
    r = render.build(MANIFEST, findings, {}, tmp_path)
    ids = [t["id"] for t in r["triage"]]
    assert ids == ["QOT-bbbbbbbbbb", "QOT-aaaaaaaaaa"]  # sorted by severity; rejected excluded
    assert r["triage"][0] == {"id": "QOT-bbbbbbbbbb", "sensitive": True, "severity": "critical",
                              "kind": "Security finding", "reported_privately": "not yet reported"}
    assert r["scorecard"]["counts"] == {"security_vulnerability": 1, "dependency_advisory": 0, "correctness": 1,
                                        "docs_tests_maintenance": 0}
    md = render.to_markdown(r)
    assert "pkg/remote.py" not in md and "pickle" not in md
    assert "Not a bug" not in md
    assert "incomplete" in md and "codex not installed" in md  # incomplete is never shown as clean
    assert redact.check(md, [findings[1]]) == []
    page = render.to_html(r)
    assert page.startswith("<!doctype html>") and "<script" not in page and "http" not in page.split("<main>")[0]


def test_severity_must_be_set_by_a_person(findings, tmp_path):
    findings[0]["severity"]["final"] = None
    with pytest.raises(render.NotReady):
        render.build(MANIFEST, findings, {}, tmp_path)


def test_redact_blocks_leaks(findings):
    sec = findings[1]
    assert redact.check("see pkg/remote.py:28 for details", [sec])
    assert redact.check(f"Title: {sec['title']}", [sec])
    assert redact.check('token = "qtk_live_7Hq2Vx9Lm4Rt8Wz1Np6Ks3Df5Gb0Jc2Ye"', [])
    assert redact.check("an RCE via crafted payload", [])
    assert redact.check("contact someone@example.com", [])
    assert redact.check("pkg/remote.py:3 has a docs typo", [sec]) == []  # same file, different finding


def _write_run(tmp_path, findings):
    d = tmp_path / "run" / "org__repo"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps(MANIFEST))
    (d / "findings.json").write_text(json.dumps(findings))
    (d / "scan-summary.json").write_text(json.dumps({}))
    return d


def test_publisher_writes_local_outbox(findings, tmp_path):
    d = _write_run(tmp_path, findings)
    ok, res = publish_repo(tmp_path / "run", d, tmp_path / "outbox")
    assert ok, res
    out = tmp_path / "outbox" / "org__repo"
    assert {p.name for p in out.iterdir()} == {"workspace.json", "report.json", "report.md", "report.html",
                                               "planned-branches.json"}
    ws = json.loads((out / "workspace.json").read_text())
    assert ws["title"] == "org/repo: run record" and ws["project"].startswith("Quantum open-source review")


def test_publisher_blocks_when_sensitive_detail_would_leak(findings, tmp_path):
    findings[0]["title"] = "Bug next to " + findings[1]["title"]
    d = _write_run(tmp_path, findings)
    ok, res = publish_repo(tmp_path / "run", d, tmp_path / "outbox")
    assert not ok and res["blocked"]
    assert (tmp_path / "outbox" / "org__repo" / "BLOCKED.txt").exists()
    assert not (tmp_path / "outbox" / "org__repo" / "report.md").exists()


def test_publisher_runs_as_its_own_process(findings, tmp_path):
    _write_run(tmp_path, findings)
    p = subprocess.run([sys.executable, "-m", "harness.publish", str(tmp_path / "run"), "--public-summary"],
                       capture_output=True, text=True, cwd=REPO_ROOT)
    assert p.returncode == 0, p.stdout + p.stderr
    summary = json.loads((tmp_path / "run" / "outbox" / "public-summary.json").read_text())
    assert summary["projects"][0]["counts"]["security_vulnerability"] == 1
    assert "QOT-" not in json.dumps(summary)


def _imports(pkg: str) -> set[str]:
    names = set()
    for path in (REPO_ROOT / "harness" / pkg).rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
            elif isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
    return names


def test_three_parts_stay_separate():
    publish = _imports("publish")
    assert not any(n.startswith(("harness.adapters", "harness.workers", "harness.controller", "harness.stages"))
                   for n in publish), publish
    for part in ("controller", "stages", "adapters", "workers", "scanners"):
        assert not any(n.startswith("harness.publish") for n in _imports(part)), part


def test_marqov_key_is_referenced_only_by_the_publisher():
    hits = [p for p in (REPO_ROOT / "harness").rglob("*.py") if "api-key" in p.read_text()]
    assert [p.relative_to(REPO_ROOT).as_posix() for p in hits] == ["harness/publish/marqov.py"]


def test_publish_is_a_dry_run_by_default_and_never_reads_the_key(findings, tmp_path):
    _write_run(tmp_path, findings)
    home = tmp_path / "home-without-key"
    home.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}
    p = subprocess.run([sys.executable, "-m", "harness.publish", str(tmp_path / "run"), "--public-summary"],
                       capture_output=True, text=True, cwd=REPO_ROOT, env=env)
    assert p.returncode == 0, p.stdout + p.stderr
    out = json.loads(p.stdout)[-1]["marqov"]
    assert out["dry_run"] is True
    titles = [d["title"] for d in out["would_upload"]]
    assert titles == ["org/repo: run record", "org/repo: review", "Round one: overview", "Round one: public summary"]
    assert all(d["gate"] == "passed" for d in out["would_upload"])
    assert [d["target"] for d in out["would_upload"]] == ["repo", "repo", "hub", "hub"]
    assert out["live_blocked_by"]  # no Project ids are configured in the repository
    assert not (tmp_path / "run" / "outbox" / "marqov-published.json").exists()
    # --live with no key file refuses, uploads nothing.
    p = subprocess.run([sys.executable, "-m", "harness.publish", str(tmp_path / "run"), "--live"],
                       capture_output=True, text=True, cwd=REPO_ROOT, env=env)
    assert p.returncode == 1 and "no Project configured" in p.stdout
