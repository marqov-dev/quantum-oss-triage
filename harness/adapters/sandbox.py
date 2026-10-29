"""Reviewer sandbox: run an AI CLI that reads files with shell commands inside a
container, so text in a repository cannot get code run on the host.

One image per CLI (docker/reviewer.Dockerfile). Each call gets a fresh
container with:

- the read-only review copy at /review;
- a per-call output folder at /out (the reply file and the schema);
- a harness-owned home at /home/qot holding only that CLI's sign-in and the
  harness's own settings for it. Nothing from the operator's home directory is
  mounted or copied, apart from the sign-in file when the operator chooses to
  copy it (`qot sandbox-login --copy`);
- a read-only root, no capabilities, no-new-privileges, CPU, memory and
  process limits, and a seccomp profile that differs from Docker's default only
  in letting the CLI's own command sandbox (bubblewrap) create user namespaces.

The CLI itself needs the network to reach its provider, so the container is on
the default bridge. Codex runs its shell commands in its own read-only,
no-network sandbox inside the container; see docs/METHOD.md for Antigravity.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from harness.controller import cleanenv
from harness.paths import REPO_ROOT

REVIEW, OUT, HOME = "/review", "/out", "/home/qot"
SECCOMP = REPO_ROOT / "docker" / "reviewer-seccomp.json"
DOCKERFILE = REPO_ROOT / "docker" / "reviewer.Dockerfile"

# Where each CLI keeps user-level state on the operator's machine (never
# mounted), and the configuration inside it: settings, permission rules,
# instructions, skills, MCP servers, memory. doctor checks that no copy of any
# of these reaches the sandbox home; sign-in files are the only exception.
PERSONAL_ROOTS = {"codex": [".codex"], "agy": [".gemini"]}
PERSONAL_CONFIG = {
    "codex": [".codex/config.toml", ".codex/AGENTS.md", ".codex/rules", ".codex/skills", ".codex/hooks.json",
              ".codex/prompts", ".codex/memories"],
    "agy": [".gemini/config", ".gemini/GEMINI.md", ".gemini/settings.json", ".gemini/antigravity-cli/settings.json",
            ".gemini/antigravity/mcp_config.json", ".gemini/antigravity/knowledge", ".gemini/antigravity/brain"],
}
# Folders the CLI itself writes identically into every home (bundled skills):
# shipped with the CLI, not personal, so they are left out of the comparison.
CLI_MANAGED = {"codex": [".codex/skills/.system"], "agy": [".gemini/antigravity-cli/builtin"]}
# Files the CLI writes on first start with fixed content. They match the
# operator's copy byte for byte, so they are left out only while they still
# hold exactly this default.
CLI_DEFAULTS = {"agy": {".gemini/config/projects/default-cli-project.json":
                        {"id": "default-cli-project", "name": "CLI Project", "projectResources": {}}}}

# Host folders a probe or evaluation exposes inside the container at the same
# path, so a hook or instruction that is obeyed leaves a visible marker file.
_MARKER_DIRS: list[Path] = []


@contextlib.contextmanager
def probe_markers(path: Path):
    path = Path(path).resolve()
    _MARKER_DIRS.append(path)
    try:
        yield path
    finally:
        _MARKER_DIRS.remove(path)


@dataclass
class CliSpec:
    cli: str               # binary name inside the image
    target: str            # Dockerfile build target
    auth_files: tuple      # paths inside the sandbox home that hold the sign-in
    personal_auth: tuple   # the operator's own sign-in file(s) that --copy may copy
    login_cmd: tuple       # interactive sign-in inside the container
    harness_files: dict = field(default_factory=dict)  # home-relative path -> content, rewritten each run


CODEX_CONFIG = """\
# Written by quantum-oss-triage on every run. Do not add MCP servers, profiles or plugins.
project_doc_max_bytes = 0
sandbox_mode = "read-only"
approval_policy = "never"
web_search = "disabled"

[features]
apps = false
browser_use = false
browser_use_external = false
computer_use = false
goals = false
hooks = false
image_generation = false
multi_agent = false
plugins = false
remote_plugin = false
skill_mcp_dependency_install = false
skill_search = false
tool_suggest = false
"""

SPECS = {
    "codex": CliSpec(
        cli="codex", target="codex",
        auth_files=(".codex/auth.json",),
        personal_auth=(".codex/auth.json",),
        login_cmd=("codex", "login", "--device-auth"),
        harness_files={".codex/config.toml": CODEX_CONFIG},
    ),
    "agy": CliSpec(
        cli="agy", target="agy",
        # Filled in from what agy writes on Linux after a sign-in; see auth_present().
        auth_files=(),
        personal_auth=(),  # macOS keeps the agy sign-in in the keychain: nothing to copy
        login_cmd=("agy", "-p", "Reply with the single word OK.", "--output-format", "text"),
        harness_files={".gemini/antigravity-cli/settings.json": '{"trustedWorkspaces": []}\n'},
    ),
}


def default_image(cli: str) -> str:
    return f"quantum-oss-triage-reviewer-{cli}:dev"


def home_dir(cli: str) -> Path:
    return cleanenv.CONFIG_ROOT / "sandbox" / cli / "home"


class ReviewerSandbox:
    def __init__(self, cli: str, image: str | None = None, home: Path | None = None, docker: str = "docker",
                 cpus: str = "2", memory: str = "2g", pids: int = 512, seccomp: Path | None = None):
        self.spec = SPECS[cli]
        self.cli = cli
        self.image = image or default_image(cli)
        self.home = Path(home) if home else home_dir(cli)
        self.docker, self.cpus, self.memory, self.pids = docker, cpus, memory, pids
        self.seccomp = Path(seccomp) if seccomp else SECCOMP

    # --- discovery ---------------------------------------------------------
    def image_id(self) -> str | None:
        if not shutil.which(self.docker):
            return None
        try:
            r = subprocess.run([self.docker, "image", "inspect", "--format", "{{.Id}}", self.image],
                               capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            return None
        return r.stdout.strip() if r.returncode == 0 else None

    def auth_present(self) -> bool:
        if self.spec.auth_files:
            return all((self.home / f).is_file() for f in self.spec.auth_files)
        # agy on Linux: no keyring in the container, so it falls back to a file
        # under its state folder. Treat any credential-looking file as present.
        state = self.home / ".gemini"
        return state.is_dir() and any(_looks_like_credential(p) for p in state.rglob("*") if p.is_file())

    def available(self) -> tuple[bool, str]:
        if not shutil.which(self.docker):
            return False, "docker not installed"
        if not self.image_id():
            return False, (f"reviewer image {self.image} not built "
                           f"(docker build -f docker/reviewer.Dockerfile --target {self.spec.target} -t {self.image} docker)")
        if not self.auth_present():
            return False, f"not signed in inside the reviewer sandbox (run `qot sandbox-login {self.cli}`)"
        return True, self.image

    def version(self) -> str | None:
        iid = self.image_id()
        if not iid:
            return None
        try:
            r = subprocess.run([self.docker, "run", "--rm", "--network", "none", self.image, self.spec.cli, "--version"],
                               capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            return None
        text = (r.stdout or r.stderr).strip()
        line = text.splitlines()[-1] if text else "unknown"
        # A rebuilt image needs its own attestation.
        return f"{line} (sandbox {iid.split(':')[-1][:12]})"

    # --- running -----------------------------------------------------------
    def prepare_home(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        os.chmod(self.home, 0o700)
        for rel, content in self.spec.harness_files.items():
            p = self.home / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)

    def mounts(self, review_dir: Path, out_dir: Path) -> list[tuple[str, str, str]]:
        m = [(str(Path(review_dir).resolve()), REVIEW, "ro"),
             (str(Path(out_dir).resolve()), OUT, "rw"),
             (str(self.home.resolve()), HOME, "rw")]
        return m + [(str(d), str(d), "rw") for d in _MARKER_DIRS if d.is_dir()]

    def docker_args(self, name: str, review_dir: Path, out_dir: Path, *, interactive: bool = False) -> list[str]:
        args = [self.docker, "run", "--rm", "--name", name]
        args += ["-it"] if interactive else []
        args += ["--network", "bridge", "--read-only", "--cap-drop", "ALL",
                 "--security-opt", "no-new-privileges", "--security-opt", f"seccomp={self.seccomp}",
                 "--pids-limit", str(self.pids), "--memory", self.memory, "--memory-swap", self.memory,
                 "--cpus", self.cpus, "--tmpfs", "/tmp:size=512m,mode=1777"]
        if os.name == "posix" and hasattr(os, "getuid") and _host_is_linux():
            args += ["--user", f"{os.getuid()}:{os.getgid()}"]
        for src, dst, mode in self.mounts(review_dir, out_dir):
            args += ["-v", f"{src}:{dst}:{mode}"]
        # Only these variables reach the CLI; nothing from the host environment.
        args += ["-e", f"HOME={HOME}", "-e", "TERM=dumb", "-e", "NO_COLOR=1", "-w", REVIEW, self.image]
        return args

    def wrap(self, cmd: list[str], cwd: Path, out_dir: Path, name: str) -> list[str]:
        """Turn a host command line into the same call inside a container."""
        self.prepare_home()
        mapping = [(str(Path(out_dir).resolve()), OUT), (str(Path(out_dir)), OUT),
                   (str(Path(cwd).resolve()), REVIEW), (str(Path(cwd)), REVIEW)]
        inner = [self.spec.cli] + [_map_path(part, mapping) for part in cmd[1:]]
        return self.docker_args(name, cwd, out_dir) + inner

    def kill(self, name: str) -> None:
        subprocess.run([self.docker, "kill", name], capture_output=True, timeout=60)

    def login_command(self, name: str = "qot-sandbox-login") -> list[str]:
        self.prepare_home()
        empty = self.home.parent / "login-review"
        empty.mkdir(exist_ok=True)
        out = self.home.parent / "login-out"
        out.mkdir(exist_ok=True)
        return self.docker_args(name, empty, out, interactive=True) + list(self.spec.login_cmd)

    def copy_personal_auth(self) -> list[str]:
        """Copy only the operator's sign-in file(s) into the sandbox home."""
        copied = []
        self.prepare_home()
        for rel in self.spec.personal_auth:
            src = Path.home() / rel
            if src.is_file():
                dst = self.home / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
                os.chmod(dst, 0o600)
                copied.append(rel)
        return copied

    # --- isolation checks used by qot doctor -------------------------------
    def isolation_report(self, review_dir: Path, out_dir: Path, personal_home: Path | None = None) -> dict:
        """What the sandbox would expose, and whether any personal config is in it."""
        personal_home = Path(personal_home or Path.home()).resolve()
        roots = [personal_home / p for p in PERSONAL_ROOTS.get(self.cli, [])]
        bad_mounts = []
        for src, _dst, _mode in self.mounts(review_dir, out_dir):
            s = Path(src)
            if s == personal_home or any(_within(s, r) or _within(r, s) for r in roots):
                bad_mounts.append(src)
        auth = {(personal_home / a).resolve() for a in self.spec.personal_auth}
        managed = [personal_home / m for m in CLI_MANAGED.get(self.cli, [])]
        personal_hashes = {}
        for rel in PERSONAL_CONFIG.get(self.cli, []):
            root = personal_home / rel
            files = [root] if root.is_file() else (_walk_files(root, limit=5000) if root.is_dir() else [])
            for p in files:
                if (p.resolve() in auth or not 0 < p.stat().st_size <= 5_000_000
                        or any(_within(p, m) for m in managed)):
                    continue
                if _is_cli_default(self.cli, str(p.relative_to(personal_home)), p):
                    continue
                personal_hashes.setdefault(_sha(p), str(p.relative_to(personal_home)))
        copies = []
        symlinks = []
        for p in self.home.rglob("*"):
            if p.is_symlink():
                # A relative link that stays inside the home (agy's cli.log ->
                # log/cli-<time>.log) is the CLI's own; anything else is flagged.
                target = os.readlink(p)
                if os.path.isabs(target) or not _within(p, self.home):
                    symlinks.append(str(p.relative_to(self.home)))
            elif p.is_file() and p.stat().st_size <= 5_000_000 and p.stat().st_size > 0:
                h = _sha(p)
                if h in personal_hashes:
                    copies.append({"sandbox": str(p.relative_to(self.home)), "personal": personal_hashes[h]})
        return {"mounts": [f"{s} -> {d} ({m})" for s, d, m in self.mounts(review_dir, out_dir)],
                "personal_mounts": bad_mounts, "personal_copies": copies, "symlinks_in_home": symlinks}


def _map_path(part: str, mapping: list[tuple[str, str]]) -> str:
    for host, inner in mapping:
        if part == host or part.startswith(host + "/"):
            return inner + part[len(host):]
    return part


def _is_cli_default(cli: str, rel: str, p: Path) -> bool:
    default = CLI_DEFAULTS.get(cli, {}).get(rel)
    if default is None:
        return False
    try:
        return json.loads(p.read_text()) == default
    except (ValueError, OSError):
        return False


def _within(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _walk_files(root: Path, limit: int):
    n = 0
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            p = Path(dirpath) / f
            if p.is_file() and not p.is_symlink():
                yield p
                n += 1
                if n >= limit:
                    return


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _looks_like_credential(p: Path) -> bool:
    n = p.name.lower()
    return any(k in n for k in ("token", "credential", "oauth", "auth")) and p.stat().st_size > 0


def _host_is_linux() -> bool:
    return os.uname().sysname == "Linux"
