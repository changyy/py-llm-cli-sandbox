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


def test_chat_returns_reply_and_timings(monkeypatch):
    payload = json.dumps({
        "message": {"role": "assistant", "content": "pong"},
        "load_duration": 39_800_000_000,  # 39.8s in nanoseconds
        "eval_duration": 200_000_000,      # 0.2s
        "total_duration": 40_000_000_000,
        "eval_count": 3,
    }).encode()
    monkeypatch.setattr(ollama.urllib.request, "urlopen", lambda *a, **k: FakeResp(payload))
    r = ollama.chat("http://h:11434", "m")
    assert r.reply == "pong"
    assert r.load_seconds == 39.8 and r.eval_seconds == 0.2


def test_loaded_model_names(monkeypatch):
    payload = json.dumps({"models": [{"name": "qwen2.5-coder:7b"}]}).encode()
    monkeypatch.setattr(ollama.urllib.request, "urlopen", lambda *a, **k: FakeResp(payload))
    assert ollama.loaded_model_names("http://h:11434") == {"qwen2.5-coder:7b"}


def test_model_installed_matches_exact_and_latest(monkeypatch):
    payload = json.dumps({"models": [{"name": "qwen2.5-coder:7b"}, {"name": "llama3.1:latest"}]}).encode()
    monkeypatch.setattr(ollama.urllib.request, "urlopen", lambda *a, **k: FakeResp(payload))
    assert ollama.model_installed("http://h:11434", "qwen2.5-coder:7b") is True
    assert ollama.model_installed("http://h:11434", "llama3.1") is True  # :latest fallback
    assert ollama.model_installed("http://h:11434", "qwen2.5-coder:32b") is False


def test_model_installed_raises_when_unreachable(monkeypatch):
    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(ollama.urllib.request, "urlopen", boom)
    try:
        ollama.model_installed("http://h:11434", "x")
    except OSError:
        pass
    else:
        raise AssertionError("expected OSError")


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
