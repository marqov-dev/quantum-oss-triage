from __future__ import annotations

import re

from harness.scanners.base import ScanResult, Scanner, has_files


class ProjectTests(Scanner):
    """The project's own test suite at this commit, offline, as a baseline.

    Runs with the dependencies the deps stage installed (mounted read-only at
    /deps). If they could not be installed, a suite that needs them fails at
    import and is reported as such.
    """

    name = "project-tests"
    version_key = "pytest"
    timeout_s = 1200

    def applies(self, src):
        ok = has_files(src, ("tests/**/*.py", "test/**/*.py", "**/test_*.py"))
        return (True, "") if ok else (False, "no Python tests found")

    def script(self) -> str:
        return "python -m pytest -q -p no:cacheprovider --no-header -o addopts= >/tmp/pt.txt 2>&1; rc=$?; tail -n 40 /tmp/pt.txt; exit $rc"

    def parse(self, stdout, stderr, exit_code) -> ScanResult:
        tail = stdout.strip().splitlines()[-1:] or [""]
        counts = {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|error|errors|skipped)", tail[0])}
        status = "ok" if counts else "failed"
        return ScanResult(self.name, status, hygiene={"summary": tail[0][:200], **counts},
                          note="" if counts else "could not read a pytest summary")
