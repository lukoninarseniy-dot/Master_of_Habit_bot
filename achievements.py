"""Каталог достижений и движок их выдачи.

Каталог хранится в коде (как в ТЗ, раздел 10): добавить новую ачивку = добавить
строку в CATALOG. Факт получения хранится в таблице user_achievements.

Поля ачивки: code, icon, title, desc, xp, coins, hidden.
hidden=True — «секретная»: до получения на экране показывается как «??? — секрет».

Часть ачивок завязана на фичи Фазы 2 (заморозка, сундук, категории, пауза) —
они есть в каталоге, но пока не выдаются: подключатся, когда появятся фичи.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import config
import database as db

CATALOG = [
    # 10.1 Серии и постоянство
    {"code": "first_step", "icon": "🐣", "title": "Первый шаг", "desc": "первое выполнение", "xp": 20, "coins": 2, "hidden": False},
    {"code": "warmup", "icon": "🔥", "title": "Разогрев", "desc": "серия 3 дня", "xp": 30, "coins": 5, "hidden": False},
    {"code": "week", "icon": "💪", "title": "Неделя силы", "desc": "серия 7 дней", "xp": 50, "coins": 10, "hidden": False},
    {"code": "invincible", "icon": "🛡", "title": "Несокрушимый", "desc": "серия 30 дней", "xp": 250, "coins": 50, "hidden": False},
    {"code": "summit", "icon": "🏔", "title": "Покоритель вершины", "desc": "серия 100 дней", "xp": 1000, "coins": 200, "hidden": False},
    {"code": "legend365", "icon": "👑", "title": "Легенда", "desc": "серия 365 дней", "xp": 5000, "coins": 1000, "hidden": False},
    {"code": "phoenix", "icon": "🧊→🔥", "title": "Феникс", "desc": "восстановил серию до 7 дней после обнуления", "xp": 100, "coins": 20, "hidden": False},

    # 10.2 Объём
    {"code": "vp10", "icon": "🥾", "title": "В путь", "desc": "10 выполнений", "xp": 20, "coins": 3, "hidden": False},
    {"code": "vp100", "icon": "🏃", "title": "Марафонец", "desc": "100 выполнений", "xp": 200, "coins": 30, "hidden": False},
    {"code": "vp500", "icon": "🚀", "title": "Космонавт", "desc": "500 выполнений", "xp": 800, "coins": 100, "hidden": False},
    {"code": "vp1000", "icon": "🪐", "title": "Властелин рутины", "desc": "1000 выполнений", "xp": 2000, "coins": 300, "hidden": False},

    # 10.3 Идеальность
    {"code": "perfect_day", "icon": "✨", "title": "Идеальный день", "desc": "все привычки дня выполнены", "xp": 30, "coins": 5, "hidden": False},
    {"code": "perfect_week", "icon": "📅", "title": "Безупречная неделя", "desc": "7 идеальных дней подряд", "xp": 150, "coins": 30, "hidden": False},
    {"code": "perfectionist", "icon": "🎯", "title": "Перфекционист", "desc": "100% выполнения за календарный месяц", "xp": 500, "coins": 80, "hidden": False},

    # 10.4 Время суток
    {"code": "early_bird", "icon": "🐦", "title": "Ранняя пташка", "desc": "отметка до 06:00", "xp": 30, "coins": 5, "hidden": False},
    {"code": "coffee", "icon": "☕", "title": "Кофе подождёт", "desc": "отметка до 08:00 пять раз", "xp": 40, "coins": 8, "hidden": False},
    {"code": "night_owl", "icon": "🦉", "title": "Полуночник", "desc": "отметка после 23:00", "xp": 30, "coins": 5, "hidden": False},
    {"code": "vampire", "icon": "🧛", "title": "Я вампир, я не сплю", "desc": "отметка между 02:00 и 04:00", "xp": 50, "coins": 10, "hidden": True},

    # 10.5 Экономика
    {"code": "first_coin", "icon": "🪙", "title": "Первая монетка", "desc": "заработал первую монету", "xp": 10, "coins": 0, "hidden": False},
    {"code": "capitalist", "icon": "💰", "title": "Капиталист", "desc": "накоплено 100 монет", "xp": 100, "coins": 20, "hidden": False},
    {"code": "dragon", "icon": "🐉", "title": "Дракон на золоте", "desc": "накоплено 500 монет", "xp": 300, "coins": 50, "hidden": False},
    {"code": "shopaholic", "icon": "🛒", "title": "Шопоголик", "desc": "первая покупка в магазине", "xp": 20, "coins": 3, "hidden": False},

    # 10.6 Магазин и фейлы
    {"code": "oops", "icon": "🤷", "title": "Ну, бывает", "desc": "первый пропуск", "xp": 10, "coins": 1, "hidden": False},
    {"code": "sloth", "icon": "🦥", "title": "Режим ленивца", "desc": "3 пропуска подряд", "xp": 5, "coins": 0, "hidden": False},
    {"code": "rollercoaster", "icon": "🎢", "title": "Американские горки", "desc": "пропуск сразу после серии 14+ дней", "xp": 20, "coins": 0, "hidden": True},
    {"code": "bought_off", "icon": "🛟", "title": "Откупился", "desc": "первый официальный пропуск", "xp": 10, "coins": 0, "hidden": False},
    {"code": "chameleon", "icon": "🎭", "title": "Хамелеон", "desc": "впервые заменил привычку на день", "xp": 15, "coins": 2, "hidden": False},
    {"code": "ice_break", "icon": "🧊", "title": "Лёд тронулся", "desc": "впервые использовал заморозку серии", "xp": 20, "coins": 3, "hidden": False},
    {"code": "just_looking", "icon": "🤡", "title": "Я просто посмотреть", "desc": "создал привычку и удалил её в тот же день", "xp": 5, "coins": 0, "hidden": True},
    {"code": "clean_game", "icon": "🦸", "title": "Чистая игра", "desc": "30 дней без покупки пропусков", "xp": 200, "coins": 40, "hidden": False},

    # 10.7 Коллекционер
    {"code": "collector5", "icon": "📚", "title": "Коллекционер", "desc": "создано 5 привычек", "xp": 30, "coins": 5, "hidden": False},
    {"code": "collector10", "icon": "🗂", "title": "Менеджер проектов", "desc": "создано 10 привычек", "xp": 60, "coins": 10, "hidden": False},
    {"code": "versatile", "icon": "🧩", "title": "Разносторонний", "desc": "привычки в 4 разных категориях", "xp": 50, "coins": 10, "hidden": False},

    # 10.8 Долгожитель и камбэки
    {"code": "dino", "icon": "🦖", "title": "Динозавр", "desc": "одной привычке исполнилось 100 дней", "xp": 100, "coins": 20, "hidden": False},
    {"code": "birthday", "icon": "🎂", "title": "С днём рождения", "desc": "365 дней с регистрации", "xp": 500, "coins": 100, "hidden": False},
    {"code": "comeback", "icon": "🧗", "title": "Великое возвращение", "desc": "вернулся и отметился после 7+ дней тишины", "xp": 50, "coins": 10, "hidden": False},
    {"code": "turtle", "icon": "🐢", "title": "Тише едешь", "desc": "вернулся из режима паузы/отпуска", "xp": 20, "coins": 3, "hidden": False},

    # 10.9 Особые / секретные
    {"code": "lucky", "icon": "🎰", "title": "Везунчик", "desc": "выбил максимум из ежедневного сундука", "xp": 30, "coins": 5, "hidden": True},
    {"code": "swiss_watch", "icon": "⏰", "title": "Швейцарские часы", "desc": "отметка ровно в минуту напоминания", "xp": 40, "coins": 8, "hidden": True},
    {"code": "flip", "icon": "🌗", "title": "Перевёртыш", "desc": "в один день и «ранняя пташка», и «полуночник»", "xp": 50, "coins": 10, "hidden": True},
    {"code": "zen", "icon": "🧘", "title": "Дзен-мастер", "desc": "выполнил духовную привычку 50 раз", "xp": 100, "coins": 20, "hidden": True},
]

BY_CODE = {a["code"]: a for a in CATALOG}


def _grant(user_id, code, already, newly):
    if code in already:
        return
    a = BY_CODE[code]
    if db.try_unlock_achievement(user_id, code, a["xp"], a["coins"]):
        already.add(code)
        newly.append(a)


def check_all(user_id, *, now=None, event=None, habit_id=None, prior_streak=None, perfect_day=False):
    """Проверяет все доступные ачивки по текущему состоянию + контексту события.

    Возвращает список только что открытых ачивок (для уведомления).
    Вызов идемпотентен: повторный вызов ничего не выдаёт заново.
    """
    user = db.get_user(user_id)
    if user is None:
        return []
    tz = user["timezone"]
    already = db.get_unlocked_codes(user_id)
    newly: list = []

    def g(code):
        _grant(user_id, code, already, newly)

    today = now.date() if now is not None else (db.user_now(tz).date() if tz else date.today())

    # Объём и первое выполнение
    total = db.count_completions(user_id)
    if total >= 1:
        g("first_step")
        g("first_coin")
    if total >= 10:
        g("vp10")
    if total >= 100:
        g("vp100")
    if total >= 500:
        g("vp500")
    if total >= 1000:
        g("vp1000")

    # Серии (по рекорду longest_streak)
    rec = db.max_longest_streak(user_id)
    if rec >= 3:
        g("warmup")
    if rec >= 7:
        g("week")
    if rec >= 30:
        g("invincible")
    if rec >= 100:
        g("summit")
    if rec >= 365:
        g("legend365")

    # Феникс: текущая серия 7+ у привычки, у которой раньше был пропуск
    habits = db.get_habits(user_id)
    for h in habits:
        if h["current_streak"] >= 7 and db.habit_has_missed(h["id"]):
            g("phoenix")
            break

    # Экономика
    if user["coins"] >= 100:
        g("capitalist")
    if user["coins"] >= 500:
        g("dragon")

    # Магазин
    if db.count_shop_ops(user_id) >= 1:
        g("shopaholic")
    if db.count_official_skips(user_id) >= 1:
        g("bought_off")
    if db.count_replacements(user_id) >= 1:
        g("chameleon")
    if db.count_freezes_used(user_id) >= 1:
        g("ice_break")

    # Фейлы
    if db.count_misses(user_id) >= 1:
        g("oops")
    if db.max_consecutive_missed_runs(user_id) >= 3:
        g("sloth")
    if event == "miss" and prior_streak is not None and prior_streak >= 14:
        g("rollercoaster")

    # Коллекционер и категории
    hcount = db.count_habits(user_id)
    if hcount >= 5:
        g("collector5")
    if hcount >= 10:
        g("collector10")
    if db.count_distinct_categories(user_id) >= 4:
        g("versatile")
    if db.count_completions_in_category(user_id, config.ZEN_CATEGORY) >= 50:
        g("zen")

    # Сундуки и возвращение из паузы
    if db.has_event(user_id, "daily_chest_max"):
        g("lucky")
    if event == "resume":
        g("turtle")

    # Долгожитель: возраст привычки
    for h in habits:
        try:
            age = (today - date.fromisoformat(h["start_date"])).days
        except (TypeError, ValueError):
            continue
        if age >= 100:
            g("dino")
            break

    # День рождения аккаунта и «чистая игра»
    reg = None
    try:
        if tz and user["created_at"]:
            reg = datetime.fromisoformat(user["created_at"]).astimezone(ZoneInfo(tz)).date()
    except (TypeError, ValueError):
        reg = None
    if reg is not None:
        if (today - reg).days >= 365:
            g("birthday")
        if (today - reg).days >= 30 and db.count_official_skips(user_id) == 0:
            g("clean_game")

    # Идеальный день / неделя
    if perfect_day:
        g("perfect_day")
        if db.count_consecutive_perfect_days(user_id, today.isoformat()) >= 7:
            g("perfect_week")

    # Возвращение после паузы в активности
    if event == "completion":
        prev = db.last_completed_date_before(user_id, today.isoformat())
        if prev:
            if (today - date.fromisoformat(prev)).days >= 7:
                g("comeback")

    # Время суток (только при реальной отметке)
    if event == "completion" and now is not None:
        hour = now.hour
        if hour < 6:
            g("early_bird")
        if hour >= 23:
            g("night_owl")
        if 2 <= hour < 4:
            g("vampire")
        if habit_id is not None:
            hb = db.get_habit(habit_id)
            if hb and hb["reminder_time"] and hb["reminder_time"] == now.strftime("%H:%M"):
                g("swiss_watch")
        if tz:
            if db.count_completions_before_hour(user_id, tz, 8) >= 5:
                g("coffee")
            if db.today_has_early_and_late(user_id, tz, today.isoformat()):
                g("flip")

    return newly


def check_just_looking(user_id, habit_start_date, today_str):
    """Скрытая ачивка: привычка создана и удалена в один день."""
    if habit_start_date != today_str:
        return []
    already = db.get_unlocked_codes(user_id)
    newly: list = []
    _grant(user_id, "just_looking", already, newly)
    return newly
