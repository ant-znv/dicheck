# AGENTS.md

## Проект

DI_Check — локальное веб-приложение для проверки должностных инструкций (ДИ) через LLM API (DeepSeek, z.ai). Запуск — `start.bat` (создаёт venv, ставит зависимости, собирает фронтенд при первом запуске, поднимает сервер на http://127.0.0.1:8787 и открывает браузер).

## Структура

- `backend/app/` — FastAPI-бэкенд (порт 8787):
  - `main.py` — endpoints (контракт: `docs/api-contract.md`), джобы проверок в памяти;
  - `extractors.py` — извлечение текста из .docx/.doc/.pdf/.txt/.md/.odt;
  - `llm.py` — OpenAI-совместимый async-клиент (httpx);
  - `settings.py` — конфиг в `%APPDATA%\DI_Check\config.json`, API-ключи шифруются DPAPI;
  - `logsetup.py` — настройка логирования (`setup_logging`, `build_uvicorn_log_config`): ротируемый файловый лог `%APPDATA%\DI_Check\logs\di_check.log` (5 МБ × 3 копии), консольный хендлер только в dev/console-режиме;
  - `default_prompt.md` — системный промт по умолчанию (первоисточник — методичка `analiz-DI-goskontrakt-v4.docx`, раздел «2. Промт для ИИ»; сам файл в репо не хранится).
- `frontend/` — React 19 + TypeScript + Vite 7 + Tailwind CSS v4; сборка в `frontend/dist`, раздаётся бэкендом как статика.
- `backend/testdata/` — генераторы тестовых ДИ (`make_sample.py`, `make_samples_batch.py`) и сквозной тест `verify_batch.py` (check → export docx → fix-all, нужен запущенный сервер и API-ключ). Сами `.docx`/отчёты в репо не хранятся (`.gitignore`: любые `*.docx` кроме `analiz-DI-goskontrakt-v4.docx`) — при необходимости сгенерировать: `python backend/testdata/make_sample.py`.
- `requirements.txt` — зависимости бэкенда, ставятся в `.venv` в корне; `requirements.lock.txt` — зафиксированные версии (`pip freeze`); `requirements-dev.txt` — pytest и pyinstaller.
- `backend/tests/` — pytest-сьют бэкенда (LLM мокается, сеть/ключи/Word/Tesseract не нужны); запуск из корня проекта.
- `run.py` + `DI_Check.spec` + `build_exe.bat` — портативная сборка (PyInstaller onedir, windowed — консоли в exe нет): exe со встроенными фронтендом и промтом; `build_exe.bat` собирает `dist\DI_Check\` и `DI_Check_portable.zip`. В frozen-режиме ресурсы берутся из `sys._MEIPASS` (см. FRONTEND_DIST в main.py). `run.py` (с версии 0.2.0): GUI-режим по умолчанию — окно pywebview/WebView2, сервер FastAPI в фоновом потоке, закрытие окна останавливает приложение; `--console` — fallback (лог в консоль, браузер открывается сам; `--no-browser` действует только там). Если порт 8787 занят — просто открывается окно к работающему экземпляру. GUI-зависимость: `pywebview>=5.0` (Windows).
- `backend/app/updater.py` — самообновление через GitHub Releases (check/install, внешние вызовы инъецируются); `DI_Check.iss` — установщик Inno Setup (per-user, чистка `_PYI_*`, taskkill без `/T`, `[Run] skipifnotsilent`); `.github/workflows/build.yml` — CI: артефакты на push в main, релиз на тегах `vX.Y.Z`. Релиз: поднять `APP_VERSION` в `backend/app/version.py` (текущая — 0.2.0, оконный режим по умолчанию) → тег `v*` → push.

## Команды

- Запуск всего: `start.bat`
- Окно приложения, как в exe (GUI-режим `run.py`): `.venv/Scripts/python.exe run.py` (флаги `--port`, `--console`, `--no-browser`)
- Бэкенд вручную (console-режим, лог в консоль): `.venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8787`
- Тесты бэкенда: `.venv/Scripts/python.exe -X utf8 -m pytest backend/tests -q`
- Фронтенд dev (прокси на 8787): `cd frontend && npm run dev`
- Фронтенд сборка: `cd frontend && npm run build`
- Сборка портативного exe: `build_exe.bat` (или `.venv/Scripts/python.exe -m PyInstaller --noconfirm --clean DI_Check.spec`)
- Python в консоли Windows: вывод русского текста только в файл с `encoding='utf-8'` (консоль cp1251 падает на `print`); либо `python -X utf8`.

## Правила

- Зависимости только в `.venv` и `frontend/node_modules`; ничего не ставить глобально и вне рабочей директории.
- API-контракт фронтенд↔бэкенд — `docs/api-contract.md`; при изменении API обновлять его.
- API-ключи никогда не возвращать через API наружу — только флаг `hasApiKey`.

## Git

- Git-репозиторий — корень проекта. Все git-команды выполнять только внутри него.
- Hazard: git из родительских директорий (выше корня проекта) может резолвиться на посторонний репозиторий, который видит весь диск как untracked. Никогда не запускать `git add`/`git commit`/`git clean` за пределами проекта.
