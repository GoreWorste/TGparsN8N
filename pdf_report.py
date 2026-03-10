"""
Генерация PDF-дайджеста с результатами классификации.
Использует reportlab. Поддерживает кириллицу через встроенный шрифт DejaVu.
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from datetime import datetime
import os

# ── Шрифт с кириллицей ────────────────────────────────────────
_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]

def _register_fonts():
    regular = next((p for p in _FONT_PATHS if "Bold" not in p and os.path.exists(p)), None)
    bold    = next((p for p in _FONT_PATHS if "Bold" in p     and os.path.exists(p)), None)
    if regular:
        pdfmetrics.registerFont(TTFont("DejaVu",     regular))
    if bold:
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", bold))
    return bool(regular)

_HAS_DEJAVU = _register_fonts()
FONT        = "DejaVu"      if _HAS_DEJAVU else "Helvetica"
FONT_BOLD   = "DejaVu-Bold" if _HAS_DEJAVU else "Helvetica-Bold"


# ── Цвета светофора ───────────────────────────────────────────
COLOR = {
    "HIGH":   colors.HexColor("#E53935"),   # красный
    "MEDIUM": colors.HexColor("#FB8C00"),   # оранжевый
    "LOW":    colors.HexColor("#43A047"),   # зелёный
}
BG_COLOR = {
    "HIGH":   colors.HexColor("#FFEBEE"),
    "MEDIUM": colors.HexColor("#FFF3E0"),
    "LOW":    colors.HexColor("#E8F5E9"),
}
LABEL = {
    "HIGH":   "🔴 ВАЖНО",
    "MEDIUM": "🟡 СРЕДНЕ",
    "LOW":    "🟢 НЕ ВАЖНО",
}


# ── Основная функция ──────────────────────────────────────────

def build_pdf(path: str, title: str, channel: str, data: dict) -> None:
    """
    data = {
        "total": int,
        "HIGH":   [post, ...],
        "MEDIUM": [post, ...],
        "LOW":    [post, ...],
    }
    """
    doc = SimpleDocTemplate(
        path,
        pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm,  bottomMargin=20*mm,
    )

    story = []

    # ── Заголовок ────────────────────────────────────────────
    story.append(Paragraph(title, ParagraphStyle(
        "Title", fontName=FONT_BOLD, fontSize=20, spaceAfter=4,
        textColor=colors.HexColor("#1A237E"),
    )))
    if channel:
        story.append(Paragraph(f"Канал: {channel}", ParagraphStyle(
            "Sub", fontName=FONT, fontSize=11, textColor=colors.grey, spaceAfter=2,
        )))
    story.append(Paragraph(
        datetime.now().strftime("Сформирован: %d.%m.%Y %H:%M"),
        ParagraphStyle("Date", fontName=FONT, fontSize=9, textColor=colors.grey, spaceAfter=8),
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1A237E")))
    story.append(Spacer(1, 6*mm))

    # ── Сводная таблица ───────────────────────────────────────
    summary_data = [
        ["Приоритет", "Кол-во постов"],
        [LABEL["HIGH"],   str(len(data.get("HIGH",   [])))],
        [LABEL["MEDIUM"], str(len(data.get("MEDIUM", [])))],
        [LABEL["LOW"],    str(len(data.get("LOW",    [])))],
        ["ВСЕГО",         str(data.get("total", 0))],
    ]
    summary_table = Table(summary_data, colWidths=[110*mm, 40*mm])
    summary_table.setStyle(TableStyle([
        ("FONTNAME",    (0, 0), (-1, -1),  FONT),
        ("FONTNAME",    (0, 0), (-1,  0),  FONT_BOLD),
        ("FONTNAME",    (0, 4), (-1,  4),  FONT_BOLD),
        ("FONTSIZE",    (0, 0), (-1, -1),  10),
        ("BACKGROUND",  (0, 0), (-1,  0),  colors.HexColor("#1A237E")),
        ("TEXTCOLOR",   (0, 0), (-1,  0),  colors.white),
        ("BACKGROUND",  (0, 1), (-1,  1),  BG_COLOR["HIGH"]),
        ("BACKGROUND",  (0, 2), (-1,  2),  BG_COLOR["MEDIUM"]),
        ("BACKGROUND",  (0, 3), (-1,  3),  BG_COLOR["LOW"]),
        ("BACKGROUND",  (0, 4), (-1,  4),  colors.HexColor("#E8EAF6")),
        ("ALIGN",       (1, 0), (1, -1),   "CENTER"),
        ("GRID",        (0, 0), (-1, -1),  0.5, colors.grey),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 8*mm))

    # ── Посты по группам ──────────────────────────────────────
    for priority in ("HIGH", "MEDIUM", "LOW"):
        posts = data.get(priority, [])
        if not posts:
            continue

        story.append(Paragraph(LABEL[priority], ParagraphStyle(
            f"H_{priority}",
            fontName=FONT_BOLD, fontSize=13,
            textColor=COLOR[priority],
            spaceBefore=6, spaceAfter=3,
        )))
        story.append(HRFlowable(width="100%", thickness=0.5, color=COLOR[priority]))
        story.append(Spacer(1, 2*mm))

        for post in posts:
            text     = (post.get("text") or "—").replace("\n", " ").strip()
            url      = post.get("url") or ""
            dt       = post.get("dateTime") or post.get("time") or ""
            views    = post.get("views")
            author   = post.get("author") or ""

            meta_parts = []
            if author: meta_parts.append(author)
            if dt:     meta_parts.append(dt[:16])
            if views:  meta_parts.append(f"👁 {views:,}")
            meta = "  |  ".join(meta_parts)

            card_data = [[
                Paragraph(text[:400], ParagraphStyle(
                    "CardText", fontName=FONT, fontSize=9, leading=13,
                )),
            ]]
            if meta:
                card_data.append([
                    Paragraph(meta, ParagraphStyle(
                        "CardMeta", fontName=FONT, fontSize=8,
                        textColor=colors.grey,
                    ))
                ])
            if url:
                card_data.append([
                    Paragraph(f'<link href="{url}">{url}</link>', ParagraphStyle(
                        "CardUrl", fontName=FONT, fontSize=8,
                        textColor=colors.blue,
                    ))
                ])

            card = Table(card_data, colWidths=[170*mm])
            card.setStyle(TableStyle([
                ("FONTNAME",   (0, 0), (-1, -1), FONT),
                ("BACKGROUND", (0, 0), (-1, -1), BG_COLOR[priority]),
                ("BOX",        (0, 0), (-1, -1), 0.5, COLOR[priority]),
                ("LEFTPADDING",  (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING",   (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
            ]))
            story.append(card)
            story.append(Spacer(1, 2*mm))

        story.append(Spacer(1, 4*mm))

    doc.build(story)
