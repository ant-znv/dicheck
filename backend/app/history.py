"""История проверок: SQLite-хранилище (%APPDATA%\\DI_Check\\history.db).

Сюда попадают все проверенные ДИ: документ (метаданные), версии (исходная
«check» и исправленные «fix» с байтами файла) и замечания (findings).
Схема инициализируется лениво при первом соединении; путь БД резолвится из
settings._CONFIG_DIR при каждом обращении (тесты уводят конфиг в tmp_path и
получают собственную изолированную БД).

Модуль — сервисный слой без HTTP-понятий: ошибки отдаёт исключениями,
вызывающий код (main.py) оборачивает вызовы в try/except, чтобы история
никогда не ломала проверку/фикс.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import settings

# Один писатель за раз; чтения в WAL-режиме идут параллельно записям.
_write_lock = threading.Lock()
# Пути, для которых схема уже создана (инициализация — один раз на файл БД).
_schema_ready: set[str] = set()
_schema_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    position TEXT NOT NULL DEFAULT '',
    department TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS check_batches (
    id INTEGER PRIMARY KEY,
    job_id TEXT UNIQUE,
    provider TEXT,
    model TEXT,
    contract_subject TEXT,
    employment_type TEXT,
    extra_context TEXT,
    started_at TEXT
);
CREATE TABLE IF NOT EXISTS versions (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    batch_id INTEGER REFERENCES check_batches(id) ON DELETE SET NULL,
    parent_version_id INTEGER REFERENCES versions(id) ON DELETE SET NULL,
    origin TEXT NOT NULL CHECK (origin IN ('check', 'fix')),
    filename TEXT,
    file_ext TEXT,
    file_bytes BLOB NOT NULL DEFAULT x'',
    text TEXT NOT NULL DEFAULT '',
    text_truncated INTEGER NOT NULL DEFAULT 0,
    report TEXT,
    verdict TEXT,
    fix_method TEXT,
    applied_edit_ids TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_versions_document ON versions(document_id);
CREATE INDEX IF NOT EXISTS ix_versions_batch ON versions(batch_id);
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    edit_id TEXT,
    title TEXT,
    original TEXT,
    replacement TEXT,
    reason TEXT,
    UNIQUE (version_id, edit_id)
);
CREATE INDEX IF NOT EXISTS ix_findings_version ON findings(version_id);
CREATE TABLE IF NOT EXISTS overlap_reports (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    document_ids_json TEXT NOT NULL DEFAULT '[]',
    result_json TEXT NOT NULL DEFAULT '{}'
);
"""

# Колонки documents, добавляемые миграцией (БД версии до фичи «пересечения» их
# не содержат); миграция не деструктивная — только ALTER TABLE ADD COLUMN.
_MIGRATION_COLUMNS = (
    ("duties_json", "TEXT"),          # JSON-массив строк обязанностей
    ("duties_version_id", "INTEGER"),  # версия, из которой обязанности извлечены
    ("duties_extracted_at", "TEXT"),
)

# Поля documents, доступные для обновления (update_document/extract_meta_update).
_META_FIELDS = ("position", "department", "title", "notes")

# Общие колонки сводки документа (агрегаты по версиям) — для списка и одиночного чтения.
_SUMMARY_COLUMNS = """
    d.id AS id,
    d.position AS position,
    d.department AS department,
    d.title AS title,
    d.notes AS notes,
    d.created_at AS created_at,
    d.updated_at AS updated_at,
    (SELECT COUNT(*) FROM versions v WHERE v.document_id = d.id) AS versions_count,
    (SELECT COUNT(*) FROM versions v WHERE v.document_id = d.id AND v.origin = 'fix') AS fixed_count,
    (SELECT v.verdict FROM versions v WHERE v.document_id = d.id AND v.origin = 'check'
        ORDER BY v.id DESC LIMIT 1) AS last_verdict,
    (SELECT v.created_at FROM versions v WHERE v.document_id = d.id AND v.origin = 'check'
        ORDER BY v.id DESC LIMIT 1) AS last_check_at,
    (SELECT (SELECT COUNT(*) FROM findings f WHERE f.version_id = lv.id)
        FROM versions lv WHERE lv.document_id = d.id AND lv.origin = 'check'
        ORDER BY lv.id DESC LIMIT 1) AS last_findings_count
"""


def _db_path() -> Path:
    """Путь БД; резолвится при каждом вызове (не при импорте модуля)."""
    return Path(settings._CONFIG_DIR) / "history.db"


def _now() -> str:
    """UTC-метка времени в ISO8601 (фиксированная ширина — строки сортируются)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _uclower(value: object) -> object:
    """lower() средствами Python — работает и для кириллицы (в отличие от SQL lower)."""
    return value.lower() if isinstance(value, str) else value


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Дописывает duties-колонки в documents старым БД (данные не трогаются)."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(documents)")}
    for name, decl in _MIGRATION_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE documents ADD COLUMN {name} {decl}")


def _ensure_schema(conn: sqlite3.Connection, path: Path) -> None:
    key = str(path)
    if key in _schema_ready:
        return
    with _schema_lock:
        if key in _schema_ready:
            return
        conn.executescript(_SCHEMA)
        _migrate_schema(conn)
        conn.commit()
        _schema_ready.add(key)


def _connect() -> sqlite3.Connection:
    """Новое короткоживущее соединение: прагмы + ленивая инициализация схемы."""
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.create_function("uclower", 1, _uclower, deterministic=True)
    _ensure_schema(conn, path)
    return conn


def _loads_ids(raw: str | None) -> list[str]:
    try:
        data = json.loads(raw or "[]")
        return [str(x) for x in data] if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


# ---------- Сервисные функции ----------

def ensure_batch(
    job_id: str,
    provider: str,
    model: str,
    contract_subject: str,
    employment_type: str,
    extra_context: str,
) -> int:
    """Возвращает id батча по job_id, создавая запись при первом обращении."""
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO check_batches"
                "(job_id, provider, model, contract_subject, employment_type,"
                " extra_context, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (job_id, provider, model, contract_subject, employment_type,
                 extra_context, _now()),
            )
            conn.commit()
            row = conn.execute(
                "SELECT id FROM check_batches WHERE job_id = ?", (job_id,)
            ).fetchone()
            return int(row["id"])
        finally:
            conn.close()


def save_check_version(
    batch_id: int,
    filename: str,
    file_ext: str,
    file_bytes: bytes,
    text: str,
    text_truncated: bool,
    report: str | None,
    verdict: str | None,
    edits: list[dict],
) -> int:
    """Сохраняет результат проверки: новый документ + версия origin='check' + findings."""
    with _write_lock:
        conn = _connect()
        try:
            now = _now()
            cur = conn.execute(
                "INSERT INTO documents(title, created_at, updated_at) VALUES (?, ?, ?)",
                (Path(filename).stem, now, now),
            )
            document_id = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO versions"
                "(document_id, batch_id, origin, filename, file_ext, file_bytes,"
                " text, text_truncated, report, verdict, created_at)"
                " VALUES (?, ?, 'check', ?, ?, ?, ?, ?, ?, ?, ?)",
                (document_id, batch_id, filename, file_ext, file_bytes or b"",
                 text or "", 1 if text_truncated else 0, report, verdict, now),
            )
            version_id = cur.lastrowid
            for i, edit in enumerate(edits or [], 1):
                conn.execute(
                    "INSERT OR IGNORE INTO findings"
                    "(version_id, edit_id, title, original, replacement, reason)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (version_id,
                     str(edit.get("id") or f"e{i}"),
                     str(edit.get("title") or ""),
                     str(edit.get("original") or ""),
                     str(edit.get("replacement") or ""),
                     str(edit.get("reason") or "")),
                )
            conn.commit()
            return version_id
        finally:
            conn.close()


def save_fixed_version(
    parent_version_id: int,
    docx_bytes: bytes,
    fix_method: str,
    applied_edit_ids: list[str],
    filename: str,
) -> int:
    """Сохраняет исправленную версию (origin='fix'); document/batch наследуются."""
    with _write_lock:
        conn = _connect()
        try:
            parent = conn.execute(
                "SELECT document_id, batch_id FROM versions WHERE id = ?",
                (parent_version_id,),
            ).fetchone()
            if parent is None:
                raise ValueError(f"parent version not found: {parent_version_id}")
            now = _now()
            cur = conn.execute(
                "INSERT INTO versions"
                "(document_id, batch_id, parent_version_id, origin, filename,"
                " file_ext, file_bytes, fix_method, applied_edit_ids, created_at)"
                " VALUES (?, ?, ?, 'fix', ?, '.docx', ?, ?, ?, ?)",
                (parent["document_id"], parent["batch_id"], parent_version_id,
                 filename, docx_bytes or b"", fix_method,
                 json.dumps(list(applied_edit_ids or []), ensure_ascii=False), now),
            )
            version_id = cur.lastrowid
            conn.execute(
                "UPDATE documents SET updated_at = ? WHERE id = ?",
                (now, parent["document_id"]),
            )
            conn.commit()
            return version_id
        finally:
            conn.close()


def list_documents(search: str, limit: int, offset: int) -> tuple[int, list[dict]]:
    """(total, items): сводка по документам, сортировка updated_at desc.

    search — регистронезависимый LIKE по position/department/title (uclower —
    python-функция, чтобы кириллица сравнивалась без регистра).
    """
    where = ""
    params: list[object] = []
    term = (search or "").strip()
    if term:
        like = f"%{term}%"
        where = (
            " WHERE uclower(IFNULL(d.position, '')) LIKE uclower(?)"
            " OR uclower(IFNULL(d.department, '')) LIKE uclower(?)"
            " OR uclower(IFNULL(d.title, '')) LIKE uclower(?)"
        )
        params = [like, like, like]
    conn = _connect()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM documents d{where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT {_SUMMARY_COLUMNS} FROM documents d{where}"
            " ORDER BY d.updated_at DESC, d.id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return int(total), [dict(r) for r in rows]
    finally:
        conn.close()


def document_summary(document_id: int) -> dict | None:
    """Сводка одного документа (те же агрегаты, что в list_documents)."""
    conn = _connect()
    try:
        row = conn.execute(
            f"SELECT {_SUMMARY_COLUMNS} FROM documents d WHERE d.id = ?",
            (document_id,),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def get_document(document_id: int) -> dict | None:
    """Документ + сводка его версий (asc по created_at; без bytes/text/report)."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        if row is None:
            return None
        doc = dict(row)
        vrows = conn.execute(
            "SELECT v.id, v.origin, v.filename, v.file_ext, v.created_at, v.verdict,"
            " v.fix_method, v.applied_edit_ids, v.parent_version_id,"
            " b.job_id AS job_id,"
            " (SELECT COUNT(*) FROM findings f WHERE f.version_id = v.id) AS findings_count"
            " FROM versions v LEFT JOIN check_batches b ON b.id = v.batch_id"
            " WHERE v.document_id = ?"
            " ORDER BY v.created_at ASC, v.id ASC",
            (document_id,),
        ).fetchall()
        versions = []
        for v in vrows:
            item = dict(v)
            item["applied_edit_ids"] = _loads_ids(item.get("applied_edit_ids"))
            versions.append(item)
        doc["versions"] = versions
        return doc
    finally:
        conn.close()


def get_version(version_id: int) -> dict | None:
    """Полная версия: текст, отчёт, findings (без file_bytes)."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT v.*, b.job_id AS job_id"
            " FROM versions v LEFT JOIN check_batches b ON b.id = v.batch_id"
            " WHERE v.id = ?",
            (version_id,),
        ).fetchone()
        if row is None:
            return None
        version = dict(row)
        version.pop("file_bytes", None)
        version["applied_edit_ids"] = _loads_ids(version.get("applied_edit_ids"))
        version["text_truncated"] = bool(version.get("text_truncated"))
        version["findings"] = [
            dict(f)
            for f in conn.execute(
                "SELECT edit_id, title, original, replacement, reason"
                " FROM findings WHERE version_id = ? ORDER BY id",
                (version_id,),
            )
        ]
        return version
    finally:
        conn.close()


def get_version_bytes(version_id: int) -> bytes | None:
    """Байты файла версии; None, если версии нет."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT file_bytes FROM versions WHERE id = ?", (version_id,)
        ).fetchone()
        return None if row is None else bytes(row["file_bytes"] or b"")
    finally:
        conn.close()


def update_document(document_id: int, **fields) -> dict | None:
    """Обновляет метаданные документа (position/department/title/notes)."""
    updates = {
        k: str(v)
        for k, v in fields.items()
        if k in _META_FIELDS and v is not None
    }
    with _write_lock:
        conn = _connect()
        try:
            if updates:
                sets = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE documents SET {sets}, updated_at = ? WHERE id = ?",
                    (*updates.values(), _now(), document_id),
                )
                conn.commit()
            row = conn.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
            return dict(row) if row is not None else None
        finally:
            conn.close()


def delete_document(document_id: int) -> bool:
    """Удаляет документ; версии и findings уходят каскадом."""
    with _write_lock:
        conn = _connect()
        try:
            cur = conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def latest_check_text(document_id: int) -> str | None:
    """Текст последней check-версии документа (для extract-meta); None, если пусто."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT text FROM versions WHERE document_id = ? AND origin = 'check'"
            " ORDER BY id DESC LIMIT 1",
            (document_id,),
        ).fetchone()
        if row is None:
            return None
        return row["text"] or None
    finally:
        conn.close()


def latest_fixed_versions(document_ids: list[int] | None) -> list[tuple[str, bytes, str]]:
    """[(title, bytes, filename)] — последняя fix-версия каждого документа.

    document_ids=None — по всем документам; пустой список — пустой результат.
    """
    query = (
        "SELECT d.title AS document_title, v.file_bytes AS file_bytes,"
        " v.filename AS filename"
        " FROM versions v JOIN documents d ON d.id = v.document_id"
        " WHERE v.origin = 'fix' AND v.id = ("
        "   SELECT MAX(v2.id) FROM versions v2"
        "   WHERE v2.document_id = v.document_id AND v2.origin = 'fix')"
    )
    params: list[object] = []
    if document_ids is not None:
        ids = [int(i) for i in document_ids]
        if not ids:
            return []
        query += f" AND v.document_id IN ({','.join('?' * len(ids))})"
        params = ids
    query += " ORDER BY v.document_id ASC"
    conn = _connect()
    try:
        rows = conn.execute(query, params).fetchall()
        return [
            (r["document_title"] or "", bytes(r["file_bytes"] or b""),
             r["filename"] or "")
            for r in rows
        ]
    finally:
        conn.close()


def document_ids_missing_meta() -> list[int]:
    """id документов с пустыми position И department (для батч-extract-meta)."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id FROM documents"
            " WHERE IFNULL(position, '') = '' AND IFNULL(department, '') = ''"
            " ORDER BY id"
        ).fetchall()
        return [int(r["id"]) for r in rows]
    finally:
        conn.close()


def extract_meta_update(
    document_id: int, position: str, department: str
) -> tuple[str, str] | None:
    """Дописывает должность/подразделение; пустые значения не затирают существующие.

    Возвращает итоговые (position, department) или None, если документа нет.
    """
    with _write_lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT position, department FROM documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            if row is None:
                return None
            new_position = position if position else row["position"]
            new_department = department if department else row["department"]
            if new_position != row["position"] or new_department != row["department"]:
                conn.execute(
                    "UPDATE documents SET position = ?, department = ?, updated_at = ?"
                    " WHERE id = ?",
                    (new_position, new_department, _now(), document_id),
                )
                conn.commit()
            return new_position, new_department
        finally:
            conn.close()


# ---------- Обязанности (для поиска пересечений) ----------

def latest_check_version(document_id: int) -> tuple[int, str] | None:
    """(id, text) последней check-версии; None, если её нет или текст пуст."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, text FROM versions WHERE document_id = ? AND origin = 'check'"
            " ORDER BY id DESC LIMIT 1",
            (document_id,),
        ).fetchone()
        if row is None or not row["text"]:
            return None
        return int(row["id"]), row["text"]
    finally:
        conn.close()


def all_document_ids() -> list[int]:
    """Все id документов по порядку (для overlaps без documentIds)."""
    conn = _connect()
    try:
        rows = conn.execute("SELECT id FROM documents ORDER BY id").fetchall()
        return [int(r["id"]) for r in rows]
    finally:
        conn.close()


def set_duties(document_id: int, duties: list[str], version_id: int) -> None:
    """Сохраняет извлечённые обязанности; пустой список старые не затирает."""
    if not duties:
        return
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE documents SET duties_json = ?, duties_version_id = ?,"
                " duties_extracted_at = ?, updated_at = ? WHERE id = ?",
                (
                    json.dumps(list(duties), ensure_ascii=False),
                    int(version_id),
                    _now(),
                    _now(),
                    document_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()


def get_duties(document_id: int) -> tuple[list[str] | None, int | None, str | None]:
    """(duties | None, version_id, extracted_at); None, если обязанности не извлекались."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT duties_json, duties_version_id, duties_extracted_at"
            " FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None or not row["duties_json"]:
        return None, None, None
    try:
        duties = json.loads(row["duties_json"])
    except json.JSONDecodeError:
        return None, None, None
    if not isinstance(duties, list):
        return None, None, None
    return [str(d) for d in duties], row["duties_version_id"], row["duties_extracted_at"]


# ---------- Отчёты о пересечениях (хранятся последние 5) ----------

OVERLAP_REPORTS_LIMIT = 5


def save_overlap_report(document_ids: list[int], result: dict) -> int:
    """Сохраняет отчёт о пересечениях; более старые сверх лимита удаляются."""
    with _write_lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "INSERT INTO overlap_reports(created_at, document_ids_json, result_json)"
                " VALUES (?, ?, ?)",
                (
                    _now(),
                    json.dumps([int(i) for i in document_ids or []]),
                    json.dumps(result, ensure_ascii=False),
                ),
            )
            report_id = int(cur.lastrowid)
            conn.execute(
                "DELETE FROM overlap_reports WHERE id NOT IN"
                " (SELECT id FROM overlap_reports ORDER BY id DESC LIMIT ?)",
                (OVERLAP_REPORTS_LIMIT,),
            )
            conn.commit()
            return report_id
        finally:
            conn.close()


def latest_overlap_report() -> dict | None:
    """Последний отчёт с распарсенными JSON-полями; None, если отчётов нет."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM overlap_reports ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        try:
            result = json.loads(row["result_json"] or "{}")
        except json.JSONDecodeError:
            result = {}
        try:
            ids = json.loads(row["document_ids_json"] or "[]")
        except json.JSONDecodeError:
            ids = []
        return {
            "id": int(row["id"]),
            "created_at": row["created_at"],
            "document_ids": ids if isinstance(ids, list) else [],
            "result": result if isinstance(result, dict) else {},
        }
    finally:
        conn.close()


# ---------- Шаблон отчёта (report_template.docx в конфиг-каталоге) ----------

def template_path() -> Path:
    """Путь файла шаблона; резолвится при каждом вызове (тесты уводят конфиг)."""
    return Path(settings._CONFIG_DIR) / "report_template.docx"


def save_template(data: bytes) -> None:
    path = template_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def get_template() -> bytes | None:
    """Байты шаблона; None, если файл не загружен."""
    path = template_path()
    if not path.is_file():
        return None
    return path.read_bytes()


def delete_template() -> bool:
    """Удаляет шаблон; отсутствие файла ошибкой не считается."""
    try:
        template_path().unlink()
        return True
    except FileNotFoundError:
        return False


# ---------- Данные последней fix-версии (для шаблонного экспорта) ----------

def latest_fixed_details(document_ids: list[int] | None) -> list[dict]:
    """Данные последней fix-версии каждого документа для сборки из шаблона.

    document_ids=None — по всем документам; пустой список — пустой результат.
    Поля: document_id, position, department, document_title, notes,
    file_bytes, text, filename. Сортировка по document_id.
    """
    query = (
        "SELECT v.document_id AS document_id,"
        " d.position AS position, d.department AS department,"
        " d.title AS document_title, d.notes AS notes,"
        " v.file_bytes AS file_bytes, v.text AS text, v.filename AS filename"
        " FROM versions v JOIN documents d ON d.id = v.document_id"
        " WHERE v.origin = 'fix' AND v.id = ("
        "   SELECT MAX(v2.id) FROM versions v2"
        "   WHERE v2.document_id = v.document_id AND v2.origin = 'fix')"
    )
    params: list[object] = []
    if document_ids is not None:
        ids = [int(i) for i in document_ids]
        if not ids:
            return []
        query += f" AND v.document_id IN ({','.join('?' * len(ids))})"
        params = ids
    query += " ORDER BY v.document_id ASC"
    conn = _connect()
    try:
        rows = conn.execute(query, params).fetchall()
        return [
            {
                "document_id": int(r["document_id"]),
                "position": r["position"] or "",
                "department": r["department"] or "",
                "document_title": r["document_title"] or "",
                "notes": r["notes"] or "",
                "file_bytes": bytes(r["file_bytes"] or b""),
                "text": r["text"] or "",
                "filename": r["filename"] or "",
            }
            for r in rows
        ]
    finally:
        conn.close()
