# AGENTS.md

## Проект

DI_Check — локальное веб-приложение для проверки должностных инструкций (ДИ) через LLM API (DeepSeek, z.ai). Запуск — `start.bat` (создаёт venv, ставит зависимости, собирает фронтенд при первом запуске, поднимает сервер на http://127.0.0.1:8787 и открывает браузер).

## Структура

- `backend/app/` — FastAPI-бэкенд (порт 8787):
  - `main.py` — endpoints (контракт: `docs/api-contract.md`), джобы проверок в памяти;
  - `extractors.py` — извлечение текста из .docx/.doc/.pdf/.txt/.md/.odt;
  - `llm.py` — OpenAI-совместимый async-клиент (httpx);
  - `settings.py` — конфиг в `%APPDATA%\DI_Check\config.json`, API-ключи шифруются DPAPI;
  - `default_prompt.md` — системный промт по умолчанию (из `analiz-DI-goskontrakt-v4.docx`, раздел «2. Промт для ИИ»).
- `frontend/` — React 19 + TypeScript + Vite 7 + Tailwind CSS v4; сборка в `frontend/dist`, раздаётся бэкендом как статика.
- `backend/testdata/` — тестовые ДИ (`sample_di.docx`, генератор `make_sample.py`; доп. вариации — `make_samples_batch.py`), примеры отчётов, сквозной тест `verify_batch.py` (check → export docx → fix-all, нужен запущенный сервер и API-ключ).
- `requirements.txt` — зависимости бэкенда, ставятся в `.venv` в корне; `requirements.lock.txt` — зафиксированные версии (`pip freeze`).
- `backend/tests/` — pytest-сьют бэкенда (LLM мокается, сеть/ключи/Word/Tesseract не нужны); запуск из корня проекта.

## Команды

- Запуск всего: `start.bat`
- Бэкенд вручную: `.venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8787`
- Тесты бэкенда: `.venv/Scripts/python.exe -X utf8 -m pytest backend/tests -q`
- Фронтенд dev (прокси на 8787): `cd frontend && npm run dev`
- Фронтенд сборка: `cd frontend && npm run build`
- Python в консоли Windows: вывод русского текста только в файл с `encoding='utf-8'` (консоль cp1251 падает на `print`); либо `python -X utf8`.

## Правила

- Зависимости только в `.venv` и `frontend/node_modules`; ничего не ставить глобально и вне рабочей директории.
- API-контракт фронтенд↔бэкенд — `docs/api-contract.md`; при изменении API обновлять его.
- API-ключи никогда не возвращать через API наружу — только флаг `hasApiKey`.

## Git

- Git-репозиторий — корень проекта `` (инициализирован 2026-09-06). Все git-команды выполнять только внутри него.
- Hazard: git из родительских директорий (например, из корня `C:\`) резолвится на stray-репо, который видит весь диск как untracked. Никогда не запускать `git add`/`git commit`/`git clean` за пределами проекта.
