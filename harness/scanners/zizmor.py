from __future__ import annotations

import json

from harness.scanners.base import ScanResult, Scanner, has_files, lead, load_json

_SEV = {"High": "high", "Medium": "medium", "Low": "low", "Informational": "info", "Unknown": "low"}


class Zizmor(Scanner):
    name = "zizmor"

    def applies(self, src):
        ok = has_files(src, (".github/workflows/*.yml", ".github/workflows/*.yaml", "action.yml", "action.yaml"))
        return (True, "") if ok else (False, "no GitHub Actions workflows")

    def script(self) -> str:
        # zizmor exits non-zero when it finds something; that is not a failure.
        return "zizmor --offline --format json .; rc=$?; [ $rc -eq 0 ] || [ $rc -ge 10 ] && exit 0 || exit $rc"

    def parse(self, stdout, stderr, exit_code) -> ScanResult:
        items = load_json(stdout)
        if items is None:
            return ScanResult(self.name, "failed", note=f"no output; exit {exit_code}: {stderr[-300:]}")
        findings, low = [], 0
        for it in items:
            det = it.get("determinations", {})
            sev = _SEV.get(det.get("severity", "Unknown"), "low")
            if sev in ("low", "info") or det.get("confidence") == "Low":
                low += 1
                continue
            loc = (it.get("locations") or [{}])[0]
            key = loc.get("symbolic", {}).get("key", {}).get("Local", {})
            path = key.get("given_path") or key.get("verbatim_path") or ""
            row = loc.get("concrete", {}).get("location", {}).get("start_point", {}).get("row", 0) + 1
            findings.append(lead(tool=self.name, rule_id=it.get("ident", "?"), title=f"Workflow: {it.get('desc', it.get('ident'))}",
                                 area="security", file=path, line=row, claim=it.get("desc", ""), severity=sev,
                                 security=True))
        return ScanResult(self.name, "ok", findings=findings, hygiene={"low_or_low_confidence": low},
                          raw=json.dumps(items)[:200000])
