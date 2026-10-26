from __future__ import annotations

import json

from harness.scanners.base import ScanResult, Scanner, lead, load_json

# Fields that could hold a secret value or personal data. Removed before
# anything is stored: a private repository is not a safe home for credentials.
_SECRET_FIELDS = ("Secret", "Match", "Line")
_PERSONAL_FIELDS = ("Author", "Email", "Message")


def redact(entries: list[dict]) -> list[dict]:
    out = []
    for e in entries:
        kept = {k: v for k, v in e.items() if k not in _PERSONAL_FIELDS}
        for k in _SECRET_FIELDS:
            if k in kept:
                kept[k] = "REDACTED"
        out.append(kept)
    return out


class Gitleaks(Scanner):
    name = "gitleaks"

    def script(self) -> str:
        return ("if [ -d .git ]; then gitleaks git --redact --no-banner --exit-code 0 --report-format json --report-path - .; "
                "else gitleaks dir --redact --no-banner --exit-code 0 --report-format json --report-path - .; fi")

    def parse(self, stdout, stderr, exit_code) -> ScanResult:
        entries = redact(load_json(stdout) or [])
        findings = [
            lead(tool=self.name, rule_id=e.get("RuleID", "?"), title=f"Possible secret in source ({e.get('RuleID')})",
                 area="security", file=e.get("File", ""), line=e.get("StartLine", 1), end_line=e.get("EndLine"),
                 claim=f"gitleaks rule {e.get('RuleID')} matched a value that looks like a credential.",
                 severity="high", security=True,
                 evidence=f"gitleaks {e.get('RuleID')} at commit {str(e.get('Commit', ''))[:12]} (value redacted)")
            for e in entries
        ]
        return ScanResult(self.name, "ok", findings=findings, hygiene={"secrets_flagged": len(findings)},
                          raw=json.dumps(entries))
