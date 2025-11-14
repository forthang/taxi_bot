import requests
import os
from dotenv import load_dotenv
import time

load_dotenv()

token = os.getenv('BOT_TOKEN')
print(f"Token: {token[:10]}...")

# Получаем обновления
url = f'https://api.telegram.org/bot{token}/getUpdates'
response = requests.get(url)
updates = response.json()

print(f"Updates response: {updates}")
print(f"Number of updates: {len(updates.get('result', []))}")

if updates.get('result'):
    for update in updates['result']:
        print(f"Update: {update}")