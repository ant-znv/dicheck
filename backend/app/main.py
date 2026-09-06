"""FastAPI-приложение DI_Check. Порт 8787, host 127.0.0.1."""
from __future__ import annotations

import asyncio
import html as html_mod
import io
import json
import re
import uuid
from pathlib import Path
from urllib.parse import quote

from docx import Document
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import extractors, llm, settings

app = FastAPI(title="DI_Check")

# CORS для dev (Vite dev server на 5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Джобы в памяти
_jobs: dict[str, dict] = {}
_semaphore = asyncio.Semaphore(3)

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


# ---------- Модели запросов ----------

class SettingsUpdate(BaseModel):
    activeProvider: str | None = None
    activeModel: str | None = None
    systemPrompt: str | None = None


class ApiKeyUpdate(BaseModel):
    provider: str
    apiKey: str


class TestRequest(BaseModel):
    provider: str
    model: str | None = None


class FixRequest(BaseModel):
    resultIndex: int
    editIds: list[str]


# ---------- Settings ----------

@app.get("/api/settings")
async def get_settings():
    return settings.build_settings_response()


@app.put("/api/settings")
async def put_settings(body: SettingsUpdate):
    try:
        settings.update_settings(
            active_provider=body.activeProvider,
            active_model=body.activeModel,
            system_prompt=body.systemPrompt,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return settings.build_settings_response()


@app.put("/api/settings/apikey")
async def put_apikey(body: ApiKeyUpdate):
    try:
        settings.save_api_key(body.provider, body.apiKey)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "hasApiKey": settings.has_api_key(body.provider)}


@app.post("/api/settings/test")
async def test_connection(body: TestRequest):
    if body.provider not in settings.PROVIDERS:
        raise HTTPException(status_code=400, detail=f"unknown provider: {body.provider}")
    return await llm.test_connection(body.provider, body.model)


# ---------- Проверки ----------

def _build_user_message(
    filename: str,
    text: str,
    contract_subject: str,
    employment_type: str,
    extra_context: str,
) -> str:
    parts = [f"Должностная инструкция (файл: {filename}):\n\n{text}"]
    extras = []
    if contract_subject:
        extras.append(f"Предмет госконтракта: {contract_subject}")
    if employment_type == "full":
        extras.append("Занятость по контракту: сотрудник работает полностью по контракту")
    elif employment_type == "partial":
        extras.append("Занятость по контракту: сотрудник работает по контракту частично")
    if extra_context:
        extras.append(f"Дополнительный контекст (требования к персоналу и т.п.): {extra_context}")
    if extras:
        parts.append("---\n" + "\n".join(extras))
    return "\n\n".join(parts)


def _summary_verdict(report: str) -> str:
    low = report.lower()
    if "не соответствует" in low:
        return "fail"
    if "риск" in low:
        return "risk"
    return "ok"


# ---------- Структурированные правки (edits) ----------

# Фиксированная инструкция, дописываемая к системному промту при проверке.
# НЕ редактируется пользователем и не входит в default_prompt.md.
EDITS_INSTRUCTION = """

---

В КОНЦЕ своего ответа обязательно выведи fenced-блок ```json со списком конкретных правок текста должностной инструкции в формате:

```json
{"edits": [{"id": "e1", "title": "краткое название правки", "original": "дословная цитата из текста ДИ, которую нужно изменить", "replacement": "готовая формулировка для вставки вместо цитаты", "reason": "почему нужна правка (норма/риск)"}]}
```

Требования к правкам:
- original — точная дословная цитата фрагмента текста инструкции; если подходящего фрагмента нет (например, раздел нужно добавить), опиши место вставки;
- replacement — полная готовая формулировка для вставки;
- правки должны быть атомарными (одна правка — одно место в тексте), id — e1, e2, e3...;
- блок ```json должен быть САМЫМ ПОСЛЕДНИМ в ответе, после него ничего не пиши.
"""

_FENCED_RE = re.compile(r"```[ \t]*(\w*)[ \t]*\r?\n(.*?)```", re.DOTALL)
_EDIT_KEYS = ("id", "title", "original", "replacement", "reason")


def _normalize_edits(data: object) -> list[dict] | None:
    """Валидирует распарсенный JSON и приводит edits к списку dict'ов по контракту."""
    if not isinstance(data, dict) or not isinstance(data.get("edits"), list):
        return None
    edits = []
    for i, item in enumerate(data["edits"], 1):
        if not isinstance(item, dict):
            continue
        edit = {k: str(item.get(k) or "") for k in _EDIT_KEYS}
        if not edit["id"]:
            edit["id"] = f"e{i}"
        edits.append(edit)
    return edits


def _matching_brace(text: str, start: int) -> int:
    """Индекс символа после закрывающей '}' для '{' в позиции start (с учётом строк). -1, если не нашлось."""
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def _parse_edits(report: str) -> tuple[str, list[dict]]:
    """Извлекает блок {"edits": [...]} из ответа модели.

    Возвращает (очищенный отчёт, список правок). Если парсинг не удался —
    (исходный отчёт, []).
    """
    # 1) последний fenced-блок, содержащий {"edits": ...}
    for m in reversed(list(_FENCED_RE.finditer(report))):
        edits = None
        try:
            edits = _normalize_edits(json.loads(m.group(2).strip()))
        except json.JSONDecodeError:
            continue
        if edits is not None:
            return (report[: m.start()] + report[m.end() :]).strip(), edits
    # 2) brace-matching от последнего '{"edits"'
    idx = report.rfind('{"edits"')
    if idx != -1:
        end = _matching_brace(report, idx)
        if end != -1:
            try:
                edits = _normalize_edits(json.loads(report[idx:end]))
            except json.JSONDecodeError:
                edits = None
            if edits is not None:
                cleaned = (report[:idx] + report[end:]).strip()
                # убрать осиротевшие fence-ограждения вокруг удалённого блока
                cleaned = re.sub(r"```[ \t]*(?:json)?[ \t]*$", "", cleaned).strip()
                cleaned = re.sub(r"^[ \t]*```", "", cleaned).strip()
                return cleaned, edits
    return report, []


async def _check_file(
    job: dict,
    index: int,
    result: dict,
    data: bytes,
    user_fields: dict,
    state: dict,
) -> None:
    async with _semaphore:
        result["status"] = "running"
        try:
            text = await asyncio.to_thread(
                extractors.extract_text, result["filename"], data
            )
        except extractors.ExtractionError as e:
            result["status"] = "error"
            result["error"] = str(e)
            return
        # исходный текст хранится в джобе (не отдаётся через GET) — нужен для /fix
        job["_texts"][index] = text
        user_message = _build_user_message(result["filename"], text, **user_fields)
        try:
            raw_report = await llm.chat_completion(
                state["activeProvider"],
                state["activeModel"],
                state["systemPrompt"] + EDITS_INSTRUCTION,
                user_message,
            )
            report, edits = _parse_edits(raw_report)
            result["report"] = report
            result["edits"] = edits
            result["summaryVerdict"] = _summary_verdict(report)
            result["status"] = "done"
        except llm.LLMError as e:
            result["status"] = "error"
            result["error"] = str(e)


async def _run_job(job_id: str, files: list[tuple[str, bytes]], user_fields: dict) -> None:
    job = _jobs[job_id]
    state = settings.get_settings_state()
    tasks = [
        _check_file(job, index, result, data, user_fields, state)
        for index, (result, (_, data)) in enumerate(zip(job["results"], files))
    ]
    await asyncio.gather(*tasks)
    job["status"] = "done"


@app.post("/api/check")
async def create_check(
    files: list[UploadFile] = File(...),
    contractSubject: str = Form(""),
    employmentType: str = Form(""),
    extraContext: str = Form(""),
):
    state = settings.get_settings_state()
    if not settings.has_api_key(state["activeProvider"]):
        raise HTTPException(status_code=409, detail="no_api_key")

    if not files:
        raise HTTPException(status_code=400, detail="no_files")

    payloads: list[tuple[str, bytes]] = []
    results = []
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in extractors.SUPPORTED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"unsupported_format: {f.filename}",
            )
        data = await f.read()
        if not data:
            raise HTTPException(status_code=400, detail=f"empty_file: {f.filename}")
        payloads.append((f.filename, data))
        results.append(
            {
                "filename": f.filename,
                "status": "pending",
                "error": None,
                "report": None,
                "summaryVerdict": None,
                "edits": None,
            }
        )

    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {
        "id": job_id,
        "status": "running",
        "results": results,
        "_texts": {},  # index результата -> извлечённый текст (наружу не отдаётся)
    }
    user_fields = {
        "contract_subject": contractSubject,
        "employment_type": employmentType,
        "extra_context": extraContext,
    }
    asyncio.create_task(_run_job(job_id, payloads, user_fields))
    return {"jobId": job_id}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    # служебные поля ("_texts" и т.п.) наружу не отдаём
    return {"id": job["id"], "status": job["status"], "results": job["results"]}


# ---------- Применение правок (/fix) ----------

FIX_SYSTEM_PROMPT = """Ты — редактор кадровых документов. Тебе дают исходный текст должностной инструкции и список правок.

Твоя задача — внести ВСЕ перечисленные правки и вернуть ПОЛНЫЙ исправленный текст документа целиком.

Требования к ответу:
- верни ТОЛЬКО текст исправленного документа, без каких-либо комментариев, пояснений и преамбул;
- не сокращай и не опускай разделы документа — он должен остаться полным;
- оформи структуру в markdown: заголовок документа — "# ...", заголовки разделов — "## ...", перечисления — маркированные списки через "- ";
- не обрамляй ответ в ``` и не добавляй ничего после текста документа.
"""


def _clean_md_inline(text: str) -> str:
    """Убирает markdown-мусор из строки (**жирный**, `код`)."""
    return text.replace("**", "").replace("__", "").replace("`", "").strip()


def _markdown_to_docx(text: str) -> bytes:
    """Простая генерация .docx из markdown-подобного текста модели."""
    lines = text.strip().splitlines()
    # снять обрамление ```markdown ... ```, если модель всё же обернула ответ
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]

    doc = Document()
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.startswith("### "):
            doc.add_heading(_clean_md_inline(line[4:]), level=3)
        elif line.startswith("## "):
            doc.add_heading(_clean_md_inline(line[3:]), level=2)
        elif line.startswith("# "):
            doc.add_heading(_clean_md_inline(line[2:]), level=1)
        elif re.match(r"^\s*[-*•]\s+", line):
            item = re.sub(r"^\s*[-*•]\s+", "", line)
            doc.add_paragraph(_clean_md_inline(item), style="List Bullet")
        elif re.match(r"^\s*\d+[.)]\s+", line):
            item = re.sub(r"^\s*\d+[.)]\s+", "", line)
            doc.add_paragraph(_clean_md_inline(item), style="List Number")
        else:
            doc.add_paragraph(_clean_md_inline(line))
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@app.post("/api/jobs/{job_id}/fix")
async def fix_document(job_id: str, body: FixRequest):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    if body.resultIndex < 0 or body.resultIndex >= len(job["results"]):
        raise HTTPException(status_code=404, detail="result_not_found")
    result = job["results"][body.resultIndex]

    if not body.editIds:
        raise HTTPException(status_code=400, detail="empty_edit_ids")
    source_text = job.get("_texts", {}).get(body.resultIndex)
    if not source_text:
        raise HTTPException(status_code=400, detail="no_source_text")

    by_id = {e["id"]: e for e in (result.get("edits") or [])}
    unknown = [eid for eid in body.editIds if eid not in by_id]
    if unknown:
        raise HTTPException(
            status_code=400, detail=f"unknown_edit_ids: {', '.join(unknown)}"
        )
    chosen = [by_id[eid] for eid in body.editIds]

    edits_desc = "\n".join(
        f'{i}. Заменить «{e["original"]}» на «{e["replacement"]}»'
        + (f' (основание: {e["reason"]})' if e["reason"] else "")
        for i, e in enumerate(chosen, 1)
    )
    user_message = (
        f"Исходный текст должностной инструкции:\n\n{source_text}\n\n"
        f"---\n\nПравки, которые нужно внести:\n{edits_desc}"
    )

    state = settings.get_settings_state()
    try:
        fixed_text = await llm.chat_completion(
            state["activeProvider"],
            state["activeModel"],
            FIX_SYSTEM_PROMPT,
            user_message,
        )
    except llm.LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))

    docx_bytes = await asyncio.to_thread(_markdown_to_docx, fixed_text)
    filename = f"{Path(result['filename']).stem}_исправленная.docx"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )


# ---------- Экспорт ----------

def _export_markdown(job: dict) -> str:
    lines = [f"# Сводный отчёт DI_Check\n", f"Джоб: `{job['id']}`\n"]
    for r in job["results"]:
        lines.append(f"\n---\n\n## {r['filename']}\n")
        if r["status"] == "error":
            lines.append(f"**Ошибка:** {r['error']}\n")
        elif r["report"]:
            lines.append(r["report"] + "\n")
        else:
            lines.append("_Нет результата._\n")
    return "\n".join(lines)


def _export_html(job: dict) -> str:
    md = _export_markdown(job)
    return (
        "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        f"<title>Отчёт DI_Check {html_mod.escape(job['id'])}</title>\n"
        "<style>body{font-family:Segoe UI,Arial,sans-serif;max-width:960px;"
        "margin:2em auto;padding:0 1em;}"
        "pre{white-space:pre-wrap;word-wrap:break-word;}</style>\n"
        "</head>\n<body>\n<pre>"
        + html_mod.escape(md)
        + "</pre>\n</body>\n</html>"
    )


@app.get("/api/jobs/{job_id}/export")
async def export_job(job_id: str, format: str = "md"):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    if format == "md":
        content = _export_markdown(job)
        media_type = "text/markdown; charset=utf-8"
        ext = "md"
    elif format == "html":
        content = _export_html(job)
        media_type = "text/html; charset=utf-8"
        ext = "html"
    else:
        raise HTTPException(status_code=400, detail="unsupported export format")
    return Response(
        content=content.encode("utf-8"),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="di_check_{job_id}.{ext}"'
        },
    )


# ---------- Статика фронтенда (prod) ----------

if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
