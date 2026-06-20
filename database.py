import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import config


def get_connection() -> sqlite3.Connection:
    """Открывает соединение с базой. row_factory=Row даёт обращаться к полям по имени."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Создаёт все таблицы, если их ещё нет. Вызывается один раз при старте бота.

    Таблицы создаём сразу все (по разделу 14 ТЗ), хотя на Шаге 1 используется
    только users. Так на следующих шагах не придётся менять схему базы.
    """
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
    """Текущее время UTC в виде строки (для служебных меток created_at)."""
    return datetime.now(ZoneInfo("UTC")).isoformat(timespec="seconds")


# --- Работа с пользователями ---

def get_user(telegram_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return row


def create_user(telegram_id: int, username: str | None) -> None:
    """Создаёт пользователя без часового пояса (его выберем сразу после /start)."""
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
    """Текущее дата-время в часовом поясе пользователя.

    Понадобится на следующих шагах (дни, напоминания, штрафы считаются
    по времени пользователя).
    """
    return datetime.now(ZoneInfo(timezone))
