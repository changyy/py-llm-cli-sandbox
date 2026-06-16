import io
import json

from llm_cli_sandbox import probe


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_anthropic_messages_extracts_text(monkeypatch):
    payload = json.dumps(
        {"content": [{"type": "text", "text": "pong"}, {"type": "other", "x": 1}]}
    ).encode()
    monkeypatch.setattr(probe.urllib.request, "urlopen", lambda *a, **k: FakeResp(payload))
    assert probe.anthropic_messages("http://127.0.0.1:18080", "m") == "pong"


def test_anthropic_tool_call_detects_tool_use(monkeypatch):
    payload = json.dumps(
        {"content": [{"type": "tool_use", "name": "get_weather", "input": {"city": "Tokyo"}}]}
    ).encode()
    monkeypatch.setattr(probe.urllib.request, "urlopen", lambda *a, **k: FakeResp(payload))
    assert probe.anthropic_tool_call("http://127.0.0.1:18080", "m") is True


def test_anthropic_tool_call_text_reply_is_false(monkeypatch):
    payload = json.dumps(
        {"content": [{"type": "text", "text": '{"name": "get_weather", "arguments": {}}'}]}
    ).encode()
    monkeypatch.setattr(probe.urllib.request, "urlopen", lambda *a, **k: FakeResp(payload))
    assert probe.anthropic_tool_call("http://127.0.0.1:18080", "m") is False


def test_anthropic_messages_propagates_oserror(monkeypatch):
    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(probe.urllib.request, "urlopen", boom)
    try:
        probe.anthropic_messages("http://127.0.0.1:18080", "m")
    except OSError:
        pass
    else:
        raise AssertionError("expected OSError")
