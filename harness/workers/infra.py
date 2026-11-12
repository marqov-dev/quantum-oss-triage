"""Is the infrastructure a worker needs there: the Docker daemon, the image, disk space?

A worker that cannot start, or whose container dies because Docker went away,
says nothing about the project under review. Recording it as a failed install
or a failed test would be wrong, and round one had to redo such units by hand.
So the controller checks before each launch (cheaply, cached for a few
seconds), rechecks after any failed launch, and raises InfrastructureUnavailable
instead of returning a result. The pipeline then pauses the repository, writes
nothing for the unit that hit the outage, and a rerun of the same command
resumes there.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

GB = 1024 ** 3

# Docker Desktop keeps its disk image in a folder on the host, set in its
# settings. The daemon's own root dir is inside the VM on macOS and Windows.
DOCKER_DESKTOP_SETTINGS = (
    Path.home() / "Library" / "Group Containers" / "group.com.docker" / "settings-store.json",
    Path.home() / "Library" / "Group Containers" / "group.com.docker" / "settings.json",
    Path.home() / ".docker" / "desktop" / "settings-store.json",
    Path.home() / ".docker" / "desktop" / "settings.json",
)


class InfrastructureUnavailable(RuntimeError):
    """The worker infrastructure is down: not a property of the project."""

    def __init__(self, kind: str, reason: str):
        super().__init__(reason)
        self.kind = kind  # "docker", "image" or "disk"
        self.reason = reason


@dataclass
class DiskCheck:
    label: str
    path: Path
    min_free_gb: float
    must_exist: bool = False  # Docker's data folder: missing means its volume is not mounted


def _existing(path: Path) -> Path:
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


def _free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def docker_data_path(setting, settings_files=DOCKER_DESKTOP_SETTINGS) -> Path | None:
    """The host folder holding Docker's data: a configured path, or with "auto"
    Docker Desktop's DataFolder setting. None when it cannot be found."""
    if not setting:
        return None
    if setting != "auto":
        return Path(setting).expanduser()
    for f in settings_files:
        try:
            folder = json.loads(Path(f).read_text()).get("DataFolder")
        except (OSError, ValueError, AttributeError):
            continue
        if folder:
            return Path(folder)
    return None


class InfraGuard:
    """Checks the Docker daemon, images and free disk space, caching each answer for `ttl_s`."""

    def __init__(self, docker: str = "docker", disks=(), ttl_s: float = 5.0, timeout_s: float = 10.0,
                 run: Callable = subprocess.run, free_bytes: Callable[[Path], int] = _free_bytes,
                 clock: Callable[[], float] = time.monotonic, which: Callable = shutil.which):
        self.docker, self.disks, self.ttl_s, self.timeout_s = docker, list(disks), ttl_s, timeout_s
        self._run, self._free, self._clock, self._which = run, free_bytes, clock, which
        self._cache: dict[str, tuple[float, InfrastructureUnavailable | None]] = {}
        self._lock = threading.Lock()

    # --- single checks, each returning the problem or None ---------------------
    def _cached(self, key: str, force: bool, probe: Callable[[], InfrastructureUnavailable | None]):
        with self._lock:
            hit = self._cache.get(key)
            if hit and not force and self._clock() - hit[0] < self.ttl_s:
                return hit[1]
        problem = probe()
        with self._lock:
            self._cache[key] = (self._clock(), problem)
        return problem

    def _docker(self, args: list[str]) -> tuple[int | None, str]:
        try:
            r = self._run([self.docker, *args], capture_output=True, text=True, timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            return None, f"not responding within {self.timeout_s:g}s"
        except OSError as e:
            return None, str(e)
        return r.returncode, (r.stderr or r.stdout or "").strip()

    def daemon_problem(self, force: bool = False) -> InfrastructureUnavailable | None:
        def probe():
            if not self._which(self.docker):
                return InfrastructureUnavailable("docker", f"{self.docker} is not installed")
            rc, text = self._docker(["info", "--format", "{{.ServerVersion}}"])
            if rc == 0:
                return None
            detail = text.splitlines()[-1][:300] if text else f"exit {rc}"
            if rc is None:
                return InfrastructureUnavailable("docker", f"Docker daemon not responding ({detail})")
            return InfrastructureUnavailable("docker", f"Docker daemon unavailable ({detail})")
        return self._cached("daemon", force, probe)

    def image_problem(self, image: str, force: bool = False) -> InfrastructureUnavailable | None:
        def probe():
            rc, text = self._docker(["image", "inspect", "--format", "{{.Id}}", image])
            if rc == 0:
                return None
            if rc is None:
                return InfrastructureUnavailable("docker", f"Docker daemon not responding ({text})")
            return InfrastructureUnavailable("image", f"worker image {image} is not available "
                                                      f"({text.splitlines()[-1][:200] if text else f'exit {rc}'})")
        return self._cached(f"image:{image}", force, probe)

    def disk_problem(self, force: bool = False) -> InfrastructureUnavailable | None:
        def probe():
            for c in self.disks:
                if c.must_exist and not Path(c.path).exists():
                    return InfrastructureUnavailable("disk", f"{c.label} ({c.path}) does not exist (volume not mounted?)")
                try:
                    free = self._free(_existing(c.path))
                except OSError as e:
                    return InfrastructureUnavailable("disk", f"{c.label} ({c.path}): cannot read free space ({e})")
                if free < c.min_free_gb * GB:
                    return InfrastructureUnavailable(
                        "disk", f"{c.label} ({c.path}) has {free / GB:.1f} GB free, below the {c.min_free_gb:g} GB minimum")
            return None
        return self._cached("disk", force, probe)

    # --- what callers use --------------------------------------------------------
    def check(self, image: str | None = None, *, docker: bool = True, force: bool = False) -> None:
        """Raise InfrastructureUnavailable if a worker launch should not happen now."""
        problem = self.disk_problem(force)
        if not problem and docker:
            problem = self.daemon_problem(force) or (self.image_problem(image, force) if image else None)
        if problem:
            raise problem

    def outage_after_failure(self, exit_code, stderr: str = "", image: str | None = None):
        """After a failed launch or a failed container: was the infrastructure the cause?

        Rechecks (uncached) the daemon and the disk; and the image when
        `docker run` itself failed (exit 125). Returns the problem, or None when
        the failure belongs to the project."""
        problem = self.daemon_problem(force=True) or self.disk_problem(force=True)
        if not problem and image and exit_code == 125:
            problem = self.image_problem(image, force=True)
        return problem

    def raise_if_outage(self, exit_code, stderr: str = "", image: str | None = None) -> None:
        problem = self.outage_after_failure(exit_code, stderr, image)
        if problem:
            raise problem

    def status(self) -> dict:
        """A report for `qot doctor`: never raises."""
        out = {"docker": None, "disks": []}
        p = self.daemon_problem(force=True)
        out["docker"] = "ok" if not p else p.reason
        for c in self.disks:
            try:
                free = self._free(_existing(c.path)) / GB
            except OSError as e:
                out["disks"].append({"label": c.label, "path": str(c.path), "error": str(e)})
                continue
            out["disks"].append({"label": c.label, "path": str(c.path), "free_gb": round(free, 1),
                                 "min_free_gb": c.min_free_gb, "ok": free >= c.min_free_gb})
        return out


def from_config(worker_cfg: dict, run_dir: Path | None, docker: str = "docker") -> InfraGuard | None:
    """Build the guard from `worker.preflight` in config/harness.yaml (all keys optional)."""
    cfg = (worker_cfg or {}).get("preflight") or {}
    if cfg.get("enabled", True) is False:
        return None
    disks = []
    if run_dir is not None:
        disks.append(DiskCheck("run directory", Path(run_dir), float(cfg.get("run_dir_min_free_gb", 8))))
    data = docker_data_path(cfg.get("docker_data_path", "auto"))
    if data is not None:
        disks.append(DiskCheck("Docker data", data, float(cfg.get("docker_data_min_free_gb", 40)), must_exist=True))
    return InfraGuard(docker=docker, disks=disks, ttl_s=float(cfg.get("cache_s", 5)),
                      timeout_s=float(cfg.get("docker_timeout_s", 10)))
