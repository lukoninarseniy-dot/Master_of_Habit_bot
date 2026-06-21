"""Тепловая карта привычки: PNG-«календарь» из цветных квадратов (как на GitHub).

Зелёный — выполнено, красный — пропуск, серый — нейтральный день (официальный
пропуск / заморозка), светлый — нет активности.

Текст на картинку НЕ наносим: встроенный шрифт Pillow не поддерживает кириллицу.
Название привычки и легенду бот добавляет в подпись к фото.
"""

import io
from datetime import date, timedelta

from PIL import Image, ImageDraw

CELL = 14
GAP = 3
STEP = CELL + GAP
MARGIN = 10
MAX_WEEKS = 53

COLOR_BG = (255, 255, 255)
COLOR_EMPTY = (235, 237, 240)
COLOR_DONE = (46, 204, 113)
COLOR_MISS = (231, 76, 60)
COLOR_NEUTRAL = (149, 165, 166)


def _color(status):
    if status in ("completed", "temporary_replace"):
        return COLOR_DONE
    if status == "missed":
        return COLOR_MISS
    if status in ("official_skip", "freeze"):
        return COLOR_NEUTRAL
    return COLOR_EMPTY


def generate_heatmap(title: str, status_by_date: dict, start_date, today) -> bytes:
    start = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
    if isinstance(today, str):
        today = date.fromisoformat(today)

    first_monday = start - timedelta(days=start.weekday())
    last_monday = today - timedelta(days=today.weekday())
    weeks = (last_monday - first_monday).days // 7 + 1
    if weeks > MAX_WEEKS:
        first_monday = last_monday - timedelta(weeks=MAX_WEEKS - 1)
        weeks = MAX_WEEKS

    width = MARGIN * 2 + weeks * STEP - GAP
    height = MARGIN * 2 + 7 * STEP - GAP
    img = Image.new("RGB", (width, height), COLOR_BG)
    draw = ImageDraw.Draw(img)

    for w in range(weeks):
        for d in range(7):
            day = first_monday + timedelta(weeks=w, days=d)
            if day < start or day > today:
                color = COLOR_BG  # привычка ещё не существовала / будущее
            else:
                color = _color(status_by_date.get(day.isoformat()))
            x = MARGIN + w * STEP
            y = MARGIN + d * STEP
            draw.rectangle([x, y, x + CELL - 1, y + CELL - 1], fill=color)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
