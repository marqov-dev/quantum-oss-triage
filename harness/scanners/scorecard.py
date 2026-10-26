from __future__ import annotations

import shutil

from harness.scanners.base import ScanResult, Scanner


class Scorecard(Scanner):
    """OpenSSF Scorecard reads a repository's GitHub settings and history through
    the GitHub API, so it needs a token and a GitHub remote. It is not in the
    worker image (workers hold no credentials). Run by the publisher-side step
    in a later version; until then it is recorded as unavailable."""

    name = "scorecard"

    def run(self, worker, src, versions) -> ScanResult:
        if not shutil.which("scorecard"):
            return ScanResult(self.name, "unavailable", None,
                              note="scorecard not installed; needs a GitHub token, which workers never hold")
        return ScanResult(self.name, "not_applicable", None,
                          note="scorecard runs against the GitHub remote, not a local snapshot; not wired up in v0.1")
