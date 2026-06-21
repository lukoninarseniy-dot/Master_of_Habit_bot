import os

# --- Токен и база ---
# Токен бота берём ТОЛЬКО из переменной окружения. В коде его нет и быть не должно.
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Путь к файлу базы SQLite.
# На Railway рекомендуется подключить Volume и указать DB_PATH=/data/habits.db,
# иначе при каждом редеплое база будет обнуляться (см. README).
DB_PATH = os.getenv("DB_PATH", "habits.db")

# --- Лимиты привычек ---
MAX_HABITS = 15            # максимум привычек на одного пользователя
HABIT_TITLE_MAX_LEN = 60   # максимальная длина названия привычки

# --- Экономика (все числа можно крутить здесь) ---
XP_PER_COMPLETION = 10
COINS_PER_COMPLETION = 1
XP_PERFECT_DAY = 20
COINS_PERFECT_DAY = 3
COINS_PENALTY = 5          # штраф монетами за пропуск (но баланс не уходит ниже 0)

# Вехи серии: длина серии -> (XP, монеты)
STREAK_MILESTONES = {
    7: (50, 10),
    14: (100, 20),
    30: (250, 50),
    100: (1000, 200),
}

# --- Уровни ---
# XP для уровня N считается накопительно: на каждый уровень нужно 100 * N XP.
XP_PER_LEVEL_FACTOR = 100

# --- Часовые пояса для выбора при первом запуске ---
# (подпись на кнопке, имя зоны IANA). Список можно дополнять.
TIMEZONES = [
    ("Калининград · UTC+2", "Europe/Kaliningrad"),
    ("Москва · UTC+3", "Europe/Moscow"),
    ("Минск · UTC+3", "Europe/Minsk"),
    ("Кишинёв · UTC+2/+3", "Europe/Chisinau"),
    ("Самара · UTC+4", "Europe/Samara"),
    ("Ереван · UTC+4", "Asia/Yerevan"),
    ("Баку · UTC+4", "Asia/Baku"),
    ("Тбилиси · UTC+4", "Asia/Tbilisi"),
    ("Екатеринбург · UTC+5", "Asia/Yekaterinburg"),
    ("Ташкент · UTC+5", "Asia/Tashkent"),
    ("Алматы · UTC+5", "Asia/Almaty"),
    ("Душанбе · UTC+5", "Asia/Dushanbe"),
    ("Омск · UTC+6", "Asia/Omsk"),
    ("Бишкек · UTC+6", "Asia/Bishkek"),
    ("Красноярск · UTC+7", "Asia/Krasnoyarsk"),
    ("Иркутск · UTC+8", "Asia/Irkutsk"),
    ("Якутск · UTC+9", "Asia/Yakutsk"),
    ("Владивосток · UTC+10", "Asia/Vladivostok"),
    ("Магадан · UTC+11", "Asia/Magadan"),
    ("Камчатка · UTC+12", "Asia/Kamchatka"),
]

# --- Дни недели (0=Пн ... 6=Вс), для расписания типа weekdays ---
WEEKDAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

# --- Магазин (цены в монетах) ---
SHOP_OFFICIAL_SKIP_COST = 3   # официальный пропуск: день нейтральный, без штрафа
SHOP_REPLACE_COST = 1         # замена привычки на день: засчитывается как выполнение
# Фаза 2: заморозка серии (5), сундук удачи (10), полный сброс (7)
