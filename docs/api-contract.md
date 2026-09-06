# API Contract — DI_Check

Бэкенд: FastAPI на `http://127.0.0.1:8787`. Все пути под `/api`.
Фронтенд в проде отдаётся бэкендом как статика (`frontend/dist`), в деве — Vite dev server с прокси на 8787.

## Модели данных

```jsonc
// ProviderDescriptor
{
  "id": "deepseek" | "zai",
  "name": "DeepSeek" | "z.ai (GLM)",
  "baseUrl": "https://api.deepseek.com",   // OpenAI-совместимый endpoint
  "defaultModels": ["deepseek-chat", "deepseek-reasoner"], // подсказки для combobox
  "hasApiKey": true                          // ключ сохранён (сам ключ никогда не отдаём)
}

// Settings (GET /api/settings)
{
  "providers": [ProviderDescriptor],
  "activeProvider": "deepseek",
  "activeModel": "deepseek-chat",
  "systemPrompt": "…",                       // текущий системный промт (редактируемый)
  "defaultSystemPrompt": "…"                 // промт по умолчанию (для кнопки «сбросить»)
}
```

## Endpoints

### GET /api/settings
Возвращает `Settings`. При первом запуске активный провайдер — `deepseek`, промт — по умолчанию. API-ключи задаются пользователем в настройках и хранятся зашифрованными в `%APPDATA%` (в репозитории ключей нет).

### PUT /api/settings
Body: `{ "activeProvider"?, "activeModel"?, "systemPrompt"? }` → возвращает обновлённый `Settings`.

### PUT /api/settings/apikey
Body: `{ "provider": "deepseek"|"zai", "apiKey": "sk-..." }` — сохраняет ключ зашифрованным (DPAPI) в `%APPDATA%\DI_Check\config.json`. Пустая строка — удалить ключ. Ответ: `{ "ok": true, "hasApiKey": true }`.

### POST /api/settings/test
Body: `{ "provider": "deepseek"|"zai", "model"?: string }` — проверяет соединение: дёргает `GET {baseUrl}/models` (или минимальный chat completion). Ответ: `{ "ok": true, "models": ["..."] }` или `{ "ok": false, "error": "..." }`. Используется кнопкой «Проверить соединение» и для подгрузки списка моделей.

### POST /api/check
`multipart/form-data`: поле `files` — один или несколько файлов (`.docx`, `.doc`, `.pdf`, `.txt`, `.md`, `.odt`); опциональные текстовые поля: `contractSubject` (предмет госконтракта), `employmentType` (`full`|`partial`|``), `extraContext` (требования к персоналу и т.п.).
Создаёт джоб, запускает проверки в фоне (по файлам — параллельно, разумный лимит конкурентности). Ответ: `{ "jobId": "..." }`.
Ошибки: 400 — неподдерживаемый формат / пустой файл; 409 — нет API-ключа у активного провайдера (в ответе `{"detail": "no_api_key"}`).

### GET /api/jobs/{jobId}
```jsonc
{
  "id": "...",
  "status": "running" | "done" | "error",
  "results": [
    {
      "filename": "instr.docx",
      "status": "pending" | "running" | "done" | "error",
      "error": null | "…",
      "report": null | "…markdown-отчёт от модели…",
      "summaryVerdict": null | "ok" | "risk" | "fail",   // грубая выжимка из отчёта для сводной таблицы
      "edits": [                       // структурированные правки (может быть пустым)
        {
          "id": "e1",
          "title": "Краткое название правки",
          "original": "дословная цитата из ДИ (или описание места, если фрагмента нет)",
          "replacement": "готовая формулировка для вставки",
          "reason": "почему нужна правка (норма/риск)"
        }
      ]
    }
  ]
}
```
Фронтенд поллит раз в 1–2 сек.

Как получаются `edits`: бэкенд дописывает к системному промту фиксированную (не редактируемую пользователем) инструкцию — в конце ответа вывести fenced-блок ` ```json ` вида `{"edits": [...]}`. Бэкенд парсит его (последний fenced-блок / brace-matching), убирает блок из `report` (в UI он не показывается) и кладёт массив в `edits`. Если парсинг не удался — `edits: []`, отчёт остаётся как есть. Исходный извлечённый текст файла хранится в джобе (в памяти, наружу не отдаётся) — нужен для `/fix`.

### POST /api/jobs/{jobId}/fix
Body: `{ "resultIndex": 0, "editIds": ["e1", "e3"] }` — применить выбранные правки к исходной ДИ.
Бэкенд делает второй LLM-вызов: исходный текст ДИ + список выбранных правок (original → replacement) → модель возвращает полный исправленный текст документа. Из него генерируется `.docx` (python-docx; простое форматирование: заголовки, абзацы, списки).
Ответ: 200, `Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document`, `Content-Disposition: attachment; filename="<имя>_исправленная.docx"`.
Ошибки: 404 — нет джобы/результата; 400 — пустой `editIds` или нет исходного текста; 502 — ошибка LLM (`{"detail": "..."}`).

### GET /api/jobs/{jobId}/export?format=md|html
Возвращает файл со сводным отчётом по всем результатам джобы (`Content-Disposition: attachment`).

## Хранение настроек

`%APPDATA%\DI_Check\config.json` (вне репозитория). API-ключи — зашифрованы Windows DPAPI (CryptProtectData, текущий пользователь), в файле — base64. Остальное — plaintext JSON. Ключ из файла никогда не возвращается через API — только флаг `hasApiKey`.

## LLM-вызов

OpenAI-совместимый `POST {baseUrl}/chat/completions`, `httpx` async, таймаут ~300 с. Текст файла подставляется в user-message вместе с входными полями (предмет контракта, занятость и т.д.). Возвращается markdown-отчёт модели как есть.
