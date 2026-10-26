"""A local, unisolated worker for the harness's own unit tests only.

It runs scripts on the host. It refuses to run unless QOT_ALLOW_LOCAL_WORKER=1,
so it can never be picked up by accident for a real repository.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from harness.workers.base import MAX_OUTPUT_BYTES, Worker, WorkerResult


class LocalWorker(Worker):
    name = "local-unsafe"

    def available(self) -> tuple[bool, str]:
        if os.environ.get("QOT_ALLOW_LOCAL_WORKER") != "1":
            return False, "local worker is for harness tests only (set QOT_ALLOW_LOCAL_WORKER=1)"
        return True, "local"

    def describe(self) -> dict:
        return {"tag": "local-unsafe", "digest": None, "available": self.available()[0], "note": "test only"}

    def run(self, script: str, src: Path, *, inputs: Path | None = None, network: bool = False,
            timeout_s: int = 600, writable_copy: bool = True) -> WorkerResult:
        ok, reason = self.available()
        if not ok:
            raise RuntimeError(reason)
        with tempfile.TemporaryDirectory(prefix="qot-local-") as tmp:
            work = Path(tmp) / "work"
            if writable_copy:
                shutil.copytree(src, work, symlinks=True)
            cwd = work if writable_copy else Path(src)
            # Scripts written for the container refer to /src, /work and /inputs.
            script = script.replace("/inputs", str(inputs or "/nonexistent")).replace("/work", str(work)).replace("/src", str(src))
            start = time.monotonic()
            try:
                p = subprocess.run(["sh", "-c", script], cwd=cwd, capture_output=True, text=True, timeout=timeout_s,
                                   env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tmp})
            except subprocess.TimeoutExpired:
                return WorkerResult(None, "", "timed out", timed_out=True, duration_s=time.monotonic() - start)
            return WorkerResult(p.returncode, p.stdout[:MAX_OUTPUT_BYTES], p.stderr[:MAX_OUTPUT_BYTES],
                                truncated=len(p.stdout) > MAX_OUTPUT_BYTES, duration_s=time.monotonic() - start)
