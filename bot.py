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
import achievements as ach
from scheduler import setup_scheduler, run_startup_catchup

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


class ShopForm(StatesGroup):
    replace_text = State()  # ввод текста замены при покупке «замены на день»


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


def level_from_xp(xp: int) -> int:
    """Уровень по XP. Чтобы достичь уровня L, нужно накопить 50*(L-1)*L XP."""
    level = 1
    while 50 * level * (level + 1) <= xp:
        level += 1
    return level


def _coins_word(n: int) -> str:
    """Склонение слова «монета» по числу."""
    n = abs(n) % 100
    if 11 <= n <= 14:
        return "монет"
    d = n % 10
    if d == 1:
        return "монета"
    if 2 <= d <= 4:
        return "монеты"
    return "монет"


def _habit_stats_text(habit, user) -> str:
    s = db.get_habit_stats(habit["id"])
    completed, missed, skips = s["completed"], s["missed"], s["skips"]
    active = completed + missed + skips
    denom = completed + missed  # обязательные дни минус официальные пропуски
    percent = f"{round(completed / denom * 100)}%" if denom > 0 else "—"
    level = level_from_xp(user["xp"])
    return (
        f"{habit['title']}\n\n"
        f"Активных дней: {active}\n"
        f"Выполнено: {completed}\n"
        f"Пропущено: {missed}\n"
        f"Официальных пропусков: {skips}\n"
        f"Текущая серия: {habit['current_streak']} дн.\n"
        f"Лучшая серия: {habit['longest_streak']} дн.\n\n"
        f"Процент выполнения: {percent}\n\n"
        f"Текущий баланс: {user['coins']} {_coins_word(user['coins'])}\n"
        f"Уровень: {level} ({level_title(level)})"
    )


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


def _shop_text(user) -> str:
    return (
        "Магазин\n"
        f"Баланс: {user['coins']} {_coins_word(user['coins'])}\n\n"
        "Выбери покупку:"
    )


async def _finalize_replacement(target: Message, state: FSMContext, telegram_id: int, alt_text):
    data = await state.get_data()
    habit_id = data["habit_id"]
    habit, user = _owned_habit(habit_id, telegram_id)
    await state.clear()
    if habit is None:
        await target.answer("Привычка не найдена.")
        return
    today = db.user_now(user["timezone"]).date().isoformat()
    res = db.buy_replacement(user["id"], habit_id, today, alt_text)
    if res["status"] == "no_coins":
        await target.answer(f"Недостаточно монет: нужно {res['need']}, у тебя {res['have']}.")
    elif res["status"] == "already_logged":
        await target.answer("За сегодня по этой привычке уже есть запись.")
    else:
        extra = f" Замена: {alt_text}." if alt_text else ""
        await target.answer(
            f"Замена для «{habit['title']}» засчитана как выполнение.{extra} "
            f"Серия: {res['streak']} дн. Списано {res['cost']} {_coins_word(res['cost'])}.",
            reply_markup=kb.main_menu(),
        )
        newly = ach.check_all(
            user["id"], now=db.user_now(user["timezone"]), event="completion", habit_id=habit_id
        )
        await _notify_achievements(target, newly)


async def _notify_achievements(target: Message, newly) -> None:
    if not newly:
        return
    if len(newly) == 1:
        a = newly[0]
        reward = f"+{a['xp']} XP"
        if a["coins"]:
            reward += f", +{a['coins']} {_coins_word(a['coins'])}"
        await target.answer(f"Достижение получено: {a['icon']} {a['title']}! {reward}")
    else:
        lines = ["Открыты достижения:"]
        for a in newly:
            reward = f"+{a['xp']} XP" + (f", +{a['coins']}" if a["coins"] else "")
            lines.append(f"{a['icon']} {a['title']} ({reward})")
        await target.answer("\n".join(lines))


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
        f"Напоминание: {t}",
        reply_markup=kb.main_menu(),
    )
    newly = ach.check_all(user["id"], event="create")
    await _notify_achievements(message, newly)


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


@router.message(ShopForm.replace_text)
async def shop_replace_text(message: Message, state: FSMContext):
    if await _guard_menu(message, state):
        return
    alt = (message.text or "").strip()[:200] or None
    await _finalize_replacement(message, state, message.from_user.id, alt)


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
        newly = ach.check_all(user["id"], event="create")
        await _notify_achievements(callback.message, newly)
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
    habit, user = _owned_habit(habit_id, callback.from_user.id)
    if habit is None:
        await callback.answer("Не найдено.", show_alert=True)
        return
    start_date = habit["start_date"]
    today_iso = db.user_now(user["timezone"]).date().isoformat()
    db.delete_habit(habit_id)
    await callback.message.edit_text("Привычка удалена.")
    await callback.answer()
    newly = ach.check_just_looking(user["id"], start_date, today_iso)
    await _notify_achievements(callback.message, newly)


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
    now_dt = db.user_now(user["timezone"])
    today = now_dt.date()
    if not db.is_required_today(
        habit["schedule_type"], habit["schedule_data"], habit["start_date"], today
    ):
        await callback.answer("Сегодня эта привычка не обязательна.", show_alert=True)
        return
    result = db.complete_habit(habit_id, today.isoformat())
    perfect = None
    if result is None:
        await callback.answer("Уже отмечено сегодня.", show_alert=True)
    else:
        toast = (
            f"+{result['xp']} XP, +{result['coins']} {_coins_word(result['coins'])}. "
            f"Серия: {result['streak']} дн."
        )
        if result["milestone"]:
            toast += " Веха серии!"
        await callback.answer(toast)
        perfect = db.try_award_perfect_day(user["id"], today.isoformat())

    due = _due_habits(user)
    if not due:
        await callback.message.edit_text("Готово. Все привычки на сегодня отмечены.")
    else:
        await callback.message.edit_text(
            "Отметь выполненные за сегодня:", reply_markup=kb.due_habits_keyboard(due)
        )

    if perfect:
        await callback.message.answer(
            "Идеальный день! Все привычки на сегодня выполнены. "
            f"Бонус +{perfect['xp']} XP, +{perfect['coins']} {_coins_word(perfect['coins'])}."
        )

    if result is not None:
        newly = ach.check_all(
            user["id"], now=now_dt, event="completion",
            habit_id=habit_id, perfect_day=bool(perfect),
        )
        await _notify_achievements(callback.message, newly)


@router.callback_query(F.data.startswith("stat:"))
async def stat_open(callback: CallbackQuery, state: FSMContext):
    habit_id = int(callback.data.split(":", 1)[1])
    habit, user = _owned_habit(habit_id, callback.from_user.id)
    if habit is None:
        await callback.answer("Не найдено.", show_alert=True)
        return
    await callback.message.edit_text(
        _habit_stats_text(habit, user), reply_markup=kb.stat_card_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "stat_back")
async def stat_back(callback: CallbackQuery, state: FSMContext):
    user = db.get_user(callback.from_user.id)
    habits = db.get_habits(user["id"]) if user else []
    if not habits:
        await callback.message.edit_text("Сначала добавь привычки.")
    else:
        await callback.message.edit_text(
            "Статистика по привычкам:", reply_markup=kb.stats_list_keyboard(habits)
        )
    await callback.answer()


# =========================================================
#  Магазин (inline-кнопки)
# =========================================================

@router.callback_query(F.data == "shop_back")
async def shop_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = db.get_user(callback.from_user.id)
    await callback.message.edit_text(_shop_text(user), reply_markup=kb.shop_keyboard())
    await callback.answer()


@router.callback_query(F.data == "shop:skip")
async def shop_skip(callback: CallbackQuery, state: FSMContext):
    user = _active_user(callback.from_user.id)
    if user is None:
        await callback.answer("Не найдено.", show_alert=True)
        return
    if user["coins"] < config.SHOP_OFFICIAL_SKIP_COST:
        await callback.answer(
            f"Недостаточно монет: нужно {config.SHOP_OFFICIAL_SKIP_COST}, у тебя {user['coins']}.",
            show_alert=True,
        )
        return
    due = _due_habits(user)
    if not due:
        await callback.message.edit_text(
            "Сегодня нечего пропускать: всё отмечено или сегодня нет обязательных привычек.",
            reply_markup=kb.shop_habits_keyboard([], "skip"),
        )
    else:
        await callback.message.edit_text(
            "Для какой привычки купить официальный пропуск на сегодня?",
            reply_markup=kb.shop_habits_keyboard(due, "skip"),
        )
    await callback.answer()


@router.callback_query(F.data == "shop:replace")
async def shop_replace(callback: CallbackQuery, state: FSMContext):
    user = _active_user(callback.from_user.id)
    if user is None:
        await callback.answer("Не найдено.", show_alert=True)
        return
    if user["coins"] < config.SHOP_REPLACE_COST:
        await callback.answer(
            f"Недостаточно монет: нужно {config.SHOP_REPLACE_COST}, у тебя {user['coins']}.",
            show_alert=True,
        )
        return
    due = _due_habits(user)
    if not due:
        await callback.message.edit_text(
            "Сегодня нечего заменять: всё отмечено или сегодня нет обязательных привычек.",
            reply_markup=kb.shop_habits_keyboard([], "repl"),
        )
    else:
        await callback.message.edit_text(
            "Какую привычку заменить на сегодня?",
            reply_markup=kb.shop_habits_keyboard(due, "repl"),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("skipsel:"))
async def shop_skip_select(callback: CallbackQuery, state: FSMContext):
    habit_id = int(callback.data.split(":", 1)[1])
    habit, _ = _owned_habit(habit_id, callback.from_user.id)
    if habit is None:
        await callback.answer("Не найдено.", show_alert=True)
        return
    await callback.message.edit_text(
        f"Купить официальный пропуск для «{habit['title']}» на сегодня "
        f"за {config.SHOP_OFFICIAL_SKIP_COST} монеты?\n\n"
        "День станет нейтральным: штрафа не будет, серия сохранится, выполнение не засчитывается.",
        reply_markup=kb.skip_confirm_keyboard(habit_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("skipbuy:"))
async def shop_skip_buy(callback: CallbackQuery, state: FSMContext):
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
    res = db.buy_official_skip(user["id"], habit_id, today.isoformat())
    if res["status"] == "no_coins":
        await callback.answer(
            f"Недостаточно монет: нужно {res['need']}, у тебя {res['have']}.", show_alert=True
        )
    elif res["status"] == "already_logged":
        await callback.answer("За сегодня по этой привычке уже есть запись.", show_alert=True)
    else:
        await callback.answer(f"Куплено. Списано {res['cost']} {_coins_word(res['cost'])}.")
        await callback.message.edit_text(
            f"Официальный пропуск для «{habit['title']}» на сегодня куплен. "
            "День нейтральный, серия сохранится."
        )
        newly = ach.check_all(user["id"], event="purchase")
        await _notify_achievements(callback.message, newly)


@router.callback_query(F.data.startswith("replsel:"))
async def shop_replace_select(callback: CallbackQuery, state: FSMContext):
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
    if db.get_log(habit_id, today.isoformat()) is not None:
        await callback.answer("За сегодня по этой привычке уже есть запись.", show_alert=True)
        return
    await state.set_state(ShopForm.replace_text)
    await state.update_data(habit_id=habit_id)
    await callback.message.edit_text(
        f"Замена для «{habit['title']}» на сегодня.\n"
        "Напиши, чем заменяешь (коротко), или нажми «Пропустить».",
        reply_markup=kb.replace_text_keyboard(),
    )
    await callback.answer()


@router.callback_query(ShopForm.replace_text, F.data == "repl_notext")
async def shop_replace_notext(callback: CallbackQuery, state: FSMContext):
    await _finalize_replacement(callback.message, state, callback.from_user.id, None)
    await callback.answer()


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


@router.message(F.text == kb.BTN_STATS)
async def show_stats(message: Message, state: FSMContext):
    user = _active_user(message.from_user.id)
    if user is None:
        await message.answer("Сначала нажми /start и выбери часовой пояс.")
        return
    habits = db.get_habits(user["id"])
    if not habits:
        await message.answer("Сначала добавь привычки.")
        return
    await message.answer("Статистика по привычкам:", reply_markup=kb.stats_list_keyboard(habits))


@router.message(F.text == kb.BTN_SHOP)
async def open_shop(message: Message, state: FSMContext):
    user = _active_user(message.from_user.id)
    if user is None:
        await message.answer("Сначала нажми /start и выбери часовой пояс.")
        return
    await message.answer(_shop_text(user), reply_markup=kb.shop_keyboard())


@router.message(F.text == kb.BTN_BALANCE)
async def show_balance(message: Message):
    user = _active_user(message.from_user.id)
    if user is None:
        await message.answer("Сначала нажми /start и выбери часовой пояс.")
        return
    xp = user["xp"]
    level = level_from_xp(xp)
    next_threshold = 50 * level * (level + 1)
    remaining = next_threshold - xp
    await message.answer(
        "Баланс\n\n"
        f"Монеты: {user['coins']}\n"
        f"Опыт (XP): {xp}\n"
        f"Уровень: {level} ({level_title(level)})\n"
        f"До уровня {level + 1}: ещё {remaining} XP"
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


@router.message(F.text == kb.BTN_ACHIEVEMENTS)
async def show_achievements(message: Message, state: FSMContext):
    user = _active_user(message.from_user.id)
    if user is None:
        await message.answer("Сначала нажми /start и выбери часовой пояс.")
        return
    unlocked = db.get_unlocked_codes(user["id"])
    got = sum(1 for a in ach.CATALOG if a["code"] in unlocked)
    lines = [f"Достижения: {got} из {len(ach.CATALOG)}", ""]
    for a in ach.CATALOG:
        if a["code"] in unlocked:
            lines.append(f"✅ {a['icon']} {a['title']} — {a['desc']}")
        elif a["hidden"]:
            lines.append("🔒 ??? — секрет")
        else:
            lines.append(f"🔒 {a['icon']} {a['title']} — {a['desc']}")
    await message.answer("\n".join(lines))


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

    # Планировщик: напоминания, вечерняя проверка в 22:00, штрафы в полночь.
    scheduler = setup_scheduler(bot)
    # Закрываем дни, пропущенные пока бот не работал (идемпотентно).
    run_startup_catchup()

    logging.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
