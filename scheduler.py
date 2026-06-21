"""Планировщик: напоминания, вечерняя проверка и закрытие дня со штрафами.

Подход к часовым поясам: один тик раз в минуту (по UTC, в начале каждой минуты).
На каждом тике для КАЖДОГО пользователя считаем его локальное время и решаем,
что нужно сделать именно сейчас. Так корректно поддерживаются любые таймзоны.
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import database as db
import achievements as ach

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 30   # на сколько дней назад «доштрафовать» после простоя бота
EVENING_HOUR = 22    # час вечерней проверки

# Защита от повторной отправки одного и того же сообщения в рамках процесса.
_sent_keys: set[str] = set()


def _seen(key: str) -> bool:
    """True, если по ключу уже отправляли. Иначе помечает ключ и возвращает False."""
    if key in _sent_keys:
        return True
    if len(_sent_keys) > 20000:
        _sent_keys.clear()
    _sent_keys.add(key)
    return False


# =========================================================
#  Закрытие дня (штрафы) — синхронная работа с базой
# =========================================================

def _close_out_day(user, day) -> None:
    """Закрывает один прошедший день: за обязательные, но не отмеченные привычки —
    штраф и обнуление серии. Полностью идемпотентно (см. db.apply_miss).
    Ачивки за пропуски выдаются молча (без ночных уведомлений)."""
    for h in db.get_habits(user["id"]):
        if h["is_paused"]:
            continue
        if not db.is_required_today(h["schedule_type"], h["schedule_data"], h["start_date"], day):
            continue
        prior_streak = h["current_streak"]
        if db.apply_miss(h["id"], day.isoformat()):
            ach.check_all(user["id"], event="miss", prior_streak=prior_streak)


def run_startup_catchup() -> None:
    """При запуске закрывает дни, которые могли быть пропущены, пока бот не работал.
    Идёт по каждому пользователю и его последним LOOKBACK_DAYS дням (без сегодня)."""
    for user in db.get_all_users_with_tz():
        try:
            today = datetime.now(ZoneInfo(user["timezone"])).date()
            for i in range(1, LOOKBACK_DAYS + 1):
                _close_out_day(user, today - timedelta(days=i))
        except Exception:
            logger.exception("Ошибка catch-up для пользователя %s", user["telegram_id"])


# =========================================================
#  Напоминания и вечерняя проверка — асинхронная отправка
# =========================================================

async def _send_reminders(bot, user, today, hhmm) -> None:
    for h in db.get_habits(user["id"]):
        if h["is_paused"]:
            continue
        if not h["reminder_time"] or h["reminder_time"] != hhmm:
            continue
        if not db.is_required_today(h["schedule_type"], h["schedule_data"], h["start_date"], today):
            continue
        if db.get_log(h["id"], today.isoformat()) is not None:
            continue
        if _seen(f"rem:{h['id']}:{today.isoformat()}"):
            continue
        try:
            await bot.send_message(user["telegram_id"], f"Пора выполнить привычку «{h['title']}».")
        except Exception:
            logger.exception("Не удалось отправить напоминание %s", user["telegram_id"])


async def _evening_check(bot, user, today) -> None:
    """В 22:00 предупреждаем о невыполненных привычках (только тех, где напоминания включены)."""
    pending = []
    for h in db.get_habits(user["id"]):
        if h["is_paused"]:
            continue
        if not h["reminder_time"]:  # напоминания у привычки выключены — не тревожим
            continue
        if not db.is_required_today(h["schedule_type"], h["schedule_data"], h["start_date"], today):
            continue
        if db.get_log(h["id"], today.isoformat()) is not None:
            continue
        pending.append(h["title"])

    if not pending or _seen(f"eve:{user['id']}:{today.isoformat()}"):
        return

    if len(pending) == 1:
        text = (
            f"Сегодня не отмечена привычка «{pending[0]}». "
            "Если не выполнить до полуночи — спишутся монеты и серия обнулится."
        )
    else:
        names = ", ".join(f"«{t}»" for t in pending)
        text = (
            f"Сегодня не отмечены привычки: {names}. "
            "Если не выполнить до полуночи — спишутся монеты и серии обнулятся."
        )
    try:
        await bot.send_message(user["telegram_id"], text)
    except Exception:
        logger.exception("Не удалось отправить вечернее предупреждение %s", user["telegram_id"])


# =========================================================
#  Тик раз в минуту
# =========================================================

async def _process_user(bot, user) -> None:
    try:
        now = datetime.now(ZoneInfo(user["timezone"]))
    except Exception:
        return
    today = now.date()
    hhmm = now.strftime("%H:%M")

    # Полночь — закрываем вчерашний день (штрафы), молча.
    if hhmm == "00:00":
        _close_out_day(user, today - timedelta(days=1))

    # Напоминания в их время.
    await _send_reminders(bot, user, today, hhmm)

    # Вечерняя проверка.
    if hhmm == f"{EVENING_HOUR:02d}:00":
        await _evening_check(bot, user, today)


async def _tick(bot) -> None:
    for user in db.get_all_users_with_tz():
        try:
            await _process_user(bot, user)
        except Exception:
            logger.exception("Ошибка тика для пользователя %s", user["telegram_id"])


def setup_scheduler(bot) -> AsyncIOScheduler:
    """Создаёт и запускает планировщик с тиком в начале каждой минуты."""
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _tick,
        CronTrigger(second=0),
        args=[bot],
        id="minute_tick",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    return scheduler
