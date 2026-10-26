"""Stage 6: human triage. Writes triage.md and a decisions.yaml template, and
applies the decisions a person has recorded.

Nothing here decides for the reviewer. Every decision, severity and change to
the sensitive flag comes from decisions.yaml.
"""

from __future__ import annotations

from datetime import datetime, timezone

import yaml

from harness.controller import merge
from harness.controller.context import RepoContext
from harness.controller.ledger import now

DECISIONS = ("pending", "accept", "reject", "duplicate", "defer", "investigate")

_HEADER = """# Decisions for {repo} at {commit}
#
# One entry per finding in triage.md. For each, set:
#   decision: accept | reject | duplicate | defer | investigate   (pending = not decided)
#   severity: critical | high | medium | low | info               (you set it; models only propose)
#   sensitive: true | false     clearing a flag that the rules set needs removal_reason
#   duplicate_of: QOT-...       when decision is duplicate
#   note: free text
# Then run:  qot triage-apply {run_dir} --repo {repo}
"""


def _loc(f: dict) -> str:
    return f"{f['file']}:{f['line_start']}" + (f"-{f['line_end']}" if f["line_end"] != f["line_start"] else "")


def _models(ctx: RepoContext) -> str:
    rows = ctx.manifest.data.get("adapters", [])
    used = [a["name"] for a in rows if a.get("used")]
    missing = [f"{a['name']} ({a['reason']})" for a in rows if not a.get("used")]
    return f"used: {', '.join(used) or 'none'}; not used: {', '.join(missing) or 'none'}"


def render_triage(ctx: RepoContext, findings: list[dict]) -> str:
    main = sorted((f for f in findings if f["disposition"]["queue"] == "main"),
                  key=lambda f: not f["sensitivity"]["sensitive"])
    low = [f for f in findings if f["disposition"]["queue"] == "low"]
    m = ctx.manifest.data
    lines = [f"# Triage: {ctx.spec.name} at `{ctx.commit[:12]}`", "",
             f"Generated {now()} for {ctx.config.reviewer}. Record decisions in `decisions.yaml` "
             f"(same folder), then run `qot triage-apply {ctx.run_dir} --repo {ctx.spec.name}`.", "",
             "This file is private: it contains security details.", "",
             "## Completion", "",
             f"- Models: {_models(ctx)}",
             f"- Scope: include {ctx.spec.include or ['(whole repository)']}, exclude {ctx.spec.exclude or []}",
             f"- Incomplete checks: {len(m['coverage']['incomplete_checks'])}"]
    lines += [f"  - {c}" for c in m["coverage"]["incomplete_checks"]]
    lines += ["", f"## Main queue ({len(main)})", ""]
    if not main:
        lines += ["No finding met the main-queue rule.", ""]
    for f in main:
        lines += _detail(f)
    lines += [f"## Low-priority list ({len(low)})", "",
              "Refuted, single-source or unconfirmed claims. Skim; promote any you believe by deciding it.", "",
              "| ID | Title | Location | Proposed | Why low |", "| --- | --- | --- | --- | --- |"]
    for f in low:
        lines.append(f"| {f['id']} | {f['title']} | {_loc(f)} | {merge.top_proposed_severity(f)} | "
                     f"{f['disposition']['queue_reason']} |")
    lines += ["", "## Scanner hygiene counts", ""]
    for name, s in (ctx.read_json("scan-summary.json", {}) or {}).items():
        lines.append(f"- **{name}** ({s['status']}{', ' + s['version'] if s.get('version') else ''}): "
                     f"{_hygiene(s.get('hygiene', {}))}{' ' + s['note'] if s.get('note') else ''}")
    return "\n".join(lines) + "\n"


def _hygiene(h: dict) -> str:
    return ", ".join(f"{k} {v}" for k, v in h.items() if not isinstance(v, (list, dict))) or "-"


def _detail(f: dict) -> list[str]:
    sens = f["sensitivity"]
    out = [f"### {f['id']} · {f['title']}", "",
           f"- **Area:** {f['area']} ({f['category']}) · **Location:** `{_loc(f)}`",
           f"- **Sensitive:** {'yes: ' + '; '.join(sens['reasons']) if sens['sensitive'] else 'no'}",
           f"- **Queue:** {f['disposition']['queue_reason']}",
           f"- **Proposed severity:** " + ", ".join(f"{p['by']}={p['value']}" for p in f["severity"]["proposed"]),
           f"- **Detected by:** " + ", ".join(sorted({d['tool'] + (f'/{d['skill']}' if d.get('skill') else '') for d in f['detection']['detections']})),
           f"- **Corroboration:** {f['corroboration']['status']}",
           f"- **Validation:** {f['validation']['status']}: {f['validation']['notes']}"
           + (f" (evidence: `{f['validation']['evidence_ref']}`)" if f["validation"].get("evidence_ref") else ""),
           "", f"**Claim.** {f['claim']}", "", f"**Evidence.** {f['evidence']}", "",
           f"**Why it matters.** {f['why_it_matters']}", ""]
    if f.get("applies_because"):
        out += [f"**Applies because.** {f['applies_because']}", ""]
    if f["corroboration"]["verifications"]:
        out += ["| Verifier | Independence | Verdict | Reason |", "| --- | --- | --- | --- |"]
        for v in f["corroboration"]["verifications"]:
            out.append(f"| {v['verifier']} | {v['independence']} | {v['verdict']} | {v['reason'][:400].replace('|', '/').replace(chr(10), ' ')} |")
        out.append("")
    return out


def write(ctx: RepoContext, findings: list[dict]) -> None:
    (ctx.repo_dir / "triage.md").write_text(render_triage(ctx, findings))
    path = ctx.repo_dir / "decisions.yaml"
    existing = (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}
    entries = existing.get("findings", {}) if isinstance(existing, dict) else {}
    for f in findings:
        entries.setdefault(f["id"], {"title": f["title"], "queue": f["disposition"]["queue"], "decision": "pending",
                                     "severity": None, "sensitive": f["sensitivity"]["sensitive"],
                                     "removal_reason": None, "duplicate_of": None, "note": ""})
    doc = {"reviewer": existing.get("reviewer", ctx.config.reviewer), "triage_minutes": existing.get("triage_minutes"),
           "findings": entries}
    path.write_text(_HEADER.format(repo=ctx.spec.name, commit=ctx.commit[:12], run_dir=ctx.run_dir)
                    + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    ctx.manifest.stage("triage", "complete" if ctx.manifest.data["stages"]["triage"].get("applied_at") else "running",
                       generated_at=now(), main_queue=sum(f["disposition"]["queue"] == "main" for f in findings))


class DecisionError(ValueError):
    pass


def apply(ctx: RepoContext, decided_by: str | None = None) -> dict:
    """Apply decisions.yaml to findings.json. Returns counts by decision."""
    findings = ctx.read_json("findings.json", [])
    path = ctx.repo_dir / "decisions.yaml"
    doc = yaml.safe_load(path.read_text()) or {}
    entries = doc.get("findings", {})
    reviewer = decided_by or doc.get("reviewer") or ctx.config.reviewer
    errors, counts = [], {}
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for f in findings:
        d = entries.get(f["id"])
        if not d:
            continue
        decision = d.get("decision") or "pending"
        if decision not in DECISIONS:
            errors.append(f"{f['id']}: unknown decision {decision!r}")
            continue
        if d.get("severity") and d["severity"] not in merge.SEVERITY_ORDER:
            errors.append(f"{f['id']}: unknown severity {d['severity']!r}")
            continue
        if decision == "duplicate" and not d.get("duplicate_of"):
            errors.append(f"{f['id']}: duplicate needs duplicate_of")
            continue
        sens = f["sensitivity"]
        if d.get("sensitive") is False and sens["sensitive"] and sens["reasons"] != ["set by reviewer"]:
            if not d.get("removal_reason"):
                errors.append(f"{f['id']}: clearing the sensitive flag needs removal_reason")
                continue
            sens.update(sensitive=False, removal_reason=d["removal_reason"])
        elif d.get("sensitive") is True and not sens["sensitive"]:
            sens.update(sensitive=True, reasons=sens["reasons"] + ["set by reviewer"])
            f["disposition"].update(queue="main", queue_reason="security impact: always triaged by a person")
        if decision != "pending":
            f["disposition"].update(decision=decision, decided_by=reviewer, decided_at=stamp,
                                    note=d.get("note") or "", duplicate_of=d.get("duplicate_of"))
        if d.get("severity"):
            f["severity"].update(final=d["severity"], set_by=reviewer)
        counts[decision] = counts.get(decision, 0) + 1
    if errors:
        raise DecisionError("; ".join(errors))
    ctx.write_json("findings.json", findings)
    ctx.manifest.stage("triage", "complete", applied_at=stamp, decided_by=reviewer, decisions=counts,
                       triage_minutes=doc.get("triage_minutes"))
    (ctx.repo_dir / "triage.md").write_text(render_triage(ctx, findings))
    return counts
