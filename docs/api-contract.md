# API Contract — DI_Check

Бэкенд: FastAPI на `http://127.0.0.1:8787`. Все пути под `/api`.
Фронтенд в проде отдаётся бэкендом как статика (`frontend/dist`), в деве — Vite dev server с прокси на 8787.

## Ограничения и время жизни джоб

- Максимум **20 файлов** на проверку, **20 МБ** на файл, иначе 400 (`too_many_files: N (максимум 20)`, `file_too_large: <имя> (максимум 20 МБ)`).
- Извлечённый текст длиннее **120 000 символов** обрезается; у результата ставится `textTruncated: true`.
- Джобы живут в памяти: завершённые — до **24 ч** или пока не наберётся **50 джоб** (выгрузка самых старых; активные не выгружаются). После перезапуска сервера джобы недоступны — фронтенд при 404 тихо сбрасывает сохранённый jobId.
- Все обращения к LLM ретраятся (до 3 попыток) на 429/5xx, сетевых ошибках и таймаутах, с backoff (или по `Retry-After` провайдера).
- Бэкенд пишет информационный лог (запуск/завершение джоб, длительность проверок, ошибки LLM, отмена, выгрузка джоб).

## Доступ (middleware)

Все `/api`-пути проходят middleware: запрос с `Origin` не из loopback (`127.0.0.1`/`localhost`) отклоняется с 403 `forbidden_origin`, запрос с `Host` не из loopback — с 403 `forbidden_host`. Сервер слушает только `127.0.0.1`, поэтому для штатного фронтенда (тот же host) это прозрачно.

## Модели данных

```jsonc
// ProviderDescriptor
{
  "id": "deepseek" | "zai",
  "name": "DeepSeek" | "z.ai (GLM)",
  "baseUrl": "https://api.deepseek.com",   // OpenAI-совместимый endpoint
  "defaultModels": ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"], // подсказки для combobox (у z.ai — ["glm-4.6", "glm-4.5", "glm-4.5-air"])
  "hasApiKey": true                          // ключ сохранён (сам ключ никогда не отдаём)
}

// Settings (GET /api/settings)
{
  "providers": [ProviderDescriptor],
  "activeProvider": "deepseek",
  "activeModel": "deepseek-chat",
  "systemPrompt": "…",                       // текущий системный промт (редактируемый)
  "defaultSystemPrompt": "…",                // промт по умолчанию (для кнопки «сбросить»)
  "version": "0.1.0",                        // версия приложения (backend/app/version.py)
  "update": { "repo": "ant-znv/dicheck", "hasToken": false }  // настройки самообновления
}
```

## Endpoints

### GET /api/settings
Возвращает `Settings`. При первом запуске активный провайдер — `deepseek`, промт — по умолчанию. API-ключи задаются пользователем в настройках и хранятся зашифрованными в `%APPDATA%` (в репозитории ключей нет).

### PUT /api/settings
Body: `{ "activeProvider"?, "activeModel"?, "systemPrompt"?, "updateRepo"? }` → возвращает обновлённый `Settings`. `updateRepo` — репозиторий самообновления в формате `owner/repo`.

### PUT /api/settings/update-token
Body: `{ "token": "ghp_..." }` — токен GitHub (нужен только для приватного репозитория обновлений), хранится зашифрованным (DPAPI). Пустая строка — удалить. Ответ: `{ "ok": true, "hasToken": true }`.

### GET /api/update/check
Проверка обновлений через GitHub Releases (`/releases/latest`, публичный — без токена, приватный — с сохранённым токеном). Никогда не падает: `{"current": "0.1.0", "latest": "v0.2.0", "updateAvailable": true, "error": null}` либо `{"current": "...", "latest": null, "updateAvailable": false, "error": "описание"}` (404 приватного репо/нет сети/не задан репозиторий — это ошибки-состояния, не исключения). Сравнение версий — семверное (тег `v`-префикс и `-суффикс` отрезаются).

### POST /api/update/install
Скачать установщик последнего релиза (asset с точным именем `DI_Check_setup.exe`) в `%TEMP%`, проверить sha256 (если GitHub отдал `digest`), запустить `setup /SILENT` в фоне без ожидания: установщик сам остановит приложение, обновит файлы и запустит новую версию (в установщике чистятся `_PYI_*`-переменные PyInstaller, делается `taskkill` приложения без `/T` и очистка `{app}\_internal`). Ответ: `{"ok": true, "version": "v0.2.0", "path": "%TEMP%\\di-check-setup-v0.2.2.exe"}` (имя файла — `sanitize_tag(тег)`, точки версии сохраняются). Ошибки: 502 — `{detail}` (нет обновления, нет asset, не совпал sha256, сетевая ошибка и т.п.); для портативной сборки (нет `unins000.exe` рядом с exe) — 502 с подсказкой скачать новый ZIP со страницы релизов (`https://github.com/<repo>/releases`) и заменить папку вручную.

### PUT /api/settings/apikey
Body: `{ "provider": "deepseek"|"zai", "apiKey": "sk-..." }` — сохраняет ключ зашифрованным (DPAPI) в `%APPDATA%\DI_Check\config.json`. Пустая строка — удалить ключ. Ответ: `{ "ok": true, "hasApiKey": true }`.

### POST /api/settings/test
Body: `{ "provider": "deepseek"|"zai", "model"?: string }` — проверяет соединение: дёргает `GET {baseUrl}/models` (или минимальный chat completion). Ответ: `{ "ok": true, "models": ["..."] }` или `{ "ok": false, "error": "..." }`. Используется кнопкой «Проверить соединение» и для подгрузки списка моделей.

### POST /api/check
`multipart/form-data`: поле `files` — один или несколько файлов (`.docx`, `.doc`, `.pdf`, `.txt`, `.md`, `.odt`); опциональные текстовые поля: `contractSubject` (предмет госконтракта), `employmentType` (`full`|`partial`|``), `extraContext` (требования к персоналу и т.п.).
Создаёт джоб, запускает проверки в фоне (по файлам — параллельно, семафор на 3). Ответ: `{ "jobId": "..." }`.
Ошибки: 400 — `invalid_file_format: <имя>` (содержимое не совпадает с форматом расширения) / пустой файл / `too_many_files: N (максимум 20)` / `file_too_large: <имя> (максимум 20 МБ)`; 409 — нет API-ключа у активного провайдера (`{"detail": "no_api_key"}`).

### GET /api/jobs/{jobId}
```jsonc
{
  "id": "...",
  "status": "running" | "done" | "error" | "cancelled",
  // "error" — все файлы завершились ошибкой; "cancelled" — проверка отменена пользователем
  "results": [
    {
      "filename": "instr.docx",
      "status": "pending" | "running" | "done" | "error" | "cancelled",
      "error": null | "…",
      "report": null | "…markdown-отчёт от модели…",
      "summaryVerdict": null | "ok" | "risk" | "fail",   // из structured-блока модели, fallback — эвристика по тексту отчёта
      "textTruncated": false,          // true, если текст ДИ обрезан лимитом 120 000 символов
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
Фронтенд поллит раз в 1.5 с; одиночные сбои сети переживает (сдаётся после 3 подряд).

Как получаются `edits` и `summaryVerdict`: бэкенд дописывает к системному промту фиксированную (не редактируемую пользователем) инструкцию — в конце ответа вывести fenced-блок ` ```json ` вида `{"verdict": "ok"|"risk"|"fail", "edits": [...]}`. Бэкенд парсит его (последний fenced-блок / brace-matching), убирает блок из `report`, кладёт массив в `edits`, а `verdict` — в `summaryVerdict` (если модель вердикт не отдала — эвристика по подстрокам «не соответствует»/«риск»). Если парсинг не удался — `edits: []`, отчёт остаётся как есть. Исходный извлечённый текст файла (`_texts`) и байты исходного файла (`_files`) хранятся в джобе (в памяти, наружу не отдаются) — нужны для `/fix`.

Починка таблиц: модель иногда выдаёт markdown-таблицу, склеенную в одну строку — рендерер показывает её сплошным текстом. После получения отчёта бэкенд пересобирает такие таблицы (поток ячеек делится серией `---`-разделителей; однозначные случаи чинятся, сомнительные не трогаются). Таблицы из отчёта рендерятся в UI (GFM) и как настоящие таблицы в docx-экспорте (шапка полужирная, стиль Table Grid).

### POST /api/jobs/{jobId}/cancel
Отменяет выполняющуюся проверку. Файлы «в работе» прерываются (статус `cancelled`), ожидающие тоже получают `cancelled`; джоба переходит в `status: "cancelled"`. Для завершённой джобы — идемпотентно: `{"ok": true, "status": "<текущий>"}`. Ошибки: 404 — нет джобы. Фронтенд показывает кнопку «Отменить», пока `status === "running"`.

### POST /api/jobs/{jobId}/fix
Body: `{ "resultIndex": 0, "editIds": ["e1", "e3"] }` — применить выбранные правки к исходной ДИ.

Применение двухступенчатое:
1. **Детерминированно, без LLM** — правки, чей `original` является дословной уникальной цитатой исходного текста. Для исходного `.docx` замена делается прямо в документе на уровне runs (сохраняется исходное форматирование, включая таблицы и колонтитулы); для остальных форматов — пересборка `.docx` из обновлённого текста.
2. **LLM-фолбэк** — оставшиеся правки (вставки без дословной цитаты, цитаты не найдены/не уникальны): исходный (уже обновлённый) текст + список правок → модель возвращает полный исправленный текст → генерируется `.docx` (python-docx; заголовки, абзацы, списки).

Ответ: 200, `Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document`, `Content-Disposition: attachment; filename="<имя>_исправленная.docx"`.
Ошибки: 404 — нет джобы/результата; 400 — пустой `editIds`, нет исходного текста, неизвестные editIds; 410 — `payload_expired`, если исходные байты файла уже выгружены из памяти (спустя ~1 ч после завершения проверки — нужно запустить проверку заново); 502 — ошибка LLM (`{"detail": "..."}`).

### GET /api/jobs/{jobId}/export?format=md|html|docx
Возвращает файл со сводным отчётом по всем результатам джобы (`Content-Disposition: attachment`). Отменённые файлы помечены «Проверка отменена».
`format=docx` — единый `.docx` (`di_check_<jobId>.docx`): титульный блок (дата, число файлов), сводная таблица (файл / вердикт / число правок / статус), затем по каждому файлу с done-статусом: заголовок с именем файла, отчёт (markdown→docx по тем же правилам, что в /fix), список правок (title, reason, «Было»/«Будет»).

### POST /api/jobs/{jobId}/fix-all
Body: `{ "items": [{ "resultIndex": 0, "editIds": ["e1", "e2"] }, ...] }` — пакетное исправление: для каждого item та же логика, что /fix (детерминированно + LLM-фолбэк). Исполнение параллельно (семафор, как в /check).
Ответ: 200, `Content-Type: application/zip`, `Content-Disposition: attachment; filename="ispravlennye_di.zip"`. В архиве: `<имя>_исправленная.docx` для каждого успешного item; если были неудачи — дополнительно `_errors.txt` со списком «файл: причина».
Ошибки уровня запроса: 404 — нет джобы; 400 — пустой `items` или resultIndex вне диапазона; 410 — `payload_expired`, если исходные байты хотя бы одного файла уже выгружены из памяти (~1 ч после завершения проверки); 502 — если не удалось исправить ни одного файла.

## История проверок

Каждая проверка сохраняется автоматически (без участия фронтенда) в локальную SQLite-БД `%APPDATA%\DI_Check\history.db`: документ (метаданные), версии (`origin: "check"` — исходная проверка с байтами исходного файла, текстом и отчётом; `origin: "fix"` — исправленный .docx) и замечания (findings — те же правки, что в `edits` результата джобы). Ошибка БД никогда не ломает проверку/фикс — только запись в лог. Данные переживают перезапуск сервера; удаляются вместе с `%APPDATA%\DI_Check`. Извлечённые обязанности хранятся прямо в документе (для поиска пересечений, с id версии-источника как ключом кэша), отчёты о пересечениях — в таблице последних 5 отчётов. БД, созданная предыдущими версиями приложения, при первом запуске автоматически получает новые поля (миграция без потери данных).

Модели данных (camelCase; даты — UTC ISO8601-строки как лежат в БД):

```jsonc
// DocumentSummary (элемент списка и ответ PATCH)
{
  "id": 1,
  "title": "instr",                       // имя файла первой check-версии без расширения
  "position": "", "department": "", "notes": "",   // редактируемые метаданные
  "createdAt": "2026-09-07T09:00:00.000+00:00",
  "updatedAt": "…",                       // обновляется при добавлении версии/правке метаданных
  "versionsCount": 2, "fixedCount": 1,
  "lastCheck": {                          // последняя check-версия или null
    "verdict": "risk" | "ok" | "fail" | null,
    "checkedAt": "…",
    "findingsCount": 3
  }
}

// VersionSummary (элемент versions в детализации документа)
{
  "id": 7,
  "origin": "check" | "fix",
  "filename": "instr.docx",               // у fix — "<stem>_исправленная.docx"
  "createdAt": "…",
  "verdict": "risk" | null,               // осмыслен только у check
  "findingsCount": 3,
  "fixMethod": null | "docx" | "text" | "llm",  // только у fix (как /fix)
  "appliedEditIds": ["e1"],               // только у fix
  "parentVersionId": null | 5,            // у fix — id check-версии-родителя
  "jobId": "abc123"                       // jobId джобы, из которой получена версия
}

// VersionDetail (GET /api/history/versions/{id}) = VersionSummary плюс:
{
  "documentId": 1,
  "text": "…",                            // извлечённый текст (у fix — пустая строка)
  "textTruncated": false,
  "report": "…markdown-отчёт…",           // у fix — null
  "findings": [                           // только у check
    { "editId": "e1", "title": "…", "original": "…", "replacement": "…", "reason": "…" }
  ]
}
```

### GET /api/history/documents?search=&limit=100&offset=0
`{"total": N, "items": [DocumentSummary]}`, сортировка по `updatedAt` по убыванию. `search` — регистронезависимый (включая кириллицу) LIKE по position/department/title. Валидация: `limit` 1..500 (иначе 400 `invalid_limit`), `offset` ≥ 0 (иначе 400 `invalid_offset`).

### GET /api/history/documents/{id}
200 — поля документа (`id`, `title`, `position`, `department`, `notes`, `createdAt`, `updatedAt`) + `"versions": [VersionSummary]` (по возрастанию `createdAt`; без bytes/text/report). 404 — `document_not_found`.

### PATCH /api/history/documents/{id}
Body: `{ "position"?, "department"?, "title"?, "notes"? }` — обновляются только переданные поля. 200 — обновлённый `DocumentSummary` (с агрегатами); 404 — `document_not_found`.

### DELETE /api/history/documents/{id}
200 — `{"ok": true}`; версии и замечания удаляются каскадом. 404 — `document_not_found`.

### GET /api/history/versions/{id}
200 — `VersionDetail`; 404 — `version_not_found`.

### GET /api/history/versions/{id}/download
Байты сохранённого файла: у check — исходный загруженный файл (любого поддерживаемого формата), у fix — исправленный .docx. `Content-Disposition: attachment; filename*=UTF-8''…`, media_type по расширению (docx/pdf/odt/doc/txt/md). 404 — `version_not_found`; 404 — `no_file_data`, если байты не сохранились (пустые).

### POST /api/history/documents/{id}/extract-meta
Заполнение должности/подразделения одним LLM-вызовом: в модель уходят первые 6000 символов текста последней check-версии; ответ — JSON `{"position": "…", "department": "…"}` (парсится json.loads с fallback на brace-matching; не-словарь/не-строки — ошибка). Сохраняются только непустые значения — пустые не затирают существующие.
200 — `{"position": "…", "department": "…"}` (итоговые значения после слияния); 404 — `document_not_found`; 409 — `no_text` (нет check-версии или её текст пуст); 502 — ошибка LLM или `{"detail": "invalid_meta_response"}`.

### POST /api/history/extract-meta
Пакетное извлечение: body `{ "documentIds": [1,2] | null }`; `null`/отсутствие — все документы с пустыми position И department. Обработка параллельно, до 2 одновременно; ошибка одного документа не прерывает остальные. 200 — `{"results": [{ "documentId": 1, "position": "…", "department": "…", "error": null | "код или текст ошибки" }]}` (при ошибке position/department — пустые строки; коды ошибок те же: `document_not_found`, `no_text`, `invalid_meta_response`, текст ошибки LLM).

### POST /api/history/documents/{id}/extract-duties
Извлечение списка обязанностей одним LLM-вызовом: в модель уходят первые 60 000 символов текста последней check-версии; ответ — JSON `{"duties": ["…", …]}` (парсится json.loads с fallback на brace-matching; не-словарь/не-список/пустой список — ошибка `invalid_duties_response`). Результат нормализуется: пустые строки отбрасываются, cap 40 пунктов, каждый — до 300 символов; сохраняется в документ вместе с id check-версии, из которой извлечён (используется как ключ кэша для пересечений).
200 — `{"documentId": 1, "count": 12, "duties": ["…", …]}`; 404 — `document_not_found`; 409 — `no_text` (нет check-версии или её текст пуст); 502 — текст ошибки LLM или `{"detail": "invalid_duties_response"}`.

### POST /api/history/overlaps
Поиск пересечений обязанностей между РАЗНЫМИ подразделениями. Body: `{ "documentIds": [1,2] | null }`; `null`/отсутствие — все документы истории (пустая БД или пустой список → 400 `no_documents`). Для каждого документа гарантируются обязанности: если извлекались ранее из актуальной check-версии — берётся кэш, иначе LLM-извлечение (параллельно, до 2 одновременно). Несуществующие id и документы, для которых обязанности получить не удалось, не прерывают запрос, а попадают в `skipped` (коды: `document_not_found`, `no_text`, `«извлечение не удалось: <текст>»`). Документы с обязанностями сравниваются чанками по ≤8 (один LLM-вызов на чанк); из ответа модели остаются только группы с ≥2 обязанностями из РАЗНЫХ подразделений и documentId строго из запроса. Отчёт сохраняется (в БД хранятся последние 5).
200 — `{"id": 3, "createdAt": "…", "documents": [...], "groups": [...], "skipped": [...]}`:
```jsonc
{
  "id": 3, "createdAt": "2026-09-07T09:00:00.000+00:00",
  "documents": [   // успешно проанализированные документы, в порядке запроса
    { "documentId": 1, "position": "Сторож", "department": "Служба охраны", "dutiesCount": 12 }
  ],
  "groups": [
    {
      "duty": "суть пересечения одной фразой",
      "comment": "кратко почему это проблема/что уточнить",
      "items": [   // position/department подставлены из БД по documentId
        { "documentId": 1, "position": "Сторож", "department": "Служба охраны", "duty": "формулировка из документа" }
      ]
    }
  ],
  "skipped": [
    { "documentId": 7, "position": "", "department": "", "error": "no_text" }
  ]
}
```

### GET /api/history/overlaps
Последний сохранённый отчёт (та же форма, что у POST). 404 — `no_report` (отчётов ещё нет).

### PUT /api/history/template
Загрузка шаблона отчёта для экспорта исправленных ДИ. Тело запроса — сырые байты `.docx` (`Content-Type: application/octet-stream`). Шаблон — обычный документ с плейсхолдерами `{{КЛЮЧ}}`: `ДОЛЖНОСТЬ`, `ПОДРАЗДЕЛЕНИЕ`, `НАЗВАНИЕ`, `ТЕКСТ` (место вставки содержимого исправленного ДИ), `ДАТА` (текущая дата ДД.ММ.ГГГГ), `ЗАМЕТКИ`. Плейсхолдеры работают в абзацах тела и в таблицах; при сборке форматирование абзаца сохраняется. Файл сохраняется в `%APPDATA%\DI_Check\report_template.docx`.
200 — `{"ok": true, "size": 35352, "keys": ["ДОЛЖНОСТЬ", "ТЕКСТ", …]}` — какие из TEMPLATE_KEYS найдены в шаблоне (в порядке TEMPLATE_KEYS). 400 — `invalid_template` (это не .docx: нет zip-магии или python-docx не открывает).

### GET /api/history/template
200 — `{"exists": false}` либо `{"exists": true, "size": N, "keys": [...]}` (те же ключи, что в PUT).

### DELETE /api/history/template
200 — `{"ok": true}` (идемпотентно — отсутствие шаблона ошибкой не считается).

### GET /api/history/export/fixed?documentIds=1,2&template=false
ZIP-архив с последней fix-версией каждого документа (без параметра — всех). Имена в архиве — `filename` версии; коллизии получают суффикс `_2.docx` (как в /fix-all). `Content-Disposition: attachment; filename="ispravlennye_di.zip"`, media `application/zip`. 404 — `no_fixed_files` (fix-версий нет); 400 — `invalid_document_ids` (нецелые id).

С параметром `template=true` каждый .docx детерминированно (без LLM) пересобирается из загруженного шаблона: простые ключи заменяются метаданными документа, на место `{{ТЕКСТ}}` вставляется содержимое исправленного файла (со всем его форматированием). Имена в архиве — `f"{position или title}_исправленная.docx"` (запрещённые в Windows символы имени заменяются на `_`, коллизии — суффикс `_2.docx`). Ошибки: 409 — `no_template` (шаблон не загружен); 404 — `no_fixed_files`.

## Поведение фронтенда

- Выбор файла-отчёта и правок keyed по `resultIndex` (не по имени файла) — дубликаты имён не ломают UI.
- jobId последней проверки хранится в `localStorage` (`di_check_job_id`); после перезагрузки страницы джоба восстанавливается, если ещё жива на сервере.
- Пока проверка идёт: счётчик «Готово N из M» и кнопка «Отменить».

## Хранение настроек

`%APPDATA%\DI_Check\config.json` (вне репозитория). API-ключи — зашифрованы Windows DPAPI (CryptProtectData, текущий пользователь), в файле — base64. Остальное — plaintext JSON. Ключ из файла никогда не возвращается через API — только флаг `hasApiKey`.

## LLM-вызов

OpenAI-совместимый `POST {baseUrl}/chat/completions`, `httpx` async, таймаут ~300 с, ретраи до 3 попыток на 429/5xx/сеть/таймаут с backoff или `Retry-After`. Текст файла подставляется в user-message вместе с входными полями (предмет контракта, занятость и т.д.), с обрезкой по лимиту символов. Возвращается markdown-отчёт модели как есть (минус structured-блок).

## OCR (сканированные PDF)

Если pypdf не извлёк текст из PDF, бэкенд пробует OCR: PyMuPDF (рендер страниц) + Tesseract (`rus+eng`). Если Tesseract не установлен — понятная ошибка с подсказкой установить его; установка Tesseract не входит в зависимости приложения.
