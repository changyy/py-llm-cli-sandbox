import io
import json
from pathlib import Path

from typer.testing import CliRunner

from llm_cli_sandbox import __version__, update
from llm_cli_sandbox.cli import app

runner = CliRunner()

REPO = Path(__file__).resolve().parents[1]  # a valid local source checkout


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_is_newer_compares_timestamp_scheme():
    assert update.is_newer("1.20260616.1000745", "1.20260615.1000000")
    assert update.is_newer("1.20260616.1000746", "1.20260616.1000745")
    assert not update.is_newer("1.20260616.1000745", "1.20260616.1000745")
    assert not update.is_newer("1.20260101.1000000", "1.20260616.1000745")


def test_latest_version_reads_pypi(monkeypatch):
    payload = json.dumps({"info": {"version": "9.99.9"}}).encode()
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda *a, **k: FakeResp(payload))
    assert update.latest_version() == "9.99.9"


def test_latest_version_offline_returns_none(monkeypatch):
    def boom(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr(update.urllib.request, "urlopen", boom)
    assert update.latest_version() is None


def test_upgrade_hint_is_a_runnable_string():
    hint = update.upgrade_hint()
    assert isinstance(hint, str) and hint


def test_update_command_reports_newer(monkeypatch):
    monkeypatch.setattr(update, "latest_version", lambda *a, **k: "9.99.9")
    result = runner.invoke(app, ["update"])
    assert result.exit_code == 0
    assert "newer version is available" in result.stdout


def test_update_command_up_to_date(monkeypatch):
    from llm_cli_sandbox import __version__

    monkeypatch.setattr(update, "latest_version", lambda *a, **k: __version__)
    result = runner.invoke(app, ["update"])
    assert result.exit_code == 0
    assert "latest version" in result.stdout


def test_update_command_offline(monkeypatch):
    monkeypatch.setattr(update, "latest_version", lambda *a, **k: None)
    result = runner.invoke(app, ["update", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["latest"] is None and data["update_available"] is False


# --- --from (install from a chosen source) -----------------------------------


def test_classify_source():
    assert update.classify_source("/tmp/xxx") == "local"
    assert update.classify_source("./dist/pkg.whl") == "local"
    assert update.classify_source("git+https://github.com/x/y") == "url"
    assert update.classify_source("https://example.com/y.whl") == "url"


def test_local_source_error_accepts_repo():
    assert update.local_source_error(REPO) is None


def test_local_source_error_rejects_missing(tmp_path):
    assert update.local_source_error(tmp_path / "nope") is not None


def test_local_source_error_rejects_wrong_package(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "something-else"\n')
    err = update.local_source_error(tmp_path)
    assert err and "something-else" in err


def test_local_source_version_reads_init():
    assert update.local_source_version(REPO) == __version__


def test_update_from_runs_install_with_yes(monkeypatch):
    captured = {}

    def fake_install(source):
        captured["source"] = source
        return 0

    monkeypatch.setattr(update, "run_install", fake_install)
    result = runner.invoke(app, ["update", "--from", str(REPO), "--yes"])
    assert result.exit_code == 0
    assert captured["source"] == str(REPO)
    assert "updated" in result.stdout


def test_update_from_aborts_when_declined(monkeypatch):
    called = {}
    monkeypatch.setattr(update, "run_install", lambda s: called.setdefault("ran", True))
    result = runner.invoke(app, ["update", "--from", str(REPO)], input="n\n")
    assert "ran" not in called
    assert result.exit_code != 0


def test_update_from_rejects_bad_path(tmp_path):
    result = runner.invoke(app, ["update", "--from", str(tmp_path / "nope")])
    assert result.exit_code == 2


def test_install_argv_uses_pip_by_default(monkeypatch):
    monkeypatch.setattr(update, "is_pipx_install", lambda: False)
    argv = update.install_argv("/tmp/src")
    assert argv[:2] == [update.sys.executable, "-m"] and "pip" in argv
    assert argv[-1] == "/tmp/src"


def test_install_argv_uses_pipx_when_managed(monkeypatch):
    monkeypatch.setattr(update, "is_pipx_install", lambda: True)
    monkeypatch.setattr(update.shutil, "which", lambda _: "/usr/bin/pipx")
    assert update.install_argv("/tmp/src") == ["pipx", "install", "--force", "/tmp/src"]


def test_install_argv_falls_back_to_pip_without_pipx_cli(monkeypatch):
    # pipx-managed but the pipx CLI isn't on PATH -> raw pip into the venv works.
    monkeypatch.setattr(update, "is_pipx_install", lambda: True)
    monkeypatch.setattr(update.shutil, "which", lambda _: None)
    assert update.install_argv("/tmp/src")[:1] == [update.sys.executable]
