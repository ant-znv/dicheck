"""Настройки приложения: %APPDATA%\\DI_Check\\config.json.

API-ключи шифруются Windows DPAPI (CryptProtectData, CurrentUser), в файле — base64.
Ключ никогда не возвращается наружу — только флаг hasApiKey.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import threading
from ctypes import wintypes
from pathlib import Path

PROVIDERS = {
    "deepseek": {
        "id": "deepseek",
        "name": "DeepSeek",
        "baseUrl": "https://api.deepseek.com",
        "defaultModels": ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"],
    },
    "zai": {
        "id": "zai",
        "name": "z.ai (GLM)",
        "baseUrl": "https://api.z.ai/api/paas/v4",
        "defaultModels": ["glm-4.6", "glm-4.5", "glm-4.5-air"],
    },
}

_CONFIG_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "DI_Check"
CONFIG_PATH = _CONFIG_DIR / "config.json"

_lock = threading.Lock()

_DEFAULT_PROMPT_PATH = Path(__file__).parent / "default_prompt.md"


def default_system_prompt() -> str:
    return _DEFAULT_PROMPT_PATH.read_text(encoding="utf-8")


# ---------- DPAPI ----------

class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _make_blob(data: bytes) -> _DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    blob = _DATA_BLOB()
    blob.cbData = len(data)
    blob.pbData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
    blob._buf = buf  # держим ссылку, чтобы буфер не собрал GC
    return blob


def _dpapi_protect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob = _make_blob(data)
    out_blob = _DATA_BLOB()
    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob = _make_blob(data)
    out_blob = _DATA_BLOB()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


# ---------- Загрузка / сохранение ----------

def _load() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save(cfg: dict) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


# ---------- Публичный API ----------

def get_settings_state() -> dict:
    with _lock:
        cfg = _load()
    return {
        "activeProvider": cfg.get("activeProvider", "deepseek"),
        "activeModel": cfg.get("activeModel", "deepseek-v4-flash"),
        "systemPrompt": cfg.get("systemPrompt") or default_system_prompt(),
    }


def update_settings(
    active_provider: str | None = None,
    active_model: str | None = None,
    system_prompt: str | None = None,
) -> None:
    with _lock:
        cfg = _load()
        if active_provider is not None:
            if active_provider not in PROVIDERS:
                raise ValueError(f"unknown provider: {active_provider}")
            cfg["activeProvider"] = active_provider
        if active_model is not None:
            cfg["activeModel"] = active_model
        if system_prompt is not None:
            cfg["systemPrompt"] = system_prompt
        _save(cfg)


def has_api_key(provider: str) -> bool:
    with _lock:
        cfg = _load()
    keys = cfg.get("apiKeys", {})
    return bool(keys.get(provider))


def get_api_key(provider: str) -> str | None:
    """Внутреннее использование: возвращает расшифрованный ключ."""
    with _lock:
        cfg = _load()
    keys = cfg.get("apiKeys", {})
    if provider in keys:
        enc = keys[provider]
        if not enc:
            return None
        try:
            return _dpapi_unprotect(base64.b64decode(enc)).decode("utf-8")
        except Exception:
            return None
    return None


def save_api_key(provider: str, api_key: str) -> None:
    """Пустая строка — удалить ключ."""
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    with _lock:
        cfg = _load()
        keys = cfg.setdefault("apiKeys", {})
        if not api_key:
            keys[provider] = ""
        else:
            keys[provider] = base64.b64encode(
                _dpapi_protect(api_key.encode("utf-8"))
            ).decode("ascii")
        _save(cfg)


def build_settings_response() -> dict:
    state = get_settings_state()
    providers = []
    for p in PROVIDERS.values():
        providers.append({**p, "hasApiKey": has_api_key(p["id"])})
    return {
        "providers": providers,
        "activeProvider": state["activeProvider"],
        "activeModel": state["activeModel"],
        "systemPrompt": state["systemPrompt"],
        "defaultSystemPrompt": default_system_prompt(),
    }
