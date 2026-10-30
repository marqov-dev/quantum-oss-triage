from __future__ import annotations

import re

from harness import secrets
from harness.scanners.base import ScanResult, Scanner, has_files

_COUNT = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b")
# pytest exit codes: 0 all passed, 1 some failed, 2 interrupted (including
# collection errors), 3 internal error, 4 usage error, 5 no tests collected.
_EXIT = {2: "interrupted", 3: "internal error", 4: "usage error", 5: "no tests collected"}


class ProjectTests(Scanner):
    """The project's own test suite at this commit, offline, as a baseline.

    Runs with the dependencies the deps stage installed (mounted read-only at
    /deps). If they could not be installed, a suite that needs them fails at
    import and is reported as such.

    Recorded as ok only when the suite ran: pytest exited 0 or 1, at least one
    test ran, and there were no errors (collection or setup). Failing tests are
    a baseline, not a problem with the run. Anything else, including a timeout,
    is recorded as failed, so the run shows as incomplete. A repository whose
    suite needs longer sets tests.timeout_s in config/repos.yaml.
    """

    name = "project-tests"
    version_key = "pytest"
    timeout_s = 1200

    def applies(self, src):
        ok = has_files(src, ("tests/**/*.py", "test/**/*.py", "**/test_*.py"))
        return (True, "") if ok else (False, "no Python tests found")

    def script(self) -> str:
        return ("python -m pytest -q -p no:cacheprovider --no-header -o addopts= -rfE >/tmp/pt.txt 2>&1; rc=$?; "
                "tail -n 200 /tmp/pt.txt; exit $rc")

    def parse(self, stdout, stderr, exit_code) -> ScanResult:
        lines = [x for x in stdout.strip().splitlines() if x.strip()]
        summary = next((x for x in reversed(lines) if _COUNT.search(x) or "no tests ran" in x), "")
        counts: dict[str, int] = {}
        for v, k in _COUNT.findall(summary):
            k = "errors" if k.startswith("error") else k
            counts[k] = counts.get(k, 0) + int(v)
        ran = sum(counts.get(k, 0) for k in ("passed", "failed", "xfailed", "xpassed"))
        problems = []
        if counts.get("errors"):
            problems.append(f"{counts['errors']} errors (collection or setup)")
        if exit_code in _EXIT:
            problems.append(f"pytest exit {exit_code} ({_EXIT[exit_code]})")
        elif exit_code not in (0, 1):
            problems.append(f"pytest exit {exit_code}")
        if not ran:
            problems.append("no tests ran" if summary else "could not read a pytest summary")
        status = "failed" if problems else "ok"
        return ScanResult(self.name, status, hygiene={"summary": summary[:200], "exit_code": exit_code, **counts},
                          note="; ".join(problems), raw=secrets.redact("\n".join(lines[-200:])))
