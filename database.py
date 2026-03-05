import sqlite3
import datetime

import os

# Если на сервере есть папка /data, сохраняем туда. Иначе — в текущую папку.
if os.path.exists("/data"):
    DB_NAME = "/data/valueit.db"
else:
    DB_NAME = "valueit.db"

def init_db():
    """Создает базу и таблицу, если их еще нет"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            device_name TEXT,
            price INTEGER,
            date TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_evaluation(user_id, device_name, price):
    """Записывает новую оценку в базу"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('INSERT INTO evaluations (user_id, device_name, price, date) VALUES (?, ?, ?, ?)',
                   (user_id, device_name, price, now))
    conn.commit()
    conn.close()

