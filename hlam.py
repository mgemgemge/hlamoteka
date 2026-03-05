import asyncio
import os
import io
import json
from typing import List
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, FSInputFile
import google.generativeai as genai
import PIL.Image

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv

from database import init_db, add_evaluation

# Загружаем переменные окружения
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WEB_APP_URL = "https://mgemgemge.github.io/hlamoteka/?v=2"

# Инициализация
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_class=HTMLResponse)
async def read_index():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "API сервера работает! 🚀"

# 🔄 ОБНОВЛЕННАЯ ФУНКЦИЯ (ПРИНИМАЕТ МАССИВ ФОТО)
@app.post("/api/upload")
async def upload_image(files: List[UploadFile] = File(...), user_id: int = Form(...)):
    # Бот теперь пишет, сколько именно фото он получил
    msg = await bot.send_message(user_id, f"🔍 Принял {len(files)} фото из сканера! Включаю нейронные сети...")
    
    try:
        # Распаковываем все присланные файлы в картинки
        images = []
        for file in files:
            image_data = await file.read()
            img = PIL.Image.open(io.BytesIO(image_data))
            images.append(img)
        
        prompt = """
        Ты профессиональный оценщик любых вещей для барахолки (Авито, Юла, Ebay). Проанализируй эти фотографии.
        
        🛑 ПРАВИЛО 1: В кадре должна быть СТРОГО ОДНА вещь (или один логичный комплект, например пара обуви). Если видишь сборную солянку разных предметов (мышка, часы и эспандер вместе) — ставь "is_valuable": false и пиши в "reason": "Эй, я не оцениваю оптом! 😅 Пожалуйста, оставь в кадре только одну вещь."
        🛑 ПРАВИЛО 2: Вещь должна иметь хоть какую-то ценность на вторичном рынке. Если на фото мусор, живые люди, животные, еда или пустая комната — ставь "is_valuable": false и пиши смешную причину отказа.
        
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
        
        await bot.edit_message_text("🧠 Сканирую каждый пиксель...", chat_id=user_id, message_id=msg.message_id)
        
        request_content = [prompt] + images
        response = await asyncio.to_thread(model.generate_content, request_content)
        
        # Очистка JSON
        raw_text = response.text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:-3].strip()
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:-3].strip()
            
        ai_data = json.loads(raw_text)
        
        # 🛑 НОВАЯ ВСЕЯДНАЯ ЗАЩИТА ОТ ДУРАКА
        if not ai_data.get("is_valuable"):
            funny_text = f"❌ **Оценка прервана!**\n\nИИ говорит: *{ai_data.get('reason')}*"
            await bot.edit_message_text(funny_text, chat_id=user_id, message_id=msg.message_id, parse_mode="Markdown")
            return {"status": "not_valuable"}

        # ⚙️ ИЗВЛЕЧЕНИЕ ДАННЫХ
        device_name = ai_data.get("item_name", "Неизвестная вещь")
        condition = ai_data.get("condition", "Не определено")
        multiplier = float(ai_data.get("condition_multiplier", 1.0))
        base_price = int(ai_data.get("estimated_market_price", 0))
        reason = ai_data.get("reason", "")
        
        await bot.edit_message_text(f"📊 Рассчитываю ликвидность {device_name}...", chat_id=user_id, message_id=msg.message_id)
        
        # 🧮 УМНАЯ МАТЕМАТИКА ЦЕН
        market_price = int(base_price * multiplier)
        quick_price = int(market_price * 0.85)
        instant_price = int(market_price * 0.70)
        
        # Запись в базу
        add_evaluation(user_id, device_name, market_price)
        
        final_text = (
            f"📱 **Опознано:** {device_name}\n"
            f"🔎 **Состояние:** {condition}\n"
            f"💡 **Вердикт ИИ:** {reason}\n\n"
            f"💰 **Рыночная цена:** {market_price} ₽\n"
            f"⚡ **Быстрая продажа:** {quick_price} ₽\n"
            f"🤝 **Мгновенный выкуп:** {instant_price} ₽"
        )
        
        # Возвращаем кнопки в чат
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Опубликовать (Рынок)", callback_data="action_publish")],
            [InlineKeyboardButton(text=f"💸 Продать сейчас за {instant_price} ₽", callback_data="action_instant")]
        ])
        
        await bot.edit_message_text(final_text, chat_id=user_id, message_id=msg.message_id, parse_mode="Markdown", reply_markup=keyboard)
            
    except Exception as e:
        await bot.edit_message_text(f"❌ Произошла ошибка: {e}", chat_id=user_id, message_id=msg.message_id)
        
    return {"status": "ok"}

# ==========================================
# --- 🤖 ЧАСТЬ 2: ТЕЛЕГРАМ БОТ (ЛОГИКА) ---
# ==========================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    web_app_btn = InlineKeyboardButton(
        text="📷 Запустить сканер Hlamik", 
        web_app=WebAppInfo(url=WEB_APP_URL) 
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[web_app_btn]])
    await message.answer("Привет! Я ИИ-оценщик Hlamik 🤖\nЖми кнопку ниже, чтобы открыть сканер.", reply_markup=keyboard)

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    await message.answer("🕵️‍♂️ Привет, Босс. Формирую выгрузку базы данных...")
    try:
        db_file = FSInputFile("valueit.db")
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
    
    print("\n" + "="*50)
    print(f"🚨 ВНИМАНИЕ! НОВЫЙ ЛИД! 🚨")
    print(f"Пользователь с ID {callback_query.from_user.id} готов продать гаджет ПРЯМО СЕЙЧАС!")
    print("="*50 + "\n")

# ==========================================
# --- 🚀 ЧАСТЬ 3: ЗАПУСК ГИБРИДНОГО СЕРВЕРА ---
# ==========================================

@app.on_event("startup")
async def on_startup():
    init_db()
    asyncio.create_task(dp.start_polling(bot))

if __name__ == "__main__":
    print("🚀 Стартуем сервер Хламика на порту 80...")
    uvicorn.run(app, host="0.0.0.0", port=80)








