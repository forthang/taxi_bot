import os
import json
import aiohttp
import asyncio
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

class DeepSeekProcessor:
    def __init__(self):
        self.api_key = "sk-a8087b9cb466425cb27016f8dc0b0794"
        self.api_url = "https://api.deepseek.com/v1/chat/completions"
        
    async def process_taxi_message(self, message_text):
        """Обрабатывает сообщение такси через DeepSeek API"""
        
        prompt = f"""
        Проанализируй это сообщение о заказе такси и извлеки структурированные данные.
        
        Сообщение:
        {message_text}
        
        Извлеки следующие данные в формате JSON:
        {{
            "route": "маршрут (откуда-куда)",
            "date": "дата в формате DD.MM.YYYY или null если нет",
            "time": "время в формате HH:MM или null если нет",
            "price": число (только цифры) или null если нет,
            "passengers": число пассажиров или null если нет,
            "luggage": "описание багажа или null если нет",
            "vehicle_type": "тип транспорта (стандарт/минивэн/грузовой) или null",
            "additional_services": "дополнительные услуги или null",
            "status": "статус заказа (active/closed) или null",
            "contact": "контактная информация или null",
            "is_valid": true/false (является ли это валидным заказом такси)
        }}
        
        Если это не заказ такси, установи is_valid: false.
        Возвращай только валидный JSON без дополнительного текста.
        """
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "deepseek-chat",
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.1,
            "max_tokens": 1000
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, headers=headers, json=data) as response:
                    if response.status == 200:
                        result = await response.json()
                        content = result['choices'][0]['message']['content']
                        
                        # Пытаемся извлечь JSON из ответа
                        try:
                            # Ищем JSON в ответе
                            start = content.find('{')
                            end = content.rfind('}') + 1
                            if start != -1 and end != 0:
                                json_str = content[start:end]
                                parsed_data = json.loads(json_str)
                                
                                # Добавляем метаданные
                                parsed_data['processed_at'] = datetime.now().isoformat()
                                parsed_data['source_message'] = message_text
                                
                                return parsed_data
                            else:
                                return None
                        except json.JSONDecodeError:
                            print(f"Ошибка парсинга JSON: {content}")
                            return None
                    else:
                        print(f"Ошибка API: {response.status}")
                        return None
                        
        except Exception as e:
            print(f"Ошибка при обработке через AI: {e}")
            return None

# Функция для тестирования
async def test_processor():
    processor = DeepSeekProcessor()
    
    test_messages = [
        "Сегодня 30.07 в 19:00\nМагнитогорск-Челябинск\n3 человека+ручная кладь\n8000 на руки",
        "Дата: 01.08.2025\n11:40\n🚩 А: г Санкт-Петербург, тер Пулково-1\n🏁 Б: Новгородская обл, Крестецкий р-н\nСтоимость: 7560₽\nПассажиры: 4\nБагаж: Да"
    ]
    
    for msg in test_messages:
        print(f"\nОбрабатываю: {msg}")
        result = await processor.process_taxi_message(msg)
        if result:
            print(f"Результат: {json.dumps(result, indent=2, ensure_ascii=False)}")
        else:
            print("Ошибка обработки")

if __name__ == "__main__":
    asyncio.run(test_processor()) 