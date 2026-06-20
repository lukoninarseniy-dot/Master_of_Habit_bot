from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

import config

# Подписи кнопок главного меню вынесены в константы,
# чтобы не было опечаток при сравнении текста в bot.py.
BTN_ADD = "➕ Добавить привычку"
BTN_LIST = "📋 Мои привычки"
BTN_CHECK = "✅ Отметить выполнение"
BTN_STATS = "📊 Статистика"
BTN_SHOP = "🛒 Магазин"
BTN_BALANCE = "💰 Баланс"
BTN_ACHIEVEMENTS = "🏆 Достижения"
BTN_SETTINGS = "⚙ Настройки"


def main_menu() -> ReplyKeyboardMarkup:
    """Главное меню — постоянная нижняя клавиатура (раздел 13 ТЗ)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_ADD), KeyboardButton(text=BTN_LIST)],
            [KeyboardButton(text=BTN_CHECK), KeyboardButton(text=BTN_STATS)],
            [KeyboardButton(text=BTN_SHOP), KeyboardButton(text=BTN_BALANCE)],
            [KeyboardButton(text=BTN_ACHIEVEMENTS), KeyboardButton(text=BTN_SETTINGS)],
        ],
        resize_keyboard=True,
    )


def timezone_keyboard() -> InlineKeyboardMarkup:
    """Inline-кнопки выбора часового пояса (по 2 в ряд)."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for label, tz_name in config.TIMEZONES:
        row.append(InlineKeyboardButton(text=label, callback_data=f"tz:{tz_name}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)
