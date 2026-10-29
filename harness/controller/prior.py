"""Earlier work by the reviewer on a repository, read as evidence.

`prior-work.yaml` lives in the repository's run folder (private, never in this
repository). It lists what the reviewer already found, reported, fixed or
rejected, taken from their own notes:

    source: where the notes were read, and when
    items:
      - id: PW-1
        title: short title
        area: security | correctness | quantum | docs | tests | maintenance
        file: path/in/repo.py
        lines: [10, 14]          # optional
        claim: what the notes say is wrong
        status: found | reported | fixed | rejected
        upstream: [https://github.com/org/repo/issues/123]   # optional
        note: anything else from the notes (optional)

Each item becomes a lead like a scanner's. A model finding at the same place
is merged with it, so it is not presented as new; an item no model raised is
still verified by every model, so an earlier conclusion is checked, not
inherited. A prior item never counts as an independent model.
"""

from __future__ import annotations

import yaml

TOOL = "prior-work"
STATUSES = ("found", "reported", "fixed", "rejected")
AREAS = ("security", "correctness", "quantum", "docs", "tests", "maintenance")
FILE = "prior-work.yaml"


class PriorWorkError(ValueError):
    pass


def load(repo_dir, repo: str) -> list[dict]:
    """Leads from the run folder's prior-work.yaml, or [] when there is none."""
    path = repo_dir / FILE
    if not path.is_file():
        return []
    doc = yaml.safe_load(path.read_text()) or {}
    leads, errors = [], []
    for i, it in enumerate(doc.get("items") or []):
        pid = str(it.get("id") or f"PW-{i + 1}")
        missing = [k for k in ("title", "area", "file", "claim", "status") if not it.get(k)]
        if missing:
            errors.append(f"{pid}: missing {', '.join(missing)}")
            continue
        if it["status"] not in STATUSES or it["area"] not in AREAS:
            errors.append(f"{pid}: status must be one of {STATUSES} and area one of {AREAS}")
            continue
        start, end = (list(it.get("lines") or [1, 1]) + [None])[:2]
        leads.append({
            "tool": TOOL, "unit": f"{repo}/prior/{pid}/-", "skill": None, "model_id": None, "rule_id": None,
            "area": it["area"], "file": it["file"], "line_start": int(start), "line_end": int(end or start),
            "title": it["title"], "claim": it["claim"], "evidence": it.get("note") or "from the reviewer's earlier notes",
            "why_it_matters": it.get("note") or it["claim"], "proposed_severity": it.get("severity") or "medium",
            "security_impact": False,
            "prior": {"id": pid, "status": it["status"], "upstream": list(it.get("upstream") or []),
                      "note": it.get("note") or ""},
        })
    if errors:
        raise PriorWorkError(f"{path}: " + "; ".join(errors))
    return leads


def summary(candidates: list[dict]) -> list[dict]:
    """The prior-work entries a merged finding carries."""
    return [c["prior"] for c in candidates if c.get("tool") == TOOL and c.get("prior")]
