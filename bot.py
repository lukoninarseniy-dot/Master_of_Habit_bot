import asyncio
import logging

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery

import config
import database as db
import keyboards as kb

logging.basicConfig(level=logging.INFO)

router = Router()


def level_title(level: int) -> str:
    """Звание по уровню (таблица из раздела 3 ТЗ)."""
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


@router.message(CommandStart())
async def cmd_start(message: Message):
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
        await message.answer(
            "С возвращением. Главное меню ниже.",
            reply_markup=kb.main_menu(),
        )


@router.callback_query(F.data.startswith("tz:"))
async def choose_timezone(callback: CallbackQuery):
    tz_name = callback.data.split(":", 1)[1]
    db.set_timezone(callback.from_user.id, tz_name)

    await callback.message.edit_text(f"Часовой пояс сохранён: {tz_name}")
    await callback.message.answer(
        "Готово. Вот главное меню — отсюда работают все разделы.",
        reply_markup=kb.main_menu(),
    )
    await callback.answer()


def _require_user(message: Message):
    """Возвращает пользователя, если у него выбран часовой пояс. Иначе None."""
    user = db.get_user(message.from_user.id)
    if user is None or user["timezone"] is None:
        return None
    return user


@router.message(F.text == kb.BTN_BALANCE)
async def show_balance(message: Message):
    user = _require_user(message)
    if user is None:
        await message.answer("Сначала нажми /start и выбери часовой пояс.")
        return
    text = (
        "Баланс\n\n"
        f"Монеты: {user['coins']}\n"
        f"Опыт (XP): {user['xp']}\n"
        f"Уровень: {user['level']} ({level_title(user['level'])})"
    )
    await message.answer(text)


@router.message(F.text == kb.BTN_SETTINGS)
async def show_settings(message: Message):
    user = _require_user(message)
    if user is None:
        await message.answer("Сначала нажми /start и выбери часовой пояс.")
        return
    await message.answer(
        f"Настройки\n\nТекущий часовой пояс: {user['timezone']}\n\n"
        "Чтобы сменить — выбери новый ниже.",
        reply_markup=kb.timezone_keyboard(),
    )


# Кнопки разделов, которые добавим на следующих шагах.
PLACEHOLDER_BUTTONS = {
    kb.BTN_ADD,
    kb.BTN_LIST,
    kb.BTN_CHECK,
    kb.BTN_STATS,
    kb.BTN_SHOP,
    kb.BTN_ACHIEVEMENTS,
}


@router.message(F.text.in_(PLACEHOLDER_BUTTONS))
async def placeholder(message: Message):
    await message.answer("Этот раздел появится на следующих шагах сборки.")


@router.message()
async def fallback(message: Message):
    await message.answer("Не понял. Пользуйся кнопками меню или нажми /start.")


async def main():
    if not config.BOT_TOKEN:
        raise RuntimeError(
            "Не задан BOT_TOKEN. Добавь переменную окружения BOT_TOKEN "
            "(в Railway Variables или в .env)."
        )

    db.init_db()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logging.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
