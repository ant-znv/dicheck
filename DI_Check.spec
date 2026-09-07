# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: портативная сборка DI_Check (onedir, консольное окно с логом).

Сборка: .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean DI_Check.spec
Результат: dist/DI_Check/ (DI_Check.exe + _internal).
"""

from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("frontend/dist", "frontend/dist"),
        ("backend/app/default_prompt.md", "backend/app"),
    ],
    hiddenimports=[
        # uvicorn: loop/protocol/lifespan грузятся динамически — берём всё
        *collect_submodules("uvicorn"),
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
        # окно приложения (pywebview/WebView2 через pythonnet)
        "webview",
        "webview.platforms.edgechromium",
        "webview.platforms.winforms",
        "clr",
        "clr_loader",
        "pythonnet",
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
    # окно приложения без консоли; логи — в %APPDATA%\DI_Check\logs
    console=False,
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
