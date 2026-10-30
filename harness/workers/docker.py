"""Docker worker: credential-free, disposable, resource-limited containers."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from harness.workers.base import MAX_OUTPUT_BYTES, Worker, WorkerResult, venv_installed

DEFAULT_IMAGE = "quantum-oss-triage-worker:dev"
PROXY_SCRIPT = Path(__file__).resolve().parents[2] / "docker" / "registry-proxy.py"
# The package registries the dependency step may reach, and nothing else.
# Package registries the dependency stage may reach, by name. Only these hosts,
# only HTTPS; which ones a run uses is set by worker.registries in the config.
REGISTRIES = {
    "pypi": ("pypi.org", "files.pythonhosted.org"),
    "crates": ("index.crates.io", "static.crates.io", "crates.io"),  # Rust crates for maturin builds
}
PROXY_PORT = 3128

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
                 work_size: str = "1g", tmp_size: str = "512m", docker: str = "docker",
                 registries: tuple[str, ...] = ("pypi",)):
        unknown = [r for r in registries if r not in REGISTRIES]
        if unknown:
            raise ValueError(f"unknown registries {unknown}; known: {sorted(REGISTRIES)}")
        self.registries = tuple(registries)
        self.image, self.cpus, self.memory, self.pids = image, cpus, memory, pids
        self.work_size, self.tmp_size, self.docker = work_size, tmp_size, docker
        self.deps_dir: Path | None = None

    def with_deps(self, deps_dir: Path) -> "DockerWorker":
        w = copy.copy(self)
        w.deps_dir = Path(deps_dir) if venv_installed(deps_dir) else None
        return w

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
        if self.deps_dir is not None:
            # Installed dependencies, read-only. The code under review comes
            # from the working copy, which shadows any installed copy of it.
            root = "/work" if writable_copy else "/src"
            cmd += ["-v", f"{self.deps_dir.resolve()}:/deps:ro",
                    "-e", "PATH=/deps/venv/bin:/usr/local/bin:/usr/bin:/bin",
                    "-e", f"PYTHONPATH={root}/src:{root}", "-e", "PYTHONDONTWRITEBYTECODE=1"]
        return cmd + [self.image, "sh", "-c", wrapper]

    def registry_hosts(self) -> tuple[str, ...]:
        return tuple(h for r in self.registries for h in REGISTRIES[r])

    def install_deps(self, script: str, src: Path, deps_dir: Path, *, timeout_s: int = 1800) -> WorkerResult:
        """Run `script` with network access to the package registry only.

        The install container joins an internal network with no route out; a
        proxy container on that network and the default bridge forwards HTTPS
        to the configured registries' hosts only. The container writes only to
        /deps (the repository's dependency folder) and its own tmpfs, which is
        mounted with exec here (and only here) because build backends run the
        tools they install there (cmake, meson, compilers).
        """
        tag = uuid.uuid4().hex[:12]
        net, proxy, name = f"qot-registry-{tag}", f"qot-proxy-{tag}", f"qot-deps-{tag}"
        deps_dir = Path(deps_dir)
        deps_dir.mkdir(parents=True, exist_ok=True)
        deps_dir.chmod(0o777)  # the container user is 65534
        d = self.docker
        start = time.monotonic()
        log = ""
        try:
            subprocess.run([d, "network", "create", "--internal", net], check=True, capture_output=True, timeout=60)
            subprocess.run([d, "run", "-d", "--rm", "--name", proxy, "--network", net,
                            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                            "--user", "65534:65534", "--memory", "256m", "--pids-limit", "64",
                            "-v", f"{PROXY_SCRIPT}:/proxy.py:ro", self.image,
                            "python", "/proxy.py", str(PROXY_PORT), *self.registry_hosts()],
                           check=True, capture_output=True, timeout=60)
            subprocess.run([d, "network", "connect", "bridge", proxy], check=True, capture_output=True, timeout=60)
            cap = MAX_OUTPUT_BYTES
            wrapper = _WRAPPER % (script, cap, cap, cap, cap)
            url = f"http://{proxy}:{PROXY_PORT}"
            cmd = [d, "run", "--rm", "--name", name, "--network", net,
                   "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                   "--pids-limit", str(self.pids), "--memory", "4g", "--memory-swap", "4g", "--cpus", self.cpus,
                   "--user", "65534:65534",
                   "--tmpfs", f"/work:size={self.work_size},uid=65534,gid=65534,mode=0700,exec",
                   "--tmpfs", "/tmp:size=3g,mode=1777,exec",
                   "-v", f"{Path(src).resolve()}:/src:ro", "-v", f"{deps_dir.resolve()}:/deps:rw",
                   "-e", "HOME=/tmp", "-e", "QOT_COPY=1", "-e", "QOT_CWD=/work",
                   "-e", f"HTTPS_PROXY={url}", "-e", f"https_proxy={url}",
                   "-e", "PIP_DISABLE_PIP_VERSION_CHECK=1", "-e", "PIP_NO_INPUT=1", "-e", "PIP_NO_CACHE_DIR=1",
                   self.image, "sh", "-c", wrapper]
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, stdin=subprocess.DEVNULL,
                                   errors="replace")
                result = WorkerResult(p.returncode, p.stdout, p.stderr, truncated="[qot: output truncated]" in p.stderr)
            except subprocess.TimeoutExpired:
                subprocess.run([d, "kill", name], capture_output=True)
                result = WorkerResult(None, "", "timed out", timed_out=True)
            log = subprocess.run([d, "logs", proxy], capture_output=True, text=True, timeout=60).stdout
        finally:
            subprocess.run([d, "rm", "-f", proxy, name], capture_output=True, timeout=60)
            subprocess.run([d, "network", "rm", net], capture_output=True, timeout=60)
        result.duration_s = time.monotonic() - start
        result.proxy_log = [json.loads(x) for x in log.splitlines() if x.startswith("{")]
        return result

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
