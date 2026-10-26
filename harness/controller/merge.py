"""Group duplicate claims, merge them by root cause, and apply the evidence rules.

Every original claim is kept inside the merged record's detections. The rules
here are deliberately small and explicit so they can be audited and tuned:

- Main queue: anything sensitive (security impact is always looked at by a
  person, even when refuted), or validated, or found independently by two
  models, or confirmed by an independent verifier with no refutation, or
  disputed (confirm + refute).
- Sensitive: area security, or any model marked security impact, or raised by
  a secrets, advisory or workflow scanner. Severity never decides this.
"""

from __future__ import annotations

import hashlib
import re

from harness import secrets
from harness.controller import snapshot

SENSITIVE_SCANNERS = {"gitleaks", "osv-scanner", "zizmor"}
MODEL_TOOLS = {"claude", "codex", "antigravity"}
SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]
_FAMILY = {"security": "security", "correctness": "logic", "quantum": "logic", "docs": "docs",
           "tests": "tests", "maintenance": "maintenance"}
_WORD = re.compile(r"[a-z0-9_]{3,}")


def family(area: str) -> str:
    return _FAMILY.get(area, area)


def fingerprint(area: str, path: str, snippet: str) -> str:
    norm = re.sub(r"\s+", "", snippet or "")
    return f"{family(area)}:{path}:{hashlib.sha256(norm.encode()).hexdigest()[:12]}"


def stable_id(repo: str, fp: str) -> str:
    return "QOT-" + hashlib.sha256(f"{repo}|{fp}".encode()).hexdigest()[:10]


def _words(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower()))


def _same_issue(a: dict, b: dict, slack: int = 2) -> bool:
    if a["file"] != b["file"]:
        return False
    if a["line_start"] > b["line_end"] + slack or b["line_start"] > a["line_end"] + slack:
        return False
    same_family = family(a["area"]) == family(b["area"])
    if same_family and (a["tool"] not in MODEL_TOOLS or b["tool"] not in MODEL_TOOLS):
        return True
    wa, wb = _words(a["title"] + " " + a["claim"]), _words(b["title"] + " " + b["claim"])
    overlap = len(wa & wb) / len(wa | wb) if wa and wb else 0.0
    return overlap >= (0.15 if same_family else 0.25)


def _units(g: list[dict]) -> set[str]:
    return {m["unit"] for m in g if m.get("unit")}


def group(candidates: list[dict]) -> list[list[dict]]:
    """Single-link grouping of candidate claims that look like the same issue.

    Two claims from the same unit (one model running one skill, or one
    scanner) are distinct by construction and are never merged.
    """
    groups: list[list[dict]] = []
    for c in sorted(candidates, key=lambda c: (c["file"], c["line_start"], c["tool"], c.get("skill") or "")):
        hits = [g for g in groups if any(_same_issue(c, m) for m in g) and c.get("unit") not in _units(g)]
        if not hits:
            groups.append([c])
            continue
        first = hits[0]
        first.append(c)
        for other in hits[1:]:
            if _units(first) & _units(other):
                continue
            first.extend(other)
            groups.remove(other)
    return groups


def representative(g: list[dict]) -> dict:
    models = [c for c in g if c["tool"] in MODEL_TOOLS]
    pool = models or g
    return min(pool, key=lambda c: (c["line_start"], c["tool"], c.get("skill") or "", c["title"]))


def group_key(repo: str, g: list[dict], source_dir) -> str:
    rep = representative(g)
    snippet = snapshot.read_lines(source_dir, rep["file"], rep["line_start"], rep["line_end"])
    return stable_id(repo, fingerprint(rep["area"], rep["file"], snippet))


def corroboration_status(independent_models: list[str], verifications: list[dict]) -> str:
    ind = [v for v in verifications if v["independence"] == "independent"]
    confirms = sum(v["verdict"] == "confirm" for v in ind)
    refutes = sum(v["verdict"] == "refute" for v in ind)
    if confirms and refutes:
        return "disputed"
    if refutes:
        return "refuted"
    if confirms:
        return "confirmed"
    if len(independent_models) >= 2:
        return "independent_discovery"
    if any(v["verdict"] in ("pending", "failed") for v in verifications):
        return "pending"
    if any(v["verdict"] == "unsure" for v in verifications):
        return "unsure"
    return "single_source"


def queue_for(validation_status: str, independent_models: list[str], verifications: list[dict],
              sensitive: bool = False) -> tuple[str, str]:
    ind = [v for v in verifications if v["independence"] == "independent"]
    confirms = sum(v["verdict"] == "confirm" for v in ind)
    refutes = sum(v["verdict"] == "refute" for v in ind)
    if sensitive:
        return "main", "security impact: always triaged by a person"
    if validation_status == "reproduced":
        return "main", "validated by reproduction"
    if len(independent_models) >= 2:
        return "main", f"found independently by {len(independent_models)} models"
    if confirms and refutes:
        return "main", "disputed (confirmed and refuted)"
    if confirms:
        return "main", "confirmed by an independent verifier, no refutation"
    if refutes:
        return "low", "refuted, not confirmed"
    return "low", "single source, not independently confirmed or validated"


def sensitivity_for(candidates: list[dict], verifications: list[dict]) -> dict:
    reasons = []
    if any(c.get("area") == "security" for c in candidates):
        reasons.append("area is security")
    if any(c.get("security_impact") for c in candidates if c["tool"] in MODEL_TOOLS):
        reasons.append("a model marked security impact")
    if any(v.get("security_impact") for v in verifications):
        reasons.append("a verifier marked security impact")
    scanners = sorted({c["tool"] for c in candidates if c["tool"] in SENSITIVE_SCANNERS})
    if scanners:
        reasons.append(f"raised by {', '.join(scanners)}")
    return {"sensitive": bool(reasons), "reasons": reasons, "removal_reason": None}


def category_for(candidates: list[dict], sensitive: bool, area: str) -> str:
    if any(c["tool"] == "osv-scanner" or c.get("known_advisory") for c in candidates):
        return "dependency_advisory"
    if sensitive:
        return "security_vulnerability"
    if area in ("correctness", "quantum"):
        return "correctness"
    return "docs_tests_maintenance"


_TEXT_FIELDS = ("title", "claim", "evidence", "why_it_matters", "applies_because", "suggested_check")


def redact_candidate(c: dict) -> dict:
    return {**c, **{k: secrets.redact(c[k]) for k in _TEXT_FIELDS if isinstance(c.get(k), str)}}


def build_record(repo: str, commit: str, fid: str, g: list[dict], verifications: list[dict], validation: dict,
                 source_dir) -> dict:
    g = [redact_candidate(c) for c in g]
    verifications = [{**v, "reason": secrets.redact(v.get("reason", ""))} for v in verifications]
    rep = representative(g)
    detections = [{
        "source": "model" if c["tool"] in MODEL_TOOLS else "scanner", "tool": c["tool"],
        "model_id": c.get("model_id"), "skill": c.get("skill"), "unit": c.get("unit", ""), "title": c["title"],
        "line_start": c["line_start"], "line_end": c["line_end"], "proposed_severity": c["proposed_severity"],
        "security_impact": bool(c.get("security_impact")), "rule_id": c.get("rule_id"),
    } for c in g]
    independent_models = sorted({c["tool"] for c in g if c["tool"] in MODEL_TOOLS})
    sens = sensitivity_for(g, verifications)
    queue, why = queue_for(validation["status"], independent_models, verifications, sens["sensitive"])
    snippet = snapshot.read_lines(source_dir, rep["file"], rep["line_start"], rep["line_end"])
    proposed = [{"by": c["tool"] + (f"/{c['skill']}" if c.get("skill") else ""), "value": c["proposed_severity"]} for c in g]
    proposed += [{"by": f"verify/{v['verifier']}", "value": v["proposed_severity"]} for v in verifications
                 if v.get("proposed_severity")]
    return {
        "id": fid, "repo": repo, "commit": commit, "title": rep["title"], "area": rep["area"],
        "category": category_for(g, sens["sensitive"], rep["area"]),
        "file": rep["file"], "line_start": rep["line_start"], "line_end": rep["line_end"],
        "fingerprint": fingerprint(rep["area"], rep["file"], snippet),
        "claim": rep["claim"], "evidence": rep["evidence"], "why_it_matters": rep["why_it_matters"],
        "applies_because": rep.get("applies_because"),
        "detection": {"detections": detections, "detected_by": sorted({c["tool"] for c in g})},
        "corroboration": {"independent_models": independent_models, "verifications": verifications,
                          "status": corroboration_status(independent_models, verifications)},
        "validation": validation,
        "impact": {"statement": rep["why_it_matters"], "security_impact": sens["sensitive"],
                   "affected_behaviours": sorted({c["title"] for c in g})},
        "severity": {"proposed": proposed, "final": None, "set_by": None},
        "sensitivity": sens,
        "disposition": {"queue": queue, "queue_reason": why, "decision": "pending", "decided_by": None,
                        "decided_at": None, "note": "", "duplicate_of": None},
        "fix": None,
    }


def top_proposed_severity(record: dict) -> str:
    values = [p["value"] for p in record["severity"]["proposed"]]
    return min(values, key=SEVERITY_ORDER.index) if values else "info"
