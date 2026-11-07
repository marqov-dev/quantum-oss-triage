"""The round's main page shows progress only, from the run records."""

import json

from harness.publish import overview, redact


def _repo(root, name, stages, units):
    d = root / name.replace("/", "__")
    (d / "units").mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"repo": {"name": name},
                                                 "stages": {s: {"status": v} for s, v in stages.items()}}))
    for i, (stage, model, status) in enumerate(units):
        (d / "units" / f"{stage}__X{i}__{model}.json").write_text(json.dumps({"status": status}))
    return d


ALL = {s: "complete" for s in ("review", "verify", "validate", "gates", "challenge", "fixgate")}


def test_status_reached_and_model_cells(tmp_path):
    _repo(tmp_path, "o/done", ALL, [("review", "claude", "done"), ("review", "antigravity", "done")])
    _repo(tmp_path, "o/fixed", {**ALL, "fixgate": "incomplete"}, [("review", "claude", "done")])
    _repo(tmp_path, "o/paused", {"review": "complete", "verify": "paused"},
          [("review", "claude", "done"), ("review", "antigravity", "done"), ("review", "antigravity", "failed"),
           ("verify", "codex", "done"), ("verify", "codex", "failed")])
    _repo(tmp_path, "o/new", {}, [])
    s = overview.build(tmp_path, ["claude", "codex", "antigravity"], {"o/done:report": {}})
    by = {r["repo"]: r for r in s["rows"]}
    assert [r["repo"] for r in s["rows"]] == ["o/done", "o/fixed", "o/paused", "o/new"]
    assert by["o/done"]["reached"] == "Report" and by["o/done"]["report"] == "in Marqov"
    assert by["o/fixed"]["reached"] == "Fixed blind" and by["o/fixed"]["report"] == "being checked"
    assert by["o/paused"]["reached"] == "Reviewed"  # a paused cross-check is not counted
    assert by["o/paused"]["models"] == {"claude": "✅", "codex": "not yet", "antigravity": "review in progress"}
    assert by["o/new"]["reached"] == "–"
    assert dict(s["funnel"]) == {"Reviewed": 3, "Cross-checked": 2, "Tested": 2, "Challenged": 2,
                                 "Fixed blind": 2, "Report": 1}


def test_codex_cross_check_in_progress(tmp_path):
    _repo(tmp_path, "o/r", {"review": "complete"},
          [("review", "codex", "done"), ("verify", "codex", "done"), ("verify", "codex", "failed")])
    assert overview.build(tmp_path, ["codex"], {})["rows"][0]["models"]["codex"] == "cross-check in progress"


def test_page_has_sections_no_findings_and_passes_the_check(tmp_path):
    _repo(tmp_path, "o/done", ALL, [("review", "claude", "done")])
    parts = overview.to_blocks(overview.build(tmp_path, ["claude", "antigravity"], {}), {"claude": "claude-opus-5-5"})
    md = "\n\n".join(v for _, v in parts)
    sections = [v for _, v in parts if v.startswith("## ")]
    assert sections == ["## Progress", "## Models", "## Projects", "## How each project is reviewed",
                        "## Run this on your own code"]
    assert "| o/done | ✅ | not yet | Fixed blind | being checked |" in md
    assert "`claude-opus-5-5`" in md and "https://marqov.ai/request-access" in md
    assert "defect" not in md.lower() and "QOT-" not in md
    assert " of 1 |" in md and not any(" of " in line for line in md.split("## Projects")[1].splitlines()[4:])
    assert redact.check(md, []) == []
