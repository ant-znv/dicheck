"""FastAPI-приложение DI_Check. Порт 8787, host 127.0.0.1."""
from __future__ import annotations

import asyncio
import html as html_mod
import io
import json
import logging
import re
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from docx import Document
from docx.text.paragraph import Paragraph
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import extractors, llm, settings

logger = logging.getLogger("di_check")
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

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
# Сильные ссылки на фоновые задачи (иначе create_task может быть собран GC)
_run_tasks: set[asyncio.Task] = set()

# Лимиты входа и хранения
MAX_FILES = 20
MAX_FILE_SIZE = 20 * 1024 * 1024  # байт на файл
MAX_TEXT_CHARS = 120_000          # предел текста ДИ в user-message
JOB_TTL_SECONDS = 24 * 3600       # сколько жить завершённой джобе
MAX_JOBS = 50                     # максимум джоб в памяти

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
    """Эвристический вердикт по тексту отчёта (fallback, если модель не отдала свой)."""
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

В КОНЦЕ своего ответа обязательно выведи fenced-блок ```json со сводным вердиктом и списком конкретных правок текста должностной инструкции в формате:

```json
{"verdict": "risk", "edits": [{"id": "e1", "title": "краткое название правки", "original": "дословная цитата из текста ДИ, которую нужно изменить", "replacement": "готовая формулировка для вставки вместо цитаты", "reason": "почему нужна правка (норма/риск)"}]}
```

где verdict — общий вердикт по всей ДИ: "ok" (соответствует), "risk" (есть риски) или "fail" (не соответствует).

Требования к правкам:
- original — точная дословная цитата фрагмента текста инструкции; если подходящего фрагмента нет (например, раздел нужно добавить), опиши место вставки;
- replacement — полная готовая формулировка для вставки;
- правки должны быть атомарными (одна правка — одно место в тексте), id — e1, e2, e3...;
- блок ```json должен быть САМЫМ ПОСЛЕДНИМ в ответе, после него ничего не пиши.
"""

_FENCED_RE = re.compile(r"```[ \t]*(\w*)[ \t]*\r?\n(.*?)```", re.DOTALL)
_EDIT_KEYS = ("id", "title", "original", "replacement", "reason")
_VALID_VERDICTS = {"ok", "risk", "fail"}


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


def _parse_edits(report: str) -> tuple[str, list[dict], str | None]:
    """Извлекает блок {"verdict": ..., "edits": [...]} из ответа модели.

    Возвращает (очищенный отчёт, список правок, вердикт | None). Вердикт берётся
    из structured-блока; если его нет — вызывающий код использует эвристику.
    Если парсинг не удался — (исходный отчёт, [], None).
    """
    # 1) последний fenced-блок, содержащий {"edits": ...}
    for m in reversed(list(_FENCED_RE.finditer(report))):
        try:
            data = json.loads(m.group(2).strip())
        except json.JSONDecodeError:
            continue
        edits = _normalize_edits(data)
        if edits is not None:
            verdict = data.get("verdict")
            return (
                (report[: m.start()] + report[m.end() :]).strip(),
                edits,
                verdict if verdict in _VALID_VERDICTS else None,
            )
    # 2) brace-matching от последнего '{"edits"'
    idx = report.rfind('{"edits"')
    if idx != -1:
        end = _matching_brace(report, idx)
        if end != -1:
            try:
                data = json.loads(report[idx:end])
            except json.JSONDecodeError:
                data = None
            edits = _normalize_edits(data)
            if edits is not None:
                verdict = data.get("verdict") if isinstance(data, dict) else None
                cleaned = (report[:idx] + report[end:]).strip()
                # убрать осиротевшие fence-ограждения вокруг удалённого блока
                cleaned = re.sub(r"```[ \t]*(?:json)?[ \t]*$", "", cleaned).strip()
                cleaned = re.sub(r"^[ \t]*```", "", cleaned).strip()
                return cleaned, edits, verdict if verdict in _VALID_VERDICTS else None
    return report, [], None


async def _check_file(
    job: dict,
    index: int,
    result: dict,
    data: bytes,
    user_fields: dict,
    state: dict,
) -> None:
    started = time.monotonic()
    try:
        async with _semaphore:
            result["status"] = "running"
            try:
                text = await asyncio.to_thread(
                    extractors.extract_text, result["filename"], data
                )
            except extractors.ExtractionError as e:
                result["status"] = "error"
                result["error"] = str(e)
                logger.warning(
                    "Джоба %s, файл %s: извлечение текста не удалось: %s",
                    job["id"], result["filename"], e,
                )
                return
            if len(text) > MAX_TEXT_CHARS:
                text = text[:MAX_TEXT_CHARS]
                result["textTruncated"] = True
                logger.warning(
                    "Джоба %s, файл %s: текст обрезан до %d символов (слишком длинный)",
                    job["id"], result["filename"], MAX_TEXT_CHARS,
                )
            # исходный текст и байты хранятся в джобе (не отдаются через GET):
            # текст нужен для /fix, байты — для детерминированных правок .docx
            job["_texts"][index] = text
            job["_files"][index] = data
            user_message = _build_user_message(result["filename"], text, **user_fields)
            raw_report = await llm.chat_completion(
                state["activeProvider"],
                state["activeModel"],
                state["systemPrompt"] + EDITS_INSTRUCTION,
                user_message,
            )
            report, edits, verdict = _parse_edits(raw_report)
            result["report"] = report
            result["edits"] = edits
            result["summaryVerdict"] = verdict or _summary_verdict(report)
            result["status"] = "done"
            logger.info(
                "Джоба %s, файл %s: готово за %.1f с, правок %d, вердикт %s",
                job["id"], result["filename"], time.monotonic() - started,
                len(edits), result["summaryVerdict"],
            )
    except asyncio.CancelledError:
        # отмену не пробрасываем: gather соберёт задачу, джоба получит статус cancelled
        result["status"] = "cancelled"
        logger.info("Джоба %s, файл %s: проверка отменена", job["id"], result["filename"])
    except llm.LLMError as e:
        result["status"] = "error"
        result["error"] = str(e)
        logger.warning(
            "Джоба %s, файл %s: ошибка LLM: %s", job["id"], result["filename"], e
        )
    except Exception:
        logger.exception(
            "Джоба %s, файл %s: неожиданная ошибка проверки", job["id"], result["filename"]
        )
        result["status"] = "error"
        result["error"] = "Внутренняя ошибка проверки (подробности в логе сервера)"


async def _run_job(job_id: str, files: list[tuple[str, bytes]], user_fields: dict) -> None:
    job = _jobs[job_id]
    state = settings.get_settings_state()
    tasks = [
        asyncio.create_task(_check_file(job, index, result, data, user_fields, state))
        for index, (result, (_, data)) in enumerate(zip(job["results"], files))
    ]
    job["tasks"] = tasks
    try:
        # исключения _check_file обрабатывает сам; gather — страховка
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        job["tasks"] = []
    for out in outcomes:
        if isinstance(out, BaseException) and not isinstance(out, asyncio.CancelledError):
            logger.error("Джоба %s: задача проверки упала исключением: %r", job_id, out)
    if job.get("cancel_requested"):
        job["status"] = "cancelled"
    elif all(r["status"] == "error" for r in job["results"]):
        job["status"] = "error"
    else:
        job["status"] = "done"
    logger.info("Джоба %s завершена, статус: %s", job_id, job["status"])


def _evict_expired_jobs() -> None:
    """Выгружает завершённые джобы старше TTL и сверх MAX_JOBS (активные не трогаем)."""
    now = time.monotonic()
    expired = [
        j for j in _jobs.values()
        if j["status"] != "running" and now - j["created_at"] > JOB_TTL_SECONDS
    ]
    for j in expired:
        del _jobs[j["id"]]
    if expired:
        logger.info("Выгружено просроченных джоб: %d", len(expired))
    while len(_jobs) > MAX_JOBS:
        finished = sorted(
            (j for j in _jobs.values() if j["status"] != "running"),
            key=lambda j: j["created_at"],
        )
        if not finished:
            break
        oldest = finished[0]
        del _jobs[oldest["id"]]
        logger.info(
            "Выгружена старая джоба %s (превышен лимит %d джоб)", oldest["id"], MAX_JOBS
        )


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
    if len(files) > MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"too_many_files: {len(files)} (максимум {MAX_FILES})",
        )

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
        if len(data) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"file_too_large: {f.filename} "
                    f"(максимум {MAX_FILE_SIZE // (1024 * 1024)} МБ)"
                ),
            )
        payloads.append((f.filename, data))
        results.append(
            {
                "filename": f.filename,
                "status": "pending",
                "error": None,
                "report": None,
                "summaryVerdict": None,
                "edits": None,
                "textTruncated": False,
            }
        )

    _evict_expired_jobs()

    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {
        "id": job_id,
        "status": "running",
        "created_at": time.monotonic(),
        "results": results,
        "_texts": {},  # index результата -> извлечённый текст (наружу не отдаётся)
        "_files": {},  # index результата -> исходные байты файла (для правок .docx)
        "tasks": [],   # активные задачи файлов (для отмены)
        "cancel_requested": False,
    }
    user_fields = {
        "contract_subject": contractSubject,
        "employment_type": employmentType,
        "extra_context": extraContext,
    }
    task = asyncio.create_task(_run_job(job_id, payloads, user_fields))
    _run_tasks.add(task)
    task.add_done_callback(_run_tasks.discard)
    logger.info(
        "Джоба %s запущена: файлов %d, провайдер %s, модель %s",
        job_id, len(files), state["activeProvider"], state["activeModel"],
    )
    return {"jobId": job_id}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    # служебные поля ("_texts", "_files", "tasks" и т.п.) наружу не отдаём
    return {"id": job["id"], "status": job["status"], "results": job["results"]}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Отменяет проверку: файлы в работе прерываются, ожидающие — получают cancelled."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    if job["status"] != "running":
        return {"ok": True, "status": job["status"]}
    job["cancel_requested"] = True
    for task in list(job.get("tasks") or []):
        task.cancel()
    logger.info("Джоба %s: запрошена отмена", job_id)
    return {"ok": True}


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


def _markdown_into_docx(doc: Document, text: str) -> None:
    """Добавляет markdown-подобный текст модели в существующий Document."""
    lines = text.strip().splitlines()
    # снять обрамление ```markdown ... ```, если модель всё же обернула ответ
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]

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


def _markdown_to_docx(text: str) -> bytes:
    """Простая генерация .docx из markdown-подобного текста модели."""
    doc = Document()
    _markdown_into_docx(doc, text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


class FixError(Exception):
    """Ошибка применения правок к одному файлу (для /fix-all — в _errors.txt)."""


# ---------- Детерминированное применение правок к исходному .docx ----------

def _iter_table_paragraphs(table):
    for row in table.rows:
        for cell in row.cells:
            yield from cell.paragraphs
            for nested in cell.tables:
                yield from _iter_table_paragraphs(nested)


def _iter_docx_paragraphs(doc: Document):
    """Все абзацы документа: тело, таблицы и непустые колонтитулы."""
    yield from doc.paragraphs
    for table in doc.tables:
        yield from _iter_table_paragraphs(table)
    for section in doc.sections:
        for hf in (
            section.header,
            section.footer,
            section.first_page_header,
            section.first_page_footer,
            section.even_page_header,
            section.even_page_footer,
        ):
            try:
                if hf.is_linked_to_previous:
                    continue
                yield from hf.paragraphs
                for table in hf.tables:
                    yield from _iter_table_paragraphs(table)
            except Exception:
                continue


def _replace_in_paragraph(par: Paragraph, original: str, replacement: str) -> bool:
    """Заменяет original на replacement в абзаце, работая с runs.

    Форматирование первого затронутого run'а распространяется на replacement.
    Возвращает False, если original не найден в runs абзаца.
    """
    runs = par.runs
    joined = "".join(r.text for r in runs)
    idx = joined.find(original)
    if idx == -1:
        return False
    end = idx + len(original)
    pos = 0
    placed = False
    for r in runs:
        r_start = pos
        r_end = pos + len(r.text)
        pos = r_end
        if r_end <= idx or r_start >= end:
            continue  # run вне диапазона замены
        prefix = r.text[: max(0, idx - r_start)]
        suffix = r.text[max(0, end - r_start):]
        r.text = (prefix + replacement + suffix) if not placed else (prefix + suffix)
        placed = True
    return True


def _apply_edits_to_docx(
    data: bytes, edits: list[dict]
) -> tuple[Document | None, list[dict]]:
    """Применяет правки к копии исходного .docx, сохраняя форматирование.

    Возвращает (Document | None, правки, которые не удалось применить на уровне
    runs — их добирает LLM-фолбэк).
    """
    try:
        doc = Document(io.BytesIO(data))
    except Exception as e:
        logger.warning("Детерминированные правки отменены: .docx не открылся: %s", e)
        return None, list(edits)
    failed: list[dict] = []
    for e in edits:
        applied = False
        if e["original"]:
            for par in _iter_docx_paragraphs(doc):
                joined = "".join(r.text for r in par.runs)
                if e["original"] in joined and _replace_in_paragraph(
                    par, e["original"], e["replacement"]
                ):
                    applied = True
                    break
        if not applied:
            failed.append(e)
    return doc, failed


def _build_fix_message(source_text: str, edits: list[dict]) -> str:
    edits_desc = "\n".join(
        f'{i}. Заменить «{e["original"]}» на «{e["replacement"]}»'
        + (f' (основание: {e["reason"]})' if e["reason"] else "")
        for i, e in enumerate(edits, 1)
    )
    return (
        f"Исходный текст должностной инструкции:\n\n{source_text}\n\n"
        f"---\n\nПравки, которые нужно внести:\n{edits_desc}"
    )


async def _perform_fix(job: dict, result_index: int, edit_ids: list[str]) -> tuple[bytes, str]:
    """Применяет правки к ДИ. Возвращает (docx-байты, способ: "docx"|"text"|"llm").

    Правки с дословной уникальной цитатой применяются без LLM: для исходного
    .docx — прямо в документе (сохраняя форматирование), для остальных
    источников — пересборкой из обновлённого текста. Недетерминированные правки
    (вставки, цитаты не найдены) добирает LLM-фолбэк.
    """
    result = job["results"][result_index]

    if not edit_ids:
        raise FixError("empty_edit_ids")
    source_text = job.get("_texts", {}).get(result_index)
    if not source_text:
        raise FixError("no_source_text")

    by_id = {e["id"]: e for e in (result.get("edits") or [])}
    unknown = [eid for eid in edit_ids if eid not in by_id]
    if unknown:
        raise FixError(f"unknown_edit_ids: {', '.join(unknown)}")
    chosen = [by_id[eid] for eid in edit_ids]

    # 1) детерминированная часть: дословная цитата, уникальная в исходном тексте
    rest: list[dict] = []
    updated_text = source_text
    exact_applied: list[dict] = []
    for e in chosen:
        if e["original"] and source_text.count(e["original"]) == 1:
            if e["original"] in updated_text:
                updated_text = updated_text.replace(e["original"], e["replacement"], 1)
                exact_applied.append(e)
            else:
                rest.append(e)  # предыдущая замена задела текст этой правки
        else:
            rest.append(e)

    docx_data = job.get("_files", {}).get(result_index)
    if (
        exact_applied
        and docx_data
        and Path(result["filename"]).suffix.lower() == ".docx"
    ):
        doc, failed = await asyncio.to_thread(_apply_edits_to_docx, docx_data, exact_applied)
        rest = failed + rest
        if doc is not None and not failed:
            buf = io.BytesIO()
            await asyncio.to_thread(doc.save, buf)
            return buf.getvalue(), "docx"
        # если часть правок не легла на уровень runs — добираем через LLM ниже

    if exact_applied and not rest:
        # исходник не .docx (или без байтов), зато все правки применились к тексту
        return await asyncio.to_thread(_markdown_to_docx, updated_text), "text"

    # 2) LLM-фолбэк: вставки и цитаты, которые не удалось применить дословно
    state = settings.get_settings_state()
    fixed_text = await llm.chat_completion(
        state["activeProvider"],
        state["activeModel"],
        FIX_SYSTEM_PROMPT,
        _build_fix_message(updated_text, rest),
    )
    return await asyncio.to_thread(_markdown_to_docx, fixed_text), "llm"


@app.post("/api/jobs/{job_id}/fix")
async def fix_document(job_id: str, body: FixRequest):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    if body.resultIndex < 0 or body.resultIndex >= len(job["results"]):
        raise HTTPException(status_code=404, detail="result_not_found")

    try:
        docx_bytes, method = await _perform_fix(job, body.resultIndex, body.editIds)
    except FixError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except llm.LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))

    logger.info(
        "Fix %s[%d]: применено методом %s", job_id, body.resultIndex, method
    )
    filename = f"{Path(job['results'][body.resultIndex]['filename']).stem}_исправленная.docx"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )


# ---------- Пакетное исправление (/fix-all) ----------

class FixAllItem(BaseModel):
    resultIndex: int
    editIds: list[str]


class FixAllRequest(BaseModel):
    items: list[FixAllItem]


async def _fix_one(
    sem: asyncio.Semaphore, job: dict, item: FixAllItem
) -> tuple[str, bytes | None, str | None]:
    """Исправляет один файл. Возвращает (имя файла в архиве, docx | None, ошибка | None)."""
    result = job["results"][item.resultIndex]
    arcname = f"{Path(result['filename']).stem}_исправленная.docx"
    async with sem:
        try:
            docx_bytes, method = await _perform_fix(job, item.resultIndex, item.editIds)
        except (FixError, llm.LLMError) as e:
            logger.warning(
                "Fix-all %s[%d]: не удалось: %s", job["id"], item.resultIndex, e
            )
            return arcname, None, str(e)
    logger.info(
        "Fix-all %s[%d]: применено методом %s", job["id"], item.resultIndex, method
    )
    return arcname, docx_bytes, None


@app.post("/api/jobs/{job_id}/fix-all")
async def fix_all_documents(job_id: str, body: FixAllRequest):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    if not body.items:
        raise HTTPException(status_code=400, detail="empty_items")
    for item in body.items:
        if item.resultIndex < 0 or item.resultIndex >= len(job["results"]):
            raise HTTPException(
                status_code=400, detail=f"result_index_out_of_range: {item.resultIndex}"
            )

    sem = asyncio.Semaphore(3)
    outcomes = await asyncio.gather(*[_fix_one(sem, job, item) for item in body.items])

    successes: list[tuple[str, bytes]] = []
    failures: list[str] = []
    for result_index, (arcname, docx_bytes, error) in zip(
        (i.resultIndex for i in body.items), outcomes
    ):
        if docx_bytes is not None:
            successes.append((arcname, docx_bytes))
        else:
            failures.append(f"{job['results'][result_index]['filename']}: {error}")

    if not successes:
        raise HTTPException(status_code=502, detail="no_files_fixed")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        used: set[str] = set()
        for arcname, docx_bytes in successes:
            # не допускаем коллизий имён при одинаковых исходных файлах
            name = arcname
            n = 2
            while name in used:
                name = f"{Path(arcname).stem}_{n}.docx"
                n += 1
            used.add(name)
            zf.writestr(name, docx_bytes)
        if failures:
            zf.writestr("_errors.txt", "\n".join(failures) + "\n")
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="ispravlennye_di.zip"'},
    )


# ---------- Экспорт ----------

def _export_markdown(job: dict) -> str:
    lines = [f"# Сводный отчёт DI_Check\n", f"Джоб: `{job['id']}`\n"]
    for r in job["results"]:
        lines.append(f"\n---\n\n## {r['filename']}\n")
        if r["status"] == "error":
            lines.append(f"**Ошибка:** {r['error']}\n")
        elif r["status"] == "cancelled":
            lines.append("_Проверка отменена._\n")
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


_VERDICT_LABELS = {"ok": "OK", "risk": "Есть риски", "fail": "Не соответствует"}


def _export_docx(job: dict) -> bytes:
    """Единый .docx-отчёт: титульный блок, сводная таблица, секции по файлам."""
    doc = Document()
    doc.add_heading("Сводный отчёт DI_Check", level=0)
    doc.add_paragraph(f"Дата формирования: {datetime.now():%d.%m.%Y %H:%M}")
    doc.add_paragraph(f"Файлов проверено: {len(job['results'])}")

    doc.add_heading("Сводная таблица", level=1)
    table = doc.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    for cell, text in zip(
        table.rows[0].cells, ("Файл", "Вердикт", "Правок", "Статус")
    ):
        cell.text = text
    for r in job["results"]:
        cells = table.add_row().cells
        cells[0].text = r["filename"]
        cells[1].text = _VERDICT_LABELS.get(r.get("summaryVerdict") or "", "—")
        cells[2].text = str(len(r.get("edits") or []))
        cells[3].text = r["status"]

    for r in job["results"]:
        if r["status"] != "done":
            continue
        doc.add_heading(f"Отчёт по файлу: {r['filename']}", level=1)
        if r.get("report"):
            _markdown_into_docx(doc, r["report"])
        else:
            doc.add_paragraph("Нет отчёта.")
        edits = r.get("edits") or []
        if edits:
            doc.add_heading("Правки", level=2)
            for e in edits:
                doc.add_paragraph(
                    f"{e['id']}. {e['title']}", style="List Number"
                )
                if e.get("reason"):
                    doc.add_paragraph(f"Основание: {e['reason']}")
                doc.add_paragraph(f"Было: {e['original']}")
                doc.add_paragraph(f"Будет: {e['replacement']}")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@app.get("/api/jobs/{job_id}/export")
async def export_job(job_id: str, format: str = "md"):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    if format == "md":
        content = _export_markdown(job).encode("utf-8")
        media_type = "text/markdown; charset=utf-8"
        ext = "md"
    elif format == "html":
        content = _export_html(job).encode("utf-8")
        media_type = "text/html; charset=utf-8"
        ext = "html"
    elif format == "docx":
        content = await asyncio.to_thread(_export_docx, job)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ext = "docx"
    else:
        raise HTTPException(status_code=400, detail="unsupported export format")
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="di_check_{job_id}.{ext}"'
        },
    )


# ---------- Статика фронтенда (prod) ----------

if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
