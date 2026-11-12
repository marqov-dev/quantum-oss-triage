"""The publisher process: python -m harness.publish RUN_DIR [--repo NAME] [--public-summary] [--live].

It reads only the run's approved, structured files and writes the shareable
documents: always to the local outbox, and to the hub Marqov Project only with
--live (otherwise it prints what it would upload). It imports nothing that runs
AI tools or workers.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from harness.paths import REPO_ROOT
from harness.publish import github, marqov, overview, redact, render, tiered


def publish_tiered(run_dir: Path, repo_dir: Path, outbox: Path, manifest: dict, findings: list[dict],
                   scans: dict) -> tuple[bool, dict]:
    """The report sorted by evidence (no per-finding decisions), as several Marqov blocks.
    Security details stay out; known dependency advisories are shown in full
    (docs/DISCLOSURE.md)."""
    report = tiered.load(run_dir, repo_dir)
    d = outbox / repo_dir.name
    d.mkdir(parents=True, exist_ok=True)
    parts, ev_parts = tiered.to_blocks(report), tiered.to_evidence_blocks(report)
    text = lambda ps: "\n\n".join(v for k, v in ps if k == "markdown")
    md, evidence = text(parts), text(ev_parts)
    workspace = marqov.workspace_document(manifest, scans)
    sensitive = [f for f in findings if f["sensitivity"]["sensitive"] and f["category"] != "dependency_advisory"]
    name = manifest["repo"]["name"]
    approved = redact.load_approvals(run_dir, name)
    # Check exactly what is shared: the two documents and the workspace record.
    shared = md + "\n" + evidence + "\n" + marqov.workspace_markdown(workspace)
    problems = redact.check(shared, sensitive, approved_phrases=approved)
    if problems:
        (d / "BLOCKED.txt").write_text("Not written: the sensitive-content check found:\n" + "\n".join(problems) + "\n")
        return False, {"repo": manifest["repo"]["name"], "blocked": problems}
    local_md = tiered.blocks_markdown(parts)
    marqov.write_local(outbox, repo_dir.name, workspace, report, local_md, render.markdown_to_html(local_md, report["title"]))
    (d / "evidence.md").write_text(tiered.blocks_markdown(ev_parts))
    (d / "BLOCKED.txt").unlink(missing_ok=True)
    # Record which approved phrases this publish relied on, so an audit can see what passed and why.
    used = redact.approved_used(shared, approved)
    (d / "APPROVED-PHRASES.json").unlink(missing_ok=True)
    if used:
        (d / "APPROVED-PHRASES.json").write_text(json.dumps(used, indent=2) + "\n")
    docs = [marqov.PlannedDoc(f"{name}:workspace", "workspace", workspace["title"], marqov.workspace_markdown(workspace),
                              sensitive, target="repo", repo=name, approved_phrases=approved),
            marqov.PlannedDoc(f"{name}:report", "report", report["title"], md, sensitive, share=True,
                              target="repo", repo=name, parts=parts, approved_phrases=approved),
            marqov.PlannedDoc(f"{name}:evidence", "report", f"{report['title']}: evidence", evidence, sensitive,
                              share=True, target="repo", repo=name, parts=ev_parts, approved_phrases=approved)]
    result = {"repo": name, "written": str(d), "report": report, "docs": docs, "sensitive": sensitive}
    if used:
        result["approved_phrases_used"] = used
    return True, result


def publish_repo(run_dir: Path, repo_dir: Path, outbox: Path) -> tuple[bool, dict]:
    manifest = json.loads((repo_dir / "manifest.json").read_text())
    findings = json.loads((repo_dir / "findings.json").read_text()) if (repo_dir / "findings.json").exists() else []
    scans = json.loads((repo_dir / "scan-summary.json").read_text()) if (repo_dir / "scan-summary.json").exists() else {}
    if (repo_dir / "gates.json").exists():
        return publish_tiered(run_dir, repo_dir, outbox, manifest, findings, scans)
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
    name = manifest["repo"]["name"]
    docs = [marqov.PlannedDoc(f"{name}:workspace", "workspace", workspace["title"], marqov.workspace_markdown(workspace),
                              sensitive, target="repo", repo=name),
            marqov.PlannedDoc(f"{name}:report", "report", report["title"], md, sensitive, share=True,
                              target="repo", repo=name)]
    return True, {"repo": name, "written": str(d), "report": report, "docs": docs, "sensitive": sensitive}


def _models(path: Path | None = None) -> dict[str, str | None]:
    """The configured models and their model ids, in config order (for the round overview)."""
    data = yaml.safe_load((path or REPO_ROOT / "config" / "harness.yaml").read_text()) or {}
    return {name: (m or {}).get("model") for name, m in (data.get("models") or {}).items()}


def overview_doc(run_dir: Path, outbox: Path, sensitive: list, config: Path | None = None) -> "marqov.PlannedDoc":
    """The round's main page: progress only, from every repository's run record, shared widely."""
    record = outbox / "marqov-published.json"
    published = json.loads(record.read_text()) if record.is_file() else {}
    models = _models(config)
    parts = overview.to_blocks(overview.build(run_dir, list(models), published), models)
    md = "\n\n".join(v for k, v in parts if k == "markdown")
    outbox.mkdir(parents=True, exist_ok=True)
    (outbox / "overview.md").write_text(tiered.blocks_markdown(parts))
    return marqov.PlannedDoc("round:overview", "report", overview.TITLE, md, sensitive, share=True,
                             target="hub", parts=parts)


def _marqov_targets(path: Path | None = None, local: Path | None = None) -> marqov.Targets:
    data = yaml.safe_load((path or REPO_ROOT / "config" / "harness.yaml").read_text()) or {}
    local = Path(local or marqov.LOCAL_TARGETS_PATH)
    over = (yaml.safe_load(local.read_text()) or {}) if local.is_file() else {}
    return marqov.Targets.from_settings(marqov.merge_settings((data.get("publish") or {}).get("marqov"), over))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m harness.publish")
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--repo", action="append", help="repository name (default: all in the run)")
    ap.add_argument("--outbox", type=Path)
    ap.add_argument("--public-summary", action="store_true")
    ap.add_argument("--config", type=Path, help="harness.yaml with the publish.marqov targets")
    ap.add_argument("--live", action="store_true",
                    help="upload to the configured Marqov Projects (default: dry run, the key is not read)")
    ap.add_argument("--overview-only", action="store_true",
                    help="publish only the round overview (progress for every repository), no repository documents")
    args = ap.parse_args(argv)
    outbox = args.outbox or args.run_dir / "outbox"
    repo_dirs = sorted(p.parent for p in args.run_dir.glob("*/manifest.json"))
    every_sensitive = [f for d in repo_dirs if (d / "findings.json").is_file()
                       for f in json.loads((d / "findings.json").read_text())
                       if f.get("sensitivity", {}).get("sensitive") and f.get("category") != "dependency_advisory"]
    if args.overview_only:
        repo_dirs = []
    if args.repo:
        wanted = {r.replace("/", "__") for r in args.repo}
        repo_dirs = [d for d in repo_dirs if d.name in wanted]
    results, reports, docs, sensitive, not_published, ok_all = [], [], [], [], [], True
    for d in repo_dirs:
        ok, res = publish_repo(args.run_dir, d, outbox)
        ok_all &= ok
        if ok:
            reports.append(res.pop("report"))
            docs += res.pop("docs")
            sensitive += res.pop("sensitive")
        else:
            not_published.append(res["repo"])
        results.append(res)
    targets = _marqov_targets(args.config)
    # The overview covers every repository, so it is checked against every sensitive finding.
    over = overview_doc(args.run_dir, outbox, every_sensitive, args.config)
    if problems := redact.check(over.content, every_sensitive):
        results.append({"overview": "blocked", "problems": problems})
        ok_all = False
    else:
        docs.append(over)
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
            docs.append(marqov.PlannedDoc("round:public-summary", "report", marqov.PUBLIC_SUMMARY_TITLE,
                                          marqov.public_summary_markdown(summary, targets.show_security_counts), sensitive, share=True,
                                          target="hub"))
    record_path = outbox / "marqov-published.json"
    if args.live:
        problems = targets.problems(docs)
        if problems:
            print(json.dumps(results + [{"marqov": "not uploaded", "problems": problems}], indent=2))
            return 1
        try:
            uploaded = marqov.publish_live(docs, targets, lambda kp: marqov.MarqovClient(targets.base_url, key_path=kp),
                                           record_path)
        except (FileNotFoundError, ValueError) as e:
            print(json.dumps(results + [{"marqov": "not uploaded", "reason": str(e)}], indent=2))
            return 1
        ok_all &= all(u["status"] in ("created", "updated", "unchanged") for u in uploaded)
        results.append({"marqov": {"documents": uploaded, "share_links_to_create_in_the_web_app":
                                   marqov.share_link_todo(marqov.load_record(record_path))}})
    else:
        results.append({"marqov": {"dry_run": True,
                                   "would_upload": marqov.plan_summary(docs, marqov.load_record(record_path), targets),
                                   "live_blocked_by": targets.problems(docs),
                                   "live_checks_first": (["team membership: the hub's team must have one member, "
                                                          "or hub.single_member_confirmed must be set"]
                                                         if any(targets.repo_in_hub(d) for d in docs) else []),
                                   "note": "rerun with --live to upload; share links are created in the web app"}})
    print(json.dumps(results, indent=2))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
