"""The publisher process: python -m harness.publish RUN_DIR [--repo NAME] [--public-summary].

It reads only the run's approved, structured files and writes the shareable
documents. It imports nothing that runs AI tools or workers.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness.publish import github, marqov, redact, render


def publish_repo(run_dir: Path, repo_dir: Path, outbox: Path) -> tuple[bool, dict]:
    manifest = json.loads((repo_dir / "manifest.json").read_text())
    findings = json.loads((repo_dir / "findings.json").read_text()) if (repo_dir / "findings.json").exists() else []
    scans = json.loads((repo_dir / "scan-summary.json").read_text()) if (repo_dir / "scan-summary.json").exists() else {}
    try:
        report = render.build(manifest, findings, scans, run_dir)
    except render.NotReady as e:
        return False, {"repo": manifest["repo"]["name"], "blocked": [str(e)]}
    md, page = render.to_markdown(report), render.to_html(report)
    workspace = marqov.workspace_document(manifest, scans)
    sensitive = [f for f in render.approved(findings) if f["sensitivity"]["sensitive"]]
    # Rejected or undecided sensitive findings must not leak either.
    sensitive += [f for f in findings if f["sensitivity"]["sensitive"] and f["disposition"]["decision"] != "accept"]
    problems = redact.check(md + json.dumps(report) + json.dumps(workspace), sensitive)
    slug = repo_dir.name
    if problems:
        d = outbox / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "BLOCKED.txt").write_text("Not written: the sensitive-content check found:\n" + "\n".join(problems) + "\n")
        return False, {"repo": manifest["repo"]["name"], "blocked": problems}
    d = marqov.write_local(outbox, slug, workspace, report, md, page)
    (d / "planned-branches.json").write_text(json.dumps(github.planned_branches(findings), indent=2))
    (d / "BLOCKED.txt").unlink(missing_ok=True)
    return True, {"repo": manifest["repo"]["name"], "written": str(d), "report": report}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m harness.publish")
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--repo", action="append", help="repository name (default: all in the run)")
    ap.add_argument("--outbox", type=Path)
    ap.add_argument("--public-summary", action="store_true")
    args = ap.parse_args(argv)
    outbox = args.outbox or args.run_dir / "outbox"
    repo_dirs = sorted(p.parent for p in args.run_dir.glob("*/manifest.json"))
    if args.repo:
        wanted = {r.replace("/", "__") for r in args.repo}
        repo_dirs = [d for d in repo_dirs if d.name in wanted]
    results, reports, ok_all = [], [], True
    for d in repo_dirs:
        ok, res = publish_repo(args.run_dir, d, outbox)
        ok_all &= ok
        if ok:
            reports.append(res.pop("report"))
        results.append(res)
    if args.public_summary and reports:
        summary = render.public_summary(reports)
        problems = redact.check(json.dumps(summary), [])
        if problems:
            results.append({"public_summary": "blocked", "problems": problems})
            ok_all = False
        else:
            outbox.mkdir(parents=True, exist_ok=True)
            (outbox / "public-summary.json").write_text(json.dumps(summary, indent=2))
            results.append({"public_summary": str(outbox / "public-summary.json")})
    print(json.dumps(results, indent=2))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
