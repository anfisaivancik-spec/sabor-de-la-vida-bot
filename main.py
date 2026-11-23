import asyncio
import hashlib
import logging
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Не задана переменная окружения BOT_TOKEN!")

# Хранилище в оперативной памяти (без БД)
users_db = {}          # { "login": "password_hash" }
authorized_users = {}  # { tg_id: "login" }

class AuthStates(StatesGroup):
    reg_login = State()
    reg_password = State()
    login_username = State()
    login_password = State()

def get_auth_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Регистрация"), KeyboardButton(text="🔑 Войти")]
        ],
        resize_keyboard=True
    )

def get_profile_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="🚪 Выйти")]
        ],
        resize_keyboard=True
    )

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    tg_id = message.from_user.id
    if tg_id in authorized_users:
        await message.answer(
            f"С возвращением, **{authorized_users[tg_id]}**!",
            reply_markup=get_profile_kb(),
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            "Привет! Зарегистрируйся или войди в свой аккаунт.",
            reply_markup=get_auth_kb()
        )

# --- РЕГИСТРАЦИЯ ---
@router.message(F.text == "📝 Регистрация")
async def start_reg(message: Message, state: FSMContext):
    if message.from_user.id in authorized_users:
        await message.answer("Ты уже вошел в аккаунт.", reply_markup=get_profile_kb())
        return
    await state.set_state(AuthStates.reg_login)
    await message.answer("Придумай **логин** (от 3 до 20 символов):", parse_mode="Markdown")

@router.message(AuthStates.reg_login)
async def process_reg_login(message: Message, state: FSMContext):
    login = message.text.strip()
    if not (3 <= len(login) <= 20):
        await message.answer("Логин должен быть от 3 до 20 символов. Введи другой:")
        return
    if login.lower() in (u.lower() for u in users_db):
        await message.answer("Этот логин уже занят. Попробуй другой:")
        return

    await state.update_data(login=login)
    await state.set_state(AuthStates.reg_password)
    await message.answer("Теперь придумай **пароль** (минимум 4 символа):", parse_mode="Markdown")

@router.message(AuthStates.reg_password)
async def process_reg_password(message: Message, state: FSMContext):
    password = message.text.strip()
    if len(password) < 4:
        await message.answer("Пароль слишком короткий (минимум 4 символа). Введи другой:")
        return

    data = await state.get_data()
    login = data["login"]
    
    users_db[login] = hash_password(password)
    authorized_users[message.from_user.id] = login

    try:
        await message.delete()
    except Exception:
        pass

    await state.clear()
    await message.answer(
        f"✅ Регистрация прошла успешно!\nТвой логин: **{login}**",
        reply_markup=get_profile_kb(),
        parse_mode="Markdown"
    )

# --- ВХОД ---
@router.message(F.text == "🔑 Войти")
async def start_login(message: Message, state: FSMContext):
    if message.from_user.id in authorized_users:
        await message.answer("Ты уже авторизован.", reply_markup=get_profile_kb())
        return
    await state.set_state(AuthStates.login_username)
    await message.answer("Введи свой **логин**:", parse_mode="Markdown")

@router.message(AuthStates.login_username)
async def process_login_username(message: Message, state: FSMContext):
    login = message.text.strip()
    if login not in users_db:
        await message.answer("Такой логин не найден. Проверь ввод или нажми «📝 Регистрация»:")
        return
    await state.update_data(login=login)
    await state.set_state(AuthStates.login_password)
    await message.answer("Введи **пароль**:", parse_mode="Markdown")

@router.message(AuthStates.login_password)
async def process_login_password(message: Message, state: FSMContext):
    password = message.text.strip()
    data = await state.get_data()
    login = data["login"]

    try:
        await message.delete()
    except Exception:
        pass

    if users_db.get(login) == hash_password(password):
        authorized_users[message.from_user.id] = login
        await state.clear()
        await message.answer(
            f"✅ Вход выполнен! Привет, **{login}**.",
            reply_markup=get_profile_kb(),
            parse_mode="Markdown"
        )
    else:
        await message.answer("❌ Неверный пароль. Попробуй еще раз:")

# --- ПРОФИЛЬ И ВЫХОД ---
@router.message(F.text == "👤 Мой профиль")
async def show_profile(message: Message):
    login = authorized_users.get(message.from_user.id)
    if not login:
        await message.answer("Сначала войди в аккаунт.", reply_markup=get_auth_kb())
        return
    await message.answer(
        f"👤 **Профиль**\nЛогин: `{login}`\nID: `{message.from_user.id}`",
        parse_mode="Markdown"
    )

@router.message(F.text == "🚪 Выйти")
async def logout(message: Message, state: FSMContext):
    await state.clear()
    authorized_users.pop(message.from_user.id, None)
    await message.answer("Ты вышел из аккаунта.", reply_markup=get_auth_kb())

# --- Веб-сервер для Render ---
async def handle_ping(request):
    return web.Response(text="Bot is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())