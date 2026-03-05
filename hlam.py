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

# Наши локальные модули
from price_engine import calculate_prices
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

def mock_scraper(device_name):
    """Полная версия умного симулятора парсера."""
    test_database = {
        "samsung galaxy s8": 5000,
        "iphone 11": 13000,
        "playstation 5": 42000,
        "airpods pro": 15000,
        "macbook air m1": 65000
    }
    
    base_price = None
    device_lower = device_name.lower()
    for key, price in test_database.items():
        if key in device_lower:
            base_price = price
            break
            
    if not base_price:
        base_price = random.randint(3000, 15000)
    
    mock_prices = [int(base_price * random.uniform(0.8, 1.2)) for _ in range(10)]
    mock_prices.extend([1, 500, 999999])
    return mock_prices

# ==========================================
# --- 🌐 ЧАСТЬ 1: API ДЛЯ WEB APP (МОРДА) ---
# ==========================================

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
            "is_gadget": true/false (true если это техника/электроника, false если это кот, еда, человек, мебель и т.д.),
            "device_name": "Точный бренд и модель (если is_gadget=true, иначе пусто)",
            "condition": "Краткое описание состояния (царапины, разбит экран, идеальное и т.д.)",
            "condition_multiplier": 1.0 (число: 0.5 если разбит/сломан, 0.8 если есть царапины, 1.0 норма, 1.2 если идеальное или видно коробку),
            "reason": "Одно предложение: почему ты так оценил состояние и предмет"
        }
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
        scraped_prices = mock_scraper(device_name)
        scraped_prices = mock_scraper(device_name)
        price_data = calculate_prices(device_name, scraped_prices)
        
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


