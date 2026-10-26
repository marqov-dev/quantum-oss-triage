from __future__ import annotations

from collections import Counter

from harness.scanners.base import ScanResult, Scanner, has_files, load_json


class Ruff(Scanner):
    name = "ruff"

    def applies(self, src):
        return (True, "") if has_files(src, ("**/*.py",)) else (False, "no Python files")

    def script(self) -> str:
        return "ruff check --output-format json --no-cache --exit-zero ."

    def parse(self, stdout, stderr, exit_code) -> ScanResult:
        items = load_json(stdout)
        if items is None:
            return ScanResult(self.name, "failed", note=f"no output; exit {exit_code}: {stderr[-300:]}")
        by_code = Counter(i.get("code") or "syntax" for i in items)
        return ScanResult(self.name, "ok", hygiene={"total": len(items), "by_code": dict(by_code.most_common(20))})
