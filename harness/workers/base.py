"""Workers run untrusted code: builds, scanners, tests, reproductions.

The controller never runs repository code itself. A worker gets a read-only
source snapshot at /src and a throwaway writable copy at /work, plus limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT_BYTES = 5 * 1024 * 1024


@dataclass
class WorkerResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    truncated: bool = False
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class Worker:
    name = "worker"

    def available(self) -> tuple[bool, str]:
        raise NotImplementedError

    def describe(self) -> dict:
        raise NotImplementedError

    def run(self, script: str, src: Path, *, inputs: Path | None = None, network: bool = False,
            timeout_s: int = 600, writable_copy: bool = True) -> WorkerResult:
        """Run a shell script. /src is the snapshot (read-only), /work a writable copy,
        /inputs an optional read-only directory of harness-provided files."""
        raise NotImplementedError
