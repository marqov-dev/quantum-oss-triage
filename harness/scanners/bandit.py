from __future__ import annotations

import json

from harness import secrets
from harness.scanners.base import ScanResult, Scanner, has_files, lead, load_json

_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


class Bandit(Scanner):
    name = "bandit"

    def applies(self, src):
        return (True, "") if has_files(src, ("**/*.py",)) else (False, "no Python files")

    def script(self) -> str:
        return "bandit -r -f json -q --exit-zero -x ./tests,./test,./.git ."

    def parse(self, stdout, stderr, exit_code) -> ScanResult:
        doc = load_json(stdout)
        if doc is None:
            return ScanResult(self.name, "failed", note=f"no output; exit {exit_code}: {stderr[-300:]}")
        findings, low = [], 0
        for r in doc.get("results", []):
            sev, conf = _RANK.get(r.get("issue_severity"), 0), _RANK.get(r.get("issue_confidence"), 0)
            if sev < 1 or conf < 1:
                low += 1
                continue
            findings.append(lead(tool=self.name, rule_id=r.get("test_id", "?"), title=f"Bandit {r.get('test_id')}: {r.get('test_name', '')}",
                                 area="security", file=r.get("filename", ""), line=r.get("line_number", 1),
                                 claim=secrets.redact(r.get("issue_text", "")), severity="high" if sev == 2 else "medium", security=True))
        kept = [{k: (secrets.redact(v) if isinstance(v, str) else v) for k, v in r.items() if k not in ("code", "line_range")}
                for r in doc.get("results", [])]
        return ScanResult(self.name, "ok", findings=findings, hygiene={"low": low, "leads": len(findings)},
                          raw=json.dumps(kept)[:200000])
