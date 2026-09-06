"""OpenAI-совместимый async-клиент на httpx: POST {baseUrl}/chat/completions."""
from __future__ import annotations

import httpx

from .settings import PROVIDERS, get_api_key

TIMEOUT = httpx.Timeout(300.0, connect=30.0)


class LLMError(Exception):
    """Читаемая ошибка LLM-вызова (HTTP, таймаут, сеть)."""


def _provider_config(provider: str) -> dict:
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise LLMError(f"Неизвестный провайдер: {provider}")
    return cfg


async def chat_completion(
    provider: str,
    model: str,
    system_prompt: str,
    user_message: str,
) -> str:
    """Возвращает markdown-ответ модели. Ошибки — как LLMError с читаемым текстом."""
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
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException:
        raise LLMError(f"Таймаут запроса к {cfg['name']} ({url})")
    except httpx.HTTPError as e:
        raise LLMError(f"Ошибка сети при обращении к {cfg['name']}: {e}")

    if resp.status_code != 200:
        body = resp.text[:500]
        raise LLMError(f"{cfg['name']} вернул HTTP {resp.status_code}: {body}")

    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError) as e:
        raise LLMError(f"Неожиданный формат ответа {cfg['name']}: {e}")


async def test_connection(provider: str, model: str | None = None) -> dict:
    """Проверка соединения: GET {baseUrl}/models, при неудаче — минимальный chat completion."""
    cfg = _provider_config(provider)
    api_key = get_api_key(provider)
    if not api_key:
        return {"ok": False, "error": f"Не задан API-ключ для провайдера {provider}"}

    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
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
