"""Точка входа распространяемой сборки DI_Check (PyInstaller).

Запускает локальный сервер и открывает браузер. Порт занят — значит,
приложение уже работает: просто открываем его в браузере и выходим.
"""
from __future__ import annotations

import argparse
import socket
import threading
import webbrowser

import uvicorn

from backend.app.main import app

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787


def _port_busy(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DI_Check — локальная проверка должностных инструкций через LLM"
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="адрес сервера (по умолчанию 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="порт сервера (по умолчанию 8787)")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер автоматически")
    args = parser.parse_args()
    url = f"http://{args.host}:{args.port}"

    if _port_busy(args.host, args.port):
        print(f"[DI_Check] Порт {args.port} занят — похоже, DI_Check уже запущен.")
        if not args.no_browser:
            print(f"[DI_Check] Открываю {url} ...")
            webbrowser.open(url)
        return

    if not args.no_browser:
        threading.Timer(2.0, webbrowser.open, args=(url,)).start()

    print(f"[DI_Check] Сервер: {url} (закройте это окно или Ctrl+C, чтобы остановить)")
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    except OSError as e:
        print(f"[DI_Check] Ошибка запуска сервера: {e}")
        raise


if __name__ == "__main__":
    main()
