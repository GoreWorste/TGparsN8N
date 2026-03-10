"""
Использование:
    python main.py input.json              # обработать файл
    python main.py input.json -o out.json  # сохранить результат

Формат input.json — любой из вариантов:
    [{"text": "...", ...}, ...]            # массив постов
    {"allPosts": [...]}                    # объект с полем allPosts
    {"posts": [...]}                       # объект с полем posts
"""

import json
import sys
import argparse
from pathlib import Path
from classifier import enrich_post, PRIORITY_EMOJI, PRIORITY_LABEL


def load_posts(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    for key in ("allPosts", "posts", "items", "data", "results"):
        if key in data and isinstance(data[key], list):
            return data[key]
    raise ValueError(
        f"Не могу найти массив постов. Ключи в файле: {list(data.keys())}"
    )


def print_summary(posts: list[dict]) -> None:
    totals = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for p in posts:
        totals[p["priority"]] = totals.get(p["priority"], 0) + 1

    print("\n" + "═" * 50)
    print("  ИТОГ")
    print("═" * 50)
    for priority in ("HIGH", "MEDIUM", "LOW"):
        emoji = PRIORITY_EMOJI[priority]
        label = PRIORITY_LABEL[priority]
        print(f"  {emoji} {label:12s} — {totals[priority]} постов")
    print("═" * 50)
    print(f"  Всего обработано: {len(posts)}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Фильтр постов по важности (светофор)")
    parser.add_argument("input",  help="Путь к input JSON-файлу")
    parser.add_argument("-o", "--output", help="Путь к output JSON-файлу (опционально)")
    parser.add_argument(
        "--only",
        choices=["HIGH", "MEDIUM", "LOW"],
        help="Вывести только посты с указанным приоритетом",
    )
    args = parser.parse_args()

    print(f"\n📂 Читаю файл: {args.input}")
    posts = load_posts(args.input)
    print(f"   Найдено постов: {len(posts)}\n")

    enriched = []
    for i, post in enumerate(posts, 1):
        text_preview = (post.get("text") or "—")[:60].replace("\n", " ")
        print(f"  [{i}/{len(posts)}] Классифицирую: {text_preview}...")
        result = enrich_post(post)
        enriched.append(result)
        emoji = result["priority_emoji"]
        label = result["priority_label"]
        print(f"         → {emoji} {label}")

    # Фильтрация если указан --only
    if args.only:
        filtered = [p for p in enriched if p["priority"] == args.only]
    else:
        filtered = enriched

    # Сортировка: HIGH → MEDIUM → LOW
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    filtered.sort(key=lambda p: order.get(p["priority"], 9))

    # Группировка для вывода
    output = {
        "total":  len(enriched),
        "shown":  len(filtered),
        "filter": args.only or "ALL",
        "HIGH":   [p for p in filtered if p["priority"] == "HIGH"],
        "MEDIUM": [p for p in filtered if p["priority"] == "MEDIUM"],
        "LOW":    [p for p in filtered if p["priority"] == "LOW"],
    }

    print_summary(enriched)

    if args.output:
        Path(args.output).write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"✅ Результат сохранён в: {args.output}\n")
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
