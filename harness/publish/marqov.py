"""Marqov publisher.

Round one writes the hub Project's documents as local files only, until the
platform's multiple-documents feature (marqov-platform PRs #2943 and #2971) is
merged and deployed. The layout mirrors what will be written: per repository,
a Workspace "<org>/<repo>: run record" and a Report "<org>/<repo>: review".

The Marqov API key lives only at ~/.config/marqov/api-key and is read only by
the live client below, which is deliberately not implemented yet.
"""

from __future__ import annotations

import json
from pathlib import Path

HUB_PROJECT = "Quantum open-source review, round one (2026)"
API_KEY_PATH = Path.home() / ".config" / "marqov" / "api-key"


def workspace_document(manifest: dict, scan_summary: dict) -> dict:
    """The run-record Workspace: redacted manifest, commands, scanner summary, stage status."""
    redacted_scans = {k: {"status": v["status"], "version": v.get("version"),
                          "note": v.get("note", "") if v["status"] in ("ok", "not_applicable", "unavailable") else "",
                          "counts": {hk: hv for hk, hv in (v.get("hygiene") or {}).items() if not isinstance(hv, (list, dict))}}
                      for k, v in scan_summary.items()}
    return {
        "title": f"{manifest['repo']['name']}: run record",
        "blocks": [
            {"type": "markdown", "text": f"Commit `{manifest['repo']['commit']}`, run `{manifest['run_id']}`, "
                                         f"harness `{manifest['harness_revision']}`. Status: {manifest['status']}."},
            {"type": "script", "language": "bash",
             "text": f"qot run --repo {manifest['repo']['name']} --run-dir runs/{manifest['run_id']}"},
            {"type": "json", "name": "adapters", "data": manifest["adapters"]},
            {"type": "json", "name": "scanners", "data": redacted_scans},
            {"type": "json", "name": "stages", "data": manifest["stages"]},
            {"type": "json", "name": "tokens", "data": manifest["tokens"]},
            {"type": "json", "name": "completion", "data": {
                "reviewed": manifest["coverage"]["reviewed"], "not_reviewed": manifest["coverage"]["not_reviewed"],
                "incomplete_checks": manifest["coverage"]["incomplete_checks"]}},
        ],
    }


def write_local(outbox: Path, slug: str, workspace: dict, report: dict, report_md: str, report_html: str) -> Path:
    d = Path(outbox) / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "workspace.json").write_text(json.dumps({"project": HUB_PROJECT, **workspace}, indent=2))
    (d / "report.json").write_text(json.dumps({"project": HUB_PROJECT, **report}, indent=2))
    (d / "report.md").write_text(report_md)
    (d / "report.html").write_text(report_html)
    return d


class MarqovClient:
    """Live writes to the hub Project. Not implemented in v0.1."""

    def __init__(self):
        raise NotImplementedError(
            "Live Marqov publishing waits for marqov-platform PRs #2943 and #2971; v0.1 writes local files only.")
