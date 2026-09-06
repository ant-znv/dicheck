"""Общие фикстуры тестов бэкенда DI_Check.

Изоляция: конфиг settings уводится в tmp_path (реальный %APPDATA% не
затрагивается), `_jobs` и `_run_tasks` очищаются между тестами. Всё
LLM-взаимодействие мокается на уровне `backend.app.llm.chat_completion`
(модуль-атрибут, который main.py читает в момент вызова).
"""
from __future__ import annotations

import io
import time

import pytest
from docx import Document
from fastapi.testclient import TestClient

from backend.app import main, settings


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Уводит конфиг settings в tmp_path, чтобы не трогать реальный %APPDATA%."""
    config_dir = tmp_path / "appdata" / "DI_Check"
    monkeypatch.setattr(settings, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(settings, "CONFIG_PATH", config_dir / "config.json")


@pytest.fixture(autouse=True)
def isolated_jobs():
    """Изолирует состояние джоб между тестами."""
    main._jobs.clear()
    main._run_tasks.clear()
    yield
    main._jobs.clear()
    main._run_tasks.clear()


@pytest.fixture()
def client():
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture()
def with_api_key(monkeypatch):
    """Имитирует наличие API-ключа у любого провайдера."""
    monkeypatch.setattr(settings, "has_api_key", lambda provider: True)


@pytest.fixture()
def make_fake_llm(monkeypatch):
    """Фабрика мока llm.chat_completion; возвращает список зафиксированных вызовов.

    _make(["ответ1", "ответ2"]) — ответы отдаются по порядку вызовов,
    последний повторяется при дополнительных вызовах.
    """
    def _make(responses):
        calls = []

        async def fake_chat_completion(provider, model, system_prompt, user_message):
            calls.append(
                {
                    "provider": provider,
                    "model": model,
                    "system_prompt": system_prompt,
                    "user_message": user_message,
                }
            )
            index = min(len(calls) - 1, len(responses) - 1)
            return responses[index]

        monkeypatch.setattr(main.llm, "chat_completion", fake_chat_completion)
        return calls

    return _make


@pytest.fixture()
def make_docx_bytes():
    """Фабрика .docx-байтов из списка абзацев тела документа."""
    def _make(paragraphs):
        doc = Document()
        for text in paragraphs:
            doc.add_paragraph(text)
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()

    return _make


@pytest.fixture()
def make_job():
    """Фабрика фейковых джоб: кладёт готовый dict в main._jobs и возвращает его."""
    def _make(
        job_id="fakejob01",
        status="done",
        created_at=None,
        edits=None,
        texts=None,
        files=None,
    ):
        job = {
            "id": job_id,
            "status": status,
            "created_at": time.monotonic() if created_at is None else created_at,
            "results": [
                {
                    "filename": "di.docx",
                    "status": "done",
                    "error": None,
                    "report": "Отчёт.",
                    "summaryVerdict": "ok",
                    "edits": [] if edits is None else edits,
                    "textTruncated": False,
                }
            ],
            "_texts": {0: "Текст должностной инструкции."} if texts is None else texts,
            "_files": {} if files is None else files,
            "tasks": [],
            "cancel_requested": False,
        }
        main._jobs[job_id] = job
        return job

    return _make
