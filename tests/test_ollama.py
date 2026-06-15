import io
import json

from llm_cli_sandbox import ollama


class FakeResp(io.BytesIO):
    """A urlopen() stand-in: a byte stream that is also a context manager."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_list_models(monkeypatch):
    payload = json.dumps({"models": [{"name": "gpt-oss:20b", "size": 13_000_000_000}]}).encode()
    monkeypatch.setattr(ollama.urllib.request, "urlopen", lambda *a, **k: FakeResp(payload))
    models = ollama.list_models("http://h:11434")
    assert models[0]["name"] == "gpt-oss:20b"


def test_pull_model_streams_events(monkeypatch):
    lines = b'{"status":"pulling manifest"}\n{"status":"success"}\n'
    monkeypatch.setattr(ollama.urllib.request, "urlopen", lambda *a, **k: FakeResp(lines))
    events = list(ollama.pull_model("http://h:11434", "m"))
    assert [e["status"] for e in events] == ["pulling manifest", "success"]


def test_remove_model_uses_delete(monkeypatch):
    captured = {}

    def fake_urlopen(req, *a, **k):
        captured["method"] = req.method
        captured["url"] = req.full_url
        return FakeResp(b"")

    monkeypatch.setattr(ollama.urllib.request, "urlopen", fake_urlopen)
    ollama.remove_model("http://h:11434", "m")
    assert captured["method"] == "DELETE"
    assert captured["url"].endswith("/api/delete")
