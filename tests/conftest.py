import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def tool_response(payload, name="record_reclassification"):
    return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=name, input=payload, id="toolu_1")])


def text_response(text):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


class FakeMessages:
    """Returns queued responses (or raises queued exceptions) and records every request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeAnthropic:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


@pytest.fixture
def fake_client():
    return FakeAnthropic


@pytest.fixture
def issue():
    return {"column": "nps_score", "issue_type": "NULL_CRITICAL", "count": 280, "pct": 0.14,
            "confidence_level": "MEDIUM", "recommended_action": "ESCALATE_TO_USER",
            "detail": "14% null", "example_values": []}
