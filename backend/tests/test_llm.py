"""Юнит-тесты retry-логики backend/app/llm.py (без сети)."""
from __future__ import annotations

import httpx

from backend.app import llm


def test_max_attempts_is_three():
    assert llm.MAX_ATTEMPTS == 3


def test_retry_delay_uses_retry_after_header():
    resp = httpx.Response(429, headers={"Retry-After": "12"})
    assert llm._retry_delay(resp, 1) == 12.0


def test_retry_delay_caps_retry_after():
    resp = httpx.Response(429, headers={"Retry-After": "120"})
    assert llm._retry_delay(resp, 1) == 30.0


def test_retry_delay_invalid_header_falls_back_to_backoff():
    resp = httpx.Response(429, headers={"Retry-After": "soon"})
    assert llm._retry_delay(resp, 1) == 2.0
    assert llm._retry_delay(resp, 2) == 6.0


def test_retry_delay_backoff_without_response():
    assert llm._retry_delay(None, 1) == 2.0
    assert llm._retry_delay(None, 2) == 6.0
    # последние значения backoff не растут дальше 6 с
    assert llm._retry_delay(None, 3) == 6.0
    assert llm._retry_delay(None, 10) == 6.0
