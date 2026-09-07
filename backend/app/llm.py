"""OpenAI-совместимый async-клиент на httpx: POST {baseUrl}/chat/completions.

Транзиентные сбои (429, 5xx, сетевые ошибки, таймаут) ретраятся с backoff.
"""
from __future__ import annotations

import asyncio
import logging
import ssl

import httpx

from .settings import PROVIDERS, get_api_key

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(300.0, connect=30.0)

_SSL_CONTEXT: ssl.SSLContext | None = None


def _ssl_context() -> ssl.SSLContext:
    """certifi + системные корни Windows: дефолтный набор в frozen-exe
    на части машин не проходит верификацию (см. backend/app/updater.py)."""
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        try:
            import certifi

            context = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            context = ssl.create_default_context()
        try:
            context.load_default_certs()
        except Exception:
            pass
        _SSL_CONTEXT = context
    return _SSL_CONTEXT

MAX_ATTEMPTS = 3
# Статусы, при которых имеет смысл повторить запрос (лимиты и сбои провайдера).
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_RETRY_DELAYS = (2.0, 6.0)
_MAX_RETRY_AFTER = 30.0


class LLMError(Exception):
    """Читаемая ошибка LLM-вызова (HTTP, таймаут, сеть)."""


def _provider_config(provider: str) -> dict:
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise LLMError(f"Неизвестный провайдер: {provider}")
    return cfg


def _retry_delay(resp: httpx.Response | None, attempt: int) -> float:
    """Задержка перед повтором: Retry-After провайдера, иначе экспоненциальный backoff."""
    if resp is not None:
        raw = resp.headers.get("Retry-After")
        if raw:
            try:
                return min(float(raw), _MAX_RETRY_AFTER)
            except ValueError:
                pass
    return _RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)]


async def chat_completion(
    provider: str,
    model: str,
    system_prompt: str,
    user_message: str,
) -> str:
    """Возвращает markdown-ответ модели. Ошибки — как LLMError с читаемым текстом.

    429/5xx, сетевые ошибки и таймауты ретраятся до MAX_ATTEMPTS раз с backoff
    (или по Retry-After, если провайдер его прислал).
    """
    cfg = _provider_config(provider)
    api_key = get_api_key(provider)
    if not api_key:
        raise LLMError(f"Не задан API-ключ для провайдера {provider}")

    url = f"{cfg['baseUrl']}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    last_error: LLMError
    resp: httpx.Response | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        resp = None
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, verify=_ssl_context()) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException:
            last_error = LLMError(f"Таймаут запроса к {cfg['name']} ({url})")
        except httpx.HTTPError as e:
            last_error = LLMError(f"Ошибка сети при обращении к {cfg['name']}: {e}")
        else:
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
                except (ValueError, KeyError, IndexError) as e:
                    raise LLMError(f"Неожиданный формат ответа {cfg['name']}: {e}")
            last_error = LLMError(
                f"{cfg['name']} вернул HTTP {resp.status_code}: {resp.text[:500]}"
            )

        # resp is None — сетевой сбой/таймаут до получения ответа, тоже ретраится
        retryable = resp is None or resp.status_code in _RETRY_STATUSES
        if not retryable or attempt == MAX_ATTEMPTS:
            raise last_error

        delay = _retry_delay(resp, attempt)
        logger.warning(
            "LLM %s/%s: попытка %d/%d не удалась (%s), повтор через %.0f с",
            provider, model, attempt, MAX_ATTEMPTS, last_error, delay,
        )
        await asyncio.sleep(delay)

    raise last_error  # недостижимо, но нужно для типов


async def test_connection(provider: str, model: str | None = None) -> dict:
    """Проверка соединения: GET {baseUrl}/models, при неудаче — минимальный chat completion."""
    cfg = _provider_config(provider)
    api_key = get_api_key(provider)
    if not api_key:
        return {"ok": False, "error": f"Не задан API-ключ для провайдера {provider}"}

    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, verify=_ssl_context()) as client:
            resp = await client.get(f"{cfg['baseUrl']}/models", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("id") for m in data.get("data", []) if m.get("id")]
                return {"ok": True, "models": models}
            models_error = f"GET /models → HTTP {resp.status_code}: {resp.text[:300]}"
    except httpx.HTTPError as e:
        models_error = f"GET /models → ошибка сети: {e}"

    # Fallback: минимальный chat completion
    test_model = model or cfg["defaultModels"][0]
    try:
        await chat_completion(provider, test_model, "ping", "Ответь одним словом: ok")
        return {"ok": True, "models": cfg["defaultModels"]}
    except LLMError as e:
        return {"ok": False, "error": f"{models_error}; fallback chat: {e}"}
