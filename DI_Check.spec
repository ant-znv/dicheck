# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: портативная сборка DI_Check (onedir, консольное окно с логом).

Сборка: .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean DI_Check.spec
Результат: dist/DI_Check/ (DI_Check.exe + _internal).
"""

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("frontend/dist", "frontend/dist"),
        ("backend/app/default_prompt.md", "backend/app"),
    ],
    hiddenimports=[
        # uvicorn: динамические импорты цикла событий / протоколов / lifespan
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
        # python-multipart (разбор форм; имя модуля зависит от версии)
        "multipart",
        "python_multipart",
        # ленивые импорты экстракторов (OCR-фолбэк)
        "fitz",
        "pymupdf",
        "pytesseract",
        "PIL",
        # pywin32: чтение старых .doc через Word COM
        "win32timezone",
    ],
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DI_Check",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon="resources/app.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DI_Check",
)
