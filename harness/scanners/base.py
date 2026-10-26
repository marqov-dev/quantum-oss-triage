"""Scanner wrappers. Each runs one fixed (non-AI) tool in a worker and
normalises its output.

A scanner hit is a lead, not a confirmed defect. Security and correctness leads
become candidate findings for the models to assess; lint, style and link
results become hygiene counts. A tool that fails, is missing, or does not apply
is recorded as such, never as a pass.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from harness.workers.base import Worker

SEVERITIES = ("info", "low", "medium", "high", "critical")


@dataclass
class ScanResult:
    name: str
    status: str  # ok | failed | unavailable | not_applicable
    version: str | None = None
    findings: list[dict] = field(default_factory=list)
    hygiene: dict = field(default_factory=dict)
    note: str = ""
    database_date: str | None = None
    raw: str = ""  # kept in the private evidence store only, already redacted

    def manifest_entry(self) -> dict:
        return {"name": self.name, "status": self.status, "version": self.version, "note": self.note,
                "database_date": self.database_date}


def lead(*, tool: str, rule_id: str, title: str, area: str, file: str, line: int, end_line: int | None = None,
         claim: str, severity: str, security: bool, evidence: str = "", why: str = "") -> dict:
    return {
        "title": title[:160], "area": area, "file": _rel(file), "line_start": max(int(line or 1), 1),
        "line_end": max(int(end_line or line or 1), int(line or 1), 1), "claim": claim,
        "evidence": evidence or f"{tool} rule {rule_id}", "why_it_matters": why or claim,
        "applies_because": None, "proposed_severity": severity, "security_impact": security,
        "confidence": "medium", "suggested_check": None, "rule_id": rule_id, "tool": tool,
    }


def _rel(path: str) -> str:
    p = str(path or "")
    for prefix in ("/work/", "/src/", "./"):
        if p.startswith(prefix):
            p = p[len(prefix):]
    return p.lstrip("/") or "."


def load_json(text: str):
    text = (text or "").strip()
    return json.loads(text) if text else None


class Scanner:
    name = ""
    # The tool name as printed by qot-scan-versions.
    version_key = ""
    network = False
    timeout_s = 900

    def applies(self, src: Path) -> tuple[bool, str]:
        return True, ""

    def script(self) -> str:
        raise NotImplementedError

    def parse(self, stdout: str, stderr: str, exit_code: int | None) -> ScanResult:
        raise NotImplementedError

    def run(self, worker: Worker, src: Path, versions: dict[str, str]) -> ScanResult:
        version = versions.get(self.version_key or self.name)
        if not version or version == "unavailable":
            return ScanResult(self.name, "unavailable", None, note="not installed in the worker image")
        ok, why = self.applies(src)
        if not ok:
            return ScanResult(self.name, "not_applicable", version, note=why)
        r = worker.run(self.script(), src, network=self.network, timeout_s=self.timeout_s)
        if r.timed_out:
            return ScanResult(self.name, "failed", version, note=f"timed out after {self.timeout_s}s")
        try:
            result = self.parse(r.stdout, r.stderr, r.exit_code)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            return ScanResult(self.name, "failed", version, note=f"could not parse output ({e}); exit {r.exit_code}: {r.stderr[-300:]}")
        result.version = version
        if r.truncated:
            result.status = "failed"
            result.note = (result.note + " output truncated").strip()
        return result


def has_files(src: Path, patterns: tuple[str, ...]) -> bool:
    return any(next(Path(src).glob(p), None) is not None for p in patterns)
