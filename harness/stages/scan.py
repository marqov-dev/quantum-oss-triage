"""Stage 2: fixed scanners (no AI), each in a worker."""

from __future__ import annotations

from dataclasses import asdict

from harness.controller.context import RepoContext
from harness.scanners import all_scanners, tool_versions
from harness.scanners.base import ScanResult


def in_scope(path: str, include: list[str], exclude: list[str]) -> bool:
    def under(p, root):
        return p == root or p.startswith(root.rstrip("/") + "/")
    if include and not any(under(path, i) for i in include):
        return False
    return not any(under(path, e) for e in exclude)


def run(ctx: RepoContext) -> list[dict]:
    scanners = all_scanners()
    results: list[ScanResult] = []
    worker_ok, why = ctx.worker.available() if ctx.worker else (False, "no worker configured")
    versions = tool_versions(ctx.worker, ctx.source_dir) if worker_ok else {}
    ctx.manifest.data["worker_image"] = ctx.worker.describe() if ctx.worker else {"tag": "", "digest": None}
    for s in scanners:
        unit = ctx.ledger.unit(ctx.spec.name, "scan", s.name, None)
        if unit.done():
            results.append(ScanResult(**unit.payload()))
            continue
        if not worker_ok and s.name != "scorecard":
            r = ScanResult(s.name, "unavailable", note=f"worker unavailable: {why}")
        else:
            ctx.log(f"  scan {s.name} ...")
            r = s.run(ctx.worker, ctx.source_dir, versions)
        # Raw output lives in the private evidence store; the unit keeps the summary.
        if r.raw:
            (ctx.repo_dir / "evidence" / "scans").mkdir(parents=True, exist_ok=True)
            (ctx.repo_dir / "evidence" / "scans" / f"{s.name}.json").write_text(r.raw)
        summary = asdict(r)
        summary["raw"] = ""
        # "unavailable" is rerun next time (the image or Docker may be back).
        unit.save({"ok": "done", "not_applicable": "done", "unavailable": "skipped"}.get(r.status, "failed"), summary)
        results.append(r)
    ctx.manifest.data["scanners"] = [r.manifest_entry() for r in results]
    for entry in ctx.manifest.data["scanners"]:
        if entry["status"] == "failed":  # tool output can quote repository content
            entry["note"] = "failed (details in the private run record)"
    for r in results:
        if r.status == "failed":
            ctx.manifest.incomplete(f"scanner {r.name}: failed (details in the private run record)")
        elif r.status == "unavailable":
            ctx.manifest.incomplete(f"scanner {r.name}: unavailable ({r.note})")
    leads = []
    for r in results:
        for f in r.findings:
            if in_scope(f["file"], ctx.spec.include, ctx.spec.exclude):
                leads.append({**f, "unit": f"{ctx.spec.name}/scan/{r.name}/-", "skill": None, "model_id": None})
    ctx.write_json("scan-summary.json", {r.name: {"status": r.status, "version": r.version, "hygiene": r.hygiene,
                                                  "note": r.note, "leads": len(r.findings)} for r in results})
    ctx.write_json("leads.json", leads)
    return leads
