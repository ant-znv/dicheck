"""Извлечение текста из файлов ДИ: .docx, .pdf, .txt/.md, .odt, .doc."""
from __future__ import annotations

import io
import re
import tempfile
from pathlib import Path

SUPPORTED_EXTENSIONS = {".docx", ".doc", ".pdf", ".txt", ".md", ".odt"}


class ExtractionError(Exception):
    """Ошибка извлечения текста из файла."""


def extract_text(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".docx":
        return _from_docx(data)
    if ext == ".pdf":
        return _from_pdf(data)
    if ext in (".txt", ".md"):
        return _from_text(data)
    if ext == ".odt":
        return _from_odt(data)
    if ext == ".doc":
        return _from_doc(data)
    raise ExtractionError(f"Неподдерживаемый формат файла: {ext or filename}")


def _from_docx(data: bytes) -> str:
    try:
        from docx import Document

        doc = Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        text = "\n".join(parts).strip()
    except Exception as e:
        raise ExtractionError(f"Не удалось прочитать .docx: {e}")
    if not text:
        raise ExtractionError("Файл .docx не содержит текста")
    return text


def _from_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as e:
        raise ExtractionError(f"Не удалось прочитать .pdf: {e}")
    if not text:
        raise ExtractionError(
            "Не удалось извлечь текст из .pdf (возможно, это скан — нужен OCR)"
        )
    return text


def _from_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1251"):
        try:
            text = data.decode(encoding).strip()
            if text:
                return text
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ExtractionError("Не удалось определить кодировку текстового файла")


def _from_odt(data: bytes) -> str:
    try:
        from odf.opendocument import load
        from odf import teletype, text as odftext

        doc = load(io.BytesIO(data))
        parts = []
        for elem in doc.getElementsByType(odftext.P) + doc.getElementsByType(
            odftext.H
        ):
            parts.append(teletype.extractText(elem))
        text = "\n".join(parts).strip()
    except Exception as e:
        raise ExtractionError(f"Не удалось прочитать .odt: {e}")
    if not text:
        raise ExtractionError("Файл .odt не содержит текста")
    return text


def _from_doc(data: bytes) -> str:
    """Старый бинарный .doc — через Word COM (pywin32)."""
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        raise ExtractionError(
            "pywin32 недоступен — сконвертируйте файл .doc в .docx и загрузите снова"
        )

    tmp_dir = Path(tempfile.mkdtemp(prefix="di_check_doc_"))
    src = tmp_dir / "input.doc"
    dst = tmp_dir / "output.txt"
    src.write_bytes(data)

    word = None
    try:
        pythoncom.CoInitialize()
        try:
            word = win32com.client.DispatchEx("Word.Application")
        except Exception as e:
            raise ExtractionError(
                "Не удалось запустить Microsoft Word для чтения .doc "
                f"({e}). Сконвертируйте файл в .docx и загрузите снова"
            )
        word.Visible = False
        word.DisplayAlerts = 0
        try:
            doc = word.Documents.Open(
                str(src), ReadOnly=True, ConfirmConversions=False,
                AddToRecentFiles=False, Visible=False,
            )
        except Exception as e:
            raise ExtractionError(
                f"Word не смог открыть .doc ({e}). Сконвертируйте файл в .docx"
            )
        try:
            doc.SaveAs2(str(dst), FileFormat=7)  # wdFormatUnicodeText
        finally:
            doc.Close(False)
        text = dst.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            raise ExtractionError("Файл .doc не содержит текста")
        return text
    finally:
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
        for p in (src, dst):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            tmp_dir.rmdir()
        except OSError:
            pass
