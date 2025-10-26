#!/usr/bin/env python3
import sqlite3
import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

def test_map_data():
    """Тестируем данные для карты"""
    conn = sqlite3.connect('bot.db')
    conn.row_factory = sqlite3.Row
    
    # Получаем данные заказов
    orders = conn.execute('SELECT * FROM taxi_orders LIMIT 5').fetchall()
    conn.close()
    
    print(f"Найдено заказов: {len(orders)}")
    print(f"API ключ Яндекс: {os.getenv('YANDEX_MAPS_API_KEY', 'НЕ НАЙДЕН')}")
    
    for i, order in enumerate(orders):
        print(f"\nЗаказ {i+1}:")
        print(f"  ID: {order['id']}")
        print(f"  Маршрут: {order['route']}")
        print(f"  Дата: {order['date']}")
        print(f"  Цена: {order['price']}")
        
        if order['route']:
            parts = order['route'].split(' - ')
            if len(parts) >= 2:
                print(f"  Точка А: {parts[0].strip()}")
                print(f"  Точка Б: {parts[1].strip()}")
    
    # Преобразуем в словари для JSON
    orders_dict = [dict(order) for order in orders]
    print(f"\nПреобразовано в словари: {len(orders_dict)}")
    
    # Проверяем JSON сериализацию
    import json
    try:
        json_str = json.dumps(orders_dict, ensure_ascii=False, indent=2)
        print(f"JSON сериализация успешна, длина: {len(json_str)}")
        print("Первые 200 символов JSON:")
        print(json_str[:200])
    except Exception as e:
        print(f"Ошибка JSON сериализации: {e}")

if __name__ == "__main__":
    test_map_data() 