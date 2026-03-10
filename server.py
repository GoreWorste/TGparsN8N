"""
FastAPI сервер — точка входа для n8n.

Эндпоинты:
  POST /classify        — принять список постов, вернуть JSON с приоритетами
  POST /classify/pdf    — принять список постов, вернуть готовый PDF файл
  GET  /health          — проверка работоспособности
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Any
import tempfile
import os

from classifier import enrich_post
from pdf_report import build_pdf

app = FastAPI(title="Content Classifier", version="1.0")


# ── Модели запросов ────────────────────────────────────────────

class ClassifyRequest(BaseModel):
    posts: list[dict[str, Any]]
    channel: str = ""          # название канала (для заголовка PDF)
    title: str = "Дайджест"    # заголовок отчёта


# ── Хелпер: классифицировать все посты ────────────────────────

def _classify_all(posts: list[dict]) -> dict:
    enriched = [enrich_post(p) for p in posts]
    return {
        "total":  len(enriched),
        "HIGH":   [p for p in enriched if p["priority"] == "HIGH"],
        "MEDIUM": [p for p in enriched if p["priority"] == "MEDIUM"],
        "LOW":    [p for p in enriched if p["priority"] == "LOW"],
    }


# ── Маршруты ──────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/classify")
def classify(req: ClassifyRequest):
    """Вернуть классифицированные посты в JSON."""
    if not req.posts:
        raise HTTPException(status_code=400, detail="Список постов пустой")
    result = _classify_all(req.posts)
    return JSONResponse(content=result)


@app.post("/classify/pdf")
def classify_pdf(req: ClassifyRequest):
    """Классифицировать посты и вернуть PDF-файл."""
    if not req.posts:
        raise HTTPException(status_code=400, detail="Список постов пустой")

    result = _classify_all(req.posts)

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()

    build_pdf(
        path=tmp.name,
        title=req.title,
        channel=req.channel,
        data=result,
    )

    return FileResponse(
        path=tmp.name,
        media_type="application/pdf",
        filename="digest.pdf",
        background=None,
    )
