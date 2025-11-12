# telegram_bot.py 
import os
import signal
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import datetime
import time as time_module
import re
import threading
from datetime import timedelta
import logging

# === НАСТРОЙКА ЛОГГИРОВАНИЯ ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# === ОБРАБОТКА ЗАВЕРШЕНИЯ ===
def handle_exit(signum, frame):
    logger.info("🤖 Бот завершает работу...")
    exit(0)

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

# === КОНФИГУРАЦИЯ ===
# Используем переменные окружения Railway
BOT_TOKEN = os.environ.get('BOT_TOKEN', '7546412473:AAGPRVfkVoTjf4e-yLzRk5WIS0a0nM74Evg')
bot = telebot.TeleBot(BOT_TOKEN)

# Обновленные данные ресторана
RESTAURANT_INFO = {
    'name': 'Лаундж-Бар на Уральской',
    'address': 'г. Калининград, ул. Уральская, 11',
    'phone': '+7(4012)63-69-39',
    'hours_week': 'вс-чт 16:00-02:00',
    'hours_weekend': 'пт-сб 16:00-03:00',
    'description': 'Уютный лаундж-бар с игровой приставкой, Xbox и настольными играми. Идеальное место для отдыха с друзьями!',
    'entertainment': '🎮 Игровая приставка\n🎯 Xbox\n♟️ Настольные игры'
}

ADMIN_ID = 800471772

# Состояния бронирования
class BookingState:
    DATE = 1
    TIME = 2
    GUESTS = 3
    NAME = 4
    PHONE = 5
    COMMENT = 6

# Классы для управления состояниями
class AdminStates:
    _reply_modes = {}
    _review_reply_modes = {}
    
    @classmethod
    def set_booking_reply_mode(cls, admin_id, booking_id):
        cls._reply_modes[admin_id] = booking_id
    
    @classmethod
    def get_booking_reply_mode(cls, admin_id):
        return cls._reply_modes.get(admin_id)
    
    @classmethod
    def clear_booking_reply_mode(cls, admin_id):
        cls._reply_modes.pop(admin_id, None)
    
    @classmethod
    def set_review_reply_mode(cls, admin_id, review_id):
        cls._review_reply_modes[admin_id] = review_id
    
    @classmethod
    def get_review_reply_mode(cls, admin_id):
        return cls._review_reply_modes.get(admin_id)
    
    @classmethod
    def clear_review_reply_mode(cls, admin_id):
        cls._review_reply_modes.pop(admin_id, None)

# Глобальные переменные
user_data = {}
review_data = {}

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def safe_int(value, default=0):
    """Безопасное преобразование в int"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def safe_send_message(chat_id, text, **kwargs):
    """Безопасная отправка сообщения"""
    try:
        return bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения {chat_id}: {e}")
        return None

def safe_delete_message(chat_id, message_id):
    """Безопасное удаление сообщения"""
    try:
        bot.delete_message(chat_id, message_id)
        return True
    except Exception as e:
        logger.warning(f"Не удалось удалить сообщение: {e}")
        return False

def validate_phone(phone):
    """Валидация номера телефона"""
    if not phone:
        return None
        
    clean_phone = re.sub(r'\D', '', phone)
    
    if len(clean_phone) < 10 or len(clean_phone) > 15:
        return None
    
    if clean_phone.startswith('8') and len(clean_phone) == 11:
        clean_phone = '7' + clean_phone[1:]
    
    if len(clean_phone) == 11 and clean_phone.startswith('7'):
        return f"+7 ({clean_phone[1:4]}) {clean_phone[4:7]}-{clean_phone[7:9]}-{clean_phone[9:11]}"
    elif len(clean_phone) == 10:
        return f"+7 ({clean_phone[0:3]}) {clean_phone[3:6]}-{clean_phone[6:8]}-{clean_phone[8:10]}"
    
    return None

def validate_date(date_str):
    """Валидация даты"""
    if not date_str:
        return None, "❌ Дата не указана"
        
    try:
        date_obj = datetime.datetime.strptime(date_str, '%d.%m.%Y').date()
        today = datetime.date.today()
        
        if date_obj < today:
            return None, "❌ Нельзя забронировать стол на прошедшую дату"
        
        max_date = today + timedelta(days=90)
        if date_obj > max_date:
            return None, "❌ Бронирование доступно только на 3 месяца вперед"
        
        return date_obj, None
    except ValueError:
        return None, "❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ"

def validate_time(time_str, date_str):
    """Валидация времени с учетом реального времени работы"""
    if not time_str:
        return None, "❌ Время не указано"
        
    try:
        time_obj = datetime.datetime.strptime(time_str, '%H:%M').time()
        date_obj = datetime.datetime.strptime(date_str, '%d.%m.%Y').date()
        weekday = date_obj.weekday()
        
        # Определяем время работы для этого дня
        if weekday in [4, 5]:  # Пятница (4), Суббота (5)
            min_time = datetime.time(16, 0)
            max_time = datetime.time(3, 0)  # До 03:00 следующего дня
        else:  # Воскресенье-Четверг
            min_time = datetime.time(16, 0)
            max_time = datetime.time(2, 0)   # До 02:00 следующего дня
        
        # Проверка времени
        # Для времени после полуночи (следующий день)
        if time_obj < datetime.time(12, 0):  # Время между 00:00 и 12:00
            if time_obj <= max_time:
                return time_obj, None
        else:  # Время между 12:00 и 24:00
            if time_obj >= min_time:
                return time_obj, None
        
        # Если время не подходит
        hours_info = get_restaurant_hours(date_str)
        return None, f"❌ Ресторан работает {hours_info}. Выберите время в этом интервале"
        
    except ValueError:
        return None, "❌ Неверный формат времени. Используйте ЧЧ:MM"

def validate_guests(guests_str):
    """Валидация количества гостей"""
    if not guests_str:
        return None, "❌ Количество гостей не указано"
        
    try:
        guests = int(guests_str)
        if guests < 1:
            return None, "❌ Количество гостей должно быть не менее 1"
        if guests > 12:  # Исправлено с 20 на 12
            return None, "❌ Максимальное количество гостей - 12"
        return guests, None
    except ValueError:
        return None, "❌ Введите число от 1 до 12"

def validate_name(name):
    """Валидация имени"""
    if not name:
        return None, "❌ Имя не указано"
        
    name = name.strip()
    if len(name) < 2:
        return None, "❌ Имя должно содержать минимум 2 символа"
    if len(name) > 50:
        return None, "❌ Имя слишком длинное"
    if not re.match(r'^[a-zA-Zа-яА-ЯёЁ\s\-]+$', name):
        return None, "❌ Имя может содержать только буквы, пробелы и дефисы"
    return name, None

def get_restaurant_hours(date_str):
    """Получение часов работы для указанной даты"""
    try:
        date_obj = datetime.datetime.strptime(date_str, '%d.%m.%Y').date()
        weekday = date_obj.weekday()
        if weekday in [4, 5]:  # Пятница (4), Суббота (5)
            return "пт-сб 16:00-03:00"
        else:
            return "вс-чт 16:00-02:00"
    except:
        return "вс-чт 16:00-02:00, пт-сб 16:00-03:00"

def is_booking_active(booking_date_str):
    """Проверяет, является ли бронирование актуальным (не прошедшим)"""
    try:
        booking_date = datetime.datetime.strptime(booking_date_str, '%d.%m.%Y').date()
        today = datetime.date.today()
        return booking_date >= today
    except:
        return False

def cleanup_user_data(user_id):
    """Очистка данных пользователя"""
    if user_id in user_data:
        if 'booking_steps' in user_data[user_id]:
            for msg_id in user_data[user_id]['booking_steps']:
                safe_delete_message(user_id, msg_id)
        del user_data[user_id]

# === БАЗА ДАННЫХ ===
def init_db():
    conn = sqlite3.connect('restaurant.db', check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            booking_date TEXT NOT NULL,
            booking_time TEXT NOT NULL,
            guests INTEGER NOT NULL,
            comment TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            admin_reply TEXT,
            reminder_24h_sent INTEGER DEFAULT 0,
            reminder_1h_sent INTEGER DEFAULT 0,
            review_requested INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            total_bookings INTEGER DEFAULT 0,
            approved_bookings INTEGER DEFAULT 0,
            rejected_bookings INTEGER DEFAULT 0,
            total_reviews INTEGER DEFAULT 0,
            average_rating REAL DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER,
            admin_id INTEGER,
            reply_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT,
            rating INTEGER,
            review_text TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Инициализируем статистику если не существует
    cursor.execute('INSERT OR IGNORE INTO admin_stats (id) VALUES (1)')
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

# === КЛАВИАТУРЫ ===
def main_menu(user_id=None):
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton('📅 Забронировать стол'))
    keyboard.add(KeyboardButton('📞 Контакты'), KeyboardButton('⭐ Оставить отзыв'))
    
    # Кнопка "Панель администратора" только для админа
    if user_id == ADMIN_ID:
        keyboard.add(KeyboardButton('👑 Панель администратора'))
    
    return keyboard

def admin_menu():
    """Меню администратора"""
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton('⏳ Ожидающие заявки'))
    keyboard.add(KeyboardButton('✅ Актуальные бронирования'), KeyboardButton('❌ Отклоненные заявки'))
    keyboard.add(KeyboardButton('💬 Отзывы на модерации'), KeyboardButton('📈 Общая статистика'))
    keyboard.add(KeyboardButton('🔙 В главное меню'))
    return keyboard

def cancel_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton('❌ Отмена бронирования'))
    return keyboard

def skip_comment_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton('➡️ Пропустить комментарий'))
    keyboard.add(KeyboardButton('❌ Отмена бронирования'))
    return keyboard

# === КАЛЕНДАРЬ И ВРЕМЯ ===
def generate_calendar(year=None, month=None):
    now = datetime.datetime.now()
    if year is None:
        year = now.year
    if month is None:
        month = now.month
    
    keyboard = InlineKeyboardMarkup()
    
    month_name = get_month_name(month)
    row = []
    row.append(InlineKeyboardButton("◀️", callback_data=f"calendar_prev_{year}_{month}"))
    row.append(InlineKeyboardButton(f"{month_name} {year}", callback_data="ignore"))
    row.append(InlineKeyboardButton("▶️", callback_data=f"calendar_next_{year}_{month}"))
    keyboard.row(*row)
    
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    keyboard.row(*[InlineKeyboardButton(day, callback_data="ignore") for day in days])
    
    month_days = get_month_days(year, month)
    
    for week in month_days:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="ignore"))
            else:
                date_str = f"{day:02d}.{month:02d}.{year}"
                date_obj = datetime.date(year, month, day)
                
                if date_obj < now.date():
                    row.append(InlineKeyboardButton(f"❌", callback_data="ignore"))
                else:
                    day_str = f"{day}"
                    if date_obj == now.date():
                        day_str = f"📍{day}"
                    row.append(InlineKeyboardButton(day_str, callback_data=f"calendar_day_{date_str}"))
        keyboard.row(*row)
    
    keyboard.row(InlineKeyboardButton("❌ Отмена", callback_data="calendar_cancel"))
    return keyboard

def get_month_name(month):
    months = [
        "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
    ]
    return months[month - 1]

def get_month_days(year, month):
    first_day = datetime.date(year, month, 1)
    last_day = datetime.date(year, month + 1, 1) - timedelta(days=1) if month < 12 else datetime.date(year + 1, 1, 1) - timedelta(days=1)
    
    first_weekday = (first_day.weekday()) % 7
    days = []
    current_day = 1
    
    for week in range(6):
        week_days = []
        for day in range(7):
            if (week == 0 and day < first_weekday) or current_day > last_day.day:
                week_days.append(0)
            else:
                week_days.append(current_day)
                current_day += 1
        days.append(week_days)
        if current_day > last_day.day:
            break
    return days

def generate_time_buttons(date_str):
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=4)
    
    times = []
    # Генерация времени с учетом работы лаунджа
    for hour in range(16, 24):  # С 16:00 до 23:30
        for minute in ['00', '30']:
            times.append(f"{hour:02d}:{minute}")
    
    # Добавляем время после полуночи для пятницы и субботы
    try:
        date_obj = datetime.datetime.strptime(date_str, '%d.%m.%Y').date()
        weekday = date_obj.weekday()
        if weekday in [4, 5]:  # Пятница, Суббота
            for hour in [0, 1, 2]:  # 00:00, 01:00, 02:00
                for minute in ['00', '30']:
                    if hour == 2 and minute == '30':  # До 02:30 в пт-сб
                        continue
                    times.append(f"{hour:02d}:{minute}")
    except:
        pass
    
    for i in range(0, len(times), 4):
        row = [KeyboardButton(time) for time in times[i:i+4]]
        keyboard.add(*row)
    
    keyboard.add(KeyboardButton('🔙 Назад к календарю'))
    keyboard.add(KeyboardButton('❌ Отмена бронирования'))
    return keyboard

# === СИСТЕМА БРОНИРОВАНИЯ ===
@bot.message_handler(func=lambda message: message.text == '📅 Забронировать стол')
def start_booking(message):
    user_id = message.from_user.id
    
    # Администратор не может бронировать
    if user_id == ADMIN_ID:
        safe_send_message(
            message.chat.id, 
            "⛔ *Администратор не может бронировать столы через бота*\n\n"
            "Для тестирования функционала используйте тестовый аккаунт.",
            reply_markup=main_menu(message.from_user.id),
            parse_mode='Markdown'
        )
        return
    
    cleanup_user_data(user_id)
    
    user_data[user_id] = {
        'state': BookingState.DATE,
        'booking_steps': [],
        'last_activity': time_module.time()
    }
    
    calendar = generate_calendar()
    msg = safe_send_message(
        message.chat.id,
        "🍝 *Начнем бронирование столика!*\n\n"
        "📅 **Шаг 1 из 6:** Выберите дату посещения\n"
        "• Используйте стрелки для навигации\n• 📍 Сегодняшний день\n• ❌ Недоступные даты",
        reply_markup=calendar,
        parse_mode='Markdown'
    )
    
    if msg:
        user_data[user_id]['booking_steps'].append(msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith('calendar_'))
def handle_calendar_callback(call):
    """Обработка callback календаря"""
    try:
        if call.from_user.id == ADMIN_ID:
            bot.answer_callback_query(call.id, "⛔ Администратор не может бронировать столы")
            return
        
        data = call.data
        
        if data == 'calendar_cancel':
            safe_delete_message(call.message.chat.id, call.message.message_id)
            safe_send_message(call.message.chat.id, "❌ Выбор даты отменен", reply_markup=main_menu(call.from_user.id))
            return
        
        elif data.startswith('calendar_prev_'):
            _, _, year, month = data.split('_')
            year, month = int(year), int(month)
            if month == 1:
                year -= 1
                month = 12
            else:
                month -= 1
            new_calendar = generate_calendar(year, month)
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=new_calendar)
        
        elif data.startswith('calendar_next_'):
            _, _, year, month = data.split('_')
            year, month = int(year), int(month)
            if month == 12:
                year += 1
                month = 1
            else:
                month += 1
            new_calendar = generate_calendar(year, month)
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=new_calendar)
        
        elif data.startswith('calendar_day_'):
            user_id = call.from_user.id
            
            if user_id not in user_data:
                bot.answer_callback_query(call.id, "❌ Сессия бронирования устарела. Начните заново.")
                return
            
            date_str = call.data.replace('calendar_day_', '')
            
            date_obj, error = validate_date(date_str)
            if error:
                bot.answer_callback_query(call.id, error)
                return
            
            user_data[user_id]['date'] = date_str
            user_data[user_id]['state'] = BookingState.TIME
            user_data[user_id]['last_activity'] = time_module.time()
            
            safe_delete_message(call.message.chat.id, call.message.message_id)
            
            hours_info = get_restaurant_hours(date_str)
            time_keyboard = generate_time_buttons(date_str)
            
            msg = safe_send_message(
                call.message.chat.id,
                f"✅ **Дата:** {date_str}\n🕒 **Часы работы:** {hours_info}\n\n"
                "🕐 **Шаг 2 из 6:** Выберите время бронирования:",
                reply_markup=time_keyboard,
                parse_mode='Markdown'
            )
            
            if msg:
                user_data[user_id]['booking_steps'].append(msg.message_id)
            bot.answer_callback_query(call.id, f"✅ Дата {date_str} выбрана")
        
    except Exception as e:
        logger.error(f"❌ Ошибка в handle_calendar_callback: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка")

@bot.message_handler(func=lambda message: 
                     message.from_user.id in user_data and 
                     user_data[message.from_user.id]['state'] == BookingState.TIME and
                     ':' in message.text)
def handle_time_selection(message):
    user_id = message.from_user.id
    time_str = message.text.strip()
    
    time_obj, error = validate_time(time_str, user_data[user_id]['date'])
    if error:
        msg = safe_send_message(message.chat.id, error)
        if msg and user_id in user_data:
            user_data[user_id]['booking_steps'].append(msg.message_id)
        return
    
    user_data[user_id]['time'] = time_str
    user_data[user_id]['state'] = BookingState.GUESTS
    user_data[user_id]['last_activity'] = time_module.time()
    
    msg = safe_send_message(
        message.chat.id,
        f"✅ **Время:** {time_str}\n\n"
        "👥 **Шаг 3 из 6:** Введите количество гостей (от 1 до 12):",
        reply_markup=cancel_keyboard(),
        parse_mode='Markdown'
    )
    
    if msg and user_id in user_data:
        user_data[user_id]['booking_steps'].append(msg.message_id)

@bot.message_handler(func=lambda message: 
                     message.from_user.id in user_data and 
                     user_data[message.from_user.id]['state'] == BookingState.GUESTS)
def handle_guests_selection(message):
    user_id = message.from_user.id
    guests_str = message.text.strip()
    
    guests, error = validate_guests(guests_str)
    if error:
        msg = safe_send_message(message.chat.id, error)
        if msg and user_id in user_data:
            user_data[user_id]['booking_steps'].append(msg.message_id)
        return
    
    user_data[user_id]['guests'] = guests
    user_data[user_id]['state'] = BookingState.NAME
    user_data[user_id]['last_activity'] = time_module.time()
    
    msg = safe_send_message(
        message.chat.id,
        f"✅ **Гости:** {guests} человек\n\n"
        "👤 **Шаг 4 из 6:** Введите ваше имя:",
        reply_markup=cancel_keyboard(),
        parse_mode='Markdown'
    )
    
    if msg and user_id in user_data:
        user_data[user_id]['booking_steps'].append(msg.message_id)

@bot.message_handler(func=lambda message: 
                     message.from_user.id in user_data and 
                     user_data[message.from_user.id]['state'] == BookingState.NAME)
def handle_name_selection(message):
    user_id = message.from_user.id
    name = message.text.strip()
    
    validated_name, error = validate_name(name)
    if error:
        msg = safe_send_message(message.chat.id, error)
        if msg and user_id in user_data:
            user_data[user_id]['booking_steps'].append(msg.message_id)
        return
    
    user_data[user_id]['name'] = validated_name
    user_data[user_id]['state'] = BookingState.PHONE
    user_data[user_id]['last_activity'] = time_module.time()
    
    msg = safe_send_message(
        message.chat.id,
        f"✅ **Имя:** {validated_name}\n\n"
        "📞 **Шаг 5 из 6:** Введите ваш номер телефона:\n"
        "• В любом формате\n• Пример: 89123456789 или +7 (912) 345-67-89",
        reply_markup=cancel_keyboard(),
        parse_mode='Markdown'
    )
    
    if msg and user_id in user_data:
        user_data[user_id]['booking_steps'].append(msg.message_id)

@bot.message_handler(func=lambda message: 
                     message.from_user.id in user_data and 
                     user_data[message.from_user.id]['state'] == BookingState.PHONE)
def handle_phone_selection(message):
    user_id = message.from_user.id
    phone = message.text.strip()
    
    formatted_phone = validate_phone(phone)
    if not formatted_phone:
        msg = safe_send_message(
            message.chat.id,
            "❌ Неверный формат номера телефона.\n"
            "Пожалуйста, введите корректный номер:\n"
            "• 89123456789\n• +7 (912) 345-67-89\n• 8-912-345-67-89",
            reply_markup=cancel_keyboard()
        )
        if msg and user_id in user_data:
            user_data[user_id]['booking_steps'].append(msg.message_id)
        return
    
    user_data[user_id]['phone'] = formatted_phone
    user_data[user_id]['state'] = BookingState.COMMENT
    user_data[user_id]['last_activity'] = time_module.time()
    
    msg = safe_send_message(
        message.chat.id,
        f"✅ **Телефон:** {formatted_phone}\n\n"
        "💬 **Шаг 6 из 6:** Добавьте комментарий к бронированию (по желанию):\n"
        "• Например: 'Столик у окна', 'День рождения', 'С приставкой'\n"
        "• Или пропустите этот шаг",
        reply_markup=skip_comment_keyboard(),
        parse_mode='Markdown'
    )
    
    if msg and user_id in user_data:
        user_data[user_id]['booking_steps'].append(msg.message_id)

@bot.message_handler(func=lambda message: 
                     message.from_user.id in user_data and 
                     user_data[message.from_user.id]['state'] == BookingState.COMMENT)
def handle_comment_or_complete(message):
    user_id = message.from_user.id
    
    if message.text == '➡️ Пропустить комментарий':
        user_data[user_id]['comment'] = ""
        complete_booking(message.chat.id, user_id)
    else:
        user_data[user_id]['comment'] = message.text
        complete_booking(message.chat.id, user_id)

def complete_booking(chat_id, user_id):
    if user_id not in user_data:
        safe_send_message(chat_id, "❌ Сессия бронирования устарела. Начните заново.", reply_markup=main_menu(user_id))
        return
        
    required_fields = ['name', 'phone', 'date', 'time', 'guests']
    missing_fields = []
    
    for field in required_fields:
        if field not in user_data[user_id]:
            missing_fields.append(field)
    
    if missing_fields:
        logger.error(f"Отсутствуют поля: {missing_fields} для пользователя {user_id}")
        safe_send_message(chat_id, "❌ Ошибка данных бронирования. Начните заново.", reply_markup=main_menu(user_id))
        cleanup_user_data(user_id)
        return
    
    if 'comment' not in user_data[user_id]:
        user_data[user_id]['comment'] = ""
    
    try:
        booking_id = save_booking_to_db(user_id, user_data[user_id])
        send_booking_confirmation(chat_id, user_data[user_id], booking_id)
        send_booking_to_admin(user_data[user_id], user_id, booking_id)
        cleanup_user_data(user_id)
        
        logger.info(f"✅ Бронирование успешно создано #{booking_id} для пользователя {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении брони: {e}")
        safe_send_message(chat_id, "❌ Произошла ошибка при сохранении брони. Попробуйте позже.", reply_markup=main_menu(user_id))
        cleanup_user_data(user_id)

def save_booking_to_db(user_id, data):
    conn = sqlite3.connect('restaurant.db', check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO bookings (user_id, user_name, phone, booking_date, booking_time, guests, comment, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
    ''', (
        user_id, 
        data['name'], 
        data['phone'], 
        data['date'], 
        data['time'], 
        data['guests'], 
        data.get('comment', '')
    ))
    
    booking_id = cursor.lastrowid
    cursor.execute('UPDATE admin_stats SET total_bookings = total_bookings + 1')
    conn.commit()
    conn.close()
    
    return booking_id

def send_booking_confirmation(chat_id, booking_data, booking_id):
    confirmation_text = f"""
✅ *Заявка на бронирование отправлена!*

📋 *Детали бронирования:*
• 👤 **Имя:** {booking_data['name']}
• 📞 **Телефон:** {booking_data['phone']}
• 📅 **Дата:** {booking_data['date']}
• ⏰ **Время:** {booking_data['time']}
• 👥 **Гости:** {booking_data['guests']} человек
{f"• 💬 **Комментарий:** {booking_data['comment']}" if booking_data['comment'] else ""}

🏢 *Лаундж-бар:* {RESTAURANT_INFO['name']}
📍 *Адрес:* {RESTAURANT_INFO['address']}
{RESTAURANT_INFO['entertainment']}

*Ожидайте подтверждения от администратора!* 📞
    """
    
    safe_send_message(chat_id, confirmation_text, reply_markup=main_menu(chat_id), parse_mode='Markdown')

def send_booking_to_admin(booking_data, user_id, booking_id):
    comment_text = f"\n💬 *Комментарий гостя:* {booking_data['comment']}" if booking_data.get('comment') else "\n💬 *Комментарий:* Нет комментария"
    
    booking_text = f"""
📋 *НОВАЯ ЗАЯВКА НА БРОНИРОВАНИЕ* #{booking_id}

👤 *Имя:* {booking_data['name']}
📞 *Телефон:* {booking_data['phone']}
📅 *Дата:* {booking_data['date']}
⏰ *Время:* {booking_data['time']}
👥 *Гости:* {booking_data['guests']} чел.
🆔 *ID пользователя:* {user_id}
{comment_text}

🏢 *Лаундж-бар:* {RESTAURANT_INFO['name']}
📍 *Адрес:* {RESTAURANT_INFO['address']}
    """
    
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("✅ Одобрить", callback_data=f"admin_approve_{booking_id}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"admin_reject_{booking_id}")
    )
    keyboard.row(InlineKeyboardButton("💬 Ответить гостю", callback_data=f"admin_reply_{booking_id}"))
    
    safe_send_message(ADMIN_ID, booking_text, reply_markup=keyboard, parse_mode='Markdown')

# === ИСПРАВЛЕННЫЙ ОБРАБОТЧИК ОТМЕНЫ БРОНИРОВАНИЯ ===
@bot.message_handler(func=lambda message: message.text == '❌ Отмена бронирования')
def cancel_booking(message):
    user_id = message.from_user.id
    if user_id in user_data:
        cleanup_user_data(user_id)
        safe_send_message(message.chat.id, "❌ Бронирование отменено", reply_markup=main_menu(user_id))
    else:
        safe_send_message(message.chat.id, "❌ Активное бронирование не найдено", reply_markup=main_menu(user_id))

# === ОБРАБОТКА CALLBACK-ЗАПРОСОВ ===
@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    """Глобальный обработчик callback-запросов с защитой от ошибок"""
    try:
        if not call.data:
            bot.answer_callback_query(call.id, "❌ Ошибка данных")
            return
            
        if call.data == 'ignore':
            bot.answer_callback_query(call.id)
            return
            
        # Обработка действий администратора
        elif call.data.startswith('admin_'):
            handle_admin_actions(call)
        # Обработка подтверждения визита
        elif call.data.startswith('confirm_visit_'):
            handle_visit_confirmation(call)
        # Обработка отмены визита
        elif call.data.startswith('cancel_visit_'):
            handle_visit_cancellation(call)
        # Обработка отзывов
        elif call.data.startswith('review_direct_'):
            handle_review_rating(call)
        # Обработка модерации отзывов
        elif call.data.startswith(('publish_review_', 'reject_review_', 'admin_reply_review_')):
            handle_review_moderation(call)
        else:
            bot.answer_callback_query(call.id, "❌ Неизвестная команда")
            
    except Exception as e:
        logger.error(f"❌ Ошибка в обработчике callback: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Произошла ошибка")
        except:
            pass

# === АДМИН-ПАНЕЛЬ ===
@bot.message_handler(func=lambda message: message.text == '👑 Панель администратора')
def admin_panel(message):
    if message.from_user.id == ADMIN_ID:
        safe_send_message(message.chat.id, "👑 *Панель администратора*", reply_markup=admin_menu(), parse_mode='Markdown')
    else:
        safe_send_message(message.chat.id, "⛔ Доступ запрещен", reply_markup=main_menu(message.from_user.id))

@bot.message_handler(func=lambda message: message.text == '🔙 В главное меню')
def back_to_main(message):
    safe_send_message(message.chat.id, "Главное меню", reply_markup=main_menu(message.from_user.id))

@bot.message_handler(func=lambda message: message.text == '⏳ Ожидающие заявки' and message.from_user.id == ADMIN_ID)
def show_pending_bookings(message):
    conn = sqlite3.connect('restaurant.db', check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM bookings WHERE status = "pending" ORDER BY booking_date, booking_time')
    pending_bookings = cursor.fetchall()
    conn.close()
    
    if not pending_bookings:
        safe_send_message(message.chat.id, "✅ Нет ожидающих заявок")
        return
    
    for booking in pending_bookings:
        booking_id, user_id, user_name, phone, date, time, guests, comment, status, admin_reply, _, _, _, created_at = booking
        
        comment_text = f"\n💬 *Комментарий:* {comment}" if comment else ""
        admin_reply_text = f"\n👑 *Ответ администратора:* {admin_reply}" if admin_reply else ""
        
        booking_text = f"""
⏳ *Ожидает решения* #{booking_id}

👤 *Имя:* {user_name}
📞 *Телефон:* {phone}
📅 *Дата:* {date}
⏰ *Время:* {time}
👥 *Гости:* {guests} чел.
🆔 *ID:* {user_id}
{comment_text}
{admin_reply_text}
        """
        
        keyboard = InlineKeyboardMarkup()
        keyboard.row(
            InlineKeyboardButton("✅ Одобрить", callback_data=f"admin_approve_{booking_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"admin_reject_{booking_id}")
        )
        keyboard.row(InlineKeyboardButton("💬 Ответить", callback_data=f"admin_reply_{booking_id}"))
        
        safe_send_message(message.chat.id, booking_text, reply_markup=keyboard, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '✅ Актуальные бронирования' and message.from_user.id == ADMIN_ID)
def show_approved_bookings(message):
    conn = sqlite3.connect('restaurant.db', check_same_thread=False)
    cursor = conn.cursor()
    
    # Получаем только актуальные бронирования (не прошедшие даты)
    today = datetime.date.today().strftime('%d.%m.%Y')
    
    cursor.execute('''
        SELECT * FROM bookings 
        WHERE status = "approved" 
        AND booking_date >= ?
        ORDER BY booking_date, booking_time 
        LIMIT 20
    ''', (today,))
    
    approved_bookings = cursor.fetchall()
    conn.close()
    
    if not approved_bookings:
        safe_send_message(message.chat.id, "📭 Нет актуальных бронирований")
        return
    
    safe_send_message(message.chat.id, f"✅ *Актуальные бронирования (ближайшие 20):*", parse_mode='Markdown')
    
    for booking in approved_bookings:
        booking_id, user_id, user_name, phone, date, time, guests, comment, status, admin_reply, _, _, _, created_at = booking
        
        # Проверяем актуальность брони
        is_active = is_booking_active(date)
        status_icon = "🟢" if is_active else "🔴"
        
        comment_text = f"\n💬 *Комментарий:* {comment}" if comment else ""
        admin_reply_text = f"\n👑 *Ответ:* {admin_reply}" if admin_reply else ""
        
        booking_text = f"""
{status_icon} *Актуальное бронирование* #{booking_id}

👤 *Имя:* {user_name}
📞 *Телефон:* {phone}
📅 *Дата:* {date}
⏰ *Время:* {time}
👥 *Гости:* {guests} чел.
{comment_text}
{admin_reply_text}
        """
        safe_send_message(message.chat.id, booking_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '❌ Отклоненные заявки' and message.from_user.id == ADMIN_ID)
def show_rejected_bookings(message):
    conn = sqlite3.connect('restaurant.db', check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM bookings WHERE status = "rejected" ORDER BY created_at DESC LIMIT 10')
    rejected_bookings = cursor.fetchall()
    conn.close()
    
    if not rejected_bookings:
        safe_send_message(message.chat.id, "📭 Нет отклоненных заявок")
        return
    
    safe_send_message(message.chat.id, f"❌ *Последние 10 отклоненных заявок:*", parse_mode='Markdown')
    
    for booking in rejected_bookings:
        booking_id, user_id, user_name, phone, date, time, guests, comment, status, admin_reply, _, _, _, created_at = booking
        
        comment_text = f"\n💬 *Комментарий:* {comment}" if comment else ""
        admin_reply_text = f"\n👑 *Ответ:* {admin_reply}" if admin_reply else ""
        
        booking_text = f"""
❌ *Отклонено* #{booking_id}

👤 *Имя:* {user_name}
📞 *Телефон:* {phone}
📅 *Дата:* {date}
⏰ *Время:* {time}
👥 *Гости:* {guests} чел.
{comment_text}
{admin_reply_text}
        """
        safe_send_message(message.chat.id, booking_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '📈 Общая статистика' and message.from_user.id == ADMIN_ID)
def show_stats(message):
    conn = sqlite3.connect('restaurant.db', check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('SELECT total_bookings, approved_bookings, rejected_bookings, total_reviews, average_rating FROM admin_stats')
    stats = cursor.fetchone()
    
    cursor.execute('SELECT COUNT(*) FROM bookings WHERE status = "pending"')
    pending_count = cursor.fetchone()[0]
    
    # Актуальные бронирования
    today = datetime.date.today().strftime('%d.%m.%Y')
    cursor.execute('SELECT COUNT(*) FROM bookings WHERE status = "approved" AND booking_date >= ?', (today,))
    active_bookings = cursor.fetchone()[0]
    
    cursor.execute('SELECT booking_date, COUNT(*) FROM bookings WHERE status = "approved" AND booking_date >= ? GROUP BY booking_date ORDER BY booking_date DESC LIMIT 7', (today,))
    last_week = cursor.fetchall()
    
    cursor.execute('SELECT booking_time, COUNT(*) FROM bookings WHERE status = "approved" GROUP BY booking_time ORDER BY COUNT(*) DESC LIMIT 5')
    popular_times = cursor.fetchall()
    
    conn.close()
    
    stats_text = f"""
📈 *Общая статистика лаундж-бара*

📊 *Бронирования:*
• Всего заявок: {stats[0]}
• Ожидают решения: {pending_count}
• Актуальные брони: {active_bookings}
• Одобрено всего: {stats[1]}
• Отклонено: {stats[2]}
• Процент одобрения: {(stats[1]/stats[0]*100) if stats[0] > 0 else 0:.1f}%

⭐ *Отзывы:*
• Всего отзывов: {stats[3]}
• Средний рейтинг: {stats[4]:.1f}/5

📅 *Ближайшие 7 дней:*
"""
    
    for date, count in last_week:
        stats_text += f"• {date}: {count} броней\n"
    
    stats_text += "\n⏰ *Популярное время:*\n"
    for time, count in popular_times:
        stats_text += f"• {time}: {count} броней\n"
    
    safe_send_message(message.chat.id, stats_text, parse_mode='Markdown')

def handle_admin_actions(call):
    """Обработка действий администратора"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Доступ запрещен")
        return
        
    data_parts = call.data.split('_')
    if len(data_parts) < 3:
        bot.answer_callback_query(call.id, "❌ Ошибка данных")
        return
        
    action = data_parts[1]
    booking_id = safe_int(data_parts[2])
    
    if not booking_id:
        bot.answer_callback_query(call.id, "❌ Неверный ID брони")
        return
    
    conn = sqlite3.connect('restaurant.db', check_same_thread=False)
    cursor = conn.cursor()
    
    if action == 'approve':
        cursor.execute('UPDATE bookings SET status = "approved" WHERE id = ?', (booking_id,))
        cursor.execute('UPDATE admin_stats SET approved_bookings = approved_bookings + 1')
        
        cursor.execute('SELECT user_id, user_name, booking_date, booking_time, guests, comment FROM bookings WHERE id = ?', (booking_id,))
        booking = cursor.fetchone()
        
        if booking:
            user_message = f"""
✅ *Ваше бронирование подтверждено!*

📋 *Детали:*
• 👤 Имя: {booking[1]}
• 📅 Дата: {booking[2]}
• ⏰ Время: {booking[3]}
• 👥 Гости: {booking[4]} чел.
{f"• 💬 Ваш комментарий: {booking[5]}" if booking[5] else ""}

🏢 *Лаундж-бар:* {RESTAURANT_INFO['name']}
📍 *Адрес:* {RESTAURANT_INFO['address']}
📞 *Телефон:* {RESTAURANT_INFO['phone']}
{RESTAURANT_INFO['entertainment']}

*Ждем вас в гости!* 🍝
            """
            
            try:
                safe_send_message(booking[0], user_message, parse_mode='Markdown')
            except Exception as e:
                logger.error(f"❌ Ошибка отправки уведомления пользователю: {e}")
        
        bot.answer_callback_query(call.id, "✅ Бронирование одобрено")
        
    elif action == 'reject':
        cursor.execute('UPDATE bookings SET status = "rejected" WHERE id = ?', (booking_id,))
        cursor.execute('UPDATE admin_stats SET rejected_bookings = rejected_bookings + 1')
        
        cursor.execute('SELECT user_id, user_name, booking_date, booking_time FROM bookings WHERE id = ?', (booking_id,))
        booking = cursor.fetchone()
        
        if booking:
            user_message = f"""
❌ *К сожалению, ваше бронирование отклонено.*

📅 *Дата:* {booking[2]}
⏰ *Время:* {booking[3]}

*Пожалуйста, выберите другое время или свяжитесь с нами:*
📞 {RESTAURANT_INFO['phone']}
            """
            
            try:
                safe_send_message(booking[0], user_message, parse_mode='Markdown')
            except Exception as e:
                logger.error(f"❌ Ошибка отправки уведомления пользователю: {e}")
        
        bot.answer_callback_query(call.id, "❌ Бронирование отклонено")
    
    elif action == 'reply':
        cursor.execute('SELECT user_id, user_name, comment FROM bookings WHERE id = ?', (booking_id,))
        booking = cursor.fetchone()
        
        if booking:
            AdminStates.set_booking_reply_mode(call.from_user.id, booking_id)
            
            reply_text = f"""
💬 *Ответ на комментарий гостя*

👤 *Гость:* {booking[1]}
💭 *Комментарий:* {booking[2] if booking[2] else "Нет комментария"}

*Введите ваш ответ для гостю:*
            """
            
            safe_send_message(call.from_user.id, reply_text, parse_mode='Markdown')
            bot.answer_callback_query(call.id, "💬 Введите ответ для гостя")
        else:
            bot.answer_callback_query(call.id, "❌ Бронь не найдена")
    
    conn.commit()
    conn.close()
    
    # Удаляем кнопки только для approve/reject
    if action in ['approve', 'reject']:
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception as e:
            logger.warning(f"Не удалось обновить клавиатуру: {e}")

# === ОБРАБОТКА ОТВЕТОВ АДМИНИСТРАТОРА ===
@bot.message_handler(func=lambda message: message.from_user.id == ADMIN_ID and 
                     AdminStates.get_booking_reply_mode(message.from_user.id) is not None and
                     not message.text.startswith('/'))
def handle_admin_reply(message):
    booking_id = AdminStates.get_booking_reply_mode(message.from_user.id)
    if not booking_id:
        return
        
    reply_text = message.text
    
    conn = sqlite3.connect('restaurant.db', check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('UPDATE bookings SET admin_reply = ? WHERE id = ?', (reply_text, booking_id))
    cursor.execute('INSERT INTO admin_replies (booking_id, admin_id, reply_text) VALUES (?, ?, ?)', 
                  (booking_id, message.from_user.id, reply_text))
    
    cursor.execute('SELECT user_id, user_name, booking_date, booking_time, guests, comment FROM bookings WHERE id = ?', (booking_id,))
    booking = cursor.fetchone()
    
    conn.commit()
    conn.close()
    
    # Отправляем ответ гостю
    if booking:
        user_message = f"""
👑 *Ответ от администратора лаундж-бара:*

💬 *{reply_text}*

*По вопросам бронирования:*
📞 {RESTAURANT_INFO['phone']}
        """
        
        try:
            safe_send_message(booking[0], user_message, parse_mode='Markdown')
            user_notified = True
        except Exception as e:
            logger.error(f"❌ Ошибка отправки ответа гостю: {e}")
            user_notified = False
        
        # Уведомление о результате
        if user_notified:
            safe_send_message(message.from_user.id, "✅ Ответ успешно отправлен гостю!")
        else:
            safe_send_message(message.from_user.id, "❌ Не удалось отправить ответ гостю (возможно, заблокировал бота)")
    
    # Очищаем режим ответа
    AdminStates.clear_booking_reply_mode(message.from_user.id)

# === СИСТЕМА УВЕДОМЛЕНИЙ ===
def check_reminders():
    """Проверка и отправка уведомлений"""
    while True:
        try:
            conn = sqlite3.connect('restaurant.db', check_same_thread=False)
            cursor = conn.cursor()
            
            now = datetime.datetime.now()
            current_time = now.strftime('%H:%M')
            current_date = now.strftime('%d.%m.%Y')
            
            # УВЕДОМЛЕНИЯ ЗА 24 ЧАСА
            tomorrow = (now + timedelta(days=1)).strftime('%d.%m.%Y')
            
            cursor.execute('''
                SELECT id, user_id, user_name, booking_date, booking_time, guests, comment 
                FROM bookings 
                WHERE status = "approved" 
                AND booking_date = ?
                AND reminder_24h_sent = 0
            ''', (tomorrow,))
            
            bookings_24h = cursor.fetchall()
            
            for booking in bookings_24h:
                booking_id, user_id, user_name, date, time, guests, comment = booking
                
                reminder_text = f"""
🔔 *Напоминание о бронировании*

Уважаемый(ая) {user_name}! 
Напоминаем, что завтра *{date} в {time}* 
у вас бронь в *{RESTAURANT_INFO['name']}* на *{guests}* персон.

{f"💬 *Ваш комментарий:* {comment}" if comment else ""}

📍 *Адрес:* {RESTAURANT_INFO['address']}
📞 *Телефон:* {RESTAURANT_INFO['phone']}
{RESTAURANT_INFO['entertainment']}

*Подтвердите, пожалуйста, вашу явку:* 👇
                """
                
                keyboard = InlineKeyboardMarkup()
                keyboard.row(
                    InlineKeyboardButton("✅ Подтверждаю", callback_data=f"confirm_visit_{booking_id}"),
                    InlineKeyboardButton("❌ Отменить визит", callback_data=f"cancel_visit_{booking_id}")
                )
                
                try:
                    safe_send_message(user_id, reminder_text, reply_markup=keyboard, parse_mode='Markdown')
                    cursor.execute('UPDATE bookings SET reminder_24h_sent = 1 WHERE id = ?', (booking_id,))
                    logger.info(f"✅ Отправлено уведомление за 24 часа для брони #{booking_id}")
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки уведомления за 24 часа: {e}")
            
            # УВЕДОМЛЕНИЯ ЗА 1 ЧАС
            cursor.execute('''
                SELECT id, user_id, user_name, booking_time, guests, comment 
                FROM bookings 
                WHERE status = "approved" 
                AND booking_date = ?
                AND reminder_1h_sent = 0
            ''', (current_date,))
            
            bookings_today = cursor.fetchall()
            
            for booking in bookings_today:
                booking_id, user_id, user_name, booking_time_str, guests, comment = booking
                
                booking_time_obj = datetime.datetime.strptime(booking_time_str, '%H:%M').time()
                current_time_obj = datetime.datetime.strptime(current_time, '%H:%M').time()
                
                booking_datetime = datetime.datetime.combine(now.date(), booking_time_obj)
                current_datetime = datetime.datetime.combine(now.date(), current_time_obj)
                time_diff = (booking_datetime - current_datetime).total_seconds() / 3600
                
                if 0.9 <= time_diff <= 1.1:
                    reminder_text = f"""
⏰ *Скоро встретимся!*

Уважаемый(ая) {user_name}!
Через 1 час в *{booking_time_str}* ждем вас в *{RESTAURANT_INFO['name']}*!

*Напоминаем:*
👥 *Гости:* {guests} персон
{f"💬 *Ваш комментарий:* {comment}" if comment else ""}
📍 *Адрес:* {RESTAURANT_INFO['address']}
📞 *Телефон:* {RESTAURANT_INFO['phone']}
{RESTAURANT_INFO['entertainment']}

*Ждем с нетерпением!* 🍝
                    """
                    
                    try:
                        safe_send_message(user_id, reminder_text, parse_mode='Markdown')
                        cursor.execute('UPDATE bookings SET reminder_1h_sent = 1 WHERE id = ?', (booking_id,))
                        logger.info(f"✅ Отправлено уведомление за 1 час для брони #{booking_id}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка отправки уведомления за 1 час: {e}")
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"❌ Ошибка в системе уведомлений: {e}")
        
        time_module.sleep(60)  # Проверка каждую минуту

def handle_visit_confirmation(call):
    booking_id = safe_int(call.data.replace('confirm_visit_', ''))
    if not booking_id:
        bot.answer_callback_query(call.id, "❌ Неверный ID брони")
        return
    
    conn = sqlite3.connect('restaurant.db', check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('SELECT user_name, booking_date, booking_time FROM bookings WHERE id = ?', (booking_id,))
    booking = cursor.fetchone()
    conn.close()
    
    if booking:
        user_name, date, time = booking
        
        admin_notification = f"""
✅ *Гость подтвердил визит*

👤 *Гость:* {user_name}
📅 *Дата:* {date}
⏰ *Время:* {time}

*Бронь #*{booking_id}
        """
        
        try:
            safe_send_message(ADMIN_ID, admin_notification, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"❌ Ошибка отправки уведомления администратору: {e}")
        
        bot.answer_callback_query(call.id, "✅ Спасибо за подтверждение! Ждем вас!")
    else:
        bot.answer_callback_query(call.id, "❌ Бронь не найдена")

def handle_visit_cancellation(call):
    booking_id = safe_int(call.data.replace('cancel_visit_', ''))
    if not booking_id:
        bot.answer_callback_query(call.id, "❌ Неверный ID брони")
        return
    
    conn = sqlite3.connect('restaurant.db', check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('SELECT user_name, booking_date, booking_time FROM bookings WHERE id = ?', (booking_id,))
    booking = cursor.fetchone()
    
    if booking:
        user_name, date, time = booking
        
        cursor.execute('UPDATE bookings SET status = "cancelled_by_user" WHERE id = ?', (booking_id,))
        
        admin_notification = f"""
❌ *Гость отменил визит*

👤 *Гость:* {user_name}
📅 *Дата:* {date}
⏰ *Время:* {time}

*Бронь #*{booking_id}
        """
        
        try:
            safe_send_message(ADMIN_ID, admin_notification, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"❌ Ошибка отправки уведомления администратору: {e}")
        
        bot.answer_callback_query(call.id, "❌ Бронь отменена. Надеемся увидеть вас в другой раз!")
    else:
        bot.answer_callback_query(call.id, "❌ Бронь не найдена")
    
    conn.commit()
    conn.close()

# === СИСТЕМА ОТЗЫВОВ ===
@bot.message_handler(func=lambda message: message.text == '⭐ Оставить отзыв')
def start_review(message):
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("1 ⭐", callback_data="review_direct_1"),
        InlineKeyboardButton("2 ⭐", callback_data="review_direct_2"), 
        InlineKeyboardButton("3 ⭐", callback_data="review_direct_3"),
        InlineKeyboardButton("4 ⭐", callback_data="review_direct_4"),
        InlineKeyboardButton("5 ⭐", callback_data="review_direct_5")
    )
    
    review_text = f"""
⭐ *Оцените {RESTAURANT_INFO['name']}*

Пожалуйста, оцените ваше посещение по 5-балльной шкале:

5 ⭐ - Отлично
4 ⭐ - Хорошо  
3 ⭐ - Нормально
2 ⭐ - Плохо
1 ⭐ - Очень плохо

*Выберите оценку:* 👇
    """
    
    safe_send_message(message.chat.id, review_text, reply_markup=keyboard, parse_mode='Markdown')

def handle_review_rating(call):
    global review_data
    
    rating = safe_int(call.data.replace('review_direct_', ''))
    if not rating or rating < 1 or rating > 5:
        bot.answer_callback_query(call.id, "❌ Неверная оценка")
        return
        
    user_id = call.from_user.id
    review_data[user_id] = {'rating': rating}
    
    safe_delete_message(call.message.chat.id, call.message.message_id)
    msg = safe_send_message(
        call.message.chat.id,
        f"⭐ *Спасибо за оценку {rating}/5!*\n\n*Пожалуйста, напишите ваш отзыв:*\n• Что понравилось?\n• Что можно улучшить?\n• Ваши пожелания\n\nИли нажмите /skip чтобы пропустить текст",
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['skip'])
def skip_review_text(message):
    global review_data
    user_id = message.from_user.id
    if user_id in review_data:
        save_review(user_id, "")
        safe_send_message(message.chat.id, "✅ Спасибо! Ваш отзыв сохранен.", reply_markup=main_menu(user_id))
    else:
        safe_send_message(message.chat.id, "❌ Сначала оцените ресторан")

@bot.message_handler(func=lambda message: message.from_user.id in review_data and not message.text.startswith('/'))
def handle_review_text(message):
    global review_data
    user_id = message.from_user.id
    review_text = message.text
    save_review(user_id, review_text)
    safe_send_message(message.chat.id, "✅ Спасибо! Ваш отзыв сохранен.", reply_markup=main_menu(user_id))

def save_review(user_id, review_text):
    global review_data
    if user_id not in review_data:
        return
    
    rating = review_data[user_id]['rating']
    
    conn = sqlite3.connect('restaurant.db', check_same_thread=False)
    cursor = conn.cursor()
    
    try:
        user = bot.get_chat(user_id)
        user_name = user.first_name or "Аноним"
        if user.last_name:
            user_name += f" {user.last_name}"
    except:
        user_name = "Аноним"
    
    cursor.execute('INSERT INTO reviews (user_id, user_name, rating, review_text, status) VALUES (?, ?, ?, ?, "pending")', 
                  (user_id, user_name, rating, review_text))
    
    cursor.execute('SELECT total_reviews, average_rating FROM admin_stats')
    stats = cursor.fetchone()
    
    total_reviews = stats[0] + 1
    if stats[0] == 0:
        new_avg = float(rating)
    else:
        new_avg = (stats[1] * stats[0] + rating) / total_reviews
    
    cursor.execute('UPDATE admin_stats SET total_reviews = ?, average_rating = ?', (total_reviews, new_avg))
    conn.commit()
    conn.close()
    
    send_review_to_admin(user_name, rating, review_text)
    del review_data[user_id]

def send_review_to_admin(user_name, rating, review_text, booking_id=None):
    stars = "⭐" * rating + "☆" * (5 - rating)
    booking_info = f"\n📋 *Бронь #*{booking_id}" if booking_id else ""
    
    conn = sqlite3.connect('restaurant.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM reviews ORDER BY id DESC LIMIT 1')
    last_review = cursor.fetchone()
    conn.close()
    
    review_id = last_review[0] if last_review else "1"
    
    review_message = f"""
⭐ *НОВЫЙ ОТЗЫВ* {booking_info}

👤 *Гость:* {user_name}
⭐ *Оценка:* {rating}/5 {stars}
{f"💬 *Текст отзыва:* {review_text}" if review_text else "💬 *Текст:* Без текста"}
    """
    
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("✅ Опубликовать", callback_data=f"publish_review_{review_id}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_review_{review_id}")
    )
    
    if review_text:
        keyboard.row(InlineKeyboardButton("💬 Ответить гостю", callback_data=f"admin_reply_review_{review_id}"))
    
    safe_send_message(ADMIN_ID, review_message, reply_markup=keyboard, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '💬 Отзывы на модерации' and message.from_user.id == ADMIN_ID)
def show_pending_reviews(message):
    conn = sqlite3.connect('restaurant.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM reviews WHERE status = "pending" ORDER BY created_at DESC')
    pending_reviews = cursor.fetchall()
    conn.close()
    
    if not pending_reviews:
        safe_send_message(message.chat.id, "✅ Нет отзывов на модерации")
        return
    
    for review in pending_reviews:
        review_id, user_id, user_name, rating, review_text, status, created_at = review
        stars = "⭐" * rating + "☆" * (5 - rating)
        text_display = f"💬 *Текст:* {review_text}" if review_text else "💬 *Текст:* Без текста"
        
        review_message = f"""
⭐ *ОТЗЫВ НА МОДЕРАЦИИ* #{review_id}

👤 *Гость:* {user_name}
⭐ *Оценка:* {rating}/5 {stars}
{text_display}
📅 *Дата:* {created_at}
        """
        
        keyboard = InlineKeyboardMarkup()
        keyboard.row(
            InlineKeyboardButton("✅ Опубликовать", callback_data=f"publish_review_{review_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_review_{review_id}")
        )
        
        if review_text:
            keyboard.row(InlineKeyboardButton("💬 Ответить гостю", callback_data=f"admin_reply_review_{review_id}"))
        
        safe_send_message(message.chat.id, review_message, reply_markup=keyboard, parse_mode='Markdown')

def handle_review_moderation(call):
    """Обработка модерации отзывов"""
    if not call.data:
        bot.answer_callback_query(call.id, "❌ Ошибка данных")
        return
        
    if call.data.startswith('publish_review_'):
        review_id = safe_int(call.data.replace('publish_review_', ''))
        if not review_id:
            bot.answer_callback_query(call.id, "❌ Неверный ID отзыва")
            return
            
        conn = sqlite3.connect('restaurant.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('UPDATE reviews SET status = "published" WHERE id = ?', (review_id,))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "✅ Отзыв опубликован")
        
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception as e:
            logger.warning(f"Не удалось обновить клавиатуру: {e}")
        
    elif call.data.startswith('reject_review_'):
        review_id = safe_int(call.data.replace('reject_review_', ''))
        if not review_id:
            bot.answer_callback_query(call.id, "❌ Неверный ID отзыва")
            return
            
        conn = sqlite3.connect('restaurant.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('UPDATE reviews SET status = "rejected" WHERE id = ?', (review_id,))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "❌ Отзыв отклонен")
        
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception as e:
            logger.warning(f"Не удалось обновить клавиатуру: {e}")
    
    elif call.data.startswith('admin_reply_review_'):
        review_id = safe_int(call.data.replace('admin_reply_review_', ''))
        if not review_id:
            bot.answer_callback_query(call.id, "❌ Неверный ID отзыва")
            return
            
        AdminStates.set_review_reply_mode(call.from_user.id, review_id)
        
        conn = sqlite3.connect('restaurant.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, user_name, review_text FROM reviews WHERE id = ?', (review_id,))
        review = cursor.fetchone()
        conn.close()
        
        if review:
            user_id, user_name, review_text = review
            
            reply_text = f"""
💬 *Ответ на отзыв гостя*

👤 *Гость:* {user_name}
⭐ *Отзыв:* {review_text if review_text else "Без текста"}

*Введите ваш ответ для гостя:*
            """
            
            try:
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            except Exception as e:
                logger.warning(f"Не удалось обновить клавиатуру: {e}")
            
            safe_send_message(call.from_user.id, reply_text, parse_mode='Markdown')
            bot.answer_callback_query(call.id, "💬 Введите ответ для гостя")
        else:
            bot.answer_callback_query(call.id, "❌ Отзыв не найден")

@bot.message_handler(func=lambda message: message.from_user.id == ADMIN_ID and 
                     AdminStates.get_review_reply_mode(message.from_user.id) is not None and
                     not message.text.startswith('/'))
def handle_admin_review_reply(message):
    review_id = AdminStates.get_review_reply_mode(message.from_user.id)
    if not review_id:
        return
        
    reply_text = message.text
    
    conn = sqlite3.connect('restaurant.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, user_name FROM reviews WHERE id = ?', (review_id,))
    review = cursor.fetchone()
    conn.close()
    
    if review:
        user_id, user_name = review
        user_message = f"""
👑 *Ответ от администратора на ваш отзыв:*

💬 *{reply_text}*

*Спасибо за ваш отзыв!* ❤️
        """
        try:
            safe_send_message(user_id, user_message, parse_mode='Markdown')
            safe_send_message(ADMIN_ID, "✅ Ответ успешно отправлен гостю!")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки ответа гостю: {e}")
            safe_send_message(ADMIN_ID, "❌ Не удалось отправить ответ гостю")
    
    AdminStates.clear_review_reply_mode(message.from_user.id)

# === ДОПОЛНИТЕЛЬНЫЕ ОБРАБОТЧИКИ ===
@bot.message_handler(func=lambda message: message.text == '🔙 Назад к календарю')
def back_to_calendar(message):
    user_id = message.from_user.id
    
    if user_id in user_data:
        user_data[user_id]['state'] = BookingState.DATE
        user_data[user_id]['last_activity'] = time_module.time()
    
    cleanup_user_data(user_id)
    
    calendar = generate_calendar()
    msg = safe_send_message(message.chat.id, "🗓️ Возврат к выбору даты:", reply_markup=calendar)
    
    if user_id not in user_data:
        user_data[user_id] = {}
    user_data[user_id]['booking_steps'] = [msg.message_id]
    user_data[user_id]['state'] = BookingState.DATE

# === ОСНОВНЫЕ КОМАНДЫ ===
@bot.message_handler(commands=['start'])
def start(message):
    if message.from_user.id == ADMIN_ID:
        welcome_text = f"""
👑 *Добро пожаловать в панель администратора!*

🏢 *Лаундж-бар:* {RESTAURANT_INFO['name']}
📍 *Адрес:* {RESTAURANT_INFO['address']}
{RESTAURANT_INFO['entertainment']}

*Используйте меню ниже для управления:* 👇
        """
        safe_send_message(message.chat.id, welcome_text, reply_markup=admin_menu(), parse_mode='Markdown')
    else:
        welcome_text = f"""
🍝 *Добро пожаловать в {RESTAURANT_INFO['name']}!*

{RESTAURANT_INFO['description']}

{RESTAURANT_INFO['entertainment']}

📍 *Адрес:* {RESTAURANT_INFO['address']}
📞 *Телефон:* {RESTAURANT_INFO['phone']}
🕒 *Режим работы:*
• {RESTAURANT_INFO['hours_week']}
• {RESTAURANT_INFO['hours_weekend']}

*Чем могу помочь?* 👇
        """
        safe_send_message(message.chat.id, welcome_text, reply_markup=main_menu(message.from_user.id), parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '📞 Контакты')
def contacts(message):
    contacts_text = f"""
📞 *Контакты {RESTAURANT_INFO['name']}:*

📍 *Адрес:* {RESTAURANT_INFO['address']}
📞 *Телефон:* {RESTAURANT_INFO['phone']}

🕒 *Режим работы:*
• {RESTAURANT_INFO['hours_week']}
• {RESTAURANT_INFO['hours_weekend']}

🎮 *Развлечения:*
{RESTAURANT_INFO['entertainment']}

*Ждем вас в гости!* 😊
    """
    safe_send_message(message.chat.id, contacts_text, parse_mode='Markdown')

# === СИСТЕМА ОЧИСТКИ СЕССИЙ ===
def cleanup_old_sessions():
    while True:
        try:
            current_time = time_module.time()
            max_age = 1800
            
            users_to_remove = []
            for user_id, data in user_data.items():
                if 'last_activity' in data and current_time - data['last_activity'] > max_age:
                    users_to_remove.append(user_id)
            
            for user_id in users_to_remove:
                cleanup_user_data(user_id)
                logger.info(f"🧹 Очищена старая сессия пользователя {user_id}")
            
            time_module.sleep(300)
        except Exception as e:
            logger.error(f"❌ Ошибка в очистке сессий: {e}")
            time_module.sleep(60)

def start_reminder_system():
    reminder_thread = threading.Thread(target=check_reminders)
    reminder_thread.daemon = True
    reminder_thread.start()
    logger.info("✅ Система уведомлений запущена")

# === ЗАПУСК СИСТЕМЫ ===
if __name__ == '__main__':
    print("🚀 Запуск бота на Railway...")
    print(f"🏢 Лаундж-бар: {RESTAURANT_INFO['name']}")
    print(f"📍 Адрес: {RESTAURANT_INFO['address']}")
    print(f"👑 Администратор: {ADMIN_ID}")
    print(f"🎮 Развлечения: {RESTAURANT_INFO['entertainment']}")
    
    # Инициализация базы данных
    init_db()
    
    # Запуск системы уведомлений
    start_reminder_system()
    
    # Запуск очистки сессий
    cleanup_thread = threading.Thread(target=cleanup_old_sessions)
    cleanup_thread.daemon = True
    cleanup_thread.start()
    
    print("✅ Все системы запущены!")
    print("🤖 Бот запущен и готов к работе...")
    
    # Бесконечный цикл для Railway
    while True:
        try:
            print("🔍 Ожидание сообщений...")
            bot.polling(none_stop=True, timeout=60)
        except Exception as e:
            logger.error(f"❌ Ошибка бота: {e}")
            print("🔄 Перезапуск через 10 секунд...")
            time_module.sleep(10)