"""Docker worker: credential-free, disposable, resource-limited containers."""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from harness.workers.base import MAX_OUTPUT_BYTES, Worker, WorkerResult, venv_installed
from harness.workers.infra import InfraGuard

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
if [ "$QOT_COPY" = 1 ]; then
  # Copy everything except git's object store, which can be larger than /work
  # (qilisdk 1.0 GB, pyqrack 1.4 GB). git keeps working in the copy: it reads
  # objects from the read-only original through an alternates file.
  for f in /src/* /src/.[!.]* /src/..?*; do
    [ -e "$f" ] || [ -L "$f" ] || continue
    if [ "$f" = /src/.git ] && [ -d "$f" ]; then continue; fi
    cp -R "$f" /work/ || exit 97
  done
  if [ -d /src/.git ]; then
    mkdir -p /work/.git || exit 97
    for f in /src/.git/* /src/.git/.[!.]*; do
      [ -e "$f" ] || [ -L "$f" ] || continue
      if [ "$f" = /src/.git/objects ]; then continue; fi
      cp -R "$f" /work/.git/ || exit 97
    done
    mkdir -p /work/.git/objects/info /work/.git/objects/pack || exit 97
    echo /src/.git/objects > /work/.git/objects/info/alternates || exit 97
  fi
  # Files the project's build produced that its tree lacks (a compiled extension, a
  # version file), kept by the install step (harness/stages/deps.py). Linked, not copied,
  # so an extension loads from /deps rather than the noexec tmpfs, and only where the copy
  # has no file of that name.
  if [ -d /deps/generated ] && [ "${QOT_INSTALL:-0}" != 1 ]; then cp -Rns /deps/generated/. /work/ || exit 97; fi
fi
cd "$QOT_CWD" || exit 98
( %s ) >/tmp/qot.out 2>/tmp/qot.err
rc=$?
head -c %d /tmp/qot.out
head -c %d /tmp/qot.err >&2
if [ "$(wc -c </tmp/qot.out)" -gt %d ] || [ "$(wc -c </tmp/qot.err)" -gt %d ]; then echo "[qot: output truncated]" >&2; fi
exit $rc
"""


def _cleanup(cmd: list[str]) -> None:
    """Best-effort removal: a daemon that has gone away must not hide the real error."""
    try:
        subprocess.run(cmd, capture_output=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        pass


class DockerWorker(Worker):
    name = "docker"

    def __init__(self, image: str = DEFAULT_IMAGE, cpus: str = "2", memory: str = "2g", pids: int = 256,
                 work_size: str = "1g", tmp_size: str = "512m", docker: str = "docker",
                 registries: tuple[str, ...] = ("pypi",), guard: InfraGuard | None = None):
        unknown = [r for r in registries if r not in REGISTRIES]
        if unknown:
            raise ValueError(f"unknown registries {unknown}; known: {sorted(REGISTRIES)}")
        self.registries = tuple(registries)
        self.image, self.cpus, self.memory, self.pids = image, cpus, memory, pids
        self.work_size, self.tmp_size, self.docker = work_size, tmp_size, docker
        self.deps_dir: Path | None = None
        self.python_path: tuple[str, ...] = ()  # extra package roots inside the copy, first on PYTHONPATH
        self.platform: str | None = None
        self.python: str | None = None
        self.base_image = image
        # Checks the daemon, image and disk before each launch, and after a failed one, so an
        # outage raises InfrastructureUnavailable instead of becoming a project's result.
        # Shared (not copied) by the platform and dependency variants of this worker.
        self.guard = guard

    def variant(self, platform: str | None = None, python: str | None = None) -> "DockerWorker":
        """The same worker with another image variant: the configured tag plus "-py<NN>" for
        another Python (built with --build-arg PYTHON_VERSION) and "-<arch>" for another
        platform, e.g. quantum-oss-triage-worker:dev-py310 or :dev-py310-amd64."""
        if not platform and not python:
            return self
        if python and not re.fullmatch(r"3\.\d{1,2}", python):
            raise ValueError(f"worker python {python!r} is not of the form 3.N")
        w = copy.copy(self)
        w.platform, w.python = platform or self.platform, python or self.python
        suffix = (f"-py{w.python.replace('.', '')}" if w.python else "") + (
            f"-{w.platform.split('/')[-1]}" if w.platform else "")
        w.image = f"{self.base_image}{suffix}"
        return w

    def for_platform(self, platform: str | None) -> "DockerWorker":
        """The same worker, running containers as `platform` with that platform's image
        (the configured tag plus "-<arch>", e.g. quantum-oss-triage-worker:dev-amd64)."""
        return self.variant(platform=platform)

    def _plat(self) -> list[str]:
        return ["--platform", self.platform] if self.platform else []

    def with_deps(self, deps_dir: Path, python_path: tuple[str, ...] | list[str] = ()) -> "DockerWorker":
        w = copy.copy(self)
        w.deps_dir = Path(deps_dir) if venv_installed(deps_dir) else None
        w.python_path = tuple(python_path)
        return w

    def _preflight(self, image: str | None = None) -> None:
        if self.guard is not None:
            self.guard.check(image=image or self.image)

    def _after(self, result: WorkerResult, image: str | None = None) -> WorkerResult:
        if self.guard is not None and not result.ok:
            self.guard.raise_if_outage(result.exit_code, result.stderr, image or self.image)
        return result

    def available(self) -> tuple[bool, str]:
        # With a guard, Docker or the image being down stops the run rather than
        # degrading it: a stage would otherwise record "worker unavailable" outcomes.
        self._preflight()
        if not shutil.which(self.docker):
            return False, "docker not installed"
        try:
            r = subprocess.run([self.docker, "image", "inspect", "--format", "{{.Id}}", self.image],
                               capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            return False, "docker daemon not responding"
        if r.returncode != 0:
            build = (f"docker build{' --platform ' + self.platform if self.platform else ''}"
                     f"{' --build-arg PYTHON_VERSION=' + self.python if self.python else ''}"
                     f" -f docker/worker.Dockerfile -t {self.image} .")
            return False, f"image {self.image} not built ({build})"
        return True, r.stdout.strip()

    def describe(self) -> dict:
        ok, info = self.available()
        d = {"tag": self.image, "digest": info if ok else None, "available": ok, "note": "" if ok else info}
        if self.platform:
            d["platform"] = self.platform
        if self.python:
            d["python"] = self.python
        return d

    def command(self, script: str, src: Path, *, inputs: Path | None, network: bool, writable_copy: bool,
                name: str) -> list[str]:
        cap = MAX_OUTPUT_BYTES
        wrapper = _WRAPPER % (script, cap, cap, cap, cap)
        cmd = [
            self.docker, "run", *self._plat(), "--rm", "--name", name,
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
            path = ":".join([*(f"{root}/{p}" for p in self.python_path), f"{root}/src", root])
            cmd += ["-v", f"{self.deps_dir.resolve()}:/deps:ro",
                    "-e", "PATH=/deps/venv/bin:/usr/local/bin:/usr/bin:/bin",
                    "-e", f"PYTHONPATH={path}", "-e", "PYTHONDONTWRITEBYTECODE=1"]
        return cmd + [self.image, "sh", "-c", wrapper]

    def registry_hosts(self) -> tuple[str, ...]:
        return tuple(h for r in self.registries for h in REGISTRIES[r])

    def install_deps(self, script: str, src: Path, deps_dir: Path, *, timeout_s: int = 1800,
                     prefetch_dir: Path | None = None) -> WorkerResult:
        """Run `script` with network access to the package registry only.

        `prefetch_dir` (source archives the host fetched and checked by sha256,
        see harness/stages/prefetch.py) is mounted read-only at /prefetch; the
        script unpacks them inside the container, never on the host.

        The install container joins an internal network with no route out; a
        proxy container on that network and the default bridge forwards HTTPS
        to the configured registries' hosts only. The container writes only to
        /deps (the repository's dependency folder) and its own tmpfs, which is
        mounted with exec here (and only here) because build backends run the
        tools they install there (cmake, meson, compilers).
        """
        self._preflight()
        self._preflight(self.base_image)  # the registry proxy runs from the base image
        try:
            result = self._install_deps(script, src, deps_dir, timeout_s, prefetch_dir)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            # A setup step (network, proxy, logs) failed: Docker going away is the usual cause.
            if self.guard is not None:
                err = e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
                self.guard.raise_if_outage(getattr(e, "returncode", None), err)
            raise
        return self._after(result)

    def _install_deps(self, script: str, src: Path, deps_dir: Path, timeout_s: int,
                      prefetch_dir: Path | None = None) -> WorkerResult:
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
                            "-v", f"{PROXY_SCRIPT}:/proxy.py:ro", self.base_image,
                            "python", "/proxy.py", str(PROXY_PORT), *self.registry_hosts()],
                           check=True, capture_output=True, timeout=60)
            subprocess.run([d, "network", "connect", "bridge", proxy], check=True, capture_output=True, timeout=60)
            cap = MAX_OUTPUT_BYTES
            wrapper = _WRAPPER % (script, cap, cap, cap, cap)
            url = f"http://{proxy}:{PROXY_PORT}"
            cmd = [d, "run", *self._plat(), "--rm", "--name", name, "--network", net,
                   "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                   "--pids-limit", str(self.pids), "--memory", "4g", "--memory-swap", "4g", "--cpus", self.cpus,
                   "--user", "65534:65534",
                   "--tmpfs", f"/work:size={self.work_size},uid=65534,gid=65534,mode=0700,exec",
                   "--tmpfs", "/tmp:size=3g,mode=1777,exec",
                   "-v", f"{Path(src).resolve()}:/src:ro", "-v", f"{deps_dir.resolve()}:/deps:rw",
                   *(["-v", f"{Path(prefetch_dir).resolve()}:/prefetch:ro"] if prefetch_dir else []),
                   "-e", "HOME=/tmp", "-e", "QOT_COPY=1", "-e", "QOT_CWD=/work", "-e", "QOT_INSTALL=1",
                   "-e", f"HTTPS_PROXY={url}", "-e", f"https_proxy={url}",
                   "-e", "PIP_DISABLE_PIP_VERSION_CHECK=1", "-e", "PIP_NO_INPUT=1", "-e", "PIP_NO_CACHE_DIR=1",
                   self.image, "sh", "-c", wrapper]
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, stdin=subprocess.DEVNULL,
                                   errors="replace")
                result = WorkerResult(p.returncode, p.stdout, p.stderr, truncated="[qot: output truncated]" in p.stderr)
            except subprocess.TimeoutExpired:
                _cleanup([d, "kill", name])
                result = WorkerResult(None, "", "timed out", timed_out=True)
            log = subprocess.run([d, "logs", proxy], capture_output=True, text=True, timeout=60).stdout
        finally:
            _cleanup([d, "rm", "-f", proxy, name])
            _cleanup([d, "network", "rm", net])
        result.duration_s = time.monotonic() - start
        result.proxy_log = [json.loads(x) for x in log.splitlines() if x.startswith("{")]
        return result

    def run(self, script: str, src: Path, *, inputs: Path | None = None, network: bool = False,
            timeout_s: int = 600, writable_copy: bool = True) -> WorkerResult:
        self._preflight()
        name = f"qot-{uuid.uuid4().hex[:12]}"
        cmd = self.command(script, src, inputs=inputs, network=network, writable_copy=writable_copy, name=name)
        start = time.monotonic()
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, stdin=subprocess.DEVNULL,
                               errors="replace")
        except subprocess.TimeoutExpired as e:
            _cleanup([self.docker, "kill", name])
            out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            return self._after(WorkerResult(None, out[:MAX_OUTPUT_BYTES], "timed out", timed_out=True,
                                            duration_s=time.monotonic() - start))
        return self._after(WorkerResult(p.returncode, p.stdout, p.stderr,
                                        truncated="[qot: output truncated]" in p.stderr,
                                        duration_s=time.monotonic() - start))
