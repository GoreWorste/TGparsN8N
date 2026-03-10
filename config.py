import os

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL   = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
OPENROUTER_URL     = os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")

# Описание тематики — что считать важным (можно менять)
TOPIC_DESCRIPTION = """
Ты — фильтр новостей. Оценивай посты по важности для бизнеса, технологий и рынков.
"""

# Системный промпт для классификации
CLASSIFY_PROMPT = """\
Тебе дан текст поста. Определи его важность и верни ТОЛЬКО одно слово:
- HIGH   — срочно, критично, важное событие (политика, катастрофы, крупные сделки, законы)
- MEDIUM — интересно, стоит знать (новинки, аналитика, тренды)
- LOW    — реклама, мусор, несущественное

Отвечай строго одним словом: HIGH, MEDIUM или LOW.
"""
