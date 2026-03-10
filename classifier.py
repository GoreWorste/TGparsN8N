import httpx
from config import (
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
    OPENROUTER_URL,
    CLASSIFY_PROMPT,
    TOPIC_DESCRIPTION,
)

PRIORITY_EMOJI = {
    "HIGH":   "🔴",
    "MEDIUM": "🟡",
    "LOW":    "🟢",
}

PRIORITY_LABEL = {
    "HIGH":   "Важно",
    "MEDIUM": "Средне",
    "LOW":    "Не важно",
}


def classify_post(text: str) -> str:
    """
    Отправляет текст поста в OpenRouter и возвращает приоритет:
    'HIGH', 'MEDIUM' или 'LOW'.
    При ошибке возвращает 'MEDIUM'.
    """
    if not text or not text.strip():
        return "LOW"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": TOPIC_DESCRIPTION + "\n" + CLASSIFY_PROMPT},
            {"role": "user",   "content": text[:1000]},  # обрезаем до 1000 символов
        ],
        "max_tokens": 5,
        "temperature": 0,
    }

    try:
        response = httpx.post(OPENROUTER_URL, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        answer = response.json()["choices"][0]["message"]["content"].strip().upper()
        if answer not in ("HIGH", "MEDIUM", "LOW"):
            return "MEDIUM"
        return answer
    except Exception as e:
        print(f"  [!] Ошибка OpenRouter: {e}")
        return "MEDIUM"


def enrich_post(post: dict) -> dict:
    """Добавляет к посту поля priority, emoji, label."""
    text = post.get("text") or post.get("content") or post.get("message") or ""
    priority = classify_post(text)
    return {
        **post,
        "priority":       priority,
        "priority_emoji": PRIORITY_EMOJI[priority],
        "priority_label": PRIORITY_LABEL[priority],
    }
