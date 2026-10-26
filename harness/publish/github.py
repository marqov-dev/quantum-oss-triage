"""GitHub publisher: fix branches on marqov-dev forks.

v0.1 plans branches and never pushes. Pushing needs, per branch: David's
explicit approval, a fork under marqov-dev, a token that can write only to the
forks, and a check of the project's contribution rules (CLA or DCO sign-off).
Security fixes are never pushed under any setting.
"""

from __future__ import annotations


def planned_branches(findings: list[dict]) -> list[dict]:
    out = []
    for f in findings:
        delivery = (f.get("fix") or {}).get("delivery") or {}
        if delivery.get("kind") == "fork_branch":
            out.append({"finding": f["id"], "branch": delivery["branch"], "fix_status": f["fix"]["status"],
                        "pushed": False, "requires": ["David's explicit approval for this branch",
                                                      "fork under marqov-dev", "contribution rules checked"]})
    return out


def push(*_args, **_kwargs):
    raise PermissionError("v0.1 never pushes. Each branch needs David's explicit approval and a fork-only token.")
