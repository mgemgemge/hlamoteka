import asyncio
import os
import random
import io
import json
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

# Загружаем переменные окружения из файла .env (наш сейф)
load_dotenv()

# --- БЕРЕМ КЛЮЧИ ИЗ СЕЙФА ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Ссылку на Web App теперь тоже берем из настроек. 
# Заглушка стоит на случай, если ты еще не прописал её в .env
WEB_APP_URL = "https://mgemgemge.github.io/hlamoteka/?v=2"
# Инициализация
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# Создаем наше API
app = FastAPI()

# --- ДОБАВЛЯЕМ ЗАЩИТУ ОТ CORS (чтобы запросы с GitHub Pages проходили) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Разрешаем принимать фотки с любых доменов (включая твой github.io)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_class=HTMLResponse)
async def read_index():
    """Отдает HTML, если мы тестируем локально."""
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "Файл index.html теперь живет на GitHub Pages, но API сервера работает! 🚀"

@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...), user_id: int = Form(...)):
    """Сюда прилетает фотография из твоего Web App"""
    msg = await bot.send_message(user_id, "🔍 Принял фото из сканера! Включаю нейронные сети...")
    
    try:
        image_data = await file.read()
        img = PIL.Image.open(io.BytesIO(image_data))
        
        # --- НОВЫЙ PRO-ПРОМПТ ДЛЯ ИИ ---
        prompt = """
        Ты профессиональный оценщик техники в ломбарде. Проанализируй фото и верни строго JSON-объект.
        Не пиши никакого лишнего текста, только валидный JSON.
        
        Формат ответа:
        {
            "is_gadget": true,
            "device_name": "Точный бренд и модель",
            "condition": "Краткое описание состояния",
            "condition_multiplier": 1.0,
            "estimated_market_price": 25000,
            "reason": "Почему такая оценка состояния и цены (1 предложение)"
        }
        Важно: estimated_market_price - это примерная рыночная цена Б/У устройства в рублях (целое число). Если это кот или еда, is_gadget=false.
        """
        
        await bot.edit_message_text("🧠 Сканирую каждый пиксель...", chat_id=user_id, message_id=msg.message_id)
        response = await asyncio.to_thread(model.generate_content, [prompt, img])
        
        # Очищаем ответ ИИ от лишнего мусора (иногда он добавляет символы ```json)
        raw_text = response.text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:-3].strip()
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:-3].strip()
            
        # Превращаем текст в удобный словарь Python
        ai_data = json.loads(raw_text)
        
        # 🛑 ЗАЩИТА ОТ ДУРАКА: Проверяем, техника ли это вообще
        if not ai_data.get("is_gadget"):
            funny_text = f"😅 Эй, бро! Кажется, это не техника.\n\nИИ говорит: *{ai_data.get('reason')}*\n\nЯ оцениваю только гаджеты. Давай сфоткаем телефон или ноут!"
            await bot.edit_message_text(funny_text, chat_id=user_id, message_id=msg.message_id, parse_mode="Markdown")
            return {"status": "not_a_gadget"}

        # Если это техника, достаем данные
        device_name = ai_data["device_name"]
        condition = ai_data["condition"]
        multiplier = ai_data["condition_multiplier"]
        reason = ai_data["reason"]
        
        await bot.edit_message_text(f"📊 Анализирую цены на {device_name}...", chat_id=user_id, message_id=msg.message_id)
        
        # --- КОНЕЦ НОВОГО БЛОКА ---
        
        await bot.edit_message_text(f"📊 Ищу цены на {device_name}...", chat_id=user_id, message_id=msg.message_id)
       # Если это техника, достаем данные
        device_name = ai_data.get("device_name", "Неизвестное устройство")
        condition = ai_data.get("condition", "Не определено")
        multiplier = float(ai_data.get("condition_multiplier", 1.0))
        base_price = int(ai_data.get("estimated_market_price", 0))
        reason = ai_data.get("reason", "")
        
        await bot.edit_message_text(f"📊 Рассчитываю ликвидность {device_name}...", chat_id=user_id, message_id=msg.message_id)
        
        # 🧮 НОВАЯ УМНАЯ МАТЕМАТИКА ЦЕН
        # Умножаем базовую цену ИИ на коэффициент состояния
        market_price = int(base_price * multiplier)
        
        # Высчитываем цены для быстрой продажи (-15%) и скупки (-30%)
        quick_price = int(market_price * 0.85)
        instant_price = int(market_price * 0.70)
        
        # Записываем в базу
        add_evaluation(user_id, device_name, market_price)
        
        final_text = (
            f"📱 **Опознано:** {device_name}\n"
            f"🔎 **Состояние:** {condition}\n"
            f"💡 **Вердикт ИИ:** {reason}\n\n"
            f"💰 **Рыночная цена:** {market_price} ₽\n"
            f"⚡ **Быстрая продажа:** {quick_price} ₽\n"
            f"🤝 **Мгновенный выкуп:** {instant_price} ₽"
        )
        
        if isinstance(price_data, dict):
            # Применяем коэффициент к ценам
            market_price = int(price_data['market'] * multiplier)
            quick_price = int(price_data['quick'] * multiplier)
            instant_price = int(price_data['instant'] * multiplier)
            
            add_evaluation(user_id, device_name, market_price)
            final_text = (
                f"📱 **Опознано:** {device_name}\n"
                f"🔎 **Состояние:** {condition}\n"
                f"💡 **Вердикт ИИ:** {reason}\n\n"
                f"💰 **Рыночная цена:** {market_price} ₽\n"
                f"⚡ **Быстрая продажа:** {quick_price} ₽\n"
                f"🤝 **Мгновенный выкуп:** {instant_price} ₽"
            )
        
        if isinstance(price_data, dict):
            add_evaluation(user_id, device_name, price_data['market'])
            final_text = (
                f"📱 **Опознано:** {device_name}\n"
                f"🔎 **Состояние:** {condition}\n\n"
                f"💰 **Рыночная цена:** {price_data['market']} ₽\n"
                f"⚡ **Быстрая продажа:** {price_data['quick']} ₽\n"
                f"🤝 **Мгновенный выкуп:** {price_data['instant']} ₽"
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📢 Опубликовать (Рынок)", callback_data="action_publish")],
                [InlineKeyboardButton(text=f"💸 Продать сейчас за {price_data['instant']} ₽", callback_data="action_instant")]
            ])
            await bot.edit_message_text(final_text, chat_id=user_id, message_id=msg.message_id, parse_mode="Markdown", reply_markup=keyboard)
        else:
            await bot.edit_message_text(f"❌ Ошибка оценки: {price_data}", chat_id=user_id, message_id=msg.message_id)
            
    except Exception as e:
        await bot.edit_message_text(f"❌ Произошла ошибка: {e}", chat_id=user_id, message_id=msg.message_id)
        
    return {"status": "ok"}

# ==========================================
# --- 🤖 ЧАСТЬ 2: ТЕЛЕГРАМ БОТ (ЛОГИКА) ---
# ==========================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    web_app_btn = InlineKeyboardButton(
        text="📷 Запустить сканер ValueIt", 
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
    """Запускаем базу данных и Телеграм-бота вместе с API"""
    init_db()
    asyncio.create_task(dp.start_polling(bot))

if __name__ == "__main__":
    print("🚀 Стартуем гибридный сервер (API + Bot) на порту 8000...")

    uvicorn.run(app, host="0.0.0.0", port=8000)



