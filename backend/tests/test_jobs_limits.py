"""Тесты лимитов памяти джоб: выгрузка payload'ов (_files/_texts) в main.py."""
from __future__ import annotations

import json
import time

import pytest

from backend.app import main

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
EDIT = {
    "id": "e1",
    "title": "Режим работы",
    "original": "цитата из документа",
    "replacement": "новая формулировка",
    "reason": "норма",
}


def structured_response():
    block = {"verdict": "risk", "edits": [EDIT]}
    return (
        "## Отчёт\n\nПроверено.\n\n```json\n"
        + json.dumps(block, ensure_ascii=False)
        + "\n```"
    )


def post_check(client, docx_bytes):
    return client.post(
        "/api/check",
        files={"files": ("di.docx", docx_bytes, DOCX_MIME)},
        data={"contractSubject": "", "employmentType": "", "extraContext": ""},
    )


def wait_done(client, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(f"/api/jobs/{job_id}").json()
        if data["status"] == "done":
            return data
        time.sleep(0.02)
    pytest.fail(f"джоба {job_id} не завершилась за {timeout} с")


# ---------- FILE_TTL: payload выгружается, отчёты живут, /fix даёт 410 ----------

def test_finished_job_payload_expires_reports_survive(
    client, with_api_key, make_fake_llm, make_docx_bytes, monkeypatch
):
    make_fake_llm([structured_response()])
    resp = post_check(client, make_docx_bytes(["цитата из документа — и другой текст."]))
    assert resp.status_code == 200
    job_id = resp.json()["jobId"]

    wait_done(client, job_id)
    job = main._jobs[job_id]
    assert job["_files"] and job["_texts"]
    assert job.get("_finished_at") is not None  # _run_job зафиксировал время конца

    # «истечение» FILE_TTL и выгрузка (срабатывает при создании новой джобы)
    monkeypatch.setattr(main, "FILE_TTL_SECONDS", 1.0)
    job["_finished_at"] -= 2.0
    resp2 = post_check(client, make_docx_bytes(["Другой документ."]))
    assert resp2.status_code == 200
    assert not job["_files"] and not job["_texts"]

    # джоба и отчёты доступны, служебные payload'ы ушли
    data = client.get(f"/api/jobs/{job_id}").json()
    assert data["status"] == "done"
    assert data["results"][0]["report"]
    assert [e["id"] for e in data["results"][0]["edits"]] == ["e1"]
    assert data["results"][0]["summaryVerdict"] == "risk"

    fix = client.post(
        f"/api/jobs/{job_id}/fix", json={"resultIndex": 0, "editIds": ["e1"]}
    )
    assert fix.status_code == 410
    assert fix.json()["detail"] == "payload_expired"


def test_fresh_finished_job_keeps_payload(
    client, with_api_key, make_fake_llm, make_docx_bytes
):
    make_fake_llm([structured_response()])
    resp = post_check(client, make_docx_bytes(["Текст ДИ."]))
    job_id = resp.json()["jobId"]
    wait_done(client, job_id)

    main._evict_job_payloads()  # без «истечения» TTL ничего не выгружается
    job = main._jobs[job_id]
    assert job["_files"] and job["_texts"]


# ---------- MAX_TOTAL_BYTES: вытеснение самых старых завершённых ----------

def test_max_total_bytes_evicts_oldest_finished_not_running(make_job, monkeypatch):
    payload = b"x" * 1000
    old = make_job(
        job_id="oldbytes01", status="done", created_at=1.0,
        edits=[dict(EDIT)], texts={0: "старый текст"}, files={0: payload},
    )
    new = make_job(
        job_id="newbytes01", status="done", created_at=2.0,
        edits=[dict(EDIT)], texts={0: "новый текст"}, files={0: payload},
    )
    running = make_job(
        job_id="runbytes01", status="running", created_at=0.5,
        texts={0: "рабочий текст"}, files={0: b"y" * 100},
    )
    # суммарно ~2.2 КБ, лимит — 2 КБ: вытесняется только старейшая завершённая
    monkeypatch.setattr(main, "MAX_TOTAL_BYTES", 2000)

    main._evict_job_payloads()

    assert not old["_files"] and not old["_texts"]   # старейшая завершённая — выгружена
    assert new["_files"] and new["_texts"]           # более новая уложилась в лимит
    assert running["_files"] and running["_texts"]   # запущенная не тронута


def test_running_job_payload_never_evicted_even_over_limit(make_job, monkeypatch):
    running = make_job(
        job_id="runonly001", status="running", created_at=1.0,
        texts={0: "рабочий текст"}, files={0: b"y" * 10_000},
    )
    monkeypatch.setattr(main, "MAX_TOTAL_BYTES", 100)  # лимит заведомо пробит
    main._evict_job_payloads()
    assert running["_files"] and running["_texts"]


# ---------- /fix-all по джобе с выгруженным payload ----------

def test_fix_all_with_expired_payload_returns_410(client, make_job):
    make_job(job_id="fixall0410", edits=[dict(EDIT)], texts={0: "текст"}, files={})
    resp = client.post(
        "/api/jobs/fixall0410/fix-all",
        json={"items": [{"resultIndex": 0, "editIds": ["e1"]}]},
    )
    assert resp.status_code == 410
    assert resp.json()["detail"] == "payload_expired"
