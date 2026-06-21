from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

import config

# Подписи кнопок главного меню — константы, чтобы не было опечаток при сравнении.
BTN_ADD = "➕ Добавить привычку"
BTN_LIST = "📋 Мои привычки"
BTN_CHECK = "✅ Отметить выполнение"
BTN_STATS = "📊 Статистика"
BTN_SHOP = "🛒 Магазин"
BTN_BALANCE = "💰 Баланс"
BTN_ACHIEVEMENTS = "🏆 Достижения"
BTN_SETTINGS = "⚙ Настройки"

# Набор всех кнопок меню — нужен, чтобы не принять нажатие меню за ввод текста в диалоге.
MENU_BUTTONS = {
    BTN_ADD, BTN_LIST, BTN_CHECK, BTN_STATS,
    BTN_SHOP, BTN_BALANCE, BTN_ACHIEVEMENTS, BTN_SETTINGS,
}


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


def cancel_inline() -> InlineKeyboardMarkup:
    """Кнопка отмены для диалогов добавления/редактирования."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="fsm_cancel")]]
    )


def schedule_type_keyboard() -> InlineKeyboardMarkup:
    """Выбор типа расписания при добавлении/редактировании привычки."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Каждый день", callback_data="st:daily")],
            [InlineKeyboardButton(text="Через день", callback_data="st:every2")],
            [InlineKeyboardButton(text="Каждые N дней", callback_data="st:everyn")],
            [InlineKeyboardButton(text="По дням недели", callback_data="st:weekdays")],
            [InlineKeyboardButton(text="Отмена", callback_data="fsm_cancel")],
        ]
    )


def weekday_keyboard(selected) -> InlineKeyboardMarkup:
    """Мульти-выбор дней недели. selected — множество/список выбранных индексов 0..6."""
    selected = set(selected)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i, name in enumerate(config.WEEKDAY_NAMES):
        mark = "✓ " if i in selected else ""
        row.append(InlineKeyboardButton(text=f"{mark}{name}", callback_data=f"wd:{i}"))
        if len(row) == 4:  # Пн–Чт в первом ряду, Пт–Вс во втором
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton(text="Готово", callback_data="wd:done"),
        InlineKeyboardButton(text="Отмена", callback_data="fsm_cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def habits_list_keyboard(habits) -> InlineKeyboardMarkup:
    """Список привычек — по кнопке на каждую."""
    rows = [
        [InlineKeyboardButton(text=h["title"], callback_data=f"habit:{h['id']}")]
        for h in habits
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def habit_card_keyboard(habit_id: int) -> InlineKeyboardMarkup:
    """Кнопки управления конкретной привычкой."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Изменить название", callback_data=f"et:{habit_id}")],
            [InlineKeyboardButton(text="Изменить расписание", callback_data=f"es:{habit_id}")],
            [InlineKeyboardButton(text="Изменить время", callback_data=f"etime:{habit_id}")],
            [InlineKeyboardButton(text="Удалить", callback_data=f"del:{habit_id}")],
            [InlineKeyboardButton(text="К списку", callback_data="back_list")],
        ]
    )


def delete_confirm_keyboard(habit_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, удалить", callback_data=f"delyes:{habit_id}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"delno:{habit_id}")],
        ]
    )


def reminder_prompt_keyboard() -> InlineKeyboardMarkup:
    """Кнопки на шаге выбора времени напоминания: можно вовсе отключить напоминание."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Без напоминания", callback_data="rtoff")],
            [InlineKeyboardButton(text="Отмена", callback_data="fsm_cancel")],
        ]
    )


def due_habits_keyboard(habits) -> InlineKeyboardMarkup:
    """Список привычек, которые сегодня нужно отметить."""
    rows = [
        [InlineKeyboardButton(text=h["title"], callback_data=f"done:{h['id']}")]
        for h in habits
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def stats_list_keyboard(habits) -> InlineKeyboardMarkup:
    """Список привычек для экрана статистики."""
    rows = [
        [InlineKeyboardButton(text=h["title"], callback_data=f"stat:{h['id']}")]
        for h in habits
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def stat_card_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="stat_back")]]
    )


def shop_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"Официальный пропуск — {config.SHOP_OFFICIAL_SKIP_COST}",
                callback_data="shop:skip",
            )],
            [InlineKeyboardButton(
                text=f"Замена привычки на день — {config.SHOP_REPLACE_COST}",
                callback_data="shop:replace",
            )],
            [InlineKeyboardButton(
                text=f"Заморозка серии — {config.SHOP_FREEZE_COST}",
                callback_data="shop:freeze",
            )],
        ]
    )


def freeze_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, купить", callback_data="freezebuy")],
            [InlineKeyboardButton(text="Назад", callback_data="shop_back")],
        ]
    )


def shop_habits_keyboard(habits, action: str) -> InlineKeyboardMarkup:
    """Список привычек для покупки. action: 'skip' или 'repl'."""
    prefix = "skipsel" if action == "skip" else "replsel"
    rows = [
        [InlineKeyboardButton(text=h["title"], callback_data=f"{prefix}:{h['id']}")]
        for h in habits
    ]
    rows.append([InlineKeyboardButton(text="Назад", callback_data="shop_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def skip_confirm_keyboard(habit_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, купить", callback_data=f"skipbuy:{habit_id}")],
            [InlineKeyboardButton(text="Назад", callback_data="shop_back")],
        ]
    )


def replace_text_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить", callback_data="repl_notext")],
            [InlineKeyboardButton(text="Отмена", callback_data="fsm_cancel")],
        ]
    )
