"""Render the per-repository Report from approved, structured fields only.

"Approved" means a person accepted the finding at triage. Rejected, deferred
and undecided findings never reach a report. Security rows show only an ID,
the severity a person set, and the date reported privately.
"""

from __future__ import annotations

import html
from collections import Counter
from pathlib import Path

CATEGORIES = [
    ("security_vulnerability", "Newly found security vulnerabilities"),
    ("dependency_advisory", "Known dependency advisories"),
    ("correctness", "Correctness defects (including silently wrong results)"),
    ("docs_tests_maintenance", "Documentation, test and maintenance defects"),
]
SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]


class NotReady(ValueError):
    pass


def approved(findings: list[dict]) -> list[dict]:
    return [f for f in findings if f["disposition"]["decision"] == "accept"]


def build(manifest: dict, findings: list[dict], scan_summary: dict, run_dir: Path) -> dict:
    """The structured Report. Only fields listed here can ever be shared."""
    acc = approved(findings)
    unset = [f["id"] for f in acc if not f["severity"]["final"]]
    if unset:
        raise NotReady(f"severity not set by a person for {', '.join(unset)}")
    acc.sort(key=lambda f: (SEVERITY_ORDER.index(f["severity"]["final"]), f["id"]))
    counts = Counter(f["category"] for f in acc)
    rows, details = [], []
    for f in acc:
        if f["sensitivity"]["sensitive"]:
            rows.append({"id": f["id"], "sensitive": True, "severity": f["severity"]["final"],
                         "kind": "Known dependency advisory" if f["category"] == "dependency_advisory"
                         else "Security finding",
                         "reported_privately": f["disposition"].get("reported_at") or "not yet reported"})
            continue
        found = sorted({d["tool"] for d in f["detection"]["detections"] if d["source"] == "model"})
        confirmed = sorted({v["verifier"] for v in f["corroboration"]["verifications"]
                            if v["verdict"] == "confirm" and v["independence"] == "independent"})
        fx = f.get("fix") or {}
        delivery = fx.get("delivery") or {}
        rows.append({"id": f["id"], "sensitive": False, "title": f["title"], "area": f["area"],
                     "severity": f["severity"]["final"], "validation": f["validation"]["status"],
                     "found_by": found, "confirmed_by": confirmed,
                     "scanners": sorted({d["tool"] for d in f["detection"]["detections"] if d["source"] == "scanner"}),
                     "location": f"{f['file']}:{f['line_start']}", "fix_branch": delivery.get("branch"),
                     "fix_status": fx.get("status", "no fix proposed"),
                     # Already raised upstream by the reviewer: say so, so it is not presented as new.
                     "raised_before": sorted({u for p in f.get("prior_work") or [] for u in p["upstream"]})})
        diff = None
        if fx.get("status") in ("validated", "checked_same_model_only") and fx.get("diff_ref"):
            p = run_dir / fx["diff_ref"]
            diff = p.read_text() if p.exists() else None
        details.append({"id": f["id"], "title": f["title"], "what": f["claim"], "why": f["why_it_matters"],
                        "validation": f"{f['validation']['status']}: {f['validation']['notes']}",
                        "fix_diff": diff, "fix_status": fx.get("status", "no fix proposed"),
                        "fix_caveats": [c["text"] for c in fx.get("caveats") or []],
                        "raised_before": sorted({u for p in f.get("prior_work") or [] for u in p["upstream"]})})
    used = [a for a in manifest["adapters"] if a.get("used")]
    scorecard = next((s for s in manifest["scanners"] if s["name"] == "scorecard"), None)
    return {
        "title": f"{manifest['repo']['name']}: review",
        "header": {
            "repository": manifest["repo"]["name"], "commit": manifest["repo"]["commit"],
            "review_date": (manifest.get("finished_at") or manifest["started_at"])[:10],
            "models": [{"cli": a["name"], "version": a["version"], "model_ids": a["model_ids"]} for a in used],
            "models_not_used": [{"cli": a["name"], "reason": a["reason"]} for a in manifest["adapters"] if not a.get("used")],
            "tools": [{"name": s["name"], "version": s["version"], "status": s["status"]} for s in manifest["scanners"]],
            "scope": manifest["repo"]["scope"], "completion": manifest["status"],
            "incomplete_checks": manifest["coverage"]["incomplete_checks"],
        },
        "scorecard": {"counts": {k: counts.get(k, 0) for k, _ in CATEGORIES},
                      "basis": "findings accepted after a person checked them",
                      "openssf_scorecard": (scorecard or {}).get("status", "unavailable")},
        "hygiene": {k: v.get("hygiene", {}) for k, v in scan_summary.items() if k in ("ruff", "lychee", "bandit", "project-tests")},
        "triage": rows,
        "details": details,
        "how_produced": {"method": "https://github.com/marqov-dev/quantum-oss-triage",
                         "harness_revision": manifest["harness_revision"], "run_id": manifest["run_id"],
                         "statement": "Recorded, integrity-checkable and rerunnable. A rerun is not guaranteed to give identical model answers."},
        "call_to_action": "Sign up for Marqov, or contact David Ryan about ongoing review.",
    }


def to_markdown(r: dict) -> str:
    h = r["header"]
    out = [f"# {r['title']}", "",
           f"Commit `{h['commit']}` · reviewed {h['review_date']} · completion: **{h['completion']}**", "",
           "**Models:** " + (", ".join(f"{m['cli']} {m['version'] or ''} ({', '.join(m['model_ids']) or 'model id not reported'})" for m in h["models"]) or "none"),
           ]
    if h["models_not_used"]:
        out.append("**Not used:** " + ", ".join(f"{m['cli']} ({m['reason']})" for m in h["models_not_used"]))
    out += ["", "**Tools:** " + ", ".join(f"{t['name']} {t['version'] or ''} [{t['status']}]" for t in h["tools"]),
            "", f"**Scope:** include {h['scope']['include'] or ['whole repository']}; exclude {h['scope']['exclude'] or ['nothing']}"]
    if h["incomplete_checks"]:
        out += ["", "**Not complete:**"] + [f"- {c}" for c in h["incomplete_checks"]]
    out += ["", "## Scorecard", "", f"Counts are {r['scorecard']['basis']}.", "", "| Category | Count |", "| --- | --- |"]
    out += [f"| {label} | {r['scorecard']['counts'][key]} |" for key, label in CATEGORIES]
    out += [f"| OpenSSF Scorecard | {r['scorecard']['openssf_scorecard']} |", "", "## Triage list", ""]
    if not r["triage"]:
        out.append("No accepted findings within the stated scope.")
    else:
        out += ["| ID | Title | Area | Severity | Validation | Found by | Confirmed by | Location | Fix |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for t in r["triage"]:
            if t["sensitive"]:
                out.append(f"| {t['id']} | {t['kind']}, reported privately | security | {t['severity']} | - | - | - | - | reported: {t['reported_privately']} |")
            else:
                out.append(f"| {t['id']} | {t['title']} | {t['area']} | {t['severity']} | {t['validation']} | "
                           f"{', '.join(t['found_by'] + t['scanners']) or '-'} | {', '.join(t['confirmed_by']) or '-'} | "
                           f"`{t['location']}` | {t['fix_branch'] or '-'} ({t['fix_status']}) |")
    for d in r["details"]:
        out += ["", f"### {d['id']} · {d['title']}", "", f"**What is wrong.** {d['what']}", "",
                f"**Why it matters.** {d['why']}", "", f"**How it was checked.** {d['validation']}", "",
                f"**Fix status.** {d['fix_status']}"]
        if d.get("raised_before"):
            out += ["", f"**Raised before.** {', '.join(d['raised_before'])}"]
        for c in d.get("fix_caveats") or []:
            out += ["", f"**Caveat on the fix.** {c}"]
        if d["fix_diff"]:
            out += ["", "```diff", d["fix_diff"].rstrip(), "```"]
    hp = r["how_produced"]
    out += ["", "## How this was produced", "", f"Method: {hp['method']} (harness `{hp['harness_revision']}`, run `{hp['run_id']}`).",
            "", hp["statement"], "", "---", "", r["call_to_action"], ""]
    return "\n".join(out)


_CSS = """:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#5d5b55;--line:#dedad2;--accent:#2f5d8a;--code:#f0ede6}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#17181a;--fg:#e9e7e2;--muted:#a3a09a;--line:#34363a;--accent:#8db6e0;--code:#222428}}
:root[data-theme=dark]{--bg:#17181a;--fg:#e9e7e2;--muted:#a3a09a;--line:#34363a;--accent:#8db6e0;--code:#222428}
body{background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,sans-serif;margin:0;padding:24px 16px}
main{max-width:980px;margin:0 auto}h1,h2,h3{line-height:1.25}a{color:var(--accent)}
table{border-collapse:collapse;width:100%;display:block;overflow-x:auto;font-size:14px}
td,th{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
code,pre{background:var(--code);border-radius:4px;font-size:13px}pre{padding:12px;overflow-x:auto}.muted{color:var(--muted)}"""


def to_html(r: dict) -> str:
    """A self-contained HTML page with no external resources."""
    md = to_markdown(r)
    body, in_code, in_table = [], False, False
    for line in md.splitlines():
        if line.startswith("```"):
            body.append("<pre><code>" if not in_code else "</code></pre>")
            in_code = not in_code
            continue
        if in_code:
            body.append(html.escape(line))
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set("".join(cells)) <= set("- "):
                continue
            if not in_table:
                body.append("<table>")
                in_table = True
                body.append("<tr>" + "".join(f"<th>{_inline(c)}</th>" for c in cells) + "</tr>")
            else:
                body.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            body.append("</table>")
            in_table = False
        if line.startswith("### "):
            body.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            body.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            body.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("- "):
            body.append(f"<p>• {_inline(line[2:])}</p>")
        elif line == "---":
            body.append("<hr>")
        elif line.strip():
            body.append(f"<p>{_inline(line)}</p>")
    if in_table:
        body.append("</table>")
    return (f"<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(r['title'])}</title><style>{_CSS}</style><main>" + "\n".join(body) + "</main></html>\n")


def _inline(text: str) -> str:
    import re

    t = html.escape(text)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)


def public_summary(reports: list[dict]) -> dict:
    """Per-project counts only. No titles, locations or details."""
    return {"title": "Quantum open-source review, round one (2026): public summary",
            "projects": [{"repository": r["header"]["repository"], "commit": r["header"]["commit"],
                          "scope": r["header"]["scope"], "completion": r["header"]["completion"],
                          "counts": r["scorecard"]["counts"]} for r in reports],
            "basis": "findings accepted after a person checked them"}
