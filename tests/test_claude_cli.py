import json
import os
import stat

import pytest

from spotterprep.claude_cli import ClaudeCLIClient, ClaudeCLIError
from spotterprep.llm import LLMClient

FAKE = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
prompt = sys.stdin.read()
with open(os.environ["FAKE_CLAUDE_LOG"], "a") as f:
    f.write(json.dumps({"args": args, "stdin": prompt}) + "\\n")
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
if mode == "fail":
    print(json.dumps({"is_error": True, "result": "API Error: overloaded"})); sys.exit(1)
out = {"is_error": False, "result": "Is a blank NPS a non-response?",
       "modelUsage": {"claude-haiku-x": {"outputTokens": 3}, "claude-sonnet-x": {"outputTokens": 60}}}
if "--json-schema" in args:
    out["structured_output"] = {"confidence_level": "LOW", "recommended_action": "PRESERVE_NULL",
                                "context_note": "Blank means no response."}
print(json.dumps(out))
"""


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    binary = tmp_path / "claude"
    binary.write_text(FAKE)
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "calls.jsonl"))
    return tmp_path / "calls.jsonl"


def test_reclassify_through_cli_uses_schema_and_no_tools(fake_claude, issue):
    llm = LLMClient(client=ClaudeCLIClient(), model="", log_path=None)
    out = llm.reclassify(issue, "q?", "Blank means they didn't answer.", "CUSTOMER_ORDERS")
    assert out["valid"] and out["recommended_action"] == "PRESERVE_NULL"
    call = json.loads(fake_claude.read_text().splitlines()[0])
    args = call["args"]
    assert args[args.index("--tools") + 1] == ""
    schema = json.loads(args[args.index("--json-schema") + 1])
    assert "PRESERVE_NULL" in schema["properties"]["recommended_action"]["enum"]
    assert "--model" not in args and "Blank means they didn't answer." in call["stdin"]
    assert llm.client.messages.models_seen == {"claude-sonnet-x"}


def test_question_through_cli_returns_text(fake_claude, issue):
    llm = LLMClient(client=ClaudeCLIClient(), model="sonnet", log_path=None)
    assert llm.generate_question(issue, "T") == "Is a blank NPS a non-response?"
    args = json.loads(fake_claude.read_text().splitlines()[0])["args"]
    assert args[args.index("--model") + 1] == "sonnet" and "--json-schema" not in args


def test_cli_overload_is_retried_then_raised(fake_claude, issue, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fail")
    llm = LLMClient(client=ClaudeCLIClient(), model="", log_path=None, sleep=lambda s: None, max_retries=2)
    with pytest.raises(ClaudeCLIError):
        llm.reclassify(issue, "q?", "a", "T")
    assert len(fake_claude.read_text().splitlines()) == 2
