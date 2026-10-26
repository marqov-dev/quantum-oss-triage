from harness.scanners.bandit import Bandit
from harness.scanners.gitleaks import Gitleaks
from harness.scanners.lychee import Lychee
from harness.scanners.osv import OsvScanner
from harness.scanners.project_tests import ProjectTests
from harness.scanners.ruff import Ruff
from harness.scanners.scorecard import Scorecard
from harness.scanners.semgrep import Semgrep
from harness.scanners.zizmor import Zizmor

ALL = [Gitleaks, OsvScanner, Semgrep, Zizmor, Scorecard, Ruff, Bandit, Lychee, ProjectTests]


def all_scanners():
    return [cls() for cls in ALL]


def tool_versions(worker, src) -> dict[str, str]:
    r = worker.run("qot-scan-versions", src, writable_copy=False, timeout_s=120)
    versions = {}
    for line in r.stdout.splitlines():
        if "\t" in line:
            k, v = line.split("\t", 1)
            versions[k.strip()] = v.strip()
    return versions
