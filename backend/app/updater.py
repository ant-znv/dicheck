"""Самообновление DI_Check через GitHub Releases.

Схема (по опыту BusyBar, GIT_AUTOUPDATE_RECOMMENDATIONS.md):
1. check() — GET /releases/latest, семверное сравнение тега с APP_VERSION.
2. install() — скачать установщик (asset с точным именем SETUP_ASSET_NAME) во
   %TEMP%, проверить sha256 (если GitHub отдал digest), запустить setup /SILENT
   в фоне и НЕ ждать: логика «убить старое → поставить → запустить новое»
   живёт в инсталляторе, а не здесь.
3. При запуске setup окружение чистится от _PYI_*/PYINSTALLER_* — иначе
   PyInstaller-бутлоадер свежего exe падает с "Security validation failure".

Все внешние воздействия инъецируются (fetch_json/download/launch): тесты идут
без сети и реальных процессов. check() не бросает исключений никогда.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from .version import APP_VERSION

# owner/repo по умолчанию; можно переопределить в настройках (%APPDATA% config).
DEFAULT_REPO = "ant-znv/dicheck"
SETUP_ASSET_NAME = "DI_Check_setup.exe"
GITHUB_API = "https://api.github.com"
CHECK_TIMEOUT = 15
DOWNLOAD_TIMEOUT = 60


class UpdateError(Exception):
    """Ошибка скачивания/запуска установщика (в API отдаётся как detail)."""


# ---------- Инъекция внешнего мира ----------

def _headers(token: str | None, *, octet_stream: bool) -> dict:
    headers = {
        "User-Agent": "DI_Check-updater",
        "Accept": "application/octet-stream" if octet_stream else "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _default_fetch_json(url: str, token: str | None) -> dict:
    req = urllib.request.Request(url, headers=_headers(token, octet_stream=False))
    with urllib.request.urlopen(req, timeout=CHECK_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _default_download(url: str, token: str | None, dest: str) -> None:
    req = urllib.request.Request(url, headers=_headers(token, octet_stream=True))
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp, open(dest, "wb") as f:
        while chunk := resp.read(1 << 20):
            f.write(chunk)


def _clean_env() -> dict:
    """Окружение без _PYI_*/PYINSTALLER_*: наследование их от бутлоадера PyInstaller
    приводит новый exe к 'Security validation failure'."""
    return {k: v for k, v in os.environ.items() if not k.startswith(("_PYI_", "PYINSTALLER_"))}


def _default_launch(argv: list[str]) -> None:
    # В фоне и не ждём: установщик сам остановит наше приложение и перезапустит новое.
    subprocess.Popen(argv, env=_clean_env(), cwd=str(Path(argv[0]).parent))


# ---------- Разбор версий и имён ----------

def parse_version(tag: str) -> tuple[int, ...]:
    """'v1.2.3-rc1' → (1, 2, 3); мусор → (0,). Сравнение — кортежами чисел."""
    core = tag.strip().lstrip("vV").split("-", 1)[0]
    if not core:
        return (0,)
    parts: list[int] = []
    for chunk in core.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def sanitize_tag(tag: str) -> str:
    """Тег приходит из внешнего API — не даём ему стать путём в %TEMP%."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", tag)


# ---------- API апдейтера ----------

def _latest_release(
    repo: str, token: str | None, fetch_json
) -> dict:
    return fetch_json(f"{GITHUB_API}/repos/{repo}/releases/latest", token)


def check(
    repo: str | None = None,
    token: str | None = None,
    *,
    fetch_json=_default_fetch_json,
) -> dict:
    """Проверить обновления. Никогда не бросает исключений: любая проблема —
    строка в 'error' (404 у приватного репо — штатный случай, не падение)."""
    result = {"current": APP_VERSION, "latest": None, "updateAvailable": False, "error": None}
    repo = (repo or DEFAULT_REPO).strip()
    if not repo or "/" not in repo:
        return {**result, "error": "Репозиторий обновлений не задан (настройки → Обновления)"}
    try:
        data = _latest_release(repo, token or None, fetch_json)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            return {
                **result,
                "error": "Репозиторий приватный, недоступен или релизов нет "
                "(для приватного нужен токен в настройках)",
            }
        return {**result, "error": f"GitHub вернул HTTP {e.code}"}
    except Exception as e:  # сеть, DNS, таймаут, битый JSON — всё сюда
        return {**result, "error": str(e)}

    tag = (data.get("tag_name") or "").strip()
    if not tag:
        return {**result, "error": "В последнем релизе нет тега"}
    update_available = parse_version(tag) > parse_version(APP_VERSION)
    return {**result, "latest": tag, "updateAvailable": update_available}


def install(
    repo: str | None = None,
    token: str | None = None,
    *,
    fetch_json=_default_fetch_json,
    download=_default_download,
    launch=_default_launch,
) -> dict:
    """Скачать установщик и запустить его в фоне. Бросает UpdateError."""
    repo = (repo or DEFAULT_REPO).strip()
    if not repo or "/" not in repo:
        raise UpdateError("Репозиторий обновлений не задан (настройки → Обновления)")

    data = _latest_release(repo, token or None, fetch_json)
    tag = (data.get("tag_name") or "").strip()
    if parse_version(tag) <= parse_version(APP_VERSION):
        raise UpdateError("Обновление не требуется: установлена последняя версия")

    asset = next(
        (a for a in data.get("assets", []) if a.get("name") == SETUP_ASSET_NAME), None
    )
    if asset is None:
        raise UpdateError(f"В релизе {tag} нет файла {SETUP_ASSET_NAME}")

    # Приватный репо: browser_download_url с токеном отдаёт 404 — качаем через asset API.
    if token and asset.get("id"):
        url = f"{GITHUB_API}/repos/{repo}/releases/assets/{asset['id']}"
    else:
        url = asset.get("browser_download_url")
    if not url:
        raise UpdateError(f"В релизе {tag} у файла нет ссылки для скачивания")

    filename = f"di-check-setup-{sanitize_tag(tag)}.exe"
    dest = str(Path(tempfile.gettempdir()) / filename)

    token_or_none = token or None
    download(url, token_or_none, dest)

    # digest приходит как "sha256:<hex>" не для всех assets; нет поля — пропускаем.
    digest = asset.get("digest") or ""
    if digest.startswith("sha256:"):
        expected = digest.split(":", 1)[1].lower()
        actual = hashlib.sha256(Path(dest).read_bytes()).hexdigest()
        if actual != expected:
            Path(dest).unlink(missing_ok=True)
            raise UpdateError("sha256 скачанного установщика не совпал — файл удалён")

    launch([dest, "/SILENT"])
    return {"ok": True, "version": tag, "path": dest}
