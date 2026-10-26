from __future__ import annotations

import json

from harness import secrets
from harness.scanners.base import ScanResult, Scanner, lead, load_json

_SEV = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}


class Semgrep(Scanner):
    name = "semgrep"
    timeout_s = 1200

    def script(self) -> str:
        return ("semgrep scan --config /opt/semgrep/python.yml --config /opt/semgrep/secrets.yml --json "
                "--metrics off --disable-version-check --quiet --timeout 30 .")

    def parse(self, stdout, stderr, exit_code) -> ScanResult:
        doc = load_json(stdout)
        if doc is None:
            return ScanResult(self.name, "failed", note=f"no output; exit {exit_code}: {stderr[-300:]}")
        findings, hygiene = [], {"info": 0}
        for r in doc.get("results", []):
            extra = r.get("extra", {})
            sev = _SEV.get(extra.get("severity", ""), "low")
            category = (extra.get("metadata") or {}).get("category", "")
            if sev == "low":
                hygiene["info"] += 1
                continue
            security = category == "security"
            rule = r.get("check_id", "?").split(".")[-1]
            findings.append(lead(tool=self.name, rule_id=rule, title=f"Semgrep: {rule}",
                                 area="security" if security else "correctness", file=r.get("path", ""),
                                 line=r.get("start", {}).get("line", 1), end_line=r.get("end", {}).get("line"),
                                 claim=secrets.redact(extra.get("message", ""))[:600], severity=sev, security=security))
        hygiene["errors"] = len(doc.get("errors", []))
        for r in doc.get("results", []):
            extra = r.get("extra", {})
            for k in ("lines", "metavars", "fingerprint", "dataflow_trace"):
                extra.pop(k, None)
        return ScanResult(self.name, "ok", findings=findings, hygiene=hygiene, raw=secrets.redact(json.dumps(doc))[:200000])
