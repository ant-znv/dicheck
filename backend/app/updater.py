"""Самообновление DI_Check через GitHub Releases.

Схема (по опыту BusyBar, GIT_AUTOUPDATE_RECOMMENDATIONS.md):
1. check() — GET /releases/latest, семверное сравнение тега с APP_VERSION.
2. install() — скачать установщик (asset с точным именем SETUP_ASSET_NAME) во
   %TEMP%, проверить sha256 (если GitHub отдал digest), запустить setup /SILENT
   в фоне и НЕ ждать: логика «убить старое → поставить → запустить новое»
   живёт в инсталляторе, а не здесь. Сетевые сбои заворачиваются в UpdateError
   (endpoint отдаёт detail, а не 500); для портативной сборки (нет unins000.exe
   рядом с exe) обновление через setup невозможно — UpdateError с подсказкой.
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
import ssl
import subprocess
import sys
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

_SSL_CONTEXT: ssl.SSLContext | None = None


def _ssl_context() -> ssl.SSLContext:
    """SSL-контекст с явным набором корневых сертификатов.

    Дефолтный контекст urllib в frozen-exe на части машин не находит корни
    (CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate).
    Собираем набор явно: certifi (вшивается в exe) + системные корни Windows
    поверх (покрывает корпоративные прокси с перехватом HTTPS).
    """
    global _SSL_CONTEXT
    if _SSL_CONTEXT is not None:
        return _SSL_CONTEXT
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        context = ssl.create_default_context()
    try:
        context.load_default_certs()  # добавит корни Windows к certifi
    except Exception:
        pass
    _SSL_CONTEXT = context
    return context


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
    with urllib.request.urlopen(req, timeout=CHECK_TIMEOUT, context=_ssl_context()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _default_download(url: str, token: str | None, dest: str) -> None:
    req = urllib.request.Request(url, headers=_headers(token, octet_stream=True))
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT, context=_ssl_context()) as resp, open(dest, "wb") as f:
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


def releases_url(repo: str) -> str:
    """Страница релизов репозитория — для подсказок пользователю."""
    return f"https://github.com/{repo}/releases"


def _is_portable(exe_dir: Path | None = None) -> bool:
    """Портативная ли сборка (распакованный ZIP без установки)?

    Признак: frozen-процесс и НЕТ дефолтного деинсталлятора Inno Setup
    (unins000.exe) рядом с exe — установщик всегда кладёт его рядом с
    DI_Check.exe, портатив — нет. В dev-режиме (не frozen) — False.
    """
    if not getattr(sys, "frozen", False):
        return False
    directory = Path(exe_dir) if exe_dir is not None else Path(sys.executable).parent
    return not (directory / "unins000.exe").exists()


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
    except ssl.SSLCertVerificationError as e:
        return {
            **result,
            "error": "Не удалось проверить сертификат GitHub — возможно, антивирус или "
            f"корпоративный прокси перехватывают HTTPS ({e})",
        }
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
    """Скачать установщик и запустить его в фоне. Бросает UpdateError.

    Любой сбой сети/данных (запрос релиза, скачивание, чтение файла для digest)
    превращается в UpdateError — endpoint отдаёт его как detail, а не 500.
    Для портативной сборки (ZIP без установки) автоматическое обновление
    невозможно — UpdateError с подсказкой скачать новый ZIP вручную.
    """
    repo = (repo or DEFAULT_REPO).strip()
    if not repo or "/" not in repo:
        raise UpdateError("Репозиторий обновлений не задан (настройки → Обновления)")

    if _is_portable():
        raise UpdateError(
            "Это портативная версия — автоматическое обновление не поддерживается. "
            f"Скачайте новый ZIP со страницы релизов ({releases_url(repo)}) "
            "и замените папку вручную"
        )

    try:
        data = _latest_release(repo, token or None, fetch_json)
    except UpdateError:
        raise
    except Exception as e:
        raise UpdateError(str(e)) from e

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
    try:
        download(url, token_or_none, dest)
    except UpdateError:
        raise
    except Exception as e:
        raise UpdateError(str(e)) from e

    # digest приходит как "sha256:<hex>" не для всех assets; нет поля — пропускаем.
    digest = asset.get("digest") or ""
    if digest.startswith("sha256:"):
        expected = digest.split(":", 1)[1].lower()
        try:
            actual = hashlib.sha256(Path(dest).read_bytes()).hexdigest()
        except OSError as e:
            Path(dest).unlink(missing_ok=True)
            raise UpdateError(str(e)) from e
        if actual != expected:
            Path(dest).unlink(missing_ok=True)
            raise UpdateError("sha256 скачанного установщика не совпал — файл удалён")

    launch([dest, "/SILENT"])
    return {"ok": True, "version": tag, "path": dest}
