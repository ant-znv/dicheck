"""Тесты истории проверок: сервисный слой history.py, /api/history endpoints,
хуки записи в main.py (ошибка БД не ломает проверку/фикс). Всё офлайн, БД —
в tmp_path (изоляция через conftest.isolated_settings)."""
from __future__ import annotations

import io
import json
import sqlite3
import time
import zipfile

import pytest
from docx import Document

from backend.app import history, main

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
QUOTE = "дежурить в ночное время суток"
REPLACEMENT = "НОВАЯ ФОРМУЛИРОВКА"
BODY = [
    "Должностная инструкция сторожа",
    "Сторож обязан дежурить в ночное время суток.",
]


def structured_response(verdict="risk"):
    """Ответ «модели» при проверке: отчёт + fenced-блок с verdict и edits."""
    block = {
        "verdict": verdict,
        "edits": [
            {
                "id": "e1",
                "title": "Режим работы",
                "original": QUOTE,
                "replacement": REPLACEMENT,
                "reason": "Требования трудового договора",
            }
        ],
    }
    return (
        "## Отчёт\n\nИнструкция проверена, найдены замечания.\n\n"
        "```json\n" + json.dumps(block, ensure_ascii=False) + "\n```"
    )


def post_check(client, docx_bytes, filename="di.docx"):
    return client.post(
        "/api/check",
        files={"files": (filename, docx_bytes, DOCX_MIME)},
        data={"contractSubject": "охрана объектов", "employmentType": "", "extraContext": ""},
    )


def poll_done(client, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(f"/api/jobs/{job_id}").json()
        if data["status"] == "done":
            return data
        assert data["status"] == "running", data
        time.sleep(0.02)
    pytest.fail(f"джоба {job_id} не завершилась за {timeout} с")


def run_check(client, make_fake_llm, make_docx_bytes):
    """Полный цикл проверки одного файла; возвращает (job_id, doc_id)."""
    make_fake_llm([structured_response(verdict="risk")])
    resp = post_check(client, make_docx_bytes(BODY))
    assert resp.status_code == 200
    job_id = resp.json()["jobId"]
    poll_done(client, job_id)
    docs = client.get("/api/history/documents").json()
    assert docs["total"] == 1
    return job_id, docs["items"][0]["id"]


def docx_text(content: bytes) -> str:
    return "\n".join(p.text for p in Document(io.BytesIO(content)).paragraphs)


# ---------- Ленивая инициализация ----------

def test_lazy_schema_init_on_clean_dir():
    db = history._db_path()
    assert not db.exists()  # до первого обращения БД не создаётся
    total, _ = history.list_documents("", 10, 0)
    assert total == 0
    assert db.exists()
    with sqlite3.connect(db) as conn:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
            )
        }
    for name in (
        "documents",
        "check_batches",
        "versions",
        "findings",
        "ix_versions_document",
        "ix_versions_batch",
        "ix_findings_version",
    ):
        assert name in names


# ---------- Roundtrip сервисного слоя ----------

def test_service_roundtrip(make_docx_bytes):
    batch = history.ensure_batch("jobhist01", "deepseek", "model-x", "тема", "full", "контекст")
    assert history.ensure_batch("jobhist01", "other", "m", "", "", "") == batch

    docx = make_docx_bytes(BODY)
    edits = [
        {"id": "e1", "title": "t1", "original": "o1", "replacement": "r1", "reason": "поч1"},
        {"id": "e2", "title": "t2", "original": "o2", "replacement": "r2", "reason": "поч2"},
    ]
    vid = history.save_check_version(
        batch, "ДИ сторожа.docx", ".docx", docx, "Текст ДИ", False,
        "Отчёт проверки", "risk", edits,
    )

    total, items = history.list_documents("", 100, 0)
    assert total == 1
    item = items[0]
    assert item["title"] == "ДИ сторожа"
    assert item["versions_count"] == 1
    assert item["fixed_count"] == 0
    assert item["last_verdict"] == "risk"
    assert item["last_check_at"] is not None
    assert item["last_findings_count"] == 2

    doc = history.get_document(item["id"])
    assert doc["title"] == "ДИ сторожа"
    assert len(doc["versions"]) == 1
    summary = doc["versions"][0]
    assert summary["origin"] == "check"
    assert summary["verdict"] == "risk"
    assert summary["findings_count"] == 2
    assert summary["job_id"] == "jobhist01"
    assert summary["parent_version_id"] is None

    version = history.get_version(vid)
    assert version["document_id"] == item["id"]
    assert version["batch_id"] == batch
    assert version["text"] == "Текст ДИ"
    assert version["text_truncated"] is False
    assert version["report"] == "Отчёт проверки"
    assert [f["edit_id"] for f in version["findings"]] == ["e1", "e2"]
    assert version["findings"][0]["original"] == "o1"
    assert history.get_version_bytes(vid) == docx

    fvid = history.save_fixed_version(
        vid, b"FIXED-DOCX", "docx", ["e1", "e2"], "ДИ сторожа_исправленная.docx"
    )
    fixed = history.get_version(fvid)
    assert fixed["origin"] == "fix"
    assert fixed["document_id"] == item["id"]      # document наследуется
    assert fixed["batch_id"] == batch              # batch наследуется
    assert fixed["parent_version_id"] == vid
    assert fixed["fix_method"] == "docx"
    assert fixed["applied_edit_ids"] == ["e1", "e2"]
    assert fixed["text"] == ""

    _, after = history.list_documents("", 100, 0)
    assert after[0]["fixed_count"] == 1
    assert after[0]["versions_count"] == 2

    assert history.latest_fixed_versions(None) == [
        ("ДИ сторожа", b"FIXED-DOCX", "ДИ сторожа_исправленная.docx")
    ]
    assert history.latest_fixed_versions([item["id"]]) != []
    assert history.latest_fixed_versions([99999]) == []


# ---------- e2e: проверка через API попадает в историю ----------

def test_check_recorded_in_history(client, with_api_key, make_fake_llm, make_docx_bytes):
    job_id, doc_id = run_check(client, make_fake_llm, make_docx_bytes)

    docs = client.get("/api/history/documents").json()
    item = docs["items"][0]
    assert item["title"] == "di"
    assert item["lastCheck"]["verdict"] == "risk"
    assert item["lastCheck"]["findingsCount"] == 1
    assert item["versionsCount"] == 1
    assert item["fixedCount"] == 0

    detail = client.get(f"/api/history/documents/{doc_id}").json()
    check_versions = [v for v in detail["versions"] if v["origin"] == "check"]
    assert len(check_versions) == 1
    assert check_versions[0]["verdict"] == "risk"
    assert check_versions[0]["jobId"] == job_id
    assert check_versions[0]["findingsCount"] == 1

    # детальная версия: текст, отчёт без structured-блока, findings
    vid = check_versions[0]["id"]
    version = client.get(f"/api/history/versions/{vid}").json()
    assert version["documentId"] == doc_id
    assert version["textTruncated"] is False
    assert "Инструкция проверена" in version["report"]
    assert "```" not in version["report"]
    assert version["findings"][0]["editId"] == "e1"
    assert version["findings"][0]["original"] == QUOTE

    dl = client.get(f"/api/history/versions/{vid}/download")
    assert dl.status_code == 200
    assert dl.headers["content-type"].startswith(DOCX_MIME)
    assert docx_text(dl.content) == "\n".join(BODY)


# ---------- e2e: /fix и /fix-all создают fix-версии ----------

def test_fix_creates_fix_version_and_downloads(
    client, with_api_key, make_fake_llm, make_docx_bytes
):
    job_id, doc_id = run_check(client, make_fake_llm, make_docx_bytes)
    check_vid = client.get(f"/api/history/documents/{doc_id}").json()["versions"][0]["id"]

    fix = client.post(
        f"/api/jobs/{job_id}/fix", json={"resultIndex": 0, "editIds": ["e1"]}
    )
    assert fix.status_code == 200

    summary = client.get("/api/history/documents").json()["items"][0]
    assert summary["fixedCount"] == 1
    detail = client.get(f"/api/history/documents/{doc_id}").json()
    fixed = [v for v in detail["versions"] if v["origin"] == "fix"][0]
    assert fixed["fixMethod"] == "docx"
    assert fixed["appliedEditIds"] == ["e1"]
    assert fixed["parentVersionId"] == check_vid
    assert fixed["jobId"] == job_id
    assert fixed["filename"] == "di_исправленная.docx"

    dl = client.get(f"/api/history/versions/{fixed['id']}/download")
    assert dl.status_code == 200
    text = docx_text(dl.content)
    assert REPLACEMENT in text
    assert QUOTE not in text


def test_fix_all_creates_fix_version(client, with_api_key, make_fake_llm, make_docx_bytes):
    make_fake_llm([structured_response(verdict="fail")])
    resp = post_check(client, make_docx_bytes(BODY))
    job_id = resp.json()["jobId"]
    poll_done(client, job_id)
    doc_id = client.get("/api/history/documents").json()["items"][0]["id"]
    check_vid = client.get(f"/api/history/documents/{doc_id}").json()["versions"][0]["id"]

    fix_all = client.post(
        f"/api/jobs/{job_id}/fix-all",
        json={"items": [{"resultIndex": 0, "editIds": ["e1"]}]},
    )
    assert fix_all.status_code == 200

    fixed = [
        v
        for v in client.get(f"/api/history/documents/{doc_id}").json()["versions"]
        if v["origin"] == "fix"
    ]
    assert len(fixed) == 1
    assert fixed[0]["fixMethod"] == "docx"
    assert fixed[0]["parentVersionId"] == check_vid


# ---------- PATCH / поиск / DELETE ----------

def test_patch_search_delete_document(client, with_api_key, make_fake_llm, make_docx_bytes):
    _, doc_id = run_check(client, make_fake_llm, make_docx_bytes)

    patch = client.patch(
        f"/api/history/documents/{doc_id}",
        json={"position": "Сторож", "department": "Служба охраны", "notes": "заметка"},
    )
    assert patch.status_code == 200
    body = patch.json()
    assert body["id"] == doc_id
    assert body["position"] == "Сторож"
    assert body["department"] == "Служба охраны"
    assert body["notes"] == "заметка"
    assert body["versionsCount"] == 1
    assert body["lastCheck"]["verdict"] == "risk"

    # регистронезависимый поиск по кириллице (position/department) и по title
    for term in ("сторож", "СЛУЖБА охраны", "Di"):
        found = client.get("/api/history/documents", params={"search": term}).json()
        assert found["total"] == 1, term

    assert client.get("/api/history/documents", params={"search": "неттакого"}).json()["total"] == 0

    detail = client.get(f"/api/history/documents/{doc_id}").json()
    assert detail["position"] == "Сторож"

    deleted = client.delete(f"/api/history/documents/{doc_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}

    assert client.get(f"/api/history/documents/{doc_id}").status_code == 404
    assert client.get("/api/history/documents").json()["total"] == 0
    # версии и findings ушли каскадом
    vid = detail["versions"][0]["id"]
    assert client.get(f"/api/history/versions/{vid}").status_code == 404

    assert client.delete(f"/api/history/documents/{doc_id}").status_code == 404
    assert client.patch(
        f"/api/history/documents/{doc_id}", json={"position": "x"}
    ).status_code == 404


def test_document_list_paging_validation(client):
    assert client.get("/api/history/documents", params={"limit": 0}).status_code == 400
    assert client.get("/api/history/documents", params={"limit": 501}).status_code == 400
    assert client.get("/api/history/documents", params={"offset": -1}).status_code == 400
    ok = client.get("/api/history/documents", params={"limit": 500, "offset": 0})
    assert ok.status_code == 200
    assert ok.json() == {"total": 0, "items": []}


# ---------- extract-meta ----------

def test_extract_meta_single_success(client, with_api_key, make_fake_llm, make_docx_bytes):
    make_fake_llm(
        [structured_response(), '{"position": "Сторож", "department": "Служба охраны"}']
    )
    resp = post_check(client, make_docx_bytes(BODY))
    poll_done(client, resp.json()["jobId"])
    doc_id = client.get("/api/history/documents").json()["items"][0]["id"]

    meta = client.post(f"/api/history/documents/{doc_id}/extract-meta")
    assert meta.status_code == 200
    assert meta.json() == {"position": "Сторож", "department": "Служба охраны"}

    detail = client.get(f"/api/history/documents/{doc_id}").json()
    assert detail["position"] == "Сторож"
    assert detail["department"] == "Служба охраны"


def test_extract_meta_invalid_response_502(client, with_api_key, make_fake_llm, make_docx_bytes):
    make_fake_llm([structured_response(), "совсем не JSON, просто текст"])
    resp = post_check(client, make_docx_bytes(BODY))
    poll_done(client, resp.json()["jobId"])
    doc_id = client.get("/api/history/documents").json()["items"][0]["id"]

    meta = client.post(f"/api/history/documents/{doc_id}/extract-meta")
    assert meta.status_code == 502
    assert meta.json()["detail"] == "invalid_meta_response"

    # документ не изменился
    detail = client.get(f"/api/history/documents/{doc_id}").json()
    assert detail["position"] == "" and detail["department"] == ""


def test_extract_meta_non_string_fields_502(client, with_api_key, monkeypatch):
    batch = history.ensure_batch("jobmeta07", "deepseek", "m", "", "", "")
    vid = history.save_check_version(
        batch, "doc.docx", ".docx", b"", "Есть текст", False, "R", "ok", []
    )
    doc_id = history.get_version(vid)["document_id"]

    async def fake(provider, model, system_prompt, user_message):
        return '{"position": 42, "department": null}'

    monkeypatch.setattr(main.llm, "chat_completion", fake)
    meta = client.post(f"/api/history/documents/{doc_id}/extract-meta")
    assert meta.status_code == 502
    assert meta.json()["detail"] == "invalid_meta_response"


def test_extract_meta_no_text_404_409(client, with_api_key, monkeypatch):
    batch = history.ensure_batch("jobmeta08", "deepseek", "m", "", "", "")

    async def fail(provider, model, system_prompt, user_message):  # не должен зваться
        raise AssertionError("LLM не должен вызываться")

    monkeypatch.setattr(main.llm, "chat_completion", fail)

    # нет документа
    assert client.post("/api/history/documents/99999/extract-meta").status_code == 404
    assert (
        client.post("/api/history/documents/99999/extract-meta").json()["detail"]
        == "document_not_found"
    )

    # check-версия есть, но текст пуст
    vid = history.save_check_version(
        batch, "empty.docx", ".docx", b"", "", False, "R", "ok", []
    )
    doc_id = history.get_version(vid)["document_id"]
    meta = client.post(f"/api/history/documents/{doc_id}/extract-meta")
    assert meta.status_code == 409
    assert meta.json()["detail"] == "no_text"


def test_extract_meta_empty_values_keep_existing(client, with_api_key, monkeypatch):
    batch = history.ensure_batch("jobmeta09", "deepseek", "m", "", "", "")
    vid = history.save_check_version(
        batch, "doc.docx", ".docx", b"", "Текст ДИ", False, "R", "ok", []
    )
    doc_id = history.get_version(vid)["document_id"]
    history.update_document(doc_id, position="Старая должность")

    async def fake(provider, model, system_prompt, user_message):
        return '{"position": "", "department": "Новое подразделение"}'

    monkeypatch.setattr(main.llm, "chat_completion", fake)
    meta = client.post(f"/api/history/documents/{doc_id}/extract-meta")
    assert meta.status_code == 200
    # пустая должность не затёрла существующую
    assert meta.json() == {"position": "Старая должность", "department": "Новое подразделение"}


def test_extract_meta_batch_partial_failure(
    client, with_api_key, make_fake_llm, make_docx_bytes, monkeypatch
):
    # документ 1 — через полный цикл проверки (текст с маркером)
    make_fake_llm([structured_response()])
    resp = post_check(client, make_docx_bytes(["МАРК-ОДИН текст инструкции."]), filename="one.docx")
    poll_done(client, resp.json()["jobId"])
    doc1 = client.get("/api/history/documents").json()["items"][0]["id"]

    # документ 2 — через сервис (текст с другим маркером)
    batch = history.ensure_batch("jobmeta10", "deepseek", "m", "", "", "")
    vid = history.save_check_version(
        batch, "two.docx", ".docx", b"", "МАРК-ДВА текст инструкции.", False, "R", "ok", []
    )
    doc2 = history.get_version(vid)["document_id"]

    calls: list[str] = []

    async def fake(provider, model, system_prompt, user_message):
        calls.append(user_message)
        assert system_prompt == main.META_SYSTEM_PROMPT
        if "МАРК-ОДИН" in user_message:
            return '{"position": "Начальник участка", "department": "АБК"}'
        return "ерунда без json"

    monkeypatch.setattr(main.llm, "chat_completion", fake)

    batch_resp = client.post(
        "/api/history/extract-meta", json={"documentIds": [doc1, doc2]}
    )
    assert batch_resp.status_code == 200
    results = batch_resp.json()["results"]
    assert [r["documentId"] for r in results] == [doc1, doc2]
    assert results[0]["error"] is None
    assert results[0]["position"] == "Начальник участка"
    assert results[1]["error"] == "invalid_meta_response"
    assert results[1]["position"] == ""

    # doc1 заполнен, doc2 — нет
    d1 = client.get(f"/api/history/documents/{doc1}").json()
    d2 = client.get(f"/api/history/documents/{doc2}").json()
    assert d1["position"] == "Начальник участка" and d1["department"] == "АБК"
    assert d2["position"] == "" and d2["department"] == ""

    # documentIds=null: обрабатываются только документы с пустыми position И department
    second = client.post("/api/history/extract-meta", json={"documentIds": None})
    assert second.status_code == 200
    results2 = second.json()["results"]
    assert [r["documentId"] for r in results2] == [doc2]
    assert results2[0]["error"] == "invalid_meta_response"


# ---------- export/fixed ----------

def test_export_fixed_zip(client, with_api_key, make_fake_llm, make_docx_bytes):
    job_id, doc_id = run_check(client, make_fake_llm, make_docx_bytes)

    # fix-версий ещё нет
    empty = client.get("/api/history/export/fixed")
    assert empty.status_code == 404
    assert empty.json()["detail"] == "no_fixed_files"

    client.post(f"/api/jobs/{job_id}/fix", json={"resultIndex": 0, "editIds": ["e1"]})

    export = client.get("/api/history/export/fixed")
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("application/zip")
    assert "attachment" in export.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(export.content)) as zf:
        assert zf.namelist() == ["di_исправленная.docx"]
        text = docx_text(zf.read("di_исправленная.docx"))
    assert REPLACEMENT in text

    # фильтр по documentIds: чужой id → 404, свой → архив
    by_id = client.get("/api/history/export/fixed", params={"documentIds": str(doc_id)})
    assert by_id.status_code == 200
    assert client.get("/api/history/export/fixed", params={"documentIds": "999"}).status_code == 404
    assert (
        client.get("/api/history/export/fixed", params={"documentIds": "abc"}).status_code == 400
    )


def test_export_fixed_collision_names(client, with_api_key, make_fake_llm, make_docx_bytes):
    """Одинаковые имена исправленных файлов получают суффиксы, как в /fix-all."""
    make_fake_llm([structured_response(), structured_response()])
    resp = client.post(
        "/api/check",
        files=[
            ("files", ("same.docx", make_docx_bytes(BODY), DOCX_MIME)),
            ("files", ("same.docx", make_docx_bytes(BODY), DOCX_MIME)),
        ],
        data={"contractSubject": "", "employmentType": "", "extraContext": ""},
    )
    assert resp.status_code == 200
    job_id = resp.json()["jobId"]
    poll_done(client, job_id)

    fix_all = client.post(
        f"/api/jobs/{job_id}/fix-all",
        json={"items": [{"resultIndex": 0, "editIds": ["e1"]}, {"resultIndex": 1, "editIds": ["e1"]}]},
    )
    assert fix_all.status_code == 200

    export = client.get("/api/history/export/fixed")
    assert export.status_code == 200
    with zipfile.ZipFile(io.BytesIO(export.content)) as zf:
        assert sorted(zf.namelist()) == [
            "same_исправленная.docx",
            "same_исправленная_2.docx",
        ]


# ---------- download: граничные случаи ----------

def test_version_download_missing_and_empty_bytes(client):
    assert client.get("/api/history/versions/99999/download").status_code == 404
    assert (
        client.get("/api/history/versions/99999/download").json()["detail"]
        == "version_not_found"
    )

    batch = history.ensure_batch("jobdl001", "deepseek", "m", "", "", "")
    vid = history.save_check_version(
        batch, "no bytes.docx", ".docx", b"", "текст", False, "R", "ok", []
    )
    resp = client.get(f"/api/history/versions/{vid}/download")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "no_file_data"


def test_version_download_media_type_by_ext(client):
    batch = history.ensure_batch("jobdl002", "deepseek", "m", "", "", "")
    vid = history.save_check_version(
        batch, "scan.pdf", ".pdf", b"%PDF-1.4 fake", "текст", False, "R", "ok", []
    )
    resp = client.get(f"/api/history/versions/{vid}/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert "scan.pdf" in resp.headers["content-disposition"]


# ---------- ошибка БД не ломает проверку и фикс ----------

def test_db_failure_does_not_break_check(
    client, with_api_key, make_fake_llm, make_docx_bytes, monkeypatch
):
    make_fake_llm([structured_response()])

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(history, "save_check_version", boom)

    resp = post_check(client, make_docx_bytes(BODY))
    assert resp.status_code == 200
    data = poll_done(client, resp.json()["jobId"])
    assert data["results"][0]["status"] == "done"
    assert data["results"][0]["summaryVerdict"] == "risk"
    assert data["results"][0]["edits"][0]["id"] == "e1"
    # в историю ничего не попало
    assert client.get("/api/history/documents").json()["total"] == 0


def test_db_failure_does_not_break_fix(
    client, with_api_key, make_fake_llm, make_docx_bytes, monkeypatch
):
    job_id, _ = run_check(client, make_fake_llm, make_docx_bytes)

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(history, "save_fixed_version", boom)
    fix = client.post(
        f"/api/jobs/{job_id}/fix", json={"resultIndex": 0, "editIds": ["e1"]}
    )
    assert fix.status_code == 200
    assert REPLACEMENT in docx_text(fix.content)
