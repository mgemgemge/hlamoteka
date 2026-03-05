import os
import json
import asyncio
import sqlite3
import base64
from typing import List

from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import uvicorn

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    WebAppInfo, 
    FSInputFile, 
    MenuButtonWebApp,
    BufferedInputFile
)

from openai import AsyncOpenAI

# ==========================================
# --- НАСТРОЙКИ СЕРВЕРА И КЛЮЧИ ---
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WEB_APP_URL = "https://hlamik-hlamik.amvera.io/"

# 🚨 МАГИЯ ТУННЕЛЯ CLOUDFLARE 🚨
# Убедись, что тут твоя ссылка на воркер!
CLOUDFLARE_URL = "https://hlamik.ike92.workers.dev/v1beta/openai/"

openai_client = AsyncOpenAI(
    api_key=GEMINI_API_KEY,
    base_url=CLOUDFLARE_URL 
)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# --- БАЗА ДАННЫХ ---
# ==========================================
if os.path.exists("/data"):
    DB_NAME = "/data/valueit.db"
else:
    DB_NAME = "valueit.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            device_name TEXT,
            condition TEXT,
            base_price INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def save_item(user_id, device_name, condition, base_price):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO requests (user_id, device_name, condition, base_price)
        VALUES (?, ?, ?, ?)
    ''', (user_id, device_name, condition, base_price))
    conn.commit()
    conn.close()

# ==========================================
# --- ФОНОВАЯ ЗАДАЧА: РАБОТА ИИ ---
# ==========================================
async def process_images_task(file_bytes_list: list, user_id: int):
    # Отправляем сообщение, что процесс пошел (чтобы человек не скучал)
    msg = await bot.send_message(
        user_id, 
        "👀 **Фотки получил!**\n\n🔍 Изучаю детали...\n📊 Анализирую рынок...\n⏳ Считаю денюжки...",
        parse_mode="Markdown"
    )
    
    prompt = """
    Ты профессиональный оценщик любых вещей для барахолки. Проанализируй эти фотографии.
    
    🛑 ПРАВИЛО 1: В кадре должна быть СТРОГО ОДНА вещь (или один логичный комплект). Если видишь сборную солянку — "is_valuable": false.
    🛑 ПРАВИЛО 2: Вещь должна иметь ценность на вторичном рынке. Если мусор — "is_valuable": false.
    
    Формат ответа (СТРОГО JSON):
    {
        "is_valuable": true,
        "item_name": "Точное название предмета, бренд, модель",
        "condition": "Краткое описание состояния",
        "market_price": 5000,
        "quick_sell_price": 4000,
        "instant_buyout_price": 3000,
        "reason": "Почему такая оценка (1-2 предложения)"
    }
    Важно: 
    - market_price: средняя рыночная цена Б/У вещи.
    - quick_sell_price: цена для быстрой продажи (около 80-85% от рынка).
    - instant_buyout_price: цена для мгновенного выкупа нами (около 60-70% от рынка).
    Все цены - целые числа в рублях.
    """

    try:
        messages_content = [{"type": "text", "text": prompt}]
        
        for file_bytes in file_bytes_list:
            base64_image = base64.b64encode(file_bytes).decode('utf-8')
            messages_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
            })
            
        response = await openai_client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[{"role": "user", "content": messages_content}],
            response_format={ "type": "json_object" }
        )
        
        raw_text = response.choices[0].message.content
        ai_data = json.loads(raw_text)
        
        if not ai_data.get("is_valuable"):
            funny_text = f"❌ **Оценка прервана!**\n\nИИ говорит: *{ai_data.get('reason')}*"
            await bot.edit_message_text(funny_text, chat_id=user_id, message_id=msg.message_id, parse_mode="Markdown")
            return

        device_name = ai_data.get("item_name", "Неизвестная вещь")
        condition = ai_data.get("condition", "Не определено")
        reason = ai_data.get("reason", "")
        
        # Забираем наши 3 цены
        p_market = int(ai_data.get("market_price", 0))
        p_quick = int(ai_data.get("quick_sell_price", 0))
        p_buyout = int(ai_data.get("instant_buyout_price", 0))
        
        save_item(user_id, device_name, condition, p_market)

        final_text = (
            f"📦 **Находка:** {device_name}\n"
            f"🔎 **Состояние:** {condition}\n"
            f"💡 **Вердикт:** {reason}\n\n"
            f"📈 **Рыночная цена:** ~{p_market} ₽\n"
            f"⚡ **Быстрая продажа:** ~{p_quick} ₽\n"
            f"💸 **Мгновенный выкуп:** ~{p_buyout} ₽\n\n"
            f"Как поступим?"
        )
        
        inline_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💸 Продать сейчас", callback_data="action_instant")],
            [InlineKeyboardButton(text="📢 Выставить на Авито/Юлу (AI)", callback_data="action_publish")]
        ])
        
        # Готовим первую фотку для отправки
        photo = BufferedInputFile(file_bytes_list[0], filename="item.jpg")
        
        # Удаляем сообщение "Фотки получил..." и присылаем красивый результат с картинкой!
        await bot.delete_message(chat_id=user_id, message_id=msg.message_id)
        await bot.send_photo(
            chat_id=user_id, 
            photo=photo, 
            caption=final_text, 
            reply_markup=inline_kb, 
            parse_mode="Markdown"
        )

    except Exception as e:
        error_msg = f"❌ Ошибка ИИ: {e}"
        print(error_msg) 
        await bot.edit_message_text(error_msg, chat_id=user_id, message_id=msg.message_id)

# ==========================================
# --- FASTAPI: РАЗДАЧА И ПРИЕМ ФОТО ---
# ==========================================
@app.get("/")
async def get_index():
    return FileResponse("index.html")

@app.post("/api/upload")
async def upload_image(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...), user_id: int = Form(...)):
    # Читаем картинки в память СРАЗУ
    file_bytes_list = []
    for file in files:
        file_bytes_list.append(await file.read())
        
    # Запускаем ИИ думать в ФОНОВОМ РЕЖИМЕ
    background_tasks.add_task(process_images_task, file_bytes_list, user_id)
    
    # МГНОВЕННО отвечаем сканеру, чтобы он закрылся без зависаний!
    return {"status": "ok"}

# ==========================================
# --- ТЕЛЕГРАМ БОТ: ЛОГИКА ---
# ==========================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    web_app_btn = InlineKeyboardButton(
        text="📷 Запустить сканер", 
        web_app=WebAppInfo(url=WEB_APP_URL) 
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[web_app_btn]])
    
    welcome_text = (
        "👋 **Привет! Я Hlamik — твой карманный ИИ-оценщик.**\n\n"
        "Помогаю превратить вещи, которые лежат без дела, в реальные деньги.\n\n"
        "**⚙️ Как это работает:**\n"
        "1️⃣ Нажми кнопку **Запустить сканер**.\n"
        "2️⃣ Помести предмет в центр рамки и сделай от 1 до 5 фото со всех сторон.\n"
        "3️⃣ Мои нейросети проанализируют состояние вещи и выдадут её рыночную цену.\n"
        "4️⃣ Если цена устроит — жми «Продать сейчас», и мы организуем выкуп!\n\n"
        "Ну что, проверим, сколько стоит твой хлам? Жми на кнопку! 👇"
    )
    
    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="Markdown")

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    await message.answer("🕵️‍♂️ Привет, Босс. Формирую выгрузку базы данных...")
    try:
        db_file = FSInputFile(DB_NAME)
        await bot.send_document(
            message.chat.id, 
            document=db_file, 
            caption="📁 Вот вся история оценок.\nЧтобы посмотреть таблицу, используй 'DB Browser for SQLite'."
        )
    except Exception as e:
        await message.answer(f"❌ Шеф, произошла ошибка при выгрузке: {e}")

@dp.callback_query(lambda c: c.data == "action_publish")
async def process_publish_button(callback_query: types.CallbackQuery):
    await callback_query.answer()
    await bot.send_message(
        callback_query.from_user.id, 
        "🚀 **Магия началась!**\nМы сгенерировали продающее описание и отправили черновик на Авито и Юлу. Ссылка появится здесь через пару минут.",
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data == "action_instant")
async def process_instant_button(callback_query: types.CallbackQuery):
    await callback_query.answer("💸 Сделка запущена!", show_alert=False)
    await bot.send_message(
        callback_query.from_user.id, 
        "🤝 **Отлично! Мы зафиксировали цену мгновенного выкупа.**\n\n📍 Наш партнер-скупщик свяжется с вами в течение 15 минут.",
        parse_mode="Markdown"
    )

@app.on_event("startup")
async def on_startup():
    init_db()
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="📷 Сканер", web_app=WebAppInfo(url=WEB_APP_URL))
    )
    asyncio.create_task(dp.start_polling(bot))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=80)















