"""Workers run untrusted code: builds, scanners, tests, reproductions.

The controller never runs repository code itself. A worker gets a read-only
source snapshot at /src and a throwaway writable copy at /work, plus limits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    proxy_log: list = field(default_factory=list)  # registry-only steps: each allow/deny decision

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

    def with_deps(self, deps_dir: Path) -> "Worker":
        """The same worker, with a repository's installed dependencies available."""
        return self

    def install_deps(self, script: str, src: Path, deps_dir: Path, *, timeout_s: int = 1800) -> WorkerResult:
        """Run an install script with registry-only network access, writing to /deps."""
        return WorkerResult(None, "", f"{self.name} worker cannot install dependencies")


def venv_installed(deps_dir) -> bool:
    """Whether the dependency stage left a virtual environment in deps_dir.

    Checked on the host, where venv/bin/python is a symlink to the worker's
    own interpreter (a container path), so it must not be followed.
    """
    venv = Path(deps_dir) / "venv"
    python = venv / "bin" / "python"
    return (venv / "pyvenv.cfg").is_file() and (python.is_symlink() or python.is_file())
