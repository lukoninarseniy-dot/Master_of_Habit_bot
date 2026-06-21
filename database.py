import json
import sqlite3
from datetime import datetime, date
from zoneinfo import ZoneInfo

import config


def get_connection() -> sqlite3.Connection:
    """Открывает соединение с базой. row_factory=Row даёт обращаться к полям по имени."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Создаёт все таблицы по разделу 14 ТЗ, если их ещё нет."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id  INTEGER UNIQUE NOT NULL,
            username     TEXT,
            timezone     TEXT,
            xp           INTEGER NOT NULL DEFAULT 0,
            level        INTEGER NOT NULL DEFAULT 1,
            coins        INTEGER NOT NULL DEFAULT 0,
            freeze_count INTEGER NOT NULL DEFAULT 0,
            created_at   TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS habits (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL REFERENCES users(id),
            title          TEXT NOT NULL,
            category       TEXT,
            schedule_type  TEXT NOT NULL,
            schedule_data  TEXT,
            reminder_time  TEXT,
            current_streak INTEGER NOT NULL DEFAULT 0,
            longest_streak INTEGER NOT NULL DEFAULT 0,
            start_date     TEXT,
            is_active      INTEGER NOT NULL DEFAULT 1,
            is_paused      INTEGER NOT NULL DEFAULT 0,
            created_at     TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS habit_logs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id   INTEGER NOT NULL REFERENCES habits(id),
            date       TEXT NOT NULL,
            status     TEXT NOT NULL,
            mood       TEXT,
            created_at TEXT,
            UNIQUE(habit_id, date)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS shop_operations (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL REFERENCES users(id),
            operation_type TEXT NOT NULL,
            cost           INTEGER,
            habit_id       INTEGER,
            payload        TEXT,
            created_at     TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_achievements (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id          INTEGER NOT NULL REFERENCES users(id),
            achievement_code TEXT NOT NULL,
            unlocked_at      TEXT,
            UNIQUE(user_id, achievement_code)
        )
    """)

    conn.commit()
    conn.close()


def _now_utc_iso() -> str:
    return datetime.now(ZoneInfo("UTC")).isoformat(timespec="seconds")


# =========================================================
#  Пользователи
# =========================================================

def get_user(telegram_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return row


def create_user(telegram_id: int, username: str | None) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO users (telegram_id, username, created_at) VALUES (?, ?, ?)",
        (telegram_id, username, _now_utc_iso()),
    )
    conn.commit()
    conn.close()


def set_timezone(telegram_id: int, timezone: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE users SET timezone = ? WHERE telegram_id = ?",
        (timezone, telegram_id),
    )
    conn.commit()
    conn.close()


def user_now(timezone: str) -> datetime:
    """Текущее дата-время в часовом поясе пользователя."""
    return datetime.now(ZoneInfo(timezone))


# =========================================================
#  Привычки
# =========================================================

def count_habits(user_id: int) -> int:
    conn = get_connection()
    n = conn.execute(
        "SELECT COUNT(*) FROM habits WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    conn.close()
    return n


def add_habit(
    user_id: int,
    title: str,
    schedule_type: str,
    schedule_data: str | None,
    reminder_time: str,
    start_date: str,
) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO habits
           (user_id, title, schedule_type, schedule_data, reminder_time, start_date, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, title, schedule_type, schedule_data, reminder_time, start_date, _now_utc_iso()),
    )
    conn.commit()
    habit_id = cur.lastrowid
    conn.close()
    return habit_id


def get_habits(user_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM habits WHERE user_id = ? ORDER BY id", (user_id,)
    ).fetchall()
    conn.close()
    return rows


def get_habit(habit_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM habits WHERE id = ?", (habit_id,)
    ).fetchone()
    conn.close()
    return row


def update_habit_title(habit_id: int, title: str) -> None:
    conn = get_connection()
    conn.execute("UPDATE habits SET title = ? WHERE id = ?", (title, habit_id))
    conn.commit()
    conn.close()


def update_habit_schedule(habit_id: int, schedule_type: str, schedule_data: str | None) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE habits SET schedule_type = ?, schedule_data = ? WHERE id = ?",
        (schedule_type, schedule_data, habit_id),
    )
    conn.commit()
    conn.close()


def update_habit_time(habit_id: int, reminder_time: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE habits SET reminder_time = ? WHERE id = ?", (reminder_time, habit_id)
    )
    conn.commit()
    conn.close()


def delete_habit(habit_id: int) -> None:
    """Полностью удаляет привычку и её логи."""
    conn = get_connection()
    conn.execute("DELETE FROM habit_logs WHERE habit_id = ?", (habit_id,))
    conn.execute("DELETE FROM habits WHERE id = ?", (habit_id,))
    conn.commit()
    conn.close()


# =========================================================
#  Логика расписания (раздел 4.2 ТЗ) — нужна для списка и для штрафов на Шаге 4
# =========================================================

def is_required_today(
    schedule_type: str, schedule_data: str | None, start_date_str: str, today: date
) -> bool:
    """Обязателен ли указанный день для этой привычки.

    День раньше даты создания привычки (start_date) обязательным не считается —
    это важно, чтобы планировщик не штрафовал за «пропуски» до появления привычки.
    """
    try:
        start = date.fromisoformat(start_date_str)
    except (TypeError, ValueError):
        return False
    if today < start:
        return False

    if schedule_type == "daily":
        return True

    if schedule_type == "every_n_days":
        try:
            n = int(schedule_data)
        except (TypeError, ValueError):
            return False
        if n < 1:
            return False
        return (today - start).days % n == 0

    if schedule_type == "weekdays":
        try:
            days = json.loads(schedule_data)
        except (TypeError, ValueError):
            return False
        return today.weekday() in days

    return False  # custom — резерв на будущее


def format_schedule(schedule_type: str, schedule_data: str | None) -> str:
    """Человекочитаемое описание расписания."""
    if schedule_type == "daily":
        return "каждый день"

    if schedule_type == "every_n_days":
        try:
            n = int(schedule_data)
        except (TypeError, ValueError):
            return "—"
        if n == 2:
            return "через день"
        return f"каждые {n} дн."

    if schedule_type == "weekdays":
        try:
            days = json.loads(schedule_data)
        except (TypeError, ValueError):
            return "—"
        return ", ".join(config.WEEKDAY_NAMES[d] for d in sorted(days))

    return "—"


# =========================================================
#  Логи выполнения (Шаг 3)
# =========================================================

def get_log(habit_id: int, date_str: str) -> sqlite3.Row | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM habit_logs WHERE habit_id = ? AND date = ?",
        (habit_id, date_str),
    ).fetchone()
    conn.close()
    return row


def complete_habit(habit_id: int, date_str: str) -> dict | None:
    """Отмечает привычку выполненной за указанную дату.

    Возвращает словарь с начислениями и новой серией, либо None, если запись
    за этот день уже есть (защита UNIQUE(habit_id, date) — не начисляем дважды).
    """
    conn = get_connection()
    cur = conn.execute(
        "INSERT OR IGNORE INTO habit_logs (habit_id, date, status, created_at) "
        "VALUES (?, ?, 'completed', ?)",
        (habit_id, date_str, _now_utc_iso()),
    )
    if cur.rowcount == 0:
        conn.close()
        return None  # уже отмечено за этот день

    # Растёт серия; заодно обновляем рекорд longest_streak.
    conn.execute(
        "UPDATE habits SET current_streak = current_streak + 1, "
        "longest_streak = MAX(longest_streak, current_streak + 1) WHERE id = ?",
        (habit_id,),
    )

    # Начисляем XP и монеты владельцу привычки.
    owner = conn.execute("SELECT user_id FROM habits WHERE id = ?", (habit_id,)).fetchone()
    conn.execute(
        "UPDATE users SET xp = xp + ?, coins = coins + ? WHERE id = ?",
        (config.XP_PER_COMPLETION, config.COINS_PER_COMPLETION, owner["user_id"]),
    )

    new_streak = conn.execute(
        "SELECT current_streak FROM habits WHERE id = ?", (habit_id,)
    ).fetchone()[0]

    conn.commit()
    conn.close()
    return {
        "xp": config.XP_PER_COMPLETION,
        "coins": config.COINS_PER_COMPLETION,
        "streak": new_streak,
    }


# =========================================================
#  Для планировщика (Шаг 4)
# =========================================================

def get_all_users_with_tz() -> list[sqlite3.Row]:
    """Все пользователи, у которых выбран часовой пояс (по ним работает планировщик)."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM users WHERE timezone IS NOT NULL").fetchall()
    conn.close()
    return rows


def apply_miss(habit_id: int, date_str: str) -> bool:
    """Помечает день пропущенным: штраф монетами (не ниже 0) и обнуление серии.

    Возвращает True, если штраф применён сейчас. Если запись за этот день уже была
    (выполнено / пропуск / штраф) — возвращает False и ничего не меняет.
    Это и есть идемпотентность: повторная проверка того же дня не штрафует дважды.
    """
    conn = get_connection()
    cur = conn.execute(
        "INSERT OR IGNORE INTO habit_logs (habit_id, date, status, created_at) "
        "VALUES (?, ?, 'missed', ?)",
        (habit_id, date_str, _now_utc_iso()),
    )
    if cur.rowcount == 0:
        conn.close()
        return False

    owner = conn.execute("SELECT user_id FROM habits WHERE id = ?", (habit_id,)).fetchone()
    conn.execute(
        "UPDATE users SET coins = MAX(0, coins - ?) WHERE id = ?",
        (config.COINS_PENALTY, owner["user_id"]),
    )
    conn.execute("UPDATE habits SET current_streak = 0 WHERE id = ?", (habit_id,))
    conn.commit()
    conn.close()
    return True
