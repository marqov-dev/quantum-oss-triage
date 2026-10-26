"""Clean process environments for the AI CLIs.

The CLIs must not inherit the operator's environment. A desktop or IDE session
can export dozens of variables (account email, messaging sockets, proxy base
URLs, API keys). We start from an empty environment and add back only what a
CLI needs to find its own sign-in.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# The harness-owned home for CLI configuration. Never inside a repository.
CONFIG_ROOT = Path(os.environ.get("QOT_CONFIG_ROOT", Path.home() / ".config" / "quantum-oss-triage"))

_KEEP = ("HOME", "USER", "LOGNAME", "LANG", "TMPDIR")
_FORBIDDEN_MARKERS = ("API_KEY", "TOKEN", "SECRET", "MARQOV", "GITHUB", "CLAUDE_CODE_", "ANTHROPIC_", "OPENAI_", "GEMINI_", "GOOGLE_")


def base_env(extra_path: list[str] | None = None) -> dict[str, str]:
    """A minimal environment: identity of the OS user, locale and a plain PATH."""
    env = {k: os.environ[k] for k in _KEEP if k in os.environ}
    path = [*(extra_path or []), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
    env["PATH"] = os.pathsep.join(dict.fromkeys(path))
    env["TERM"] = "dumb"
    env["NO_COLOR"] = "1"
    return env


def forbidden_keys(env: dict[str, str], allowed: tuple[str, ...] = ()) -> list[str]:
    """Variables that look like credentials or host-session plumbing."""
    return sorted(k for k in env if k not in allowed and any(m in k.upper() for m in _FORBIDDEN_MARKERS))


def binary_dir(binary: str) -> list[str]:
    found = shutil.which(binary)
    return [str(Path(found).parent)] if found else []


def claude_config_dir() -> Path:
    return CONFIG_ROOT / "claude"


def codex_home() -> Path:
    """A harness-owned CODEX_HOME with no MCP servers, profiles or skills.

    Sign-in is linked from the operator's ~/.codex/auth.json if present; nothing
    else from ~/.codex is used.
    """
    home = CONFIG_ROOT / "codex"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text(
        "# Written by quantum-oss-triage. Do not add MCP servers or profiles here.\n"
        "project_doc_max_bytes = 0\n"
        'sandbox_mode = "read-only"\n'
        'approval_policy = "never"\n'
        "[mcp_servers]\n"
    )
    auth = home / "auth.json"
    personal = Path.home() / ".codex" / "auth.json"
    if not auth.exists() and personal.exists():
        auth.symlink_to(personal)
    return home


def antigravity_home() -> Path:
    home = CONFIG_ROOT / "antigravity"
    home.mkdir(parents=True, exist_ok=True)
    return home
