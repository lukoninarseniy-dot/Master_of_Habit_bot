import json
import sqlite3
from datetime import datetime, date, timedelta
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
            local_time TEXT,
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            date       TEXT NOT NULL,
            event_type TEXT NOT NULL,
            created_at TEXT,
            UNIQUE(user_id, date, event_type)
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
    new_streak = conn.execute(
        "SELECT current_streak FROM habits WHERE id = ?", (habit_id,)
    ).fetchone()[0]

    # Базовое начисление + бонус за веху серии (7 / 14 / 30 / 100 дней).
    xp = config.XP_PER_COMPLETION
    coins = config.COINS_PER_COMPLETION
    milestone = None
    if new_streak in config.STREAK_MILESTONES:
        m_xp, m_coins = config.STREAK_MILESTONES[new_streak]
        xp += m_xp
        coins += m_coins
        milestone = new_streak

    owner = conn.execute("SELECT user_id FROM habits WHERE id = ?", (habit_id,)).fetchone()
    conn.execute(
        "UPDATE users SET xp = xp + ?, coins = coins + ? WHERE id = ?",
        (xp, coins, owner["user_id"]),
    )

    conn.commit()
    conn.close()
    return {"xp": xp, "coins": coins, "streak": new_streak, "milestone": milestone}


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


# =========================================================
#  Идеальный день и статистика (Шаг 5)
# =========================================================

def try_award_perfect_day(user_id: int, date_str: str) -> dict | None:
    """Если ВСЕ обязательные сегодня привычки выполнены — выдаёт бонус «идеальный день».

    Идемпотентно: не больше одного такого бонуса в день (таблица daily_events).
    Возвращает начисление или None.
    """
    day = date.fromisoformat(date_str)
    habits = [h for h in get_habits(user_id) if not h["is_paused"]]
    required = [
        h for h in habits
        if is_required_today(h["schedule_type"], h["schedule_data"], h["start_date"], day)
    ]
    if not required:
        return None
    did_something = False
    for h in required:
        log = get_log(h["id"], date_str)
        if log is None:
            return None  # обязательная, но день ещё не закрыт
        status = log["status"]
        if status in ("official_skip", "freeze"):
            continue  # нейтральный день — не мешает идеальному
        if status in ("completed", "temporary_replace"):
            did_something = True
            continue
        return None  # пропуск
    if not did_something:
        return None  # все обязательные были пропусками — это не «идеальный день»

    conn = get_connection()
    cur = conn.execute(
        "INSERT OR IGNORE INTO daily_events (user_id, date, event_type, created_at) "
        "VALUES (?, ?, 'perfect_day', ?)",
        (user_id, date_str, _now_utc_iso()),
    )
    if cur.rowcount == 0:
        conn.close()
        return None
    conn.execute(
        "UPDATE users SET xp = xp + ?, coins = coins + ? WHERE id = ?",
        (config.XP_PERFECT_DAY, config.COINS_PERFECT_DAY, user_id),
    )
    conn.commit()
    conn.close()
    return {"xp": config.XP_PERFECT_DAY, "coins": config.COINS_PERFECT_DAY}


def get_habit_stats(habit_id: int) -> dict:
    """Сводка по логам привычки для экрана статистики.

    Временная замена (когда появится на Шаге 6) считается как выполнение,
    официальный пропуск — как нейтральный день.
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT status, COUNT(*) AS c FROM habit_logs WHERE habit_id = ? GROUP BY status",
        (habit_id,),
    ).fetchall()
    conn.close()
    counts = {r["status"]: r["c"] for r in rows}
    completed = counts.get("completed", 0) + counts.get("temporary_replace", 0)
    missed = counts.get("missed", 0)
    skips = counts.get("official_skip", 0)
    return {"completed": completed, "missed": missed, "skips": skips}


# =========================================================
#  Магазин (Шаг 6)
# =========================================================

def buy_official_skip(user_id: int, habit_id: int, date_str: str) -> dict:
    """Покупка официального пропуска на день: день нейтральный, штрафа нет, серия не рвётся.

    Возвращает {"status": "ok"|"no_coins"|"already_logged", ...}.
    """
    conn = get_connection()
    coins = conn.execute("SELECT coins FROM users WHERE id = ?", (user_id,)).fetchone()["coins"]
    if coins < config.SHOP_OFFICIAL_SKIP_COST:
        conn.close()
        return {"status": "no_coins", "have": coins, "need": config.SHOP_OFFICIAL_SKIP_COST}

    cur = conn.execute(
        "INSERT OR IGNORE INTO habit_logs (habit_id, date, status, created_at) "
        "VALUES (?, ?, 'official_skip', ?)",
        (habit_id, date_str, _now_utc_iso()),
    )
    if cur.rowcount == 0:
        conn.close()
        return {"status": "already_logged"}

    conn.execute(
        "UPDATE users SET coins = coins - ? WHERE id = ?",
        (config.SHOP_OFFICIAL_SKIP_COST, user_id),
    )
    conn.execute(
        "INSERT INTO shop_operations (user_id, operation_type, cost, habit_id, payload, created_at) "
        "VALUES (?, 'official_skip', ?, ?, NULL, ?)",
        (user_id, config.SHOP_OFFICIAL_SKIP_COST, habit_id, _now_utc_iso()),
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "cost": config.SHOP_OFFICIAL_SKIP_COST}


def buy_replacement(user_id: int, habit_id: int, date_str: str, alt_text: str | None) -> dict:
    """Покупка замены привычки на день: засчитывается как выполнение, серия продолжается."""
    conn = get_connection()
    coins = conn.execute("SELECT coins FROM users WHERE id = ?", (user_id,)).fetchone()["coins"]
    if coins < config.SHOP_REPLACE_COST:
        conn.close()
        return {"status": "no_coins", "have": coins, "need": config.SHOP_REPLACE_COST}

    cur = conn.execute(
        "INSERT OR IGNORE INTO habit_logs (habit_id, date, status, created_at) "
        "VALUES (?, ?, 'temporary_replace', ?)",
        (habit_id, date_str, _now_utc_iso()),
    )
    if cur.rowcount == 0:
        conn.close()
        return {"status": "already_logged"}

    # Замена засчитывается как выполнение — серия растёт.
    conn.execute(
        "UPDATE habits SET current_streak = current_streak + 1, "
        "longest_streak = MAX(longest_streak, current_streak + 1) WHERE id = ?",
        (habit_id,),
    )
    conn.execute(
        "UPDATE users SET coins = coins - ? WHERE id = ?",
        (config.SHOP_REPLACE_COST, user_id),
    )
    conn.execute(
        "INSERT INTO shop_operations (user_id, operation_type, cost, habit_id, payload, created_at) "
        "VALUES (?, 'replacement', ?, ?, ?, ?)",
        (user_id, config.SHOP_REPLACE_COST, habit_id, alt_text, _now_utc_iso()),
    )
    new_streak = conn.execute(
        "SELECT current_streak FROM habits WHERE id = ?", (habit_id,)
    ).fetchone()[0]
    conn.commit()
    conn.close()
    return {"status": "ok", "cost": config.SHOP_REPLACE_COST, "streak": new_streak}


# =========================================================
#  Запросы для движка ачивок (Шаг 7)
# =========================================================

def get_unlocked_codes(user_id: int) -> set:
    conn = get_connection()
    rows = conn.execute(
        "SELECT achievement_code FROM user_achievements WHERE user_id = ?", (user_id,)
    ).fetchall()
    conn.close()
    return {r["achievement_code"] for r in rows}


def try_unlock_achievement(user_id: int, code: str, xp: int, coins: int) -> bool:
    """Открывает ачивку и начисляет награду. Идемпотентно (UNIQUE user_id+code)."""
    conn = get_connection()
    cur = conn.execute(
        "INSERT OR IGNORE INTO user_achievements (user_id, achievement_code, unlocked_at) "
        "VALUES (?, ?, ?)",
        (user_id, code, _now_utc_iso()),
    )
    if cur.rowcount == 0:
        conn.close()
        return False
    if xp or coins:
        conn.execute(
            "UPDATE users SET xp = xp + ?, coins = coins + ? WHERE id = ?",
            (xp, coins, user_id),
        )
    conn.commit()
    conn.close()
    return True


def count_completions(user_id: int) -> int:
    conn = get_connection()
    n = conn.execute(
        "SELECT COUNT(*) FROM habit_logs l JOIN habits h ON l.habit_id = h.id "
        "WHERE h.user_id = ? AND l.status IN ('completed', 'temporary_replace')",
        (user_id,),
    ).fetchone()[0]
    conn.close()
    return n


def count_misses(user_id: int) -> int:
    conn = get_connection()
    n = conn.execute(
        "SELECT COUNT(*) FROM habit_logs l JOIN habits h ON l.habit_id = h.id "
        "WHERE h.user_id = ? AND l.status = 'missed'",
        (user_id,),
    ).fetchone()[0]
    conn.close()
    return n


def max_longest_streak(user_id: int) -> int:
    conn = get_connection()
    row = conn.execute(
        "SELECT MAX(longest_streak) AS m FROM habits WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row["m"] or 0


def habit_has_missed(habit_id: int) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM habit_logs WHERE habit_id = ? AND status = 'missed' LIMIT 1",
        (habit_id,),
    ).fetchone()
    conn.close()
    return row is not None


def count_shop_ops(user_id: int) -> int:
    conn = get_connection()
    n = conn.execute(
        "SELECT COUNT(*) FROM shop_operations WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    conn.close()
    return n


def count_official_skips(user_id: int) -> int:
    conn = get_connection()
    n = conn.execute(
        "SELECT COUNT(*) FROM shop_operations WHERE user_id = ? AND operation_type = 'official_skip'",
        (user_id,),
    ).fetchone()[0]
    conn.close()
    return n


def count_replacements(user_id: int) -> int:
    conn = get_connection()
    n = conn.execute(
        "SELECT COUNT(*) FROM shop_operations WHERE user_id = ? AND operation_type = 'replacement'",
        (user_id,),
    ).fetchone()[0]
    conn.close()
    return n


def max_consecutive_missed_runs(user_id: int) -> int:
    """Самая длинная цепочка подряд идущих 'missed' в таймлайне любой привычки."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT l.habit_id, l.status FROM habit_logs l JOIN habits h ON l.habit_id = h.id "
        "WHERE h.user_id = ? ORDER BY l.habit_id, l.date",
        (user_id,),
    ).fetchall()
    conn.close()
    best = 0
    run = 0
    cur_habit = None
    for r in rows:
        if r["habit_id"] != cur_habit:
            cur_habit = r["habit_id"]
            run = 0
        if r["status"] == "missed":
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def last_completed_date_before(user_id: int, date_str: str) -> str | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT MAX(l.date) AS d FROM habit_logs l JOIN habits h ON l.habit_id = h.id "
        "WHERE h.user_id = ? AND l.status IN ('completed', 'temporary_replace') AND l.date < ?",
        (user_id, date_str),
    ).fetchone()
    conn.close()
    return row["d"]


def count_completions_before_hour(user_id: int, tz: str, hour: int) -> int:
    """Сколько выполнений (completed) было отмечено в локальное время до указанного часа."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT l.created_at FROM habit_logs l JOIN habits h ON l.habit_id = h.id "
        "WHERE h.user_id = ? AND l.status = 'completed'",
        (user_id,),
    ).fetchall()
    conn.close()
    zone = ZoneInfo(tz)
    count = 0
    for r in rows:
        try:
            local = datetime.fromisoformat(r["created_at"]).astimezone(zone)
        except (TypeError, ValueError):
            continue
        if local.hour < hour:
            count += 1
    return count


def today_has_early_and_late(user_id: int, tz: str, today_str: str) -> bool:
    """Есть ли сегодня (локально) отметка до 06:00 И отметка после 23:00."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT l.created_at FROM habit_logs l JOIN habits h ON l.habit_id = h.id "
        "WHERE h.user_id = ? AND l.status = 'completed'",
        (user_id,),
    ).fetchall()
    conn.close()
    zone = ZoneInfo(tz)
    early = late = False
    for r in rows:
        try:
            local = datetime.fromisoformat(r["created_at"]).astimezone(zone)
        except (TypeError, ValueError):
            continue
        if local.date().isoformat() != today_str:
            continue
        if local.hour < 6:
            early = True
        if local.hour >= 23:
            late = True
    return early and late


def count_consecutive_perfect_days(user_id: int, today_str: str) -> int:
    """Сколько идеальных дней подряд заканчивая сегодняшним."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT date FROM daily_events WHERE user_id = ? AND event_type = 'perfect_day'",
        (user_id,),
    ).fetchall()
    conn.close()
    dates = {r["date"] for r in rows}
    count = 0
    day = date.fromisoformat(today_str)
    while day.isoformat() in dates:
        count += 1
        day -= timedelta(days=1)
    return count


# =========================================================
#  Уровни (Фаза 2)
# =========================================================

def level_from_xp(xp: int) -> int:
    """Уровень по XP. Чтобы достичь уровня L, нужно накопить 50*(L-1)*L XP."""
    level = 1
    while 50 * level * (level + 1) <= xp:
        level += 1
    return level


def sync_level(user_id: int) -> dict | None:
    """Синхронизирует сохранённый уровень с XP. При повышении начисляет бонус монет.

    Возвращает {"old", "new", "bonus"} при повышении уровня, иначе None.
    """
    conn = get_connection()
    row = conn.execute("SELECT xp, level FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        conn.close()
        return None
    stored = row["level"]
    new_level = level_from_xp(row["xp"])
    if new_level == stored:
        conn.close()
        return None
    if new_level > stored:
        bonus = (new_level - stored) * config.LEVEL_UP_BONUS_COINS
        conn.execute(
            "UPDATE users SET level = ?, coins = coins + ? WHERE id = ?",
            (new_level, bonus, user_id),
        )
        conn.commit()
        conn.close()
        return {"old": stored, "new": new_level, "bonus": bonus}
    # уровень почему-то ниже сохранённого — просто синхронизируем без бонуса
    conn.execute("UPDATE users SET level = ? WHERE id = ?", (new_level, user_id))
    conn.commit()
    conn.close()
    return None


# =========================================================
#  Заморозка серии (Фаза 2)
# =========================================================

def buy_freeze(user_id: int) -> dict:
    """Покупка заморозки серии в инвентарь (users.freeze_count)."""
    conn = get_connection()
    coins = conn.execute("SELECT coins FROM users WHERE id = ?", (user_id,)).fetchone()["coins"]
    if coins < config.SHOP_FREEZE_COST:
        conn.close()
        return {"status": "no_coins", "have": coins, "need": config.SHOP_FREEZE_COST}
    conn.execute(
        "UPDATE users SET coins = coins - ?, freeze_count = freeze_count + 1 WHERE id = ?",
        (config.SHOP_FREEZE_COST, user_id),
    )
    conn.execute(
        "INSERT INTO shop_operations (user_id, operation_type, cost, habit_id, payload, created_at) "
        "VALUES (?, 'freeze_buy', ?, NULL, NULL, ?)",
        (user_id, config.SHOP_FREEZE_COST, _now_utc_iso()),
    )
    freeze_count = conn.execute(
        "SELECT freeze_count FROM users WHERE id = ?", (user_id,)
    ).fetchone()["freeze_count"]
    conn.commit()
    conn.close()
    return {"status": "ok", "cost": config.SHOP_FREEZE_COST, "freeze_count": freeze_count}


def count_freezes_used(user_id: int) -> int:
    conn = get_connection()
    n = conn.execute(
        "SELECT COUNT(*) FROM habit_logs l JOIN habits h ON l.habit_id = h.id "
        "WHERE h.user_id = ? AND l.status = 'freeze'",
        (user_id,),
    ).fetchone()[0]
    conn.close()
    return n


def close_out_habit(habit_id: int, day_str: str) -> dict:
    """Закрывает прошедший день привычки. Если есть заморозка и есть что спасать
    (серия > 0) — тратит заморозку (день нейтральный, серия сохраняется).
    Иначе — пропуск: штраф и обнуление серии. Идемпотентно.

    Возвращает {"result": "already"|"frozen"|"missed", ...}.
    """
    conn = get_connection()
    owner = conn.execute("SELECT user_id FROM habits WHERE id = ?", (habit_id,)).fetchone()
    if owner is None:
        conn.close()
        return {"result": "already"}
    user_id = owner["user_id"]
    prior_streak = conn.execute(
        "SELECT current_streak FROM habits WHERE id = ?", (habit_id,)
    ).fetchone()[0]
    freeze = conn.execute(
        "SELECT freeze_count FROM users WHERE id = ?", (user_id,)
    ).fetchone()["freeze_count"]

    use_freeze = freeze > 0 and prior_streak > 0
    status = "freeze" if use_freeze else "missed"

    cur = conn.execute(
        "INSERT OR IGNORE INTO habit_logs (habit_id, date, status, created_at) "
        "VALUES (?, ?, ?, ?)",
        (habit_id, day_str, status, _now_utc_iso()),
    )
    if cur.rowcount == 0:
        conn.close()
        return {"result": "already"}  # день уже был закрыт

    if use_freeze:
        # тратим заморозку: день нейтральный, серия НЕ трогается
        conn.execute(
            "UPDATE users SET freeze_count = freeze_count - 1 WHERE id = ?", (user_id,)
        )
        conn.commit()
        conn.close()
        return {"result": "frozen", "user_id": user_id, "freeze_left": freeze - 1}

    # обычный пропуск: штраф (не ниже 0) и обнуление серии
    conn.execute(
        "UPDATE users SET coins = MAX(0, coins - ?) WHERE id = ?",
        (config.COINS_PENALTY, user_id),
    )
    conn.execute("UPDATE habits SET current_streak = 0 WHERE id = ?", (habit_id,))
    conn.commit()
    conn.close()
    return {"result": "missed", "user_id": user_id, "prior_streak": prior_streak}
