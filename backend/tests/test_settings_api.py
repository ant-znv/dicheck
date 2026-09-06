"""Тесты Settings API (GET/PUT /api/settings) на изолированном конфиге."""
from __future__ import annotations

from backend.app import settings


def test_get_settings_returns_providers_and_default_prompt(client):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["activeProvider"] == "deepseek"
    assert body["activeModel"] == "deepseek-v4-flash"
    assert body["defaultSystemPrompt"] == settings.default_system_prompt()
    assert body["systemPrompt"] == settings.default_system_prompt()
    providers = {p["id"]: p for p in body["providers"]}
    assert set(providers) == {"deepseek", "zai"}
    assert providers["deepseek"]["name"] == "DeepSeek"
    assert providers["deepseek"]["hasApiKey"] is False
    assert providers["zai"]["hasApiKey"] is False


def test_put_settings_unknown_provider_returns_400(client):
    resp = client.put("/api/settings", json={"activeProvider": "unknown"})
    assert resp.status_code == 400
    assert "unknown provider" in resp.json()["detail"]


def test_put_apikey_unknown_provider_returns_400(client):
    resp = client.put(
        "/api/settings/apikey", json={"provider": "unknown", "apiKey": "x"}
    )
    assert resp.status_code == 400
    assert "unknown provider" in resp.json()["detail"]


def test_put_apikey_roundtrip_visible_as_has_api_key(client):
    resp = client.put(
        "/api/settings/apikey", json={"provider": "deepseek", "apiKey": "test-key-123"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "hasApiKey": True}

    providers = {p["id"]: p for p in client.get("/api/settings").json()["providers"]}
    assert providers["deepseek"]["hasApiKey"] is True
    assert providers["zai"]["hasApiKey"] is False
    # сам ключ наружу не отдаётся
    raw = client.get("/api/settings").text
    assert "test-key-123" not in raw
