from __future__ import annotations

import json
from datetime import datetime, timezone

from harness.scanners.base import ScanResult, Scanner, has_files, lead, load_json

_LOCKFILES = ("requirements*.txt", "**/requirements*.txt", "poetry.lock", "uv.lock", "Pipfile.lock",
              "pyproject.toml", "**/pyproject.toml", "Cargo.lock", "package-lock.json", "pdm.lock")


def _sev(group_max: str | None) -> str:
    try:
        score = float(group_max)
    except (TypeError, ValueError):
        return "medium"
    return "critical" if score >= 9 else "high" if score >= 7 else "medium" if score >= 4 else "low"


class OsvScanner(Scanner):
    name = "osv-scanner"
    # The advisory database is queried live (osv.dev). The worker gets network
    # for this step only; osv-scanner reads lockfiles and runs no project code.
    network = True

    def applies(self, src):
        return (True, "") if has_files(src, _LOCKFILES) else (False, "no dependency manifest or lockfile")

    def script(self) -> str:
        # osv-scanner cannot read some lockfiles (pixi.lock, for one). When it
        # finds no package source at all, scan the versions the dependency
        # stage actually installed (/deps/freeze.txt) instead.
        return ("osv-scanner scan source -r --format json /src >/tmp/osv.json 2>/tmp/osv.err; rc=$?; "
                "if [ $rc -eq 128 ] && grep -q 'No package sources found' /tmp/osv.err && [ -f /deps/freeze.txt ]; then "
                "echo QOT-OSV-INSTALLED-ENV >>/tmp/osv.err; "
                "osv-scanner scan source --format json -L requirements.txt:/deps/freeze.txt >/tmp/osv.json 2>>/tmp/osv.err; rc=$?; fi; "
                "cat /tmp/osv.json; cat /tmp/osv.err >&2; [ $rc -le 1 ] && exit 0 || exit $rc")

    def parse(self, stdout, stderr, exit_code) -> ScanResult:
        if exit_code not in (0, 1):
            return ScanResult(self.name, "failed", note=f"exit {exit_code}: {stderr[-300:]}")
        doc = load_json(stdout) or {}
        installed_env = "QOT-OSV-INSTALLED-ENV" in (stderr or "")
        findings = []
        for res in doc.get("results", []):
            path = res.get("source", {}).get("path", "")
            if installed_env:
                path = "pyproject.toml"  # the versions installed from it, read from pip freeze
            for pkg in res.get("packages", []):
                p = pkg.get("package", {})
                if installed_env and p.get("name") == "pip":
                    continue  # the harness's own pip, not the project's
                for g in pkg.get("groups", []):
                    ids = g.get("ids", [])
                    findings.append(lead(
                        tool=self.name, rule_id=",".join(ids), area="maintenance", file=path, line=1,
                        title=f"Known advisory in dependency {p.get('name')} {p.get('version')}",
                        claim=f"{p.get('name')} {p.get('version')} is affected by {', '.join(ids)}. Whether the project uses the affected code is not established.",
                        severity=_sev(g.get("max_severity")), security=True,
                        evidence=f"osv-scanner group {ids} max severity {g.get('max_severity')}"))
        for f in findings:
            f["known_advisory"] = True
        note = ("no lockfile osv-scanner reads; scanned the installed environment (pip freeze), "
                "which also holds the harness's pytest" if installed_env else "")
        return ScanResult(self.name, "ok", findings=findings, hygiene={"advisories": len(findings)}, note=note,
                          database_date=f"queried live {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')}",
                          raw=json.dumps(doc)[:200000])
