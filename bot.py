import asyncio
import hashlib
import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
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
    "https://www.reddit.com/r/MachineLearning/.rss",
    "https://feeds.feedburner.com/ArtificialIntelligenceNews",
    "https://www.technologyreview.com/feed/ai/",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
]

# ================= КЛЮЧЕВЫЕ СЛОВА =================
KEYWORDS = [
    "gpt", "chatgpt", "нейросеть", "нейронная сеть", "neural network",
    "deep learning", "llm", "openai", "anthropic", "claude", "gemini",
    "bard", "midjourney", "stable diffusion", "dall-e", "искусственный интеллект",
    "ai", "machine learning", "ml", "agi", "ии", "робот"
]

# ================= НАСТРОЙКА ЛОГИРОВАНИЯ =================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ================= ИНИЦИАЛИЗАЦИЯ БОТА =================
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
translator = GoogleTranslator(source='en', target='ru')

# Файл для хранения опубликованных новостей
PUBLISHED_FILE = "published_news.txt"

# ================= КЛАСС ДЛЯ RSS ЗАПИСИ =================
class RSSEntry:
    def __init__(self):
        self.title = ""
        self.link = ""
        self.summary = ""
        self.published = ""
        self.published_parsed = None

# ================= ФУНКЦИИ ДЛЯ РАБОТЫ С RSS =================
def parse_rss_feed(url):
    """Парсит RSS ленту"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
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
                try:
                    from email.utils import parsedate_to_datetime
                    entry.published_parsed = parsedate_to_datetime(entry.published)
                except:
                    entry.published_parsed = None
            
            if entry.title and entry.link:
                entries.append(entry)
        
        return entries
    except Exception as e:
        logging.error(f"Ошибка парсинга {url}: {e}")
        return []

def load_published():
    """Загружает ID опубликованных новостей"""
    try:
        with open(PUBLISHED_FILE, "r", encoding='utf-8') as f:
            return set(line.strip() for line in f)
    except FileNotFoundError:
        return set()

def save_published(published_set):
    """Сохраняет ID опубликованных новостей"""
    with open(PUBLISHED_FILE, "w", encoding='utf-8') as f:
        for news_id in published_set:
            f.write(f"{news_id}\n")

def get_news_id(entry):
    """Генерирует уникальный ID новости"""
    return hashlib.md5(entry.link.encode()).hexdigest()

def is_relevant(entry):
    """Проверяет релевантность новости"""
    text = (entry.title + " " + entry.summary).lower()
    return any(keyword in text for keyword in KEYWORDS)

# ================= ФУНКЦИИ ПЕРЕВОДА =================
def translate_text_sync(text):
    """Синхронный перевод текста"""
    if not text or len(text.strip()) < 10:
        return text
    
    try:
        if len(text) > 3000:
            text = text[:3000]
        
        translated = translator.translate(text)
        return translated
    except Exception as e:
        logging.error(f"Ошибка перевода: {e}")
        return text

async def translate_text(text):
    """Асинхронная обёртка для перевода"""
    return await asyncio.to_thread(translate_text_sync, text)

# ================= КЛАВИАТУРА =================
async def get_subscribe_keyboard():
    """Создает клавиатуру с кнопкой подписки"""
    bot_info = await bot.get_me()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📢 ПОДПИСАТЬСЯ НА КАНАЛ", url=CHANNEL_LINK),
        ],
        [
            InlineKeyboardButton(text="🤖 ДОБАВИТЬ БОТА В КАНАЛ", url=f"https://t.me/{bot_info.username}?startchannel=true"),
        ]
    ])
    return keyboard

# ================= ФОРМАТИРОВАНИЕ НОВОСТИ =================
async def format_news_message(entry, source_name):
    """Форматирует новость для отправки"""
    title_ru = await translate_text(entry.title)
    description_ru = await translate_text(entry.summary)
    
    if len(description_ru) > 400:
        description_ru = description_ru[:400] + "..."
    
    message = f"""<b>🤖 {title_ru}</b>

<i>{description_ru}</i>

📌 <b>Источник:</b> {source_name}
🔗 <a href="{entry.link}">📖 Читать полную статью →</a>

---
<code>🌐 Новость переведена автоматически</code>"""
    
    return message

# ================= ОСНОВНАЯ ЛОГИКА БОТА =================
async def check_and_post():
    """Проверяет все RSS ленты и публикует новые новости"""
    logging.info("🔍 Начинаю проверку новостей...")
    
    published_ids = load_published()
    new_posts_count = 0
    
    for source_url in RSS_SOURCES:
        logging.info(f"  📡 Проверяю: {source_url}")
        
        entries = parse_rss_feed(source_url)
        source_name = source_url.split('/')[2].replace('www.', '')
        
        for entry in entries[:MAX_NEWS_PER_SOURCE]:
            if not is_relevant(entry):
                continue
            
            news_id = get_news_id(entry)
            if news_id in published_ids:
                continue
            
            if entry.published_parsed:
                if entry.published_parsed < datetime.now() - timedelta(days=MAX_NEWS_AGE_DAYS):
                    continue
            
            message = await format_news_message(entry, source_name)
            
            try:
                await bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=message,
                    parse_mode="HTML",
                    disable_web_page_preview=False,
                    reply_markup=await get_subscribe_keyboard()
                )
                
                published_ids.add(news_id)
                new_posts_count += 1
                logging.info(f"  ✅ Опубликовано: {entry.title[:50]}...")
                
                await asyncio.sleep(2)
                
            except Exception as e:
                logging.error(f"  ❌ Ошибка отправки: {e}")
    
    if new_posts_count > 0:
        save_published(published_ids)
        logging.info(f"📊 Всего опубликовано: {new_posts_count} новостей")
    else:
        logging.info("📭 Новых новостей не найдено")

async def periodic_check():
    """Периодическая проверка новостей"""
    await asyncio.sleep(10)
    
    while True:
        try:
            await check_and_post()
        except Exception as e:
            logging.error(f"❌ Ошибка в периодической проверке: {e}")
        
        logging.info(f"⏰ Следующая проверка через {CHECK_INTERVAL // 60} минут\n")
        await asyncio.sleep(CHECK_INTERVAL)

# ================= ОБРАБОТЧИКИ КОМАНД =================
@dp.message()
async def handle_message(message: types.Message):
    """Обработчик текстовых сообщений"""
    if message.text == '/start':
        welcome_text = f"""<b>🤖 Привет! Я бот для публикации новостей об ИИ</b>

📰 <b>Что я умею:</b>
• Собираю свежие новости из {len(RSS_SOURCES)}+ источников
• Автоматически перевожу на русский язык
• Фильтрую только важные новости об ИИ

📢 <b>Канал с новостями:</b> <a href="{CHANNEL_LINK}">Подписаться</a>

🚀 Бот работает 24/7 и публикует новости каждые {CHECK_INTERVAL // 60} минут!"""
        
        await message.answer(welcome_text, parse_mode="HTML", reply_markup=await get_subscribe_keyboard())
    
    elif message.text == '/check':
        await message.answer("🔍 Начинаю принудительную проверку новостей...")
        await check_and_post()
        await message.answer("✅ Проверка завершена!")
    
    elif message.text == '/help':
        help_text = """<b>📖 Доступные команды:</b>

/start - Приветствие и информация о боте
/check - Принудительная проверка новостей
/help - Показать эту справку

<b>📌 Как это работает:</b>
Бот проверяет RSS ленты популярных ИИ-ресурсов, отбирает релевантные новости, переводит их на русский и публикует в канал."""
        
        await message.answer(help_text, parse_mode="HTML")

# ================= ЗАПУСК БОТА =================
async def main():
    """Главная функция запуска бота"""
    logging.info("🚀 БОТ ЗАПУЩЕН И НАЧАЛ РАБОТУ")
    logging.info(f"📢 Канал: {CHANNEL_ID}")
    logging.info(f"⏰ Интервал проверки: {CHECK_INTERVAL // 60} минут")
    logging.info(f"📰 Источников: {len(RSS_SOURCES)}")
    
    # Отправляем приветствие в канал
    welcome_channel = f"""<b>🤖 Бот для публикации ИИ-новостей запущен!</b>

✅ Автоматический сбор новостей активирован
🌐 Перевод на русский язык включен
📊 Проверка каждые {CHECK_INTERVAL // 60} минут
📰 Мониторинг {len(RSS_SOURCES)} источников

<i>Скоро здесь появятся самые свежие новости об искусственном интеллекте!</i>"""
    
    try:
        await bot.send_message(
            CHANNEL_ID,
            welcome_channel,
            parse_mode="HTML",
            reply_markup=await get_subscribe_keyboard()
        )
        logging.info("✅ Приветствие отправлено в канал")
    except Exception as e:
        logging.warning(f"⚠️ Не удалось отправить приветствие: {e}")
        logging.warning("Проверьте права бота в канале!")
    
    # Запускаем периодическую проверку
    asyncio.create_task(periodic_check())
    
    # Запускаем поллинг
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Проверка настроек
    if not BOT_TOKEN:
        print("❌ ОШИБКА: Укажите BOT_TOKEN в файле .env")
        print("   Получите токен у @BotFather")
        exit(1)
    
    if not CHANNEL_ID:
        print("❌ ОШИБКА: Укажите CHANNEL_ID в файле .env")
        print("   Например: CHANNEL_ID=@my_ai_news")
        exit(1)
    
    print("✅ Бот успешно настроен")
    print("🚀 Запуск...")
    
    # Запускаем бота
    asyncio.run(main())