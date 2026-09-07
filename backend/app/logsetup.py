"""Настройка логирования DI_Check.

Файл: %APPDATA%\\DI_Check\\logs\\di_check.log, ротация 5 МБ x 3.
Консольный хендлер — только в dev (--console / запуск из исходников);
в windowed-exe stdout/stderr отсутствуют, всё пишется в файл.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "DI_Check" / "logs"
LOG_FILE = LOG_DIR / "di_check.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUPS = 3

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(console: bool = True) -> Path:
    """Идемпотентно настраивает root-логгер. Возвращает путь к лог-файлу."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(_FORMAT)

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if console and not any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
        for h in root.handlers
    ):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)
    return LOG_FILE


def build_uvicorn_log_config(file_path: Path) -> dict:
    """log_config для uvicorn: всё в файл, без консоли (для windowed-exe).

    uvicorn.access на WARNING — перегружать лог не нужно.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "file": {"format": _FORMAT},
        },
        "handlers": {
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "INFO",
                "formatter": "file",
                "filename": str(file_path),
                "maxBytes": MAX_BYTES,
                "backupCount": BACKUPS,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["file"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"handlers": ["file"], "level": "WARNING", "propagate": False},
        },
    }
