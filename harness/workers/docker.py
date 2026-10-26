"""Docker worker: credential-free, disposable, resource-limited containers."""

from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from pathlib import Path

from harness.workers.base import MAX_OUTPUT_BYTES, Worker, WorkerResult

DEFAULT_IMAGE = "quantum-oss-triage-worker:dev"

# The wrapper runs inside the container. Output goes to size-limited tmpfs
# files first, so a runaway process cannot fill the host disk or our memory.
_WRAPPER = r"""
set -u
git config --global --add safe.directory '*' 2>/dev/null
if [ "$QOT_COPY" = 1 ]; then cp -R /src/. /work/ || exit 97; fi
cd "$QOT_CWD" || exit 98
( %s ) >/tmp/qot.out 2>/tmp/qot.err
rc=$?
head -c %d /tmp/qot.out
head -c %d /tmp/qot.err >&2
if [ "$(wc -c </tmp/qot.out)" -gt %d ] || [ "$(wc -c </tmp/qot.err)" -gt %d ]; then echo "[qot: output truncated]" >&2; fi
exit $rc
"""


class DockerWorker(Worker):
    name = "docker"

    def __init__(self, image: str = DEFAULT_IMAGE, cpus: str = "2", memory: str = "2g", pids: int = 256,
                 work_size: str = "1g", tmp_size: str = "512m", docker: str = "docker"):
        self.image, self.cpus, self.memory, self.pids = image, cpus, memory, pids
        self.work_size, self.tmp_size, self.docker = work_size, tmp_size, docker

    def available(self) -> tuple[bool, str]:
        if not shutil.which(self.docker):
            return False, "docker not installed"
        try:
            r = subprocess.run([self.docker, "image", "inspect", "--format", "{{.Id}}", self.image],
                               capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            return False, "docker daemon not responding"
        if r.returncode != 0:
            return False, f"image {self.image} not built (docker build -f docker/worker.Dockerfile -t {self.image} .)"
        return True, r.stdout.strip()

    def describe(self) -> dict:
        ok, info = self.available()
        return {"tag": self.image, "digest": info if ok else None, "available": ok, "note": "" if ok else info}

    def command(self, script: str, src: Path, *, inputs: Path | None, network: bool, writable_copy: bool,
                name: str) -> list[str]:
        cap = MAX_OUTPUT_BYTES
        wrapper = _WRAPPER % (script, cap, cap, cap, cap)
        cmd = [
            self.docker, "run", "--rm", "--name", name,
            "--network", "bridge" if network else "none",
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", str(self.pids), "--memory", self.memory, "--memory-swap", self.memory,
            "--cpus", self.cpus, "--user", "65534:65534",
            "--tmpfs", f"/work:size={self.work_size},uid=65534,gid=65534,mode=0700",
            "--tmpfs", f"/tmp:size={self.tmp_size},mode=1777",
            "-v", f"{Path(src).resolve()}:/src:ro",
            # A clean environment: nothing from the host is passed through.
            "-e", "HOME=/tmp", "-e", f"QOT_COPY={1 if writable_copy else 0}",
            "-e", f"QOT_CWD={'/work' if writable_copy else '/src'}",
        ]
        if inputs is not None:
            cmd += ["-v", f"{Path(inputs).resolve()}:/inputs:ro"]
        return cmd + [self.image, "sh", "-c", wrapper]

    def run(self, script: str, src: Path, *, inputs: Path | None = None, network: bool = False,
            timeout_s: int = 600, writable_copy: bool = True) -> WorkerResult:
        name = f"qot-{uuid.uuid4().hex[:12]}"
        cmd = self.command(script, src, inputs=inputs, network=network, writable_copy=writable_copy, name=name)
        start = time.monotonic()
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, stdin=subprocess.DEVNULL,
                               errors="replace")
        except subprocess.TimeoutExpired as e:
            subprocess.run([self.docker, "kill", name], capture_output=True)
            out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            return WorkerResult(None, out[:MAX_OUTPUT_BYTES], "timed out", timed_out=True,
                                duration_s=time.monotonic() - start)
        return WorkerResult(p.returncode, p.stdout, p.stderr, truncated="[qot: output truncated]" in p.stderr,
                            duration_s=time.monotonic() - start)
