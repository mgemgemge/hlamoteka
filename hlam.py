import os
import json
import asyncio
import sqlite3
import base64
from typing import List

from fastapi import FastAPI, UploadFile, File, Form
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
    MenuButtonWebApp
)

from openai import AsyncOpenAI

# ==========================================
# --- НАСТРОЙКИ СЕРВЕРА И КЛЮЧИ ---
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WEB_APP_URL = "https://hlamik-hlamik.amvera.io/"

# 🚨 МАГИЯ ТУННЕЛЯ CLOUDFLARE 🚨
# Замени ссылку ниже на ту, что выдал тебе Cloudflare!
# ОБЯЗАТЕЛЬНО оставь на конце /v1beta/openai/
CLOUDFLARE_URL = "https://ТВОЙ_ВОРКЕР.workers.dev/v1beta/openai/"

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
# --- FASTAPI: РАЗДАЧА И ПРИЕМ ФОТО ---
# ==========================================
@app.get("/")
async def get_index():
    return FileResponse("index.html")

@app.post("/api/upload")
async def upload_image(files: List[UploadFile] = File(...), user_id: int = Form(...)):
    
    msg = await bot.send_message(user_id, "🧠 Сканирую каждый пиксель через секретный туннель...")
    
    prompt = """
    Ты профессиональный оценщик любых вещей для барахолки (Авито, Юла, Ebay). Проанализируй эти фотографии.
    
    🛑 ПРАВИЛО 1: В кадре должна быть СТРОГО ОДНА вещь (или один логичный комплект). Если видишь сборную солянку разных предметов — ставь "is_valuable": false и пиши в "reason": "Эй, я не оцениваю оптом! 😅 Пожалуйста, оставь в кадре только одну вещь."
    🛑 ПРАВИЛО 2: Вещь должна иметь ценность на вторичном рынке. Если на фото мусор, живые люди, животные или пустая комната — ставь "is_valuable": false и пиши смешную причину отказа.
    
    Верни строго JSON-объект без лишнего текста (Markdown-разметку тоже не используй).
    
    Формат ответа:
    {
        "is_valuable": true,
        "item_name": "Точное название предмета, бренд, модель (если есть)",
        "condition": "Краткое описание состояния, учитывая все ракурсы",
        "condition_multiplier": 1.0,
        "estimated_market_price": 2500,
        "reason": "Почему такая оценка (1-2 предложения)"
    }
    Важно: estimated_market_price - это примерная рыночная цена Б/У вещи в рублях (целое число).
    """

    try:
        messages_content = [{"type": "text", "text": prompt}]
        
        for file in files:
            file_bytes = await file.read()
            base64_image = base64.b64encode(file_bytes).decode('utf-8')
            messages_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
            })
            
        # Стучимся в Google Gemini через формат OpenAI!
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
            return {"status": "not_valuable"}

        device_name = ai_data.get("item_name", "Неизвестная вещь")
        condition = ai_data.get("condition", "Не определено")
        base_price = int(ai_data.get("estimated_market_price", 0))
        reason = ai_data.get("reason", "")
        
        save_item(user_id, device_name, condition, base_price)

        final_text = (
            f"📦 **Находка:** {device_name}\n"
            f"🔎 **Состояние:** {condition}\n"
            f"💡 **Вердикт:** {reason}\n\n"
            f"💰 **Рыночная цена:** ~{base_price} ₽\n\n"
            f"Хочешь продать эту вещь прямо сейчас без лишних хлопот?"
        )
        
        inline_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💸 Продать сейчас", callback_data="action_instant")],
            [InlineKeyboardButton(text="📢 Выставить на Авито/Юлу (AI)", callback_data="action_publish")]
        ])
        
        await bot.edit_message_text(final_text, chat_id=user_id, message_id=msg.message_id, reply_markup=inline_kb, parse_mode="Markdown")
        return {"status": "ok"}

    except Exception as e:
        error_msg = f"❌ Ошибка ИИ: {e}"
        print(error_msg) 
        await bot.edit_message_text(error_msg, chat_id=user_id, message_id=msg.message_id)
        return {"status": "error"}

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
        "Помогаю превратить вещи, которые лежат без дела, в реальные деньги. Я знаю цены на вторичном рынке почти на всё: от смартфонов и ноутбуков до кроссовок и гитар!\n\n"
        "**⚙️ Как это работает:**\n"
        "1️⃣ Нажми кнопку **Запустить сканер**.\n"
        "2️⃣ Помести предмет в центр рамки и сделай от 1 до 5 фото со всех сторон.\n"
        "3️⃣ Мои нейросети проанализируют состояние вещи и выдадут её рыночную цену.\n"
        "4️⃣ Если цена устроит — жми «Продать сейчас», и мы организуем выкуп!\n\n"
        "💡 *Совет: фотографируй при хорошем освещении и клади в кадр строго одну вещь.*\n\n"
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














