"""
spotterprep/claude_cli.py — Run SpotterPrep's LLM calls through the Claude Code CLI.

For people who have a Claude subscription (Pro, Max, Team or Enterprise) but no API key.
`claude -p` runs on the subscription login, accepts a replacement system prompt, and with
`--json-schema` returns output that matches a schema. This module wraps it in the same
`.messages.create(**kwargs)` shape the Anthropic SDK has, so `LLMClient` works unchanged:
the reclassification tool's input schema becomes `--json-schema`, and the structured
result comes back as a tool_use block.

Differences from the API path, recorded in every eval result:
  - temperature cannot be set, so run the eval with --repeats to measure stability
  - the CLI may add its own framing around the system prompt
  - built-in tools are switched off (--tools ""), so the model only answers

Usage:
  from spotterprep.claude_cli import ClaudeCLIClient
  llm = LLMClient(client=ClaudeCLIClient(), model="sonnet")
"""
from __future__ import annotations

import json
import shutil
import subprocess
from types import SimpleNamespace
from typing import Any, Optional


class ClaudeCLIError(RuntimeError):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable
        # LLMClient retries on 429/5xx-style status codes
        self.status_code = 529 if retryable else 400


_RETRYABLE_HINTS = ("rate_limit", "overloaded", "529", "timed out", "server_error")


def _flatten(content: Any) -> str:
    """Turn API-style message content (string or block list) into plain text."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        kind = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
        get = (lambda k: block.get(k)) if isinstance(block, dict) else (lambda k: getattr(block, k, None))
        if kind == "text":
            parts.append(get("text") or "")
        elif kind == "tool_use":
            parts.append(f"[You answered: {json.dumps(get('input'))}]")
        elif kind == "tool_result":
            parts.append(f"[That answer was rejected: {get('content')}]")
    return "\n".join(p for p in parts if p)


def _transcript(messages: list[dict]) -> str:
    if len(messages) == 1:
        return _flatten(messages[0]["content"])
    lines = []
    for m in messages:
        lines.append(f"{m['role'].upper()}:\n{_flatten(m['content'])}")
    return "\n\n".join(lines) + "\n\nRespond to the last USER message."


class _Messages:
    def __init__(self, binary: str, timeout: int, model_override: Optional[str]):
        self.binary, self.timeout, self.model_override = binary, timeout, model_override
        self.models_seen: set[str] = set()

    def create(self, *, model: str = None, system: str = "", messages: list, tools: list = None,
               tool_choice: dict = None, **_ignored) -> SimpleNamespace:
        cmd = [self.binary, "-p", "--output-format", "json", "--tools", "",
               "--no-session-persistence", "--strict-mcp-config", "--system-prompt", system or ""]
        chosen_model = self.model_override or model
        if chosen_model:
            cmd += ["--model", chosen_model]
        tool = None
        if tools:
            tool = next((t for t in tools if not tool_choice or t["name"] == tool_choice.get("name")), tools[0])
            cmd += ["--json-schema", json.dumps(tool["input_schema"])]

        try:
            proc = subprocess.run(cmd, input=_transcript(messages), capture_output=True, text=True,
                                  timeout=self.timeout)
        except subprocess.TimeoutExpired as err:
            raise ClaudeCLIError(f"claude -p timed out after {self.timeout}s", retryable=True) from err
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = None
        if proc.returncode != 0 or not isinstance(payload, dict) or payload.get("is_error"):
            detail = (payload or {}).get("result") if isinstance(payload, dict) else (proc.stderr or proc.stdout)
            text = str(detail)[:500]
            raise ClaudeCLIError(f"claude -p failed: {text}", retryable=any(h in text.lower() for h in _RETRYABLE_HINTS))

        # The CLI may use a small model for housekeeping; record the one that wrote the answer.
        usage = payload.get("modelUsage") or {}
        if usage:
            self.models_seen.add(max(usage, key=lambda m: (usage[m] or {}).get("outputTokens", 0)))
        if tool is not None:
            structured = payload.get("structured_output")
            blocks = [SimpleNamespace(type="tool_use", name=tool["name"], id="cli_tool_1", input=structured)] \
                if structured is not None else [SimpleNamespace(type="text", text=str(payload.get("result", "")))]
        else:
            blocks = [SimpleNamespace(type="text", text=str(payload.get("result", "")))]
        return SimpleNamespace(content=blocks, model=chosen_model, backend="claude-cli",
                               usage=payload.get("usage"), session_id=payload.get("session_id"))


class ClaudeCLIClient:
    """Drop-in for `anthropic.Anthropic()` that calls the local `claude` CLI."""

    def __init__(self, binary: str = "claude", timeout: int = 180, model_override: Optional[str] = None):
        path = shutil.which(binary)
        if not path:
            raise FileNotFoundError("The `claude` CLI is not on PATH. Install Claude Code and run `claude` once to log in.")
        self.messages = _Messages(path, timeout, model_override)
