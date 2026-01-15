import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.filters import Command
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncio
import yookassa
from yookassa import Payment, Configuration
import sqlite3
import json
from datetime import datetime
import os

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен бота
API_TOKEN = '8370203637:AAHR37024BBaqREiNCyqWG54DvodYjkf8kA'

# Настройки ЮKassa (нужно заполнить своими данными)
YOOKASSA_SHOP_ID = 'your_shop_id'
YOOKASSA_SECRET_KEY = 'your_secret_key'

# Инициализация бота и диспетчера с FSM
storage = MemoryStorage()
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=storage)

# Настройка ЮKassa
Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_SECRET_KEY

# База данных SQLite
DB_NAME = 'esim_bot.db'


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        registered_at TIMESTAMP
    )
    ''')

    # Таблица заказов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        user_id INTEGER,
        esim_country TEXT,
        esim_price REAL,
        payment_id TEXT,
        status TEXT,
        created_at TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')

    # Таблица eSIM стран (примерные данные)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS esim_countries (
        country_id INTEGER PRIMARY KEY AUTOINCREMENT,
        country_name TEXT,
        country_code TEXT,
        price REAL,
        data_amount TEXT,
        validity_days INTEGER,
        description TEXT
    )
    ''')

    # Добавляем тестовые страны, если их нет
    cursor.execute("SELECT COUNT(*) FROM esim_countries")
    if cursor.fetchone()[0] == 0:
        test_countries = [
            ('США', 'US', 9.99, '1GB', 7, 'eSIM для США, 1GB на 7 дней'),
            ('Германия', 'DE', 7.99, '500MB', 5, 'eSIM для Германии, 500MB на 5 дней'),
            ('Турция', 'TR', 5.99, '3GB', 10, 'eSIM для Турции, 3GB на 10 дней'),
            ('Таиланд', 'TH', 8.99, '2GB', 14, 'eSIM для Таиланда, 2GB на 14 дней'),
            ('Япония', 'JP', 12.99, '1.5GB', 7, 'eSIM для Японии, 1.5GB на 7 дней'),
        ]
        cursor.executemany(
            "INSERT INTO esim_countries (country_name, country_code, price, data_amount, validity_days, description) VALUES (?, ?, ?, ?, ?, ?)",
            test_countries
        )

    conn.commit()
    conn.close()


init_db()


# Состояния для FSM (если понадобятся)
class UserState(StatesGroup):
    waiting_for_search = State()
    waiting_for_payment = State()


# Главное меню
def get_main_menu():
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(text="🌍 Поиск eSIM", callback_data="search_esim"),
        InlineKeyboardButton(text="🛒 Мои покупки", callback_data="my_orders")
    )
    keyboard.row(
        InlineKeyboardButton(text="📱 Каталог на сайте", web_app=WebAppInfo(url="https://esimzone.ru/catalog/"))
    )
    keyboard.row(
        InlineKeyboardButton(text="❓ Помощь", callback_data="help")
    )
    return keyboard.as_markup()


# Меню поиска eSIM
def get_search_menu():
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(text="🔍 Найти по стране", callback_data="search_by_country"),
    )
    keyboard.row(
        InlineKeyboardButton(text="💰 По цене (дешевые)", callback_data="search_cheap"),
        InlineKeyboardButton(text="💎 По объему данных", callback_data="search_by_data")
    )
    keyboard.row(
        InlineKeyboardButton(text="↩️ Назад", callback_data="main_menu")
    )
    return keyboard.as_markup()


# Клавиатура для страны
def get_country_keyboard(country_id):
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(text="💳 Купить", callback_data=f"buy_{country_id}"),
        InlineKeyboardButton(text="📋 Подробнее", callback_data=f"details_{country_id}")
    )
    keyboard.row(
        InlineKeyboardButton(text="↩️ Назад к поиску", callback_data="search_esim")
    )
    return keyboard.as_markup()


# Обработчик команды /start
@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    user_id = message.from_user.id

    # Сохраняем пользователя в БД
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, registered_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, message.from_user.username, message.from_user.first_name,
         message.from_user.last_name, datetime.now())
    )
    conn.commit()
    conn.close()

    welcome_text = (
        "👋 Добро пожаловать в eSIMZone Bot!\n\n"
        "Здесь вы можете приобрести eSIM для путешествий в разные страны.\n"
        "Выберите опцию из меню ниже:"
    )

    await message.answer(welcome_text, reply_markup=get_main_menu())


# Обработчик кнопки поиска eSIM
@dp.callback_query(F.data == "search_esim")
async def process_search_esim(callback_query: types.CallbackQuery):
    await callback_query.answer()
    await callback_query.message.edit_text(
        "🔍 Выберите способ поиска eSIM:",
        reply_markup=get_search_menu()
    )


# Поиск по стране
@dp.callback_query(F.data == "search_by_country")
async def process_search_by_country(callback_query: types.CallbackQuery):
    await callback_query.answer()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT country_id, country_name, price, data_amount FROM esim_countries ORDER BY country_name")
    countries = cursor.fetchall()
    conn.close()

    if not countries:
        await callback_query.message.edit_text("Страны не найдены.")
        return

    text = "🌍 Доступные страны:\n\n"
    keyboard = InlineKeyboardBuilder()

    for country in countries:
        country_id, country_name, price, data_amount = country
        text += f"{country_name} - {data_amount} - ${price}\n"
        keyboard.row(InlineKeyboardButton(
            text=f"{country_name} (${price})",
            callback_data=f"country_{country_id}"
        ))

    keyboard.row(InlineKeyboardButton(text="↩️ Назад", callback_data="search_esim"))

    await callback_query.message.edit_text(text, reply_markup=keyboard.as_markup())


# Показать информацию о стране
@dp.callback_query(F.data.startswith("country_"))
async def process_country_info(callback_query: types.CallbackQuery):
    await callback_query.answer()
    country_id = callback_query.data.split('_')[1]

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM esim_countries WHERE country_id = ?", (country_id,))
    country = cursor.fetchone()
    conn.close()

    if country:
        country_id, country_name, country_code, price, data_amount, validity_days, description = country
        text = (
            f"🌍 {country_name} ({country_code})\n\n"
            f"📊 Объем данных: {data_amount}\n"
            f"⏱️ Срок действия: {validity_days} дней\n"
            f"💰 Цена: ${price}\n\n"
            f"📝 {description}"
        )

        await callback_query.message.edit_text(
            text,
            reply_markup=get_country_keyboard(country_id)
        )
    else:
        await callback_query.message.edit_text("Страна не найдена.")


# Обработчик покупки
@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(callback_query: types.CallbackQuery):
    await callback_query.answer()
    country_id = callback_query.data.split('_')[1]

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT country_name, price FROM esim_countries WHERE country_id = ?", (country_id,))
    country = cursor.fetchone()
    conn.close()

    if country:
        country_name, price = country
        user_id = callback_query.from_user.id

        # Создаем платеж в ЮKassa
        payment = Payment.create({
            "amount": {
                "value": f"{price}",
                "currency": "USD"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": "https://t.me/your_bot_username"
            },
            "capture": True,
            "description": f"eSIM для {country_name}",
            "metadata": {
                "user_id": user_id,
                "country_id": country_id
            }
        })

        # Сохраняем заказ в БД
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO orders (order_id, user_id, esim_country, esim_price, payment_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (payment.id, user_id, country_name, price, payment.id, 'pending', datetime.now())
        )
        conn.commit()
        conn.close()

        # Отправляем ссылку на оплату
        keyboard = InlineKeyboardBuilder()
        keyboard.row(
            InlineKeyboardButton(text="💳 Оплатить", url=payment.confirmation.confirmation_url)
        )
        keyboard.row(
            InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_payment_{payment.id}")
        )

        await callback_query.message.edit_text(
            f"💳 Для оплаты eSIM для {country_name} (${price}) нажмите кнопку ниже:\n"
            f"После оплаты нажмите 'Проверить оплату'",
            reply_markup=keyboard.as_markup()
        )


# Проверка оплаты
@dp.callback_query(F.data.startswith("check_payment_"))
async def process_check_payment(callback_query: types.CallbackQuery):
    await callback_query.answer()
    payment_id = callback_query.data.split('_')[2]

    # Проверяем статус платежа в ЮKassa
    payment = Payment.find_one(payment_id)

    if payment.status == 'succeeded':
        # Обновляем статус заказа в БД
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orders SET status = 'completed' WHERE payment_id = ?",
            (payment_id,)
        )
        conn.commit()

        # Получаем информацию о заказе
        cursor.execute(
            "SELECT esim_country FROM orders WHERE payment_id = ?",
            (payment_id,)
        )
        order = cursor.fetchone()
        conn.close()

        if order:
            esim_country = order[0]
            # Здесь должна быть логика отправки eSIM
            # Например, генерация QR-кода или отправка активационного кода
            await callback_query.message.edit_text(
                f"✅ Оплата прошла успешно!\n\n"
                f"Ваш eSIM для {esim_country} активирован.\n"
                f"Инструкции по активации отправлены в отдельном сообщении.\n\n"
                f"Для активации:\n"
                f"1. Откройте настройки телефона\n"
                f"2. Выберите 'Сотовая связь'\n"
                f"3. Нажмите 'Добавить тарифный план'\n"
                f"4. Отсканируйте QR-код или введите код вручную\n\n"
                f"Код активации: ESIM-{payment_id[:8].upper()}"
            )
    else:
        await callback_query.message.edit_text(
            "⏳ Платеж еще не подтвержден. Попробуйте проверить позже или обратитесь в поддержку."
        )


# Мои заказы
@dp.callback_query(F.data == "my_orders")
async def process_my_orders(callback_query: types.CallbackQuery):
    await callback_query.answer()
    user_id = callback_query.from_user.id

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT order_id, esim_country, esim_price, status, created_at FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
        (user_id,)
    )
    orders = cursor.fetchall()
    conn.close()

    if orders:
        text = "🛒 Ваши последние заказы:\n\n"
        for order in orders:
            order_id, esim_country, esim_price, status, created_at = order
            status_emoji = "✅" if status == 'completed' else "⏳" if status == 'pending' else "❌"
            text += f"{status_emoji} {esim_country} - ${esim_price}\n"
            text += f"   ID: {order_id[:8]}...\n"
            text += f"   Дата: {created_at}\n\n"

        keyboard = InlineKeyboardBuilder()
        keyboard.row(InlineKeyboardButton(text="↩️ Назад", callback_data="main_menu"))

        await callback_query.message.edit_text(text, reply_markup=keyboard.as_markup())
    else:
        keyboard = InlineKeyboardBuilder()
        keyboard.row(InlineKeyboardButton(text="🌍 Купить eSIM", callback_data="search_esim"))
        keyboard.row(InlineKeyboardButton(text="↩️ Назад", callback_data="main_menu"))

        await callback_query.message.edit_text(
            "У вас еще нет заказов.",
            reply_markup=keyboard.as_markup()
        )


# Помощь
@dp.callback_query(F.data == "help")
async def process_help(callback_query: types.CallbackQuery):
    await callback_query.answer()

    help_text = (
        "❓ **Помощь и поддержка**\n\n"
        "🤔 **Как это работает?**\n"
        "1. Выберите eSIM для нужной страны\n"
        "2. Оплатите через безопасную платежную систему\n"
        "3. Получите QR-код для активации\n"
        "4. Отсканируйте QR-код в настройках телефона\n\n"

        "📱 **Поддерживаемые устройства:**\n"
        "• iPhone XS и новее\n"
        "• Google Pixel 3 и новее\n"
        "• Samsung Galaxy S20 и новее\n"
        "• Другие устройства с поддержкой eSIM\n\n"

        "🔄 **Возврат средств:**\n"
        "Возврат возможен в течение 24 часов после покупки, если eSIM не был активирован.\n\n"

        "📞 **Поддержка:** @your_support_username"
    )

    keyboard = InlineKeyboardBuilder()
    keyboard.row(InlineKeyboardButton(text="🌍 Купить eSIM", callback_data="search_esim"))
    keyboard.row(InlineKeyboardButton(text="↩️ Назад", callback_data="main_menu"))

    await callback_query.message.edit_text(help_text, reply_markup=keyboard.as_markup())


# Обработчик кнопки "Назад" в главное меню
@dp.callback_query(F.data == "main_menu")
async def process_main_menu(callback_query: types.CallbackQuery):
    await callback_query.answer()

    welcome_text = (
        "👋 Добро пожаловать в eSIMZone Bot!\n\n"
        "Здесь вы можете приобрести eSIM для путешествий в разные страны.\n"
        "Выберите опцию из меню ниже:"
    )

    await callback_query.message.edit_text(welcome_text, reply_markup=get_main_menu())


# Поиск дешевых eSIM
@dp.callback_query(F.data == "search_cheap")
async def process_search_cheap(callback_query: types.CallbackQuery):
    await callback_query.answer()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT country_id, country_name, price, data_amount FROM esim_countries ORDER BY price ASC LIMIT 10")
    countries = cursor.fetchall()
    conn.close()

    text = "💰 Самые дешевые eSIM:\n\n"
    keyboard = InlineKeyboardBuilder()

    for country in countries:
        country_id, country_name, price, data_amount = country
        text += f"{country_name} - {data_amount} - ${price}\n"
        keyboard.row(InlineKeyboardButton(
            text=f"{country_name} (${price})",
            callback_data=f"country_{country_id}"
        ))

    keyboard.row(InlineKeyboardButton(text="↩️ Назад", callback_data="search_esim"))

    await callback_query.message.edit_text(text, reply_markup=keyboard.as_markup())


# Поиск по объему данных
@dp.callback_query(F.data == "search_by_data")
async def process_search_by_data(callback_query: types.CallbackQuery):
    await callback_query.answer()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT country_id, country_name, price, data_amount FROM esim_countries ORDER BY data_amount DESC LIMIT 10")
    countries = cursor.fetchall()
    conn.close()

    text = "💎 eSIM с большим объемом данных:\n\n"
    keyboard = InlineKeyboardBuilder()

    for country in countries:
        country_id, country_name, price, data_amount = country
        text += f"{country_name} - {data_amount} - ${price}\n"
        keyboard.row(InlineKeyboardButton(
            text=f"{country_name} ({data_amount})",
            callback_data=f"country_{country_id}"
        ))

    keyboard.row(InlineKeyboardButton(text="↩️ Назад", callback_data="search_esim"))

    await callback_query.message.edit_text(text, reply_markup=keyboard.as_markup())


# Команда /catalog для быстрого доступа к каталогу
@dp.message(Command("catalog"))
async def send_catalog(message: types.Message):
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(
            text="📱 Открыть каталог eSIM",
            web_app=WebAppInfo(url="https://esimzone.ru/catalog/")
        )
    )
    keyboard.row(
        InlineKeyboardButton(text="🌍 Поиск в боте", callback_data="search_esim")
    )

    await message.answer(
        "Нажмите кнопку ниже, чтобы открыть полный каталог eSIM на нашем сайте:",
        reply_markup=keyboard.as_markup()
    )


# Обработчик текстовых сообщений (поиск по названию страны)
@dp.message(F.text)
async def process_text_search(message: types.Message):
    search_query = message.text.strip()

    if len(search_query) < 2:
        await message.answer(
            "Введите название страны для поиска (минимум 2 символа).\n"
            "Или используйте команды:\n"
            "/start - Главное меню\n"
            "/catalog - Открыть каталог"
        )
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT country_id, country_name, price, data_amount FROM esim_countries WHERE country_name LIKE ? ORDER BY country_name",
        (f'%{search_query}%',)
    )
    countries = cursor.fetchall()
    conn.close()

    if countries:
        text = f"🔍 Результаты поиска по запросу '{search_query}':\n\n"
        keyboard = InlineKeyboardBuilder()

        for country in countries:
            country_id, country_name, price, data_amount = country
            text += f"{country_name} - {data_amount} - ${price}\n"
            keyboard.row(InlineKeyboardButton(
                text=f"{country_name} (${price})",
                callback_data=f"country_{country_id}"
            ))

        keyboard.row(InlineKeyboardButton(text="↩️ В главное меню", callback_data="main_menu"))

        await message.answer(text, reply_markup=keyboard.as_markup())
    else:
        keyboard = InlineKeyboardBuilder()
        keyboard.row(
            InlineKeyboardButton(
                text="📱 Открыть каталог на сайте",
                web_app=WebAppInfo(url="https://esimzone.ru/catalog/")
            )
        )
        keyboard.row(
            InlineKeyboardButton(text="🌍 Весь список стран", callback_data="search_by_country")
        )

        await message.answer(
            f"По запросу '{search_query}' ничего не найдено.\n"
            f"Попробуйте использовать полный каталог или посмотреть все доступные страны.",
            reply_markup=keyboard.as_markup()
        )


async def delete_webhook():
    """Удаляем вебхук перед запуском polling"""
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Вебхук успешно удален")
    except Exception as e:
        logger.warning(f"Не удалось удалить вебхук: {e}")


async def main():
    # Удаляем вебхук перед запуском
    await delete_webhook()

    logger.info("Бот запущен...")
    await dp.start_polling(bot)


# СПОСОБ 1: Для обычного запуска из терминала
if __name__ == '__main__':
    import sys

    # Проверяем, не запущен ли уже event loop
    try:
        asyncio.run(main())
    except RuntimeError as e:
        if "running event loop" in str(e):
            # Если event loop уже запущен (например, в Jupyter/Colab)
            print("Обнаружен запущенный event loop. Использую альтернативный метод запуска...")

            # СПОСОБ 2: Для Jupyter/Colab с использованием nest_asyncio
            try:
                import nest_asyncio

                nest_asyncio.apply()
                print("nest_asyncio применен успешно")

                # Запускаем бота
                asyncio.run(main())
            except ImportError:
                print("Установите nest_asyncio: pip install nest_asyncio")

                # Альтернатива: запуск в существующем loop
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(main())
                else:
                    loop.run_until_complete(main())
        else:
            # Если это другая ошибка
            logger.error(f"Ошибка при запуске: {e}")
            raise e
    except Exception as e:
        logger.error(f"Ошибка при запуске: {e}")
        raise e

# delete_webhook.py
import asyncio
from aiogram import Bot

async def delete_webhook():
    bot = Bot(token='8588036832:AAH17iTX500TU1EL6h3AU8em9W4va9-FRxo')
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        print("✅ Вебхук успешно удален!")
    except Exception as e:
        print(f"❌ Ошибка при удалении вебхука: {e}")
    finally:
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(delete_webhook())