## Content Priority Classifier (Telegram → JSON → PDF)

Инструмент для сортировки новостных постов по важности (красный / жёлтый / зелёный светофор) с помощью OpenRouter и генерации красивого PDF‑отчёта. 

Работает:
- **как CLI‑утилита** по JSON‑файлу
- **как HTTP‑сервис** (FastAPI) — удобно подключать к **n8n**, Telegram‑ботам и другим пайплайнам.

Проект кроссплатформенный — всё работает на **Linux / macOS / Windows**, нужен только Python 3.10+.

---

## Возможности

- **Классификация постов** на три уровня важности:
  - 🔴 `HIGH` — важно / срочно
  - 🟡 `MEDIUM` — полезно знать
  - 🟢 `LOW` — неважно / шум
- **Входной формат**: массив объектов с текстом (`text`) или объект с полем `allPosts` / `posts` — подходит к типичному JSON после парсинга Telegram‑каналов.
- **PDF‑отчёт**:
  - таблица с количеством постов каждого уровня
  - карточки постов с текстом, датой, автором, просмотрами и ссылкой
  - поддержка кириллицы (шрифты DejaVu, с запасным вариантом)
- **HTTP API**:
  - `POST /classify` → JSON с разбивкой по важности
  - `POST /classify/pdf` → готовый PDF‑файл

---

## Требования

- Python **3.10+**
- Доступ к **OpenRouter** и API‑ключ (`OPENROUTER_API_KEY`)

Python‑зависимости (также есть в `requirements.txt`):

- `httpx`
- `fastapi`
- `uvicorn[standard]`
- `reportlab`

---

## Установка (Linux / macOS / Windows)

```bash
git clone <your-repo-url> content-priority-classifier
cd content-priority-classifier

# Рекомендуется отдельное виртуальное окружение
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows (PowerShell)
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

---

## Настройка OpenRouter

1. Получите API‑ключ на OpenRouter и сохраните его в переменной окружения:

   ### Linux / macOS (bash/zsh)
   ```bash
   export OPENROUTER_API_KEY="sk-or-..."
   ```

   ### Windows (PowerShell)
   ```powershell
   setx OPENROUTER_API_KEY "sk-or-..."
   ```

2. (Необязательно) можно переопределить модель и URL:

   ```bash
   export OPENROUTER_MODEL="openai/gpt-4o-mini"
   export OPENROUTER_URL="https://openrouter.ai/api/v1/chat/completions"
   ```

Файл `config.py` читает настройки только из окружения — **секреты не хранятся в репозитории**.

---

## Формат входного JSON

Поддерживаются несколько удобных форматов:

```json
[
  { "text": "первый пост", "url": "...", "views": 100 },
  { "text": "второй пост" }
]
```

```json
{
  "allPosts": [
    { "text": "первый пост", "url": "...", "views": 100 }
  ]
}
```

```json
{
  "posts": [
    { "text": "первый пост" }
  ]
}
```

Дополнительные поля (`author`, `dateTime`, `views`, `url`) будут использованы в PDF, если присутствуют.

---

## CLI‑режим (`main.py`)

Примеры:

```bash
# Обработать JSON и вывести результат в stdout
python main.py input.json

# Сохранить результат в файл
python main.py input.json -o result.json

# Показать только важные (HIGH)
python main.py input.json --only HIGH
```

Описание формата входа и поведения есть в самом файле `main.py`.

---

## HTTP‑API (FastAPI сервер)

Запуск сервера:

```bash
# Linux / macOS
source .venv/bin/activate
uvicorn server:app --host 0.0.0.0 --port 8001

# Windows (PowerShell)
# .venv\Scripts\Activate.ps1
# uvicorn server:app --host 0.0.0.0 --port 8001
```

После запуска:

- `GET  /health` — проверка живости сервера
- `POST /classify` — вернуть JSON с приоритетами
- `POST /classify/pdf` — вернуть PDF

### Примеры запросов

**JSON‑классификация:**

```bash
curl -X POST http://localhost:8001/classify \
  -H "Content-Type: application/json" \
  -d '{"posts":[{"text":"пример поста"}]}'
```

**PDF‑отчёт:**

```bash
curl -X POST http://localhost:8001/classify/pdf \
  -H "Content-Type: application/json" \
  -d '{
        "posts":[{"text":"пример поста"}],
        "channel":"@test_channel",
        "title":"Дайджест за сегодня"
      }' \
  -o digest.pdf
```

---

## Интеграция с n8n (кратко)

Базовая схема:

1. Нода парсинга Telegram → выдаёт JSON с полем `allPosts`.
2. Нода **HTTP Request**:
   - **Method**: `POST`
   - **URL**: `http(s)://<ваш-домен-или-туннель>/classify/pdf`
   - **Body Content Type**: `JSON`
   - **Body**:
     - `posts`   = `{{$json["allPosts"]}}`
     - `channel` = `{{$json["channel_link"] || ""}}`
     - `title`   = `Дайджест`
3. Нода отправки файла (например, Telegram) берёт бинарный ответ из HTTP Request.

Если нужно, рядом с проектом есть пример workflow: `n8n_workflow.json`.

---

## Разработка

- Код отформатирован в стиле PEP 8 и разбит на модули:
  - `classifier.py` — работа с OpenRouter
  - `pdf_report.py` — генерация PDF
  - `server.py` — HTTP‑API (FastAPI)
  - `main.py` — CLI
- Для изменения логики важности настроить:
  - `TOPIC_DESCRIPTION`
  - `CLASSIFY_PROMPT`
  в файле `config.py`.

---

## Лицензия

Добавьте сюда выбранную лицензию (MIT/Apache‑2.0/etc.), если планируете публиковать репозиторий.

