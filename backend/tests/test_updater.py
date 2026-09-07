"""Тесты самообновления: всё внешнее (сеть/файлы/процессы) инъецируется."""
from __future__ import annotations

import os
import sys
import urllib.error
from pathlib import Path

import pytest

from backend.app import updater
from backend.app.updater import UpdateError, _clean_env, check, install, parse_version, sanitize_tag


# ---------- parse_version / sanitize_tag ----------

def test_parse_version():
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("V0.1.0") == (0, 1, 0)
    assert parse_version("1.2.3-rc1") == (1, 2, 3)
    assert parse_version("1.10.0") > parse_version("1.9.9")
    assert parse_version("") == (0,)
    assert parse_version("мусор") == (0,)
    assert parse_version("v1.2.beta") == (1, 2, 0)


def test_sanitize_tag():
    assert sanitize_tag("v1.2.3") == "v1.2.3"
    # слэши и прочие опасные символы заменяются — путь не обойти
    assert sanitize_tag("v1.2.3/../evil") == "v1.2.3_.._evil"
    assert "\\" not in sanitize_tag("a\\b:c*d")
    assert ":" not in sanitize_tag("a\\b:c*d")


# ---------- _clean_env (грабли 2.1: _PYI_*) ----------

def test_clean_env_strips_pyinstaller_vars(monkeypatch):
    monkeypatch.setenv("_PYI_PARENT_PROCESS_LEVEL", "1")
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "x")
    monkeypatch.setenv("PYINSTALLER_RESET_ENVIRONMENT", "1")
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    env = _clean_env()
    assert not [k for k in env if k.startswith(("_PYI_", "PYINSTALLER_"))]
    assert "PATH" in env


# ---------- check() ----------

def _release(tag: str, with_asset: bool = True, digest: str | None = None) -> dict:
    assets = (
        [{"name": updater.SETUP_ASSET_NAME, "id": 42, "browser_download_url": "https://host/setup.exe",
          **({"digest": digest} if digest else {})}]
        if with_asset
        else []
    )
    return {"tag_name": tag, "assets": assets}


def test_check_no_update():
    info = check("owner/repo", None, fetch_json=lambda url, token: _release("v0.1.0"))
    assert info["updateAvailable"] is False
    assert info["latest"] == "v0.1.0"
    assert info["error"] is None
    assert info["current"] == updater.APP_VERSION


def test_check_update_available():
    info = check("owner/repo", None, fetch_json=lambda url, token: _release("v9.9.9"))
    assert info["updateAvailable"] is True


def test_check_repo_not_set(monkeypatch):
    monkeypatch.setattr(updater, "DEFAULT_REPO", "")
    info = check(None, None, fetch_json=lambda *a: (_ for _ in ()).throw(AssertionError("no call")))
    assert info["error"] is not None and "не задан" in info["error"]


def test_check_empty_repo_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(updater, "DEFAULT_REPO", "def/repo")
    seen = {}

    def fake_fetch(url, token):
        seen["url"] = url
        return {"tag_name": "v0.1.0", "assets": []}

    info = check("", None, fetch_json=fake_fetch)
    assert seen["url"] == f"{updater.GITHUB_API}/repos/def/repo/releases/latest"
    assert info["error"] is None


def test_check_404_is_not_a_crash():
    import urllib.error

    def fail(url, token):
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

    info = check("owner/private", None, fetch_json=fail)
    assert info["error"] is not None
    assert "приватный" in info["error"]


def test_check_cert_error_is_friendly():
    import ssl

    def fail(url, token):
        raise ssl.SSLCertVerificationError(1, "certificate verify failed")

    info = check("owner/repo", None, fetch_json=fail)
    assert info["error"] is not None
    assert "сертификат" in info["error"]


def test_check_network_error_is_error_string():
    def fail(url, token):
        raise OSError("no network")

    info = check("owner/repo", None, fetch_json=fail)
    assert "no network" in info["error"]


# ---------- install(): сетевые сбои → UpdateError (не сырые исключения) ----------

def test_install_fetch_urlerror_becomes_update_error():
    def fail(url, token):
        raise urllib.error.URLError("name resolution failed")

    with pytest.raises(UpdateError, match="name resolution failed"):
        install(
            "owner/repo",
            None,
            fetch_json=fail,
            download=lambda *a: pytest.fail("no download"),
            launch=lambda argv: pytest.fail("no launch"),
        )


def test_install_fetch_bad_json_becomes_update_error():
    def fail(url, token):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    with pytest.raises(UpdateError, match="Expecting value"):
        install(
            "owner/repo",
            None,
            fetch_json=fail,
            download=lambda *a: pytest.fail("no download"),
            launch=lambda argv: pytest.fail("no launch"),
        )


def test_install_download_oserror_becomes_update_error(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))

    def fail(url, token, dest):
        raise OSError("disk full")

    with pytest.raises(UpdateError, match="disk full"):
        install(
            "owner/repo",
            None,
            fetch_json=lambda url, token: _release("v9.9.9"),
            download=fail,
            launch=lambda argv: pytest.fail("no launch"),
        )
    # недокачанный файл не остаётся мусором в %TEMP%
    assert list(tmp_path.glob("di-check-setup-*")) == []


def test_install_digest_read_oserror_becomes_update_error(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))

    def fake_download(url, token, dest):
        Path(dest).write_bytes(b"setup-bytes")

    real_read_bytes = Path.read_bytes

    def broken_read_bytes(self):
        if self.name.startswith("di-check-setup-"):
            raise OSError("unreadable file")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", broken_read_bytes)
    with pytest.raises(UpdateError, match="unreadable file"):
        install(
            "owner/repo",
            None,
            fetch_json=lambda url, token: _release("v9.9.9", digest="sha256:" + "0" * 64),
            download=fake_download,
            launch=lambda argv: pytest.fail("no launch"),
        )
    assert list(tmp_path.glob("di-check-setup-*")) == []


# ---------- портативная сборка: детект и запрет автообновления ----------

def test_is_portable_no_uninstaller(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert updater._is_portable(tmp_path) is True


def test_is_portable_with_inno_uninstaller(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    (tmp_path / "unins000.exe").write_bytes(b"")
    assert updater._is_portable(tmp_path) is False


def test_is_portable_false_in_dev(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert updater._is_portable(tmp_path) is False


def test_is_portable_default_dir_next_to_executable(monkeypatch):
    """Без аргумента смотрим рядом с sys.executable (в тестах — venv, без unins000.exe)."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert updater._is_portable() is True


def test_install_portable_raises_friendly_error(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    with pytest.raises(UpdateError) as exc_info:
        install(
            "owner/repo",
            None,
            fetch_json=lambda *a: pytest.fail("no fetch"),
            download=lambda *a: pytest.fail("no download"),
            launch=lambda argv: pytest.fail("no launch"),
        )
    message = str(exc_info.value)
    assert "портативн" in message.lower()
    assert "ZIP" in message
    # ссылка на релизы строится по переданному репозиторию
    assert "https://github.com/owner/repo/releases" in message


def test_sanitize_tag_keeps_dots():
    """Имя установщика сохраняет точки версии: di-check-setup-v0.2.2.exe."""
    assert f"di-check-setup-{sanitize_tag('v0.2.2')}.exe" == "di-check-setup-v0.2.2.exe"


# ---------- install() ----------

def test_install_success(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    launched = {}

    def fake_launch(argv):
        launched["argv"] = argv
        launched["env"] = None

    def fake_download(url, token, dest):
        Path(dest).write_bytes(b"setup-bytes")

    result = install(
        "owner/repo",
        None,
        fetch_json=lambda url, token: _release("v9.9.9", digest="sha256:" + __import__("hashlib").sha256(b"setup-bytes").hexdigest()),
        download=fake_download,
        launch=fake_launch,
    )
    assert result["ok"] is True and result["version"] == "v9.9.9"
    assert launched["argv"][1] == "/SILENT"
    assert Path(launched["argv"][0]).exists()


def test_install_digest_mismatch_deletes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))

    def fake_download(url, token, dest):
        Path(dest).write_bytes(b"corrupted")

    with pytest.raises(UpdateError, match="sha256"):
        install(
            "owner/repo",
            None,
            fetch_json=lambda url, token: _release("v9.9.9", digest="sha256:" + "0" * 64),
            download=fake_download,
            launch=lambda argv: pytest.fail("не должен запускаться"),
        )
    assert list(tmp_path.glob("di-check-setup-*")) == []


def test_install_no_asset_in_release(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    with pytest.raises(UpdateError, match="нет файла"):
        install(
            "owner/repo",
            None,
            fetch_json=lambda url, token: _release("v9.9.9", with_asset=False),
            download=lambda *a: pytest.fail("no download"),
            launch=lambda argv: pytest.fail("no launch"),
        )


def test_install_not_needed():
    with pytest.raises(UpdateError, match="не требуется"):
        install(
            "owner/repo",
            None,
            fetch_json=lambda url, token: _release("v0.1.0"),
            download=lambda *a: pytest.fail("no download"),
            launch=lambda argv: pytest.fail("no launch"),
        )


def test_install_private_repo_uses_asset_api_url(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    seen = {}

    def fake_download(url, token, dest):
        seen["url"] = url
        seen["token"] = token
        Path(dest).write_bytes(b"x")

    install(
        "owner/private",
        "gh-token",
        fetch_json=lambda url, token: _release("v9.9.9"),
        download=fake_download,
        launch=lambda argv: None,
    )
    assert seen["url"] == f"{updater.GITHUB_API}/repos/owner/private/releases/assets/42"
    assert seen["token"] == "gh-token"


def test_install_public_repo_uses_browser_url(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    seen = {}

    def fake_download(url, token, dest):
        seen["url"] = url
        Path(dest).write_bytes(b"x")

    install(
        "owner/repo",
        None,
        fetch_json=lambda url, token: _release("v9.9.9"),
        download=fake_download,
        launch=lambda argv: None,
    )
    assert seen["url"] == "https://host/setup.exe"


def test_default_launch_cleans_env(monkeypatch, tmp_path):
    """Реальный _default_launch передаёт окружение без _PYI_* (грабли 2.1)."""
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "dirty")
    captured = {}

    class FakePopen:
        def __init__(self, argv, env=None, cwd=None):
            captured["argv"] = argv
            captured["env"] = env

    monkeypatch.setattr(updater.subprocess, "Popen", FakePopen)
    script = tmp_path / "DI_Check_setup.exe"
    script.write_bytes(b"x")
    updater._default_launch([str(script), "/SILENT"])
    assert captured["argv"][1] == "/SILENT"
    assert "_PYI_ARCHIVE_FILE" not in captured["env"]
