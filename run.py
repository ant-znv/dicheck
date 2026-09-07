"""Точка входа распространяемой сборки DI_Check (PyInstaller, windowed).

GUI-режим (по умолчанию): сервер FastAPI поднимается на 127.0.0.1 в фоновом
потоке, приложение открывается в собственном окне (WebView2). Закрытие окна
останавливает приложение. Консоли нет, лог пишется в файл
(%APPDATA%\\DI_Check\\logs\\di_check.log).

--console: прежнее поведение — лог в консоль, браузер открывается сам
(полезно для диагностики; в windowed-exe консоли физически нет).

Если порт уже занят — значит, DI_Check уже запущен: просто открываем окно
(или браузер) к работающему экземпляру и выходим.

Файрвол: сервер слушает только loopback (127.0.0.1), который файрволом
не фильтруется, — разрешений Windows запрашивать не должно.
"""
from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from backend.app.logsetup import build_uvicorn_log_config, setup_logging

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
WINDOW_TITLE = "DI_Check"
log = logging.getLogger("di_check.run")

# GUID EdgeUpdate-клиента WebView2 Runtime
_WEBVIEW2_KEYS = (
    (r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",),
    (r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",),
)


def _port_busy(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _wait_ready(host: str, port: int, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_busy(host, port):
            return True
        time.sleep(0.15)
    return False


def _redirect_std_streams(log_file) -> None:
    """В windowed-exe stdout/stderr равны None — направляем их в лог-каталог."""
    if sys.stdout is None:
        sys.stdout = open(log_file.with_suffix(".stdout.log"), "a", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(log_file.with_suffix(".stderr.log"), "a", encoding="utf-8")


def _webview2_runtime_ok() -> bool:
    """Установлен ли WebView2 Runtime? На машинах без него pywebview иногда
    даёт белое окно вместо ошибки — проверяем реестр заранее."""
    try:
        import winreg

        for paths in _WEBVIEW2_KEYS:
            for path in paths:
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
                        version = winreg.QueryValueEx(key, "pv")[0]
                        if version and version != "0.0.0.0":
                            return True
                except OSError:
                    continue
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
            ) as key:
                version = winreg.QueryValueEx(key, "pv")[0]
                if version and version != "0.0.0.0":
                    return True
        except OSError:
            pass
        return False
    except Exception:
        return True  # не смогли проверить реестр — пусть pywebview пробует сам


def _open_window(url: str) -> bool:
    """Окно WebView2; блокирует до закрытия окна. False — GUI недоступен."""
    if not _webview2_runtime_ok():
        log.warning(
            "WebView2 Runtime не найден — окно недоступно. Установите "
            "https://developer.microsoft.com/microsoft-edge/webview2/ или используйте браузер"
        )
        return False
    try:
        import webview

        # Хранилище WebView2 — в %APPDATA%: рядом с exe оно не всегда доступно
        # на запись, и это известная причина «белого окна».
        storage = Path(os.environ.get("APPDATA") or Path.home()) / "DI_Check" / "webview"
        storage.mkdir(parents=True, exist_ok=True)
        os.environ["WEBVIEW2_USER_DATA_FOLDER"] = str(storage)

        window = webview.create_window(
            WINDOW_TITLE, url, width=1280, height=860, min_size=(900, 600)
        )
        window.events.loaded += lambda: log.info("Окно загрузило страницу %s", url)
        # private_mode=False: ин-memory профиль на некоторых машинах тоже даёт белое окно
        webview.start(gui="edgechromium", private_mode=False, storage_path=str(storage))
        return True
    except Exception as e:
        log.warning("Оконный движок недоступен (%s) — открываю в браузере", e)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DI_Check — локальная проверка должностных инструкций через LLM"
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="адрес сервера (по умолчанию 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="порт сервера (по умолчанию 8787)")
    parser.add_argument("--console", action="store_true", help="режим с консолью и браузером вместо окна")
    parser.add_argument("--no-browser", action="store_true", help="(--console) не открывать браузер автоматически")
    args = parser.parse_args()
    url = f"http://{args.host}:{args.port}"

    frozen_windowed = getattr(sys, "frozen", False) and not args.console
    log_file = setup_logging(console=not frozen_windowed)
    _redirect_std_streams(log_file)

    from backend.app.main import app

    if _port_busy(args.host, args.port):
        log.info("Порт %d занят — похоже, DI_Check уже запущен; открываю окно", args.port)
        if not _open_window(url) and not args.no_browser:
            webbrowser.open(url)
        return

    log.info("Запуск DI_Check: %s (лог: %s)", url, log_file)

    if args.console:
        if not args.no_browser:
            threading.Timer(2.0, webbrowser.open, args=(url,)).start()
        import uvicorn

        uvicorn.run(app, host=args.host, port=args.port, log_config=build_uvicorn_log_config(log_file))
        return

    # GUI-режим: сервер в фоновом потоке, окно — в главном.
    def serve() -> None:
        import uvicorn

        uvicorn.run(app, host=args.host, port=args.port, log_config=build_uvicorn_log_config(log_file))

    server_thread = threading.Thread(target=serve, name="di-check-server", daemon=True)
    server_thread.start()
    if not _wait_ready(args.host, args.port):
        log.error("Сервер не поднялся за отведённое время — завершаюсь")
        sys.exit(1)

    if _open_window(url):
        log.info("Окно закрыто — останавливаю приложение")
        return  # daemon-поток сервера завершится вместе с процессом

    # окна нет (WebView2/браузер недоступны) — работаем в консоли до Ctrl+C
    log.info("Открываю браузер как резервный вариант интерфейса")
    webbrowser.open(url)
    log.info("Работаю в фоне; остановка — Ctrl+C")
    server_thread.join()


if __name__ == "__main__":
    main()
