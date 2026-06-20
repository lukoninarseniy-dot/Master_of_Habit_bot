import asyncio
import json
import logging

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery

import config
import database as db
import keyboards as kb

logging.basicConfig(level=logging.INFO)

router = Router()


class HabitForm(StatesGroup):
    # Добавление
    title = State()
    schedule_type = State()
    schedule_n = State()
    weekdays = State()
    reminder_time = State()
    # Редактирование
    edit_title = State()
    edit_time = State()


# =========================================================
#  Вспомогательные функции
# =========================================================

def level_title(level: int) -> str:
    """Звание по уровню (раздел 3 ТЗ)."""
    if level >= 50:
        return "Легенда"
    if level >= 35:
        return "Гуру дисциплины"
    if level >= 20:
        return "Мастер привычек"
    if level >= 10:
        return "Хозяин рутины"
    if level >= 5:
        return "Дисциплинированный"
    return "Новичок"


def _parse_hhmm(text: str) -> str | None:
    """Проверяет время в формате ЧЧ:ММ. Принимает '8:30' и '08:30', возвращает '08:30'."""
    parts = (text or "").strip().split(":")
    if len(parts) != 2:
        return None
    hh, mm = parts
    if not (hh.isdigit() and mm.isdigit()):
        return None
    h, m = int(hh), int(mm)
    if 0 <= h <= 23 and 0 <= m <= 59:
        return f"{h:02d}:{m:02d}"
    return None


def _active_user(telegram_id: int):
    """Возвращает пользователя, если у него выбран часовой пояс, иначе None."""
    user = db.get_user(telegram_id)
    if user is None or user["timezone"] is None:
        return None
    return user


def _owned_habit(habit_id: int, telegram_id: int):
    """Возвращает привычку, только если она принадлежит этому пользователю."""
    user = db.get_user(telegram_id)
    habit = db.get_habit(habit_id)
    if user is None or habit is None or habit["user_id"] != user["id"]:
        return None, None
    return habit, user


def _habit_card_text(habit, user) -> str:
    today = db.user_now(user["timezone"]).date()
    required = db.is_required_today(
        habit["schedule_type"], habit["schedule_data"], habit["start_date"], today
    )
    log = db.get_log(habit["id"], today.isoformat())
    if log is not None and log["status"] == "completed":
        status = "выполнено сегодня"
    elif required:
        status = "сегодня нужно выполнить"
    else:
        status = "сегодня выполнять не нужно"
    reminder = habit["reminder_time"] if habit["reminder_time"] else "выкл"
    return (
        f"{habit['title']}\n\n"
        f"Расписание: {db.format_schedule(habit['schedule_type'], habit['schedule_data'])}\n"
        f"Напоминание: {reminder}\n"
        f"Текущая серия: {habit['current_streak']} дн.\n"
        f"Статус: {status}"
    )


async def _send_habit_card(target: Message, habit_id: int, telegram_id: int) -> None:
    habit, user = _owned_habit(habit_id, telegram_id)
    if habit is None:
        await target.answer("Привычка не найдена.")
        return
    await target.answer(_habit_card_text(habit, user), reply_markup=kb.habit_card_keyboard(habit_id))


def _due_habits(user):
    """Привычки, обязательные сегодня и ещё не отмеченные."""
    today = db.user_now(user["timezone"]).date()
    due = []
    for h in db.get_habits(user["id"]):
        if h["is_paused"]:
            continue
        if not db.is_required_today(h["schedule_type"], h["schedule_data"], h["start_date"], today):
            continue
        if db.get_log(h["id"], today.isoformat()) is not None:
            continue
        due.append(h)
    return due


async def _guard_menu(message: Message, state: FSMContext) -> bool:
    """Если в диалоге нажали кнопку меню — не принимаем её как ввод."""
    if message.text in kb.MENU_BUTTONS:
        await message.answer(
            "Сейчас идёт ввод. Заверши его или нажми «Отмена» / команду /cancel.",
            reply_markup=kb.cancel_inline(),
        )
        return True
    return False


async def _proceed_after_schedule(target: Message, state: FSMContext, telegram_id: int) -> None:
    """Общий шаг после выбора расписания: для add — спросить время, для edit — сохранить."""
    data = await state.get_data()
    if data.get("mode") == "edit":
        db.update_habit_schedule(data["habit_id"], data["schedule_type"], data.get("schedule_data"))
        await state.clear()
        await target.answer("Расписание обновлено.")
        await _send_habit_card(target, data["habit_id"], telegram_id)
    else:
        await state.set_state(HabitForm.reminder_time)
        await target.answer(
            "Во сколько напоминать? Формат ЧЧ:ММ, например 08:30.\n"
            "Или нажми «Без напоминания», если уведомление не нужно.",
            reply_markup=kb.reminder_prompt_keyboard(),
        )


# =========================================================
#  /start, отмена, выбор часового пояса
# =========================================================

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = db.get_user(message.from_user.id)
    if user is None:
        db.create_user(message.from_user.id, message.from_user.username)
        user = db.get_user(message.from_user.id)

    if user["timezone"] is None:
        await message.answer(
            "Привет. Это трекер привычек.\n\n"
            "Сначала выбери свой часовой пояс — по нему будут считаться "
            "дни, напоминания и серии.",
            reply_markup=kb.timezone_keyboard(),
        )
    else:
        await message.answer("С возвращением. Главное меню ниже.", reply_markup=kb.main_menu())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=kb.main_menu())


@router.callback_query(F.data == "fsm_cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Отменено.", reply_markup=kb.main_menu())
    await callback.answer()


@router.callback_query(F.data.startswith("tz:"))
async def choose_timezone(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    tz_name = callback.data.split(":", 1)[1]
    db.set_timezone(callback.from_user.id, tz_name)
    await callback.message.edit_text(f"Часовой пояс сохранён: {tz_name}")
    await callback.message.answer(
        "Готово. Вот главное меню — отсюда работают все разделы.",
        reply_markup=kb.main_menu(),
    )
    await callback.answer()


# =========================================================
#  Диалог: ввод текста (состояния FSM). Регистрируем РАНЬШЕ кнопок меню.
# =========================================================

@router.message(HabitForm.title)
async def add_title(message: Message, state: FSMContext):
    if await _guard_menu(message, state):
        return
    title = (message.text or "").strip()
    if not (1 <= len(title) <= config.HABIT_TITLE_MAX_LEN):
        await message.answer(
            f"Название должно быть от 1 до {config.HABIT_TITLE_MAX_LEN} символов. Попробуй ещё раз.",
            reply_markup=kb.cancel_inline(),
        )
        return
    await state.update_data(title=title)
    await state.set_state(HabitForm.schedule_type)
    await message.answer("Как часто выполнять?", reply_markup=kb.schedule_type_keyboard())


@router.message(HabitForm.schedule_n)
async def add_schedule_n(message: Message, state: FSMContext):
    if await _guard_menu(message, state):
        return
    txt = (message.text or "").strip()
    if not txt.isdigit() or int(txt) < 1:
        await message.answer("Нужно целое число больше 0. Попробуй ещё раз (или /cancel).")
        return
    n = int(txt)
    if n == 1:
        await state.update_data(schedule_type="daily", schedule_data=None)
    else:
        await state.update_data(schedule_type="every_n_days", schedule_data=str(n))
    await _proceed_after_schedule(message, state, message.from_user.id)


@router.message(HabitForm.reminder_time)
async def add_reminder_time(message: Message, state: FSMContext):
    if await _guard_menu(message, state):
        return
    t = _parse_hhmm(message.text or "")
    if t is None:
        await message.answer(
            "Формат ЧЧ:ММ, например 08:30. Попробуй ещё раз, "
            "или нажми «Без напоминания».",
            reply_markup=kb.reminder_prompt_keyboard(),
        )
        return
    data = await state.get_data()
    user = db.get_user(message.from_user.id)
    today = db.user_now(user["timezone"]).date().isoformat()
    db.add_habit(
        user["id"], data["title"], data["schedule_type"], data.get("schedule_data"), t, today
    )
    await state.clear()
    await message.answer(
        f"Привычка «{data['title']}» добавлена.\n"
        f"Расписание: {db.format_schedule(data['schedule_type'], data.get('schedule_data'))}\n"
        f"Напоминание: {t}\n\n"
        "Напоминания и начисления заработают на следующих шагах.",
        reply_markup=kb.main_menu(),
    )


@router.message(HabitForm.edit_title)
async def edit_title_apply(message: Message, state: FSMContext):
    if await _guard_menu(message, state):
        return
    title = (message.text or "").strip()
    if not (1 <= len(title) <= config.HABIT_TITLE_MAX_LEN):
        await message.answer(
            f"От 1 до {config.HABIT_TITLE_MAX_LEN} символов. Ещё раз (или /cancel).",
            reply_markup=kb.cancel_inline(),
        )
        return
    data = await state.get_data()
    db.update_habit_title(data["habit_id"], title)
    await state.clear()
    await message.answer("Название обновлено.")
    await _send_habit_card(message, data["habit_id"], message.from_user.id)


@router.message(HabitForm.edit_time)
async def edit_time_apply(message: Message, state: FSMContext):
    if await _guard_menu(message, state):
        return
    t = _parse_hhmm(message.text or "")
    if t is None:
        await message.answer(
            "Формат ЧЧ:ММ, например 08:30. Ещё раз, или нажми «Без напоминания».",
            reply_markup=kb.reminder_prompt_keyboard(),
        )
        return
    data = await state.get_data()
    db.update_habit_time(data["habit_id"], t)
    await state.clear()
    await message.answer("Время обновлено.")
    await _send_habit_card(message, data["habit_id"], message.from_user.id)


# Если в шагах выбора (тип расписания / дни недели) пользователь пишет текст вместо кнопки.
@router.message(StateFilter(HabitForm.schedule_type, HabitForm.weekdays))
async def schedule_use_buttons(message: Message, state: FSMContext):
    await message.answer("Пожалуйста, выбери вариант кнопками выше или нажми /cancel.")


# =========================================================
#  Диалог: выбор расписания (inline-кнопки)
# =========================================================

@router.callback_query(HabitForm.schedule_type, F.data.startswith("st:"))
async def choose_schedule_type(callback: CallbackQuery, state: FSMContext):
    kind = callback.data.split(":", 1)[1]
    if kind == "daily":
        await state.update_data(schedule_type="daily", schedule_data=None)
        await callback.message.edit_text("Расписание: каждый день.")
        await _proceed_after_schedule(callback.message, state, callback.from_user.id)
    elif kind == "every2":
        await state.update_data(schedule_type="every_n_days", schedule_data="2")
        await callback.message.edit_text("Расписание: через день.")
        await _proceed_after_schedule(callback.message, state, callback.from_user.id)
    elif kind == "everyn":
        await state.set_state(HabitForm.schedule_n)
        await callback.message.edit_text("Через сколько дней повторять? Введи число (например, 3). /cancel — отмена.")
    elif kind == "weekdays":
        await state.update_data(wd_selected=[])
        await state.set_state(HabitForm.weekdays)
        await callback.message.edit_text("Выбери дни недели:", reply_markup=kb.weekday_keyboard(set()))
    await callback.answer()


@router.callback_query(HabitForm.weekdays, F.data.startswith("wd:"))
async def toggle_weekday(callback: CallbackQuery, state: FSMContext):
    part = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected = set(data.get("wd_selected", []))

    if part == "done":
        if not selected:
            await callback.answer("Выбери хотя бы один день.", show_alert=True)
            return
        days = sorted(selected)
        await state.update_data(schedule_type="weekdays", schedule_data=json.dumps(days))
        await callback.message.edit_text("Расписание: " + db.format_schedule("weekdays", json.dumps(days)))
        await _proceed_after_schedule(callback.message, state, callback.from_user.id)
        await callback.answer()
        return

    i = int(part)
    if i in selected:
        selected.discard(i)
    else:
        selected.add(i)
    await state.update_data(wd_selected=sorted(selected))
    await callback.message.edit_reply_markup(reply_markup=kb.weekday_keyboard(selected))
    await callback.answer()


@router.callback_query(StateFilter(HabitForm.reminder_time, HabitForm.edit_time), F.data == "rtoff")
async def reminder_off(callback: CallbackQuery, state: FSMContext):
    """Отключение напоминания: при добавлении завершает создание, при редактировании — снимает время."""
    cur_state = await state.get_state()
    data = await state.get_data()
    if cur_state == HabitForm.reminder_time.state:
        user = db.get_user(callback.from_user.id)
        today = db.user_now(user["timezone"]).date().isoformat()
        db.add_habit(
            user["id"], data["title"], data["schedule_type"], data.get("schedule_data"), None, today
        )
        await state.clear()
        await callback.message.edit_text(
            f"Привычка «{data['title']}» добавлена.\n"
            f"Расписание: {db.format_schedule(data['schedule_type'], data.get('schedule_data'))}\n"
            "Напоминание: выкл."
        )
        await callback.message.answer("Готово.", reply_markup=kb.main_menu())
    else:
        db.update_habit_time(data["habit_id"], None)
        await state.clear()
        await callback.message.edit_text("Напоминание выключено.")
        await _send_habit_card(callback.message, data["habit_id"], callback.from_user.id)
    await callback.answer()


# =========================================================
#  Карточка привычки и редактирование (inline-кнопки)
# =========================================================

@router.callback_query(F.data.startswith("habit:"))
async def open_habit(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    habit_id = int(callback.data.split(":", 1)[1])
    habit, user = _owned_habit(habit_id, callback.from_user.id)
    if habit is None:
        await callback.answer("Привычка не найдена.", show_alert=True)
        return
    await callback.message.edit_text(
        _habit_card_text(habit, user), reply_markup=kb.habit_card_keyboard(habit_id)
    )
    await callback.answer()


@router.callback_query(F.data == "back_list")
async def back_to_list(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = db.get_user(callback.from_user.id)
    habits = db.get_habits(user["id"]) if user else []
    if not habits:
        await callback.message.edit_text("У тебя пока нет привычек.")
    else:
        await callback.message.edit_text("Твои привычки:", reply_markup=kb.habits_list_keyboard(habits))
    await callback.answer()


@router.callback_query(F.data.startswith("et:"))
async def edit_title_start(callback: CallbackQuery, state: FSMContext):
    habit_id = int(callback.data.split(":", 1)[1])
    habit, _ = _owned_habit(habit_id, callback.from_user.id)
    if habit is None:
        await callback.answer("Не найдено.", show_alert=True)
        return
    await state.set_state(HabitForm.edit_title)
    await state.update_data(habit_id=habit_id)
    await callback.message.answer(
        f"Введи новое название (до {config.HABIT_TITLE_MAX_LEN} символов).",
        reply_markup=kb.cancel_inline(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("es:"))
async def edit_schedule_start(callback: CallbackQuery, state: FSMContext):
    habit_id = int(callback.data.split(":", 1)[1])
    habit, _ = _owned_habit(habit_id, callback.from_user.id)
    if habit is None:
        await callback.answer("Не найдено.", show_alert=True)
        return
    await state.set_state(HabitForm.schedule_type)
    await state.update_data(mode="edit", habit_id=habit_id)
    await callback.message.answer("Выбери новое расписание:", reply_markup=kb.schedule_type_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("etime:"))
async def edit_time_start(callback: CallbackQuery, state: FSMContext):
    habit_id = int(callback.data.split(":", 1)[1])
    habit, _ = _owned_habit(habit_id, callback.from_user.id)
    if habit is None:
        await callback.answer("Не найдено.", show_alert=True)
        return
    await state.set_state(HabitForm.edit_time)
    await state.update_data(habit_id=habit_id)
    await callback.message.answer(
        "Введи новое время напоминания (ЧЧ:ММ) "
        "или нажми «Без напоминания», чтобы отключить.",
        reply_markup=kb.reminder_prompt_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("del:"))
async def delete_ask(callback: CallbackQuery, state: FSMContext):
    habit_id = int(callback.data.split(":", 1)[1])
    habit, _ = _owned_habit(habit_id, callback.from_user.id)
    if habit is None:
        await callback.answer("Не найдено.", show_alert=True)
        return
    await callback.message.edit_text(
        f"Удалить «{habit['title']}»? История привычки будет стёрта.",
        reply_markup=kb.delete_confirm_keyboard(habit_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delyes:"))
async def delete_yes(callback: CallbackQuery, state: FSMContext):
    habit_id = int(callback.data.split(":", 1)[1])
    habit, _ = _owned_habit(habit_id, callback.from_user.id)
    if habit is None:
        await callback.answer("Не найдено.", show_alert=True)
        return
    db.delete_habit(habit_id)
    await callback.message.edit_text("Привычка удалена.")
    await callback.answer()


@router.callback_query(F.data.startswith("delno:"))
async def delete_no(callback: CallbackQuery, state: FSMContext):
    habit_id = int(callback.data.split(":", 1)[1])
    habit, user = _owned_habit(habit_id, callback.from_user.id)
    if habit is None:
        await callback.answer("Не найдено.", show_alert=True)
        return
    await callback.message.edit_text(
        _habit_card_text(habit, user), reply_markup=kb.habit_card_keyboard(habit_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("done:"))
async def mark_done(callback: CallbackQuery, state: FSMContext):
    habit_id = int(callback.data.split(":", 1)[1])
    habit, user = _owned_habit(habit_id, callback.from_user.id)
    if habit is None:
        await callback.answer("Не найдено.", show_alert=True)
        return
    today = db.user_now(user["timezone"]).date()
    if not db.is_required_today(
        habit["schedule_type"], habit["schedule_data"], habit["start_date"], today
    ):
        await callback.answer("Сегодня эта привычка не обязательна.", show_alert=True)
        return
    result = db.complete_habit(habit_id, today.isoformat())
    if result is None:
        await callback.answer("Уже отмечено сегодня.", show_alert=True)
    else:
        await callback.answer(
            f"+{result['xp']} XP, +{result['coins']} монета. Серия: {result['streak']} дн."
        )
    due = _due_habits(user)
    if not due:
        await callback.message.edit_text("Готово. Все привычки на сегодня отмечены.")
    else:
        await callback.message.edit_text(
            "Отметь выполненные за сегодня:", reply_markup=kb.due_habits_keyboard(due)
        )


# =========================================================
#  Кнопки главного меню
# =========================================================

@router.message(F.text == kb.BTN_ADD)
async def add_habit_start(message: Message, state: FSMContext):
    user = _active_user(message.from_user.id)
    if user is None:
        await message.answer("Сначала нажми /start и выбери часовой пояс.")
        return
    if db.count_habits(user["id"]) >= config.MAX_HABITS:
        await message.answer(
            f"Достигнут лимит привычек ({config.MAX_HABITS}). Удали одну, чтобы добавить новую."
        )
        return
    await state.set_state(HabitForm.title)
    await state.update_data(mode="add")
    await message.answer(
        f"Введи название привычки (до {config.HABIT_TITLE_MAX_LEN} символов).",
        reply_markup=kb.cancel_inline(),
    )


@router.message(F.text == kb.BTN_LIST)
async def my_habits(message: Message, state: FSMContext):
    user = _active_user(message.from_user.id)
    if user is None:
        await message.answer("Сначала нажми /start и выбери часовой пояс.")
        return
    habits = db.get_habits(user["id"])
    if not habits:
        await message.answer("У тебя пока нет привычек. Нажми «➕ Добавить привычку».")
    else:
        await message.answer("Твои привычки:", reply_markup=kb.habits_list_keyboard(habits))


@router.message(F.text == kb.BTN_CHECK)
async def check_menu(message: Message, state: FSMContext):
    user = _active_user(message.from_user.id)
    if user is None:
        await message.answer("Сначала нажми /start и выбери часовой пояс.")
        return
    if not db.get_habits(user["id"]):
        await message.answer("Сначала добавь привычки.")
        return
    due = _due_habits(user)
    if not due:
        await message.answer(
            "На сегодня отмечать нечего: всё выполнено или сегодня нет обязательных привычек."
        )
        return
    await message.answer(
        "Отметь выполненные за сегодня:", reply_markup=kb.due_habits_keyboard(due)
    )


@router.message(F.text == kb.BTN_BALANCE)
async def show_balance(message: Message):
    user = _active_user(message.from_user.id)
    if user is None:
        await message.answer("Сначала нажми /start и выбери часовой пояс.")
        return
    await message.answer(
        "Баланс\n\n"
        f"Монеты: {user['coins']}\n"
        f"Опыт (XP): {user['xp']}\n"
        f"Уровень: {user['level']} ({level_title(user['level'])})"
    )


@router.message(F.text == kb.BTN_SETTINGS)
async def show_settings(message: Message):
    user = _active_user(message.from_user.id)
    if user is None:
        await message.answer("Сначала нажми /start и выбери часовой пояс.")
        return
    await message.answer(
        f"Настройки\n\nТекущий часовой пояс: {user['timezone']}\n\n"
        "Чтобы сменить — выбери новый ниже.",
        reply_markup=kb.timezone_keyboard(),
    )


PLACEHOLDER_BUTTONS = {kb.BTN_STATS, kb.BTN_SHOP, kb.BTN_ACHIEVEMENTS}


@router.message(F.text.in_(PLACEHOLDER_BUTTONS))
async def placeholder(message: Message):
    await message.answer("Этот раздел появится на следующих шагах сборки.")


@router.message()
async def fallback(message: Message):
    await message.answer("Не понял. Пользуйся кнопками меню или нажми /start.")


# Любой устаревший inline-клик, который не подошёл ни к одному обработчику.
@router.callback_query()
async def stale_callback(callback: CallbackQuery):
    await callback.answer("Кнопка устарела. Открой раздел заново.")


# =========================================================
#  Запуск
# =========================================================

async def main():
    if not config.BOT_TOKEN:
        raise RuntimeError(
            "Не задан BOT_TOKEN. Добавь переменную окружения BOT_TOKEN "
            "(в Railway Variables или в .env)."
        )

    db.init_db()

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logging.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
