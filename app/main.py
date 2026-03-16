import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger("news_filter")

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat-v3-0324:free")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "45"))

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class NewsItem(BaseModel):
    id: str | int | None = None
    title: str | None = None
    text: str | None = None
    description: str | None = None
    url: str | None = None
    source: str | None = None
    published_at: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class FilterRequest(BaseModel):
    items: list[NewsItem]
    max_age_hours: int = Field(default=24, ge=1, le=24 * 365)
    language: str = Field(default="ru")


class ClassifiedItem(BaseModel):
    item: NewsItem
    keep: bool
    reason: str
    is_ad: bool
    is_fake_or_unverified: bool
    is_outdated: bool
    confidence: float = Field(ge=0, le=1)


class StandardNewsItem(BaseModel):
    """Единая шаблонная структура новости, которую возвращает поле output."""
    id: str | None = None
    title: str | None = None
    content: str | None = None
    dateTime: str | None = None
    source: str | None = None
    url: str | None = None
    imageUrl: str | None = None


class FilterResponse(BaseModel):
    kept: list[ClassifiedItem]
    removed: list[ClassifiedItem]
    output: list[StandardNewsItem]
    stats: dict[str, Any]


def _to_standard(item: NewsItem) -> StandardNewsItem:
    """Конвертирует внутренний NewsItem в стандартную шаблонную структуру."""
    # content: предпочитаем text, fallback на description
    content = (item.text or item.description or "").strip() or None

    # title: берём из title, если нет — первые 80 символов content
    title = item.title
    if not title and content:
        title = content[:80].rstrip() + ("…" if len(content) > 80 else "")

    # id как строка
    item_id = str(item.id) if item.id is not None else None

    # imageUrl из extra (парсер Telegram кладёт туда photoUrl/videoThumbUrl)
    image_url: str | None = None
    if isinstance(item.extra, dict):
        image_url = item.extra.get("photoUrl") or item.extra.get("videoThumbUrl") or None

    return StandardNewsItem(
        id=item_id,
        title=title,
        content=content,
        dateTime=item.published_at,
        source=item.source,
        url=item.url,
        imageUrl=image_url,
    )


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
app = FastAPI(title="news-filter-service", version="1.0.0")


# Patterns stripped from post text before classification.
_CLEANUP_PATTERNS = [
    # "🔹 Подписаться на РИА Новости" and similar CTAs with any leading emoji/bullet
    re.compile(r"[\U0001F300-\U0001FFFF\u25AA-\u25FF\u2600-\u27FF\uFE0F•\-–—*]+\s*[Пп]одписа[^\n]*", re.UNICODE),
    re.compile(r"[Пп]одписывайтесь[^\n]*", re.IGNORECASE),
    re.compile(r"[Пп]одписаться[^\n]*", re.IGNORECASE),
    re.compile(r"@\w+\s*[-–—]\s*подписаться[^\n]*", re.IGNORECASE),
    re.compile(r"\[подписаться\][^\n]*", re.IGNORECASE),
    # Bare trailing t.me links
    re.compile(r"https?://t\.me/[\w/]+\s*$", re.MULTILINE),
    # Leftover lone emoji/bullet at end of line
    re.compile(r"^\s*[\U0001F300-\U0001FFFF\u25AA-\u27FF\uFE0F•]+\s*$", re.MULTILINE | re.UNICODE),
]

# Field name aliases from Telegram / n8n posts → canonical NewsItem fields.
_FIELD_ALIASES: dict[str, str] = {
    "postId": "id",
    "post_id": "id",
    "author": "source",
    "channel": "source",
    # published_at sources — priority resolved explicitly in _normalize_item_dict
    "sortableDate": "published_at",   # ISO string from n8n Code2 (highest priority)
    "dateTimeRaw": "published_at",    # raw datetime attribute from n8n Code2
    "dateTime": "published_at",       # may be object — handled specially below
    "date_time": "published_at",
    "publishedAt": "published_at",
    "date": "published_at",
    "link": "url",
    "message": "text",
    "content": "text",
    "body": "text",
    "caption": "description",
    "summary": "description",
}


def _clean_text(text: str | None) -> str:
    """Strip channel subscription CTAs and trailing links from post text."""
    if not text:
        return ""
    result = text
    for pattern in _CLEANUP_PATTERNS:
        result = pattern.sub("", result)
    return result.strip()


def _normalize_item_dict(raw: dict) -> dict:
    """Remap Telegram/n8n field names to canonical NewsItem field names."""
    out: dict = {}
    for key, value in raw.items():
        canonical = _FIELD_ALIASES.get(key, key)
        # Don't overwrite already-set canonical field with alias.
        if canonical not in out:
            out[canonical] = value

    # Resolve published_at with explicit priority.
    # n8n Code2 sends dateTime as a complex object {iso, raw, date, time, ...}.
    # Priority: sortableDate (ISO) > dateTimeRaw > dateTime.iso > dateTime.raw > dateTime string.
    pub: str | None = None
    if raw.get("sortableDate"):
        pub = str(raw["sortableDate"])
    elif raw.get("dateTimeRaw"):
        pub = str(raw["dateTimeRaw"])
    elif isinstance(raw.get("dateTime"), dict):
        dt = raw["dateTime"]
        pub = dt.get("iso") or dt.get("raw") or None
    elif isinstance(raw.get("dateTime"), str) and raw["dateTime"]:
        pub = raw["dateTime"]
    if pub is not None:
        out["published_at"] = pub

    # Clean text after remapping.
    if "text" in out:
        out["text"] = _clean_text(out["text"])
    if "description" in out:
        out["description"] = _clean_text(out["description"])
    return out


def _is_obviously_old(item: NewsItem, max_age_hours: int) -> bool:
    if not item.published_at:
        return False
    try:
        published = datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - published).total_seconds() / 3600
        return age_hours > max_age_hours
    except ValueError:
        return False


def _build_prompt(item: NewsItem, max_age_hours: int, language: str) -> str:
    payload = {
        "id": item.id,
        "title": item.title,
        "text": item.text,
        "description": item.description,
        "url": item.url,
        "source": item.source,
        "published_at": item.published_at,
    }
    return (
        "Ты строгий фильтр новостей. Твоя задача — отсеять всё лишнее и оставить только реальные новости.\n\n"
        "=== РЕКЛАМА (is_ad=true, keep=false) ===\n"
        "Прочти ВЕСЬ текст и определи его ОСНОВНОЙ СМЫСЛ:\n"
        "- Если главная цель — продать, привлечь, пригласить, завлечь — это РЕКЛАМА.\n"
        "- Если текст рассказывает о событии, факте, решении, действии — это НОВОСТЬ.\n\n"
        "Явные признаки рекламы (хотя бы один = реклама):\n"
        "  • Продажа товаров или услуг (любых: курсы, крипта, одежда, техника, еда)\n"
        "  • Промокоды, скидки, акции, кешбэк, бонусы\n"
        "  • Казино, ставки на спорт, букмекеры, лотереи, форекс\n"
        "  • Призывы: 'купи', 'закажи', 'перейди по ссылке', 'узнай подробнее', 'успей', 'осталось N мест'\n"
        "  • Реферальные/партнёрские ссылки (t.me/+..., r.tg/...)\n"
        "  • Розыгрыши и конкурсы с призами\n"
        "  • Рекомендации подписаться на платный сервис или канал\n"
        "  • Нативная реклама: событие описано, но главная цель — продать что-то\n"
        "  • Спонсорский/партнёрский контент, пометка 'реклама', 'sponsored', 'AD'\n"
        "  • Инвестиционные предложения, ICO, NFT-продажи, 'пассивный доход'\n\n"
        "Скрытая реклама (нативка) — сложнее. Признаки:\n"
        "  • Текст написан как новость, но в конце ссылка на магазин/продукт/сервис\n"
        "  • Чрезмерно хвалебный тон о конкретном продукте или компании\n"
        "  • Упоминание конкретной цены со ссылкой на покупку\n"
        "  • 'Эксперты рекомендуют [название продукта]' без новостного контекста\n\n"
        "=== ФЕЙК / НЕПРОВЕРЕННАЯ (is_fake_or_unverified=true, keep=false) ===\n"
        "  • Кликбейт-заголовок без конкретных фактов (кто? что? когда? где?)\n"
        "  • Анонимные источники как единственное основание ('источники сообщают')\n"
        "  • Конспирология, теории заговора\n"
        "  • Непроверенные слухи без ссылки на официальный источник\n\n"
        f"=== УСТАРЕЛА (is_outdated=true, keep=false) ===\n"
        f"  • Опубликована более {max_age_hours} часов назад.\n\n"
        "=== НЕ НОВОСТЬ (keep=false) ===\n"
        "  • Пустой текст, только хэштеги или эмодзи\n"
        "  • Гороскоп, поздравление, байка, анекдот\n"
        "  • Объявление о вакансии\n"
        "  • Инфографика без пояснительного текста ('Главное о потерях... — в инфографике')\n"
        "  • Анонс мероприятия без реальной новостной ценности\n\n"
        "=== НЕ СЧИТАТЬ РЕКЛАМОЙ ===\n"
        "  • Упоминание бренда/компании в контексте новости о ней (штраф, иск, сделка)\n"
        "  • Официальные заявления госорганов и компаний\n"
        "  • Подписные плашки каналов (уже удалены из текста)\n\n"
        f"Язык контента: {language}.\n\n"
        "Ответь ТОЛЬКО валидным JSON без markdown-обёртки:\n"
        '{"keep": boolean, "reason": string, "is_ad": boolean, '
        '"is_fake_or_unverified": boolean, "is_outdated": boolean, "confidence": number}\n\n'
        "Поле reason — одна строка на русском: кратко объясни решение.\n"
        "Поле confidence — уверенность в решении от 0.0 до 1.0.\n\n"
        f"Новость для анализа:\n{json.dumps(payload, ensure_ascii=False)}"
    )


async def _call_openrouter(body: dict, retries: int = 3, retry_delay: float = 2.0) -> dict:
    """Call OpenRouter with automatic retry on 5xx errors."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    last_error = ""
    for attempt in range(1, retries + 1):
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            try:
                response = await client.post(OPENROUTER_URL, headers=headers, json=body)
            except httpx.RequestError as exc:
                last_error = f"Network error: {exc}"
                logger.warning("OpenRouter attempt %d/%d failed: %s", attempt, retries, last_error)
                if attempt < retries:
                    await asyncio.sleep(retry_delay * attempt)
                continue

        if response.status_code < 500:
            return response.json()

        last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        logger.warning("OpenRouter attempt %d/%d → %s", attempt, retries, last_error)
        if attempt < retries:
            await asyncio.sleep(retry_delay * attempt)

    raise HTTPException(status_code=502, detail=f"OpenRouter unavailable after {retries} attempts: {last_error}")


def _pre_filter(item: NewsItem, max_age_hours: int) -> ClassifiedItem | None:
    """Fast rule-based checks before calling LLM. Returns ClassifiedItem if item should be removed."""
    # Too old.
    if _is_obviously_old(item, max_age_hours):
        return ClassifiedItem(
            item=item, keep=False,
            reason=f"Устаревшая новость: старше {max_age_hours} часов.",
            is_ad=False, is_fake_or_unverified=False, is_outdated=True, confidence=0.99,
        )
    # No meaningful text at all.
    text = (item.text or item.description or item.title or "").strip()
    if len(text) < 15:
        return ClassifiedItem(
            item=item, keep=False,
            reason="Слишком короткий текст — не является новостью.",
            is_ad=False, is_fake_or_unverified=False, is_outdated=False, confidence=0.95,
        )
    return None


async def _classify_item(item: NewsItem, max_age_hours: int, language: str) -> ClassifiedItem:
    # Fast rule-based pre-filter before LLM call.
    pre = _pre_filter(item, max_age_hours)
    if pre is not None:
        return pre

    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY is not configured.")

    body = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": "Ты строгий модератор новостей. Отвечай только JSON без markdown."},
            {"role": "user", "content": _build_prompt(item, max_age_hours, language)},
        ],
        "temperature": 0.1,
    }

    try:
        data = await _call_openrouter(body)
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return ClassifiedItem(
            item=item,
            keep=bool(parsed.get("keep", False)),
            reason=str(parsed.get("reason", "No reason")),
            is_ad=bool(parsed.get("is_ad", False)),
            is_fake_or_unverified=bool(parsed.get("is_fake_or_unverified", False)),
            is_outdated=bool(parsed.get("is_outdated", False)),
            confidence=float(parsed.get("confidence", 0.0)),
        )
    except HTTPException:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Invalid OpenRouter response: {exc}") from exc


def _parse_filter_request_payload(payload: Any) -> FilterRequest:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Body string is not valid JSON: {exc}") from exc

    # If we received a plain list, treat it as items.
    if isinstance(payload, list):
        payload = {"items": payload}

    # Unwrap common wrappers like {"jsonFile": {...}} or {"file": {...}}
    if isinstance(payload, dict):
        for wrapper_key in ("jsonFile", "file", "payload"):
            inner = payload.get(wrapper_key)
            # n8n sometimes serialises the value as a JSON string — try to parse it.
            if isinstance(inner, str):
                try:
                    inner = json.loads(inner)
                except json.JSONDecodeError:
                    inner = None
            if isinstance(inner, (dict, list)):
                # If inner is list → it's the items; if dict → it becomes the new root.
                if isinstance(inner, list):
                    payload = {"items": inner}
                else:
                    payload = inner
                break

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON payload. Expected object with 'items' array or raw JSON array.",
        )

    # 1) Try conventional keys first.
    items = payload.get("items")
    if items is None:
        for fallback_key in ("allPosts", "posts", "data"):
            if isinstance(payload.get(fallback_key), list):
                items = payload[fallback_key]
                break
            # Some n8n flows produce nested payload like {"allPosts": {"allPosts": [...]}}
            if isinstance(payload.get(fallback_key), dict):
                nested = payload[fallback_key]
                for nested_key in ("items", "allPosts", "posts", "data"):
                    if isinstance(nested.get(nested_key), list):
                        items = nested[nested_key]
                        break
                if items is not None:
                    break

    # 2) Support нескольких массивов (например, tgPosts + webPosts) в одном payload.
    candidate_lists: list[list[Any]] = []
    for key, value in payload.items():
        if isinstance(value, list):
            candidate_lists.append(value)
        elif isinstance(value, dict):
            # Один уровень вложенности достаточно для типичного JSON от n8n.
            for nested_value in value.values():
                if isinstance(nested_value, list):
                    candidate_lists.append(nested_value)

    # Если items ещё не определён, но есть несколько списков — склеиваем все.
    if items is None and candidate_lists:
        merged: list[Any] = []
        for lst in candidate_lists:
            merged.extend(lst)
        items = merged
    # Если items уже есть и есть дополнительные списки — аккуратно добавим уникальные по объекту.
    elif isinstance(items, list) and candidate_lists:
        base_id = id(items)
        for lst in candidate_lists:
            if id(lst) == base_id:
                continue
            items.extend(lst)

    # Если всё ещё нет items — считаем, что постов нет.
    if items is None:
        logger.warning("No items found in payload keys=%s — returning empty result.", list(payload.keys()))
        items = []

    # Remap Telegram/n8n field names to canonical NewsItem field names.
    if isinstance(items, list):
        items = [_normalize_item_dict(i) if isinstance(i, dict) else i for i in items]

    # Support both max_age_hours (preferred) and legacy max_age_days.
    if "max_age_hours" in payload:
        max_age_hours = int(payload["max_age_hours"])
    elif "max_age_days" in payload:
        max_age_hours = int(payload["max_age_days"]) * 24
    else:
        max_age_hours = 24

    normalized = {
        "items": items,
        "max_age_hours": max_age_hours,
        "language": payload.get("language", "ru"),
    }

    try:
        return FilterRequest.model_validate(normalized)
    except ValidationError as exc:
        logger.error("ValidationError: items type=%s value_preview=%s errors=%s",
                     type(normalized.get("items")).__name__,
                     str(normalized.get("items"))[:200],
                     exc.errors())
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Invalid request body for /filter.",
                "hint": "Send JSON with 'items' array, e.g. {'items': [...], 'max_age_days': 7, 'language': 'ru'}",
                "errors": exc.errors(),
            },
        ) from exc


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/filter", response_model=FilterResponse)
async def filter_news(
    request: Request,
    max_age_hours: int = Query(default=24, ge=1, le=24 * 365),
    max_age_days: int = Query(default=0, ge=0, le=365),
    language: str = Query(default="ru"),
) -> FilterResponse:
    # Legacy: if max_age_days query param given, convert to hours.
    if max_age_days > 0:
        max_age_hours = max_age_days * 24
    content_type = request.headers.get("content-type", "")
    logger.info("POST /filter | content-type=%s max_age_hours=%d", content_type, max_age_hours)

    # Support both JSON body and multipart upload with a JSON file.
    raw_payload: Any
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file") or form.get("jsonFile")
        if upload is None:
            raise HTTPException(
                status_code=400,
                detail="Multipart request must contain a 'file' or 'jsonFile' field with JSON.",
            )
        try:
            data = await upload.read()
            raw_payload = json.loads(data.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=400,
                detail="Uploaded file is not valid JSON.",
            ) from exc
    else:
        try:
            raw_payload = await request.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=400,
                detail="Request body must be valid JSON.",
            ) from exc

    # Query params override anything that might be in the body.
    if isinstance(raw_payload, dict):
        raw_payload.setdefault("max_age_hours", max_age_hours)
        raw_payload.setdefault("language", language)

    logger.info("raw_payload type=%s keys=%s preview=%s",
                type(raw_payload).__name__,
                list(raw_payload.keys()) if isinstance(raw_payload, dict) else "N/A",
                str(raw_payload)[:300])

    parsed_request = _parse_filter_request_payload(raw_payload)
    kept: list[ClassifiedItem] = []
    removed: list[ClassifiedItem] = []
    errors: int = 0

    for item in parsed_request.items:
        try:
            classified = await _classify_item(
                item=item,
                max_age_hours=parsed_request.max_age_hours,
                language=parsed_request.language,
            )
        except HTTPException as exc:
            # Don't crash the whole batch — mark item as removed with error reason.
            logger.error("Classification failed for item %s: %s", item.id or item.url, exc.detail)
            errors += 1
            classified = ClassifiedItem(
                item=item,
                keep=False,
                reason=f"Ошибка классификации: {exc.detail}",
                is_ad=False,
                is_fake_or_unverified=False,
                is_outdated=False,
                confidence=0.0,
            )

        if classified.keep and not (classified.is_ad or classified.is_fake_or_unverified or classified.is_outdated):
            kept.append(classified)
        else:
            removed.append(classified)

    return FilterResponse(
        kept=kept,
        removed=removed,
        output=[_to_standard(ci.item) for ci in kept],
        stats={
            "total": len(parsed_request.items),
            "kept": len(kept),
            "removed": len(removed),
            "errors": errors,
            "model": OPENROUTER_MODEL,
            "max_age_hours": parsed_request.max_age_hours,
        },
    )
