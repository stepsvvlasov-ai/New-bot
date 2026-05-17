import asyncio
import hashlib
import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from aiogram import Bot, types
from aiogram.utils import executor
from aiogram.dispatcher import Dispatcher
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from deep_translator import GoogleTranslator
from dotenv import load_dotenv
import logging

# ================= ЗАГРУЗКА НАСТРОЕК =================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
CHANNEL_LINK = os.getenv("CHANNEL_LINK")

# Настройки
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 1800))
MAX_NEWS_PER_SOURCE = int(os.getenv("MAX_NEWS_PER_SOURCE", 5))
MAX_NEWS_AGE_DAYS = int(os.getenv("MAX_NEWS_AGE_DAYS", 2))

# ================= RSS ИСТОЧНИКИ =================
RSS_SOURCES = [
    "https://www.reddit.com/r/artificial/.rss",
    "https://www.reddit.com/r/ChatGPT/.rss",
    "https://www.reddit.com/r/OpenAI/.rss",
    "https://feeds.feedburner.com/ArtificialIntelligenceNews",
    "https://www.technologyreview.com/feed/ai/",
    "https://venturebeat.com/category/ai/feed/",
]

# ================= КЛЮЧЕВЫЕ СЛОВА =================
KEYWORDS = [
    "gpt", "chatgpt", "нейросеть", "нейронная сеть", "neural network",
    "deep learning", "llm", "openai", "ai", "machine learning", "ии"
]

# ================= НАСТРОЙКА ЛОГИРОВАНИЯ =================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ================= ИНИЦИАЛИЗАЦИЯ БОТА =================
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
translator = GoogleTranslator(source='en', target='ru')

PUBLISHED_FILE = "published_news.txt"

# ================= КЛАСС ДЛЯ RSS ЗАПИСИ =================
class RSSEntry:
    def __init__(self):
        self.title = ""
        self.link = ""
        self.summary = ""
        self.published = ""

def parse_rss_feed(url):
    """Парсит RSS ленту"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        root = ET.fromstring(response.content)
        entries = []
        
        for item in root.findall('.//item'):
            entry = RSSEntry()
            
            title_elem = item.find('title')
            entry.title = title_elem.text if title_elem is not None else ""
            
            link_elem = item.find('link')
            entry.link = link_elem.text if link_elem is not None else ""
            
            desc_elem = item.find('description')
            if desc_elem is not None and desc_elem.text:
                soup = BeautifulSoup(desc_elem.text, 'html.parser')
                entry.summary = soup.get_text()[:500]
            
            pub_elem = item.find('pubDate')
            if pub_elem is not None and pub_elem.text:
                entry.published = pub_elem.text
            
            if entry.title and entry.link:
                entries.append(entry)
        
        return entries
    except Exception as e:
        logging.error(f"Ошибка парсинга {url}: {e}")
        return []

def load_published():
    try:
        with open(PUBLISHED_FILE, "r", encoding='utf-8') as f:
            return set(line.strip() for line in f)
    except FileNotFoundError:
        return set()

def save_published(published_set):
    with open(PUBLISHED_FILE, "w", encoding='utf-8') as f:
        for news_id in published_set:
            f.write(f"{news_id}\n")

def get_news_id(entry):
    return hashlib.md5(entry.link.encode()).hexdigest()

def is_relevant(entry):
    text = (entry.title + " " + entry.summary).lower()
    return any(keyword in text for keyword in KEYWORDS)

def translate_text_sync(text):
    if not text or len(text.strip()) < 10:
        return text
    try:
        if len(text) > 3000:
            text = text[:3000]
        return translator.translate(text)
    except Exception as e:
        logging.error(f"Ошибка перевода: {e}")
        return text

async def translate_text(text):
    return await asyncio.to_thread(translate_text_sync, text)

async def get_subscribe_keyboard():
    bot_info = await bot.get_me()
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton(text="📢 ПОДПИСАТЬСЯ НА КАНАЛ", url=CHANNEL_LINK)
    )
    keyboard.add(
        InlineKeyboardButton(text="🤖 ДОБАВИТЬ БОТА", url=f"https://t.me/{bot_info.username}?startchannel=true")
    )
    return keyboard

async def format_news_message(entry, source_name):
    title_ru = await translate_text(entry.title)
    desc_ru = await translate_text(entry.summary[:400])
    
    message = f"""<b>🤖 {title_ru}</b>

<i>{desc_ru}</i>

📌 <b>Источник:</b> {source_name}
🔗 <a href="{entry.link}">📖 Читать полностью →</a>

---
<code>🌐 Перевод автоматический</code>"""
    return message

async def check_and_post():
    logging.info("🔍 Проверка новостей...")
    published_ids = load_published()
    new_posts_count = 0
    
    for source_url in RSS_SOURCES:
        entries = parse_rss_feed(source_url)
        source_name = source_url.split('/')[2].replace('www.', '')
        
        for entry in entries[:MAX_NEWS_PER_SOURCE]:
            if not is_relevant(entry):
                continue
            
            news_id = get_news_id(entry)
            if news_id in published_ids:
                continue
            
            message = await format_news_message(entry, source_name)
            
            try:
                await bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=message,
                    parse_mode="HTML",
                    reply_markup=await get_subscribe_keyboard()
                )
                published_ids.add(news_id)
                new_posts_count += 1
                logging.info(f"✅ {entry.title[:50]}...")
                await asyncio.sleep(2)
            except Exception as e:
                logging.error(f"❌ Ошибка: {e}")
    
    if new_posts_count > 0:
        save_published(published_ids)
        logging.info(f"📊 Опубликовано: {new_posts_count}")

async def periodic_check():
    await asyncio.sleep(10)
    while True:
        await check_and_post()
        await asyncio.sleep(CHECK_INTERVAL)

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    await message.answer(
        f"🤖 Бот для новостей об ИИ запущен!\n📢 Канал: {CHANNEL_LINK}",
        reply_markup=await get_subscribe_keyboard()
    )

@dp.message_handler(commands=['check'])
async def cmd_check(message: types.Message):
    await message.answer("🔍 Проверка...")
    await check_and_post()
    await message.answer("✅ Готово!")

async def on_startup(dp):
    logging.info("🚀 Бот запущен")
    asyncio.create_task(periodic_check())

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ Укажите BOT_TOKEN в .env")
        exit(1)
    if not CHANNEL_ID:
        print("❌ Укажите CHANNEL_ID в .env")
        exit(1)
    
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
