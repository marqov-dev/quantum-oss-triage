"""Common adapter behaviour: run a CLI headlessly, parse, validate, retry once.

A provider refusing because its model is at capacity is retried after a
backoff; a usage limit is not (the run pauses until the window resets).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from harness.controller import schema

USAGE_LIMIT_PATTERNS = re.compile(
    r"usage limit|rate[ -]?limit|limit reached|quota|too many requests|\b429\b|resets? at|out of (?:credits|usage)",
    re.IGNORECASE,
)
# Server-side refusals that say nothing about our own usage, such as Codex's
# "Selected model is at capacity". Checked only after the usage-limit patterns.
CAPACITY_PATTERNS = re.compile(r"at capacity|overloaded|server (?:is )?busy|temporarily unavailable", re.IGNORECASE)
CAPACITY_BACKOFF_S = (30, 120, 300)
NOT_SIGNED_IN_PATTERNS = re.compile(r"not logged in|authentication failed|not logged into|please run /login|not authenticated|login required|sign in", re.IGNORECASE)


@dataclass
class Invocation:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float
    out_file_text: str | None = None


@dataclass
class AdapterResult:
    ok: bool
    data: dict | None
    raw: str
    model_id: str | None
    tokens: dict = field(default_factory=dict)
    error: str | None = None
    attempts: int = 0
    usage_limited: bool = False
    not_signed_in: bool = False
    capacity_refused: bool = False   # still refused for capacity after every backoff
    capacity_retries: int = 0
    duration_s: float = 0.0
    command: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class Parsed:
    data: dict | None
    model_id: str | None
    tokens: dict
    error: str | None
    failed_call: bool = False  # the CLI itself reported an error (not just bad JSON)


def extract_json(text: str) -> dict | None:
    """Take the JSON object out of a model's text reply (bare or fenced)."""
    if not text:
        return None
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    candidates = [fence.group(1)] if fence else []
    candidates.append(text)
    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first : last + 1])
    for c in candidates:
        try:
            value = json.loads(c)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


def model_schema(name: str) -> dict:
    """The schema as handed to a CLI: the meta keys some CLIs reject are removed."""
    s = dict(schema.load(name))
    s.pop("$schema", None)
    s.pop("$id", None)
    return s


class Adapter:
    """One AI CLI. Subclasses define the command line and how to read its output."""

    name: str = ""
    binary: str = ""
    max_timeout_s: int = 1800
    capacity_backoff_s: tuple[float, ...] = CAPACITY_BACKOFF_S
    sleep = staticmethod(time.sleep)  # tests replace it
    # A CLI is trusted to honour the clean configuration only after the hostile
    # probe (qot doctor) has passed for its exact version.
    isolation_flags_verified_for: tuple[str, ...] = ()
    # True when the CLI reads files by running shell commands. Run on the host,
    # text in the repository could then get repository code executed outside a
    # worker, so such a CLI is refused unless it runs in a reviewer sandbox.
    reads_with_shell: bool = False
    sandbox = None  # a ReviewerSandbox, for CLIs that read with shell commands

    def __init__(self, model: str | None = None, binary: str | None = None, extra_args: list[str] | None = None):
        self.model = model
        if binary:
            self.binary = binary
        self.extra_args = extra_args or []

    @property
    def runs_shell_on_host(self) -> bool:
        return self.reads_with_shell and self.sandbox is None

    def config_mode(self) -> str | None:
        return "reviewer-sandbox" if self.sandbox is not None else None

    # --- discovery ---------------------------------------------------------
    def resolved_binary(self) -> str | None:
        return shutil.which(self.binary)

    def available(self) -> tuple[bool, str]:
        if self.sandbox is not None:
            return self.sandbox.available()
        path = self.resolved_binary()
        if not path:
            return False, f"{self.binary} not installed"
        return True, path

    def version(self) -> str | None:
        if self.sandbox is not None:
            return self.sandbox.version()
        path = self.resolved_binary()
        if not path:
            return None
        try:
            out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30,
                                 env=self.env(), stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr).strip() else None

    def describe(self) -> dict:
        ok, reason = self.available()
        return {"name": self.name, "available": ok, "reason": reason, "version": self.version() if ok else None,
                "model": self.model}

    # --- to be defined by subclasses --------------------------------------
    def env(self) -> dict[str, str]:
        raise NotImplementedError

    def build_command(self, prompt: str, system: str, schema_name: str, cwd: Path, out_file: Path) -> list[str]:
        raise NotImplementedError

    def parse(self, inv: Invocation) -> Parsed:
        raise NotImplementedError

    # --- running ----------------------------------------------------------
    def _invoke(self, cmd: list[str], cwd: Path, timeout_s: int, out_file: Path) -> Invocation:
        start = time.monotonic()
        name = None
        if self.sandbox is not None:
            name = f"qot-{self.name}-{uuid.uuid4().hex[:12]}"
            cmd = self.sandbox.wrap(cmd, cwd, out_file.parent, name)
        proc = subprocess.Popen(cmd, cwd=cwd, env=self.env(), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                start_new_session=True)
        timed_out = False
        try:
            stdout, stderr = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            # Hard timeout: kill the whole process group (some CLIs hang headless).
            timed_out = True
            if name:
                self.sandbox.kill(name)  # killing the docker client leaves the container running
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate()
        out_text = out_file.read_text() if out_file.exists() else None
        return Invocation(None if timed_out else proc.returncode, stdout or "", stderr or "", timed_out,
                          time.monotonic() - start, out_text)

    def run(self, prompt: str, system: str, schema_name: str, cwd: Path, timeout_s: int = 1200) -> AdapterResult:
        """Run once; on invalid output retry once with the errors; then give up."""
        ok, reason = self.available()
        if not ok:
            return AdapterResult(False, None, "", None, error=reason)
        timeout_s = min(timeout_s, self.max_timeout_s)
        total_tokens: dict = {}
        raw_all: list[str] = []
        attempt_prompt = prompt
        last_error = None
        duration = 0.0
        cmd: list[str] = []
        model_id = None
        attempt, capacity_retries = 1, 0
        while attempt <= 2:
            with tempfile.TemporaryDirectory(prefix=f"qot-{self.name}-") as tmp:
                out_file = Path(tmp) / "out.json"
                cmd = self.build_command(attempt_prompt, system, schema_name, cwd, out_file)
                inv = self._invoke(cmd, cwd, timeout_s, out_file)
            duration += inv.duration_s
            raw_all.append(inv.stdout if inv.out_file_text is None else inv.out_file_text + "\n--- stdout ---\n" + inv.stdout)
            if inv.timed_out:
                return AdapterResult(False, None, "\n".join(raw_all), model_id, total_tokens,
                                     f"timed out after {timeout_s}s", attempt, duration_s=duration, command=_redact_cmd(cmd))
            parsed = self.parse(inv)
            model_id = parsed.model_id or model_id
            _add_tokens(total_tokens, parsed.tokens)
            if parsed.failed_call or (inv.exit_code not in (0, None) and parsed.data is None):
                # Match the CLI's own error, never stdout, which can quote repository text.
                source = parsed.error or inv.stderr[-2000:]
                limited = bool(USAGE_LIMIT_PATTERNS.search(source))
                signed_out = bool(NOT_SIGNED_IN_PATTERNS.search(source))
                capacity = not limited and not signed_out and bool(CAPACITY_PATTERNS.search(source))
                if capacity and capacity_retries < len(self.capacity_backoff_s):
                    self.sleep(self.capacity_backoff_s[capacity_retries])
                    capacity_retries += 1
                    continue
                return AdapterResult(False, None, "\n".join(raw_all), model_id, total_tokens,
                                     parsed.error or f"exit {inv.exit_code}: {inv.stderr[-500:]}", attempt,
                                     usage_limited=limited, not_signed_in=signed_out, capacity_refused=capacity,
                                     capacity_retries=capacity_retries, duration_s=duration,
                                     command=_redact_cmd(cmd))
            if parsed.data is None:
                last_error = parsed.error or "no JSON object in output"
            else:
                errors = schema.validate(schema_name, parsed.data)
                if not errors:
                    return AdapterResult(True, parsed.data, "\n".join(raw_all), model_id, total_tokens, None,
                                         attempt, capacity_retries=capacity_retries, duration_s=duration,
                                         command=_redact_cmd(cmd))
                last_error = "schema errors: " + "; ".join(errors[:10])
            attempt_prompt = (
                f"{prompt}\n\nYour previous reply was rejected by the harness ({last_error}). "
                "Reply again with only a JSON object that matches the schema exactly."
            )
            attempt += 1
        return AdapterResult(False, None, "\n".join(raw_all), model_id, total_tokens, last_error, 2,
                             duration_s=duration, command=_redact_cmd(cmd))


def _add_tokens(total: dict, new: dict) -> None:
    for k, v in (new or {}).items():
        if isinstance(v, (int, float)):
            total[k] = total.get(k, 0) + v


def _redact_cmd(cmd: list[str]) -> list[str]:
    """Keep command lines short in records: long prompt/schema arguments become hashes."""
    import hashlib

    out = []
    for part in cmd:
        if len(part) > 200:
            out.append(f"<{len(part)} chars sha256:{hashlib.sha256(part.encode()).hexdigest()[:12]}>")
        else:
            out.append(part)
    return out
