import sqlite3
from datetime import datetime

# Название файла нашей базы данных
DB_NAME = "valueit.db"

def init_db():
    """Создает базу данных и таблицу, если их еще нет."""
    # Подключаемся к файлу (если его нет - он создастся автоматически)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Создаем таблицу 'evaluations' (Оценки)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            device_name TEXT,
            market_price INTEGER,
            date TEXT
        )
    ''')
    
    # Сохраняем изменения и закрываем соединение
    conn.commit()
    conn.close()
    print("🗄 База данных успешно инициализирована!")

def add_evaluation(user_id, device_name, market_price):
    """Записывает новую оценку пользователя в базу."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Получаем текущее время в красивом формате
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Вставляем данные в таблицу
    # Используем вопросительные знаки (?) для защиты от SQL-инъекций
    cursor.execute('''
        INSERT INTO evaluations (user_id, device_name, market_price, date)
        VALUES (?, ?, ?, ?)
    ''', (user_id, device_name, market_price, current_time))
    
    conn.commit()
    conn.close()
    print(f"💾 Успешно сохранено: {device_name} (юзер: {user_id}, цена: {market_price})")

# Тестовый запуск: если запустить файл напрямую, он создаст пустую базу
if __name__ == "__main__":
    init_db()