"""Claude Code adapter: claude -p --output-format json, read and search tools only."""

from __future__ import annotations

import json
from pathlib import Path

from harness.adapters.base import Adapter, Invocation, Parsed, extract_json, model_schema
from harness.controller import cleanenv

# Every flag here exists to stop the CLI loading anything we did not hand it.
ISOLATION_FLAGS = [
    "--safe-mode",                 # no CLAUDE.md, skills, plugins, hooks, MCP, custom agents
    "--restricted",                # no code-running tools; ignore user/project/local settings
    "--setting-sources", "",       # load no settings files at all
    "--strict-mcp-config",         # only MCP servers from --mcp-config ...
    "--mcp-config", '{"mcpServers":{}}',  # ... which is none
    "--tools", "Read,Grep,Glob",   # read and search only; no shell, no edits, no web
    "--disable-slash-commands",
    "--no-session-persistence",
    "--permission-mode", "dontAsk",
]


class ClaudeAdapter(Adapter):
    name = "claude"
    binary = "claude"
    max_timeout_s = 1800
    isolation_flags_verified_for = ("2.1.310 (Claude Code)",)

    def __init__(self, model: str | None = "opus", config_dir: str | Path | None = "auto", **kw):
        super().__init__(model=model, **kw)
        self.config_dir = config_dir

    def _config_dir(self) -> Path | None:
        """Harness-owned CLAUDE_CONFIG_DIR, if David has signed in to it.

        Without it the CLI uses the default config dir; the isolation flags still
        keep CLAUDE.md, hooks, MCP and settings out, but account metadata (such
        as the account email) is still placed in the model's context.
        """
        if self.config_dir in (None, "default"):
            return None
        d = cleanenv.claude_config_dir() if self.config_dir == "auto" else Path(self.config_dir).expanduser()
        if self.config_dir == "auto" and not (d / ".claude.json").exists():
            return None
        return d

    def config_mode(self) -> str:
        return "harness-config-dir" if self._config_dir() else "default-config-dir+isolation-flags"

    def env(self) -> dict[str, str]:
        env = cleanenv.base_env(cleanenv.binary_dir(self.binary))
        d = self._config_dir()
        if d:
            env["CLAUDE_CONFIG_DIR"] = str(d)
        return env

    def build_command(self, prompt: str, system: str, schema_name: str, cwd: Path, out_file: Path) -> list[str]:
        cmd = [self.resolved_binary() or self.binary, "-p", prompt, "--output-format", "json",
               "--system-prompt", system, "--json-schema", json.dumps(model_schema(schema_name)), *ISOLATION_FLAGS]
        if self.model:
            cmd += ["--model", self.model]
        return cmd + self.extra_args

    def parse(self, inv: Invocation) -> Parsed:
        try:
            doc = json.loads(inv.stdout)
        except json.JSONDecodeError:
            # Never quote stdout here: it can contain repository text, and errors
            # feed usage-limit detection and run records.
            return Parsed(None, None, {}, f"stdout was not JSON ({len(inv.stdout)} chars); stderr: {inv.stderr[-300:]!r}",
                          failed_call=inv.exit_code not in (0, None))
        usage = doc.get("usage") or {}
        tokens = {
            "input": usage.get("input_tokens", 0),
            "output": usage.get("output_tokens", 0),
            "cache_read": usage.get("cache_read_input_tokens", 0),
            "cache_creation": usage.get("cache_creation_input_tokens", 0),
            "reported_cost_usd": doc.get("total_cost_usd", 0.0) or 0.0,
        }
        models = doc.get("modelUsage") or {}
        model_id = max(models, key=lambda m: models[m].get("outputTokens", 0)) if models else None
        if doc.get("is_error"):
            return Parsed(None, model_id, tokens, str(doc.get("result") or doc.get("subtype")), failed_call=True)
        data = doc.get("structured_output")
        if not isinstance(data, dict):
            data = extract_json(doc.get("result") or "")
        return Parsed(data, model_id, tokens, None if data else "no structured output")
