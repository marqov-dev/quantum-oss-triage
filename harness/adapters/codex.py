"""OpenAI Codex CLI adapter: codex exec --json --output-schema, read-only sandbox.

Codex reads files with shell commands, so it runs in a reviewer sandbox
(harness/adapters/sandbox.py) by default. Flags checked against
`codex exec --help` for codex-cli 0.164.0.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.adapters.base import Adapter, Invocation, Parsed, extract_json, model_schema
from harness.adapters.sandbox import ReviewerSandbox
from harness.controller import cleanenv


class CodexAdapter(Adapter):
    name = "codex"
    binary = "codex"
    max_timeout_s = 1800
    # Codex reads files with shell commands even under --sandbox read-only.
    reads_with_shell = True

    def __init__(self, model=None, binary=None, extra_args=None, sandbox: bool | dict = True, effort=None):
        super().__init__(model, binary, extra_args, effort)
        if sandbox:
            self.sandbox = ReviewerSandbox("codex", **(sandbox if isinstance(sandbox, dict) else {}))

    def env(self) -> dict[str, str]:
        if self.sandbox is not None:
            return cleanenv.base_env()  # for the docker client; the container gets its own
        env = cleanenv.base_env(cleanenv.binary_dir(self.binary))
        env["CODEX_HOME"] = str(cleanenv.codex_home())
        return env

    def build_command(self, prompt: str, system: str, schema_name: str, cwd: Path, out_file: Path) -> list[str]:
        schema_file = out_file.parent / "schema.json"
        schema_file.write_text(json.dumps(model_schema(schema_name)))
        cmd = [self.resolved_binary() or self.binary, "exec", "--json",
               "--output-schema", str(schema_file), "-o", str(out_file),
               "--sandbox", "read-only", "--skip-git-repo-check", "-C", str(cwd),
               "--ephemeral", "--ignore-rules", "-c", "project_doc_max_bytes=0"]
        if self.sandbox is not None:
            cmd.append("--strict-config")
        if self.model:
            cmd += ["-m", self.model]
        if self.effort:
            cmd += ["-c", f'model_reasoning_effort="{self.effort}"']
        # Codex has no system-prompt flag; the harness text leads the prompt.
        return cmd + self.extra_args + [f"{system}\n\n{prompt}"]

    def parse(self, inv: Invocation) -> Parsed:
        tokens = {"input": 0, "output": 0, "cache_read": 0}
        model_id = self.model
        error = None
        for line in inv.stdout.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            usage = ev.get("usage") if isinstance(ev, dict) else None
            if isinstance(usage, dict):
                tokens["input"] += usage.get("input_tokens", 0)
                tokens["output"] += usage.get("output_tokens", 0)
                tokens["cache_read"] += usage.get("cached_input_tokens", 0)
            if isinstance(ev, dict) and ev.get("model"):
                model_id = ev["model"]
            if isinstance(ev, dict) and ev.get("type") in ("error", "turn.failed"):
                error = json.dumps(ev)[:500]
        if error and not inv.out_file_text:
            return Parsed(None, model_id, tokens, error, failed_call=True)
        data = extract_json(inv.out_file_text or "")
        return Parsed(data, model_id or "codex-default", tokens, None if data else "no output file / JSON")
