"""The reviewer's earlier work is evidence: merged, verified, never counted as a model."""

import json

import pytest
import yaml

from harness.controller import pipeline, prior, schema
from harness.publish import render
from tests.test_pipeline import config, repo, two_models, worker  # noqa: F401 (fixtures)

UPSTREAM = "https://github.com/org/m/issues/7"


def write_prior(run_dir, items):
    d = run_dir / "test__m"
    d.mkdir(parents=True, exist_ok=True)
    (d / prior.FILE).write_text(yaml.safe_dump({"source": "test notes", "items": items}))


def run(tmp_path, repo, config, worker):
    pipeline.run(config, tmp_path / "run", [repo], adapters=two_models(), worker=worker, log=lambda *_: None)
    return json.loads((tmp_path / "run" / "test__m" / "findings.json").read_text())


def test_earlier_item_merges_with_the_same_model_finding(tmp_path, repo, config, worker):
    write_prior(tmp_path / "run", [{"id": "PW-1", "title": "add subtracts instead of adding", "area": "correctness",
                                    "file": "m.py", "lines": [1, 3], "claim": "add returns a - b, not a + b.",
                                    "status": "reported", "upstream": [UPSTREAM]}])
    findings = run(tmp_path, repo, config, worker)
    assert len(findings) == 1  # not a second, "new" finding
    f = findings[0]
    assert schema.validate("finding", f) == []
    assert f["prior_work"] == [{"id": "PW-1", "status": "reported", "upstream": [UPSTREAM], "note": ""}]
    assert {d["source"] for d in f["detection"]["detections"]} == {"model", "prior_work"}
    assert f["corroboration"]["independent_models"] == ["claude"]  # the notes are not a second model
    triage = (tmp_path / "run" / "test__m" / "triage.md").read_text()
    assert "Raised before by you (PW-1, reported)" in triage and UPSTREAM in triage


def test_earlier_item_no_model_raised_is_still_verified(tmp_path, repo, config, worker):
    write_prior(tmp_path / "run", [{"id": "PW-2", "title": "docstring promises a + b", "area": "docs",
                                    "file": "m.py", "lines": [2, 2], "claim": "The docstring and code disagree.",
                                    "status": "found"}])
    findings = run(tmp_path, repo, config, worker)
    mine = [f for f in findings if f.get("prior_work")]
    assert len(mine) == 1 and mine[0]["detection"]["detected_by"] == ["prior-work"]
    assert mine[0]["corroboration"]["verifications"]  # checked by the models, not inherited
    assert mine[0]["corroboration"]["independent_models"] == []


def test_published_review_links_what_was_raised_before(sample_finding, tmp_path):
    from tests.test_publish import MANIFEST, make

    public = make(sample_finding, id="QOT-aaaaaaaaaa", prior_work=[{"id": "PW-1", "status": "reported",
                                                                     "upstream": [UPSTREAM]}])
    public["disposition"]["decision"], public["severity"]["final"] = "accept", "low"
    private = "https://github.com/org/m/security/advisories/GHSA-xxxx"
    sec = make(sample_finding, id="QOT-bbbbbbbbbb", area="security", category="security_vulnerability",
               prior_work=[{"id": "PW-2", "status": "reported", "upstream": [private]}])
    sec["sensitivity"] = {"sensitive": True, "reasons": ["area is security"], "removal_reason": None}
    sec["disposition"]["decision"], sec["severity"]["final"] = "accept", "high"
    md = render.to_markdown(render.build(MANIFEST, [public, sec], {}, tmp_path))
    assert f"**Raised before.** {UPSTREAM}" in md
    assert private not in md and "PW-2" not in md  # nothing about a security item beyond its row


def test_bad_prior_work_file_stops_the_run(tmp_path):
    d = tmp_path / "test__m"
    d.mkdir()
    (d / prior.FILE).write_text(yaml.safe_dump({"items": [{"id": "PW-1", "title": "x", "status": "maybe"}]}))
    with pytest.raises(prior.PriorWorkError):
        prior.load(d, "test/m")
