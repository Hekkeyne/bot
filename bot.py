import sqlite3
import datetime
import logging
import asyncio
import os
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update
from telegram.error import BadRequest, Forbidden
import pytz

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("токен неверный")

FULL_SCHEDULE_LINK = "https://timetable.pallada.sibsau.ru/timetable/group/13922"
FOOTER_LINK = f'\n\n🔗 Полное расписание на сайте: ссылка'

KRASNOYARSK_TZ = pytz.timezone('Asia/Krasnoyarsk')

EXAMS = [
    {
        "date": "18.06.2026",
        "time": "09:40",
        "subject": "ТЕОРИЯ ВЕРОЯТНОСТЕЙ И МАТЕМАТИЧЕСКАЯ СТАТИСТИКА",
        "type": "Экзамен",
        "teacher": "Ушанов С. В.",
        "room": 'корп. "Цл" каб. "004"'
    },
    {
        "date": "22.06.2026",
        "time": "09:00",
        "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ",
        "type": "Экзамен",
        "teacher": "Якимов С. П.",
        "room": 'корп. "Ал" каб. "103"'
    },
    {
        "date": "26.06.2026",
        "time": "13:30",
        "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ",
        "type": "Экзамен",
        "teacher": "Яровой С. В.",
        "room": 'корп. "Гл" каб. "413"'
    }
]

SCHEDULE = {
    "odd": {
        "monday": [],
        "tuesday": [
            {"time": "08:00-09:30", "subject": "ЛОГИЧЕСКОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Шкаберина Г. Ш.", "room": 'корп. "Ал" каб. "213"', "groups": ["2 подгруппа"]},
            {"time": "09:40-11:10", "subject": "ПРОЕКТИРОВАНИЕ ЧЕЛОВЕКО-МАШИННОГО ИНТЕРФЕЙСА", "type": "лабораторная", "teacher": "Прикольный чел", "room": 'корп. "Ал" каб. "109"', "groups": ["2 подгруппа"]},
            {"time": "11:30-13:00", "subject": "МАТЕМАТИЧЕСКАЯ ЛОГИКА И ТЕОРИЯ АЛГОРИТМОВ", "type": "лекция", "teacher": "Иванилова Т. Н.", "room": 'корп. "Ал" каб. "212"', "groups": ["все"]},
            {"time": "13:30-15:00", "subject": "ЛОГИЧЕСКОЕ ПРОГРАММИРОВАНИЕ", "type": "лекция", "teacher": "Товбис Е. М.", "room": 'корп. "Ал" каб. "212"', "groups": ["все"]},
            {"time": "15:10-16:40", "subject": "ЛОГИЧЕСКОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Товбис Е. М.", "room": 'корп. "Ал" каб. "213"', "groups": ["1 подгруппа"]},
            {"time": "16:50-18:20", "subject": "АРХИТЕКТУРА ЭВМ", "type": "лабораторная", "teacher": "Масаев С. Н.", "room": 'корп. "Ал" каб. "103"', "groups": ["1 подгруппа"]}
        ],
        "wednesday": [
            {"time": "09:40-11:10", "subject": "ПРОФЕССИОНАЛЬНО-ПРИКЛАДНАЯ ФИЗИЧЕСКАЯ КУЛЬТУРА", "type": "практика", "teacher": "Мунгалов А. Ю.", "room": 'корп. "УСК" каб. "Набережная"', "groups": ["все"]},
            {"time": "11:30-13:00", "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ", "type": "лекция", "teacher": "Яровой С. В.", "room": 'корп. "Цл" каб. "213"', "groups": ["все"]},
            {"time": "13:30-15:00", "subject": "АРХИТЕКТУРА ЭВМ", "type": "лабораторная", "teacher": "Масаев С. Н.", "room": 'корп. "Цл" каб. "203"', "groups": ["2 подгруппа"]},
            {"time": "13:30-15:00", "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Яровой С. В.", "room": 'корп. "Цл" каб. "204"', "groups": ["1 подгруппа"]},
            {"time": "15:10-16:40", "subject": "АРХИТЕКТУРА ЭВМ", "type": "лекция", "teacher": "Масаев С. Н.", "room": 'корп. "Цл" каб. "213"', "groups": ["все"]}
        ],
        "thursday": [
            {"time": "08:00-09:30", "subject": "ПРОЕКТИРОВАНИЕ ЧЕЛОВЕКО-МАШИННОГО ИНТЕРФЕЙСА", "type": "лабораторная", "teacher": "Прикольный чел", "room": 'корп. "Ал" каб. "109"', "groups": ["1 подгруппа"]},
            {"time": "09:40-11:10", "subject": "ТЕОРИЯ ВЕРОЯТНОСТЕЙ И МАТЕМАТИЧЕСКАЯ СТАТИСТИКА", "type": "практика", "teacher": "Ушанов С. В.", "room": 'корп. "Гл" каб. "414"', "groups": ["все"]},
            {"time": "11:30-13:00", "subject": "ТЕОРИЯ ВЕРОЯТНОСТЕЙ И МАТЕМАТИЧЕСКАЯ СТАТИСТИКА", "type": "лекция", "teacher": "Ушанов С. В.", "room": 'корп. "Гл" каб. "414"', "groups": ["все"]},
            {"time": "13:30-15:00", "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ", "type": "лекция", "teacher": "Якимов С. П.", "room": 'корп. "Ал" каб. "212"', "groups": ["все"]},
            {"time": "15:10-16:40", "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Алехина А. Е.", "room": 'корп. "Гл" каб. "409"', "groups": ["2 подгруппа"]}
        ],
        "friday": [
            {"time": "09:40-11:10", "subject": "ПРОФЕССИОНАЛЬНО-ПРИКЛАДНАЯ ФИЗИЧЕСКАЯ КУЛЬТУРА", "type": "практика", "teacher": "Мунгалов А. Ю.", "room": 'корп. "УСК" каб. "Набережная"', "groups": ["все"]},
            {"time": "11:30-13:00", "subject": "МАТЕМАТИЧЕСКАЯ ЛОГИКА И ТЕОРИЯ АЛГОРИТМОВ", "type": "лабораторная", "teacher": "Иванилова Т. Н.", "room": 'корп. "Ал" каб. "215"', "groups": ["2 подгруппа"]},
            {"time": "11:30-13:00", "subject": "ИНСТРУМЕНТАРИЙ ПРИНЯТИЯ РЕШЕНИЙ", "type": "лабораторная", "teacher": "Шкаберина Г. Ш.", "room": 'корп. "Ал" каб. "103"', "groups": ["1 подгруппа"]},
            {"time": "13:30-15:00", "subject": "МАТЕМАТИЧЕСКАЯ ЛОГИКА И ТЕОРИЯ АЛГОРИТМОВ", "type": "лабораторная", "teacher": "Иванилова Т. Н.", "room": 'корп. "Ал" каб. "215"', "groups": ["1 подгруппа"]},
            {"time": "13:30-15:00", "subject": "ИНСТРУМЕНТАРИЙ ПРИНЯТИЯ РЕШЕНИЙ", "type": "лабораторная", "teacher": "Шкаберина Г. Ш.", "room": 'корп. "Ал" каб. "103"', "groups": ["2 подгруппа"]},
            {"time": "15:10-16:40", "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Якимов С. П.", "room": 'корп. "Ал" каб. "213"', "groups": ["1 подгруппа"]}
        ],
        "saturday": [],
        "sunday": []
    },
    "even": {
        "monday": [],
        "tuesday": [
            {"time": "08:00-09:30", "subject": "ИНСТРУМЕНТАРИЙ ПРИНЯТИЯ РЕШЕНИЙ", "type": "лабораторная", "teacher": "Шкаберина Г. Ш.", "room": 'корп. "Ал" каб. "213"', "groups": ["2 подгруппа"]},
            {"time": "09:40-11:10", "subject": "ПРОЕКТИРОВАНИЕ ЧЕЛОВЕКО-МАШИННОГО ИНТЕРФЕЙСА", "type": "лабораторная", "teacher": "Прикольный чел", "room": 'корп. "Ал" каб. "109"', "groups": ["2 подгруппа"]},
            {"time": "09:40-11:10", "subject": "ИНСТРУМЕНТАРИЙ ПРИНЯТИЯ РЕШЕНИЙ", "type": "лабораторная", "teacher": "Шкаберина Г. Ш.", "room": 'корп. "Ал" каб. "213"', "groups": ["1 подгруппа"]},
            {"time": "11:30-13:00", "subject": "ИНСТРУМЕНТАРИЙ ПРИНЯТИЯ РЕШЕНИЙ", "type": "лекция", "teacher": "Шкаберина Г. Ш.", "room": 'корп. "Ал" каб. "212"', "groups": ["все"]},
            {"time": "13:30-15:00", "subject": "АРХИТЕКТУРА ЭВМ", "type": "лабораторная", "teacher": "Масаев С. Н.", "room": 'корп. "Гл" каб. "407а"', "groups": ["1 подгруппа"]},
            {"time": "13:30-15:00", "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Алехина А. Е.", "room": 'корп. "Гл" каб. "409"', "groups": ["2 подгруппа"]},
            {"time": "15:10-16:40", "subject": "МАТЕМАТИЧЕСКАЯ ЛОГИКА И ТЕОРИЯ АЛГОРИТМОВ", "type": "лабораторная", "teacher": "Иванилова Т. Н.", "room": 'корп. "Ал" каб. "215"', "groups": ["1 подгруппа"]}
        ],
        "wednesday": [
            {"time": "09:40-11:10", "subject": "ПРОФЕССИОНАЛЬНО-ПРИКЛАДНАЯ ФИЗИЧЕСКАЯ КУЛЬТУРА", "type": "практика", "teacher": "Мунгалов А. Ю.", "room": 'корп. "УСК" каб. "Набережная"', "groups": ["все"]},
            {"time": "11:30-13:00", "subject": "ТЕОРИЯ ВЕРОЯТНОСТЕЙ И МАТЕМАТИЧЕСКАЯ СТАТИСТИКА", "type": "лекция", "teacher": "Ушанов С. В.", "room": 'корп. "Гл" каб. "414"', "groups": ["все"]},
            {"time": "13:30-15:00", "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ", "type": "лекция", "teacher": "Якимов С. П.", "room": 'корп. "Ал" каб. "212"', "groups": ["все"]},
            {"time": "15:10-16:40", "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Яровой С. В.", "room": 'корп. "Гл" каб. "407"', "groups": ["1 подгруппа"]}
        ],
        "thursday": [
            {"time": "11:30-13:00", "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ", "type": "лекция", "teacher": "Яровой С. В.", "room": 'корп. "Цл" каб. "213"', "groups": ["все"]},
            {"time": "13:30-15:00", "subject": "ПРОЕКТИРОВАНИЕ ЧЕЛОВЕКО-МАШИННОГО ИНТЕРФЕЙСА", "type": "лекция", "teacher": "Товбис Е. М.", "room": 'корп. "Цл" каб. "213"', "groups": ["все"]},
            {"time": "15:10-16:40", "subject": "АРХИТЕКТУРА ЭВМ", "type": "лабораторная", "teacher": "Масаев С. Н.", "room": 'корп. "Гл" каб. "409"', "groups": ["2 подгруппа"]},
            {"time": "15:10-16:40", "subject": "ПРОЕКТИРОВАНИЕ ЧЕЛОВЕКО-МАШИННОГО ИНТЕРФЕЙСА", "type": "лабораторная", "teacher": "Гриценко Е. М.", "room": 'корп. "Гл" каб. "410"', "groups": ["1 подгруппа"]},
            {"time": "16:50-18:20", "subject": "ТЕОРИЯ ВЕРОЯТНОСТЕЙ И МАТЕМАТИЧЕСКАЯ СТАТИСТИКА", "type": "практика", "teacher": "Ушанов С. В.", "room": 'корп. "Цл" каб. "212"', "groups": ["все"]}
        ],
        "friday": [
            {"time": "09:40-11:10", "subject": "ПРОФЕССИОНАЛЬНО-ПРИКЛАДНАЯ ФИЗИЧЕСКАЯ КУЛЬТУРА", "type": "практика", "teacher": "Мунгалов А. Ю.", "room": 'корп. "УСК" каб. "Набережная"', "groups": ["все"]},
            {"time": "11:30-13:00", "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Якимов С. П.", "room": 'корп. "Ал" каб. "213"', "groups": ["1 подгруппа"]},
            {"time": "11:30-13:00", "subject": "ЛОГИЧЕСКОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Шкаберина Г. Ш.", "room": 'корп. "Ал" каб. "103"', "groups": ["2 подгруппа"]},
            {"time": "13:30-15:00", "subject": "ЛОГИЧЕСКОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Товбис Е. М.", "room": 'корп. "Ал" каб. "213"', "groups": ["1 подгруппа"]},
            {"time": "13:30-15:00", "subject": "МАТЕМАТИЧЕСКАЯ ЛОГИКА И ТЕОРИЯ АЛГОРИТМОВ", "type": "лабораторная", "teacher": "Иванилова Т. Н.", "room": 'корп. "Ал" каб. "215"', "groups": ["2 подгруппа"]}
        ],
        "saturday": [
            {"time": "08:00-09:30", "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Ефимов Е. А.", "room": 'корп. "Ал" каб. "109"', "groups": ["2 подгруппа"]},
            {"time": "09:40-11:10", "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Ефимов Е. А.", "room": 'корп. "Ал" каб. "109"', "groups": ["2 подгруппа"]}
        ],
        "sunday": []
    }
}

class DatabaseManager:
    def __init__(self):
        self.init_db()

    def init_db(self):
        with sqlite3.connect("schedule_bot.db") as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS bot_messages (
                    id INTEGER PRIMARY KEY,
                    chat_id INTEGER,
                    user_id INTEGER,
                    message_id INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    auto_chat_id INTEGER,
                    message_thread_id INTEGER,
                    auto_enabled BOOLEAN DEFAULT 1,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS exam_reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    chat_id INTEGER,
                    message_thread_id INTEGER,
                    exam_date DATE,
                    exam_time TIME,
                    subject TEXT,
                    reminder_enabled BOOLEAN DEFAULT 1,
                    last_reminder_sent TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sent_reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    chat_id INTEGER,
                    exam_date DATE,
                    reminder_type TEXT,
                    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

    def save_message(self, chat_id, user_id, message_id):
        with sqlite3.connect("schedule_bot.db") as conn:
            conn.execute('DELETE FROM bot_messages WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
            conn.execute('INSERT INTO bot_messages (chat_id, user_id, message_id) VALUES (?, ?, ?)',
                         (chat_id, user_id, message_id))

    def get_last_message(self, chat_id, user_id):
        with sqlite3.connect("schedule_bot.db") as conn:
            cur = conn.execute(
                'SELECT message_id FROM bot_messages WHERE chat_id = ? AND user_id = ? ORDER BY timestamp DESC LIMIT 1',
                (chat_id, user_id)
            )
            row = cur.fetchone()
            return row[0] if row else None

    def set_auto_chat(self, user_id, chat_id, thread_id=None):
        with sqlite3.connect("schedule_bot.db") as conn:
            conn.execute('''
                INSERT OR REPLACE INTO user_settings (user_id, auto_chat_id, message_thread_id, auto_enabled)
                VALUES (?, ?, ?, 1)
            ''', (user_id, chat_id, thread_id))

    def disable_auto(self, user_id):
        with sqlite3.connect("schedule_bot.db") as conn:
            conn.execute('UPDATE user_settings SET auto_enabled = 0 WHERE user_id = ?', (user_id,))

    def get_auto_chat(self, user_id):
        with sqlite3.connect("schedule_bot.db") as conn:
            cur = conn.execute(
                'SELECT auto_chat_id, message_thread_id, auto_enabled FROM user_settings WHERE user_id = ?',
                (user_id,)
            )
            row = cur.fetchone()
            if row:
                return (row[0], row[1], bool(row[2]))
            return (None, None, False)

    def get_all_auto_chats(self):
        with sqlite3.connect("schedule_bot.db") as conn:
            cur = conn.execute(
                'SELECT user_id, auto_chat_id, message_thread_id FROM user_settings WHERE auto_enabled = 1'
            )
            return cur.fetchall()

    def set_exam_reminder(self, user_id, chat_id, thread_id, exam_date, exam_time, subject):
        with sqlite3.connect("schedule_bot.db") as conn:
            conn.execute('''
                INSERT OR REPLACE INTO exam_reminders
                (user_id, chat_id, message_thread_id, exam_date, exam_time, subject, reminder_enabled)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            ''', (user_id, chat_id, thread_id, exam_date, exam_time, subject))

    def get_active_exam_reminders(self):
        with sqlite3.connect("schedule_bot.db") as conn:
            cur = conn.execute('''
                SELECT user_id, chat_id, message_thread_id, exam_date, exam_time, subject
                FROM exam_reminders
                WHERE reminder_enabled = 1
                ORDER BY exam_date, exam_time
            ''')
            return cur.fetchall()

    def disable_exam_reminder(self, user_id, exam_date, exam_time):
        with sqlite3.connect("schedule_bot.db") as conn:
            conn.execute('''
                UPDATE exam_reminders
                SET reminder_enabled = 0
                WHERE user_id = ? AND exam_date = ? AND exam_time = ?
            ''', (user_id, exam_date, exam_time))

    def mark_reminder_sent(self, user_id, chat_id, exam_date, reminder_type):
        with sqlite3.connect("schedule_bot.db") as conn:
            conn.execute('''
                INSERT INTO sent_reminders (user_id, chat_id, exam_date, reminder_type)
                VALUES (?, ?, ?, ?)
            ''', (user_id, chat_id, exam_date, reminder_type))

    def was_reminder_sent(self, user_id, chat_id, exam_date, reminder_type):
        with sqlite3.connect("schedule_bot.db") as conn:
            cur = conn.execute('''
                SELECT COUNT(*) FROM sent_reminders
                WHERE user_id = ? AND chat_id = ? AND exam_date = ? AND reminder_type = ?
            ''', (user_id, chat_id, exam_date, reminder_type))
            return cur.fetchone()[0] > 0

    def clear_old_reminders(self, exam_date):
        with sqlite3.connect("schedule_bot.db") as conn:
            conn.execute('''
                DELETE FROM sent_reminders WHERE exam_date < ?
            ''', (exam_date,))

def get_week_type(date=None):
    if date is None:
        date = datetime.date.today()
    return "even" if date.isocalendar()[1] % 2 == 0 else "odd"

def get_day_name(date):
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    return days[date.weekday()]

def get_russian_day(eng):
    mapping = {
        "monday": "Понедельник", "tuesday": "Вторник", "wednesday": "Среда",
        "thursday": "Четверг", "friday": "Пятница", "saturday": "Суббота", "sunday": "Воскресенье"
    }
    return mapping.get(eng, eng)

def get_emoji(lesson_type):
    return {"лекция": "📚", "практика": "✏️", "лабораторная": "🔬"}.get(lesson_type, "📖")

def parse_exam_datetime(exam_date_str, exam_time_str):
    try:
        date_obj = datetime.datetime.strptime(exam_date_str, "%d.%m.%Y").date()
        time_obj = datetime.datetime.strptime(exam_time_str, "%H:%M").time()
        return datetime.datetime.combine(date_obj, time_obj)
    except ValueError:
        return None

def format_exam(exam):
    room_formatted = exam['room'].replace('"', "'")
    text = f"📝 <b>{exam['subject']}</b>\n"
    text += f"📅 {exam['date']} в {exam['time']}\n"
    text += f"👨‍🏫 {exam['teacher']}\n"
    text += f"🏫 {room_formatted}"
    return text

def format_exams_list():
    if not EXAMS:
        return "📋 <b>Список экзаменов</b>\n\n❌ Экзаменов пока нет." + FOOTER_LINK

    text = "📋 <b>Список экзаменов</b>\n\n"
    sorted_exams = sorted(EXAMS, key=lambda x: parse_exam_datetime(x['date'], x['time']) or datetime.datetime.max)

    for idx, exam in enumerate(sorted_exams, 1):
        text += f"{idx}. {format_exam(exam)}\n\n"

    text += FOOTER_LINK
    return text

def get_nearest_exam():
    now = datetime.datetime.now(KRASNOYARSK_TZ)
    nearest = None
    nearest_dt = None

    for exam in EXAMS:
        exam_dt = parse_exam_datetime(exam['date'], exam['time'])
        if exam_dt:
            exam_dt = KRASNOYARSK_TZ.localize(exam_dt) if exam_dt.tzinfo is None else exam_dt

            if exam_dt > now:
                if nearest_dt is None or exam_dt < nearest_dt:
                    nearest_dt = exam_dt
                    nearest = exam

    return nearest, nearest_dt

def format_nearest_exam():
    nearest, nearest_dt = get_nearest_exam()

    if not nearest:
        return "🔍 <b>Ближайший экзамен</b>\n\n❌ Экзаменов нет или все экзамены уже прошли." + FOOTER_LINK

    now = datetime.datetime.now(KRASNOYARSK_TZ)
    time_until = nearest_dt - now

    days = time_until.days
    hours = time_until.seconds // 3600
    minutes = (time_until.seconds % 3600) // 60

    if days > 0:
        time_info = f"через {days} дн. {hours} ч."
    elif hours > 0:
        time_info = f"через {hours} ч. {minutes} мин."
    else:
        time_info = f"через {minutes} мин."

    text = f"🔍 <b>Ближайший экзамен</b>\n\n"
    text += f"⏰ {time_info}\n\n"
    text += format_exam(nearest)
    text += FOOTER_LINK

    return text

async def cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = DatabaseManager()
    last_msg_id = manager.get_last_message(update.effective_chat.id, update.effective_user.id)
    if last_msg_id:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=last_msg_id)
        except:
            pass

def with_cleanup(handler):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await cleanup(update, context)
        return await handler(update, context)
    return wrapper

@with_cleanup
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 <b>Бот расписания</b>\n\n"
        "📋 <b>Команды расписания:</b>\n"
        "/today — сегодня\n"
        "/tomorrow — завтра\n"
        "/week — вся неделя\n"
        "/day <день> — конкретный день (напр. /day вторник)\n"
        "/setchat [chat_id] [thread_id] — настроить автоотправку после последней пары\n"
        "/disable_auto — отключить автоотправку\n"
        "/sendtext <текст> — отправить текст в настроенный чат/топик\n\n"
        "📝 <b>Команды экзаменов:</b>\n"
        "/exams — список всех экзаменов\n"
        "/nearexam — ближайший экзамен\n"
        "/setexam [chat_id] [thread_id] — настроить напоминания об экзаменах\n\n"
        "💡 <b>Примеры:</b>\n"
        "<code>/setchat</code> — в ЛС (отправка в этот чат)\n"
        "<code>/setchat -1001234567890</code> — в группу\n"
        "<code>/setchat -1001234567890 42</code> — в топик группы\n\n"
        "<code>/setexam</code> — включить напоминания об экзаменах\n"
        "<code>/setexam -1001234567890 42</code> — в конкретный чат/топик"
        + FOOTER_LINK
    )
    msg = await update.message.reply_text(text, parse_mode='HTML')
    DatabaseManager().save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)

@with_cleanup
async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.date.today()
    msg = await update.message.reply_text(
        format_schedule(get_day_name(today), get_week_type(today), today),
        parse_mode='HTML'
    )
    DatabaseManager().save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)

@with_cleanup
async def tomorrow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tmr = datetime.date.today() + datetime.timedelta(days=1)
    msg = await update.message.reply_text(
        format_schedule(get_day_name(tmr), get_week_type(tmr), tmr),
        parse_mode='HTML'
    )
    DatabaseManager().save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)

@with_cleanup
async def day_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mapping = {
        'понедельник': 'monday', 'вторник': 'tuesday', 'среда': 'wednesday',
        'четверг': 'thursday', 'пятница': 'friday', 'суббота': 'saturday', 'воскресенье': 'sunday'
    }
    arg = " ".join(context.args).lower()
    day = mapping.get(arg)
    if not day:
        msg = await update.message.reply_text(
            "❌ Укажите день: /day понедельник" + FOOTER_LINK,
            parse_mode='HTML'
        )
    else:
        target = datetime.date.today()
        while get_day_name(target) != day:
            target += datetime.timedelta(days=1)
        msg = await update.message.reply_text(
            format_schedule(day, get_week_type(target), target),
            parse_mode='HTML'
        )
    DatabaseManager().save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)

@with_cleanup
async def week_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.date.today()
    week_type = get_week_type(today)
    text = "📅 <b>Расписание на неделю</b>\n\n"
    for eng in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
        lessons = SCHEDULE[week_type].get(eng, [])
        ru = get_russian_day(eng)
        if lessons:
            time_groups = {}
            for lesson in lessons:
                time_groups.setdefault(lesson['time'], []).append(lesson)

            text += f"🔹 <b>{ru}</b>:\n"
            for time_slot in sorted(time_groups.keys(), key=lambda t: t.split('-')[0]):
                group = time_groups[time_slot]
                all_groups_lesson = next((l for l in group if l['groups'][0] == "все"), None)
                if all_groups_lesson:
                    text += f"⏰ {time_slot} | {all_groups_lesson['subject']} ({all_groups_lesson['type'].upper()})\n"
                else:
                    for lesson in group:
                        text += f"⏰ {time_slot} | {lesson['groups'][0]}: {lesson['subject']} ({lesson['type'].upper()})\n"
            text += "\n"
        else:
            text += f"🔹 <b>{ru}</b>: 🎉 Выходной\n\n"
    
    text += f"📊 Неделя: {'1-я' if week_type == 'even' else '2-я'}" + FOOTER_LINK
    msg = await update.message.reply_text(text, parse_mode='HTML')
    DatabaseManager().save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)

@with_cleanup
async def setchat_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    manager = DatabaseManager()
    target_chat_id = None
    target_thread_id = None

    if update.effective_chat.type == "private":
        if context.args:
            if len(context.args) >= 1 and context.args[0].lstrip('-').isdigit():
                target_chat_id = int(context.args[0])
            if len(context.args) >= 2 and context.args[1].isdigit():
                target_thread_id = int(context.args[1])
        if not target_chat_id:
            target_chat_id = update.effective_chat.id
    else:
        if not context.args:
            target_chat_id = update.effective_chat.id
            if update.message.is_topic_message:
                target_thread_id = update.message.message_thread_id
        else:
            if context.args[0].lstrip('-').isdigit():
                target_chat_id = int(context.args[0])
            if len(context.args) >= 2 and context.args[1].isdigit():
                target_thread_id = int(context.args[1])

    if not target_chat_id:
        msg = await update.message.reply_text(
            "⚙️ <b>Настройка автоотправки:</b>\n\n"
            "В ЛС: просто <code>/setchat</code>\n"
            "В группе: <code>/setchat &lt;chat_id&gt;</code>\n"
            "В топик: <code>/setchat &lt;chat_id&gt; &lt;thread_id&gt;</code>\n\n"
            "ID чата можно узнать через @getidsbot\n"
            "Thread ID — это ID топика в группе" + FOOTER_LINK,
            parse_mode='HTML'
        )
        manager.save_message(update.effective_chat.id, user_id, msg.message_id)
        return

    manager.set_auto_chat(user_id, target_chat_id, target_thread_id)
    thread_info = f"\nТопик: <code>{target_thread_id}</code>" if target_thread_id else "\nЧат (без топика)"
    msg = await update.message.reply_text(
        f"✅ <b>Автоотправка настроена!</b>\n\n"
        f"Чат: <code>{target_chat_id}</code>"
        f"{thread_info}\n"
        f"Отправка: сразу после последней пары по Красноярску (UTC+7)\n"
        f"Отключить: <code>/disable_auto</code>" + FOOTER_LINK,
        parse_mode='HTML'
    )
    manager.save_message(update.effective_chat.id, user_id, msg.message_id)

@with_cleanup
async def disable_auto_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    DatabaseManager().disable_auto(user_id)
    msg = await update.message.reply_text(
        "❌ Автоотправка отключена." + FOOTER_LINK,
        parse_mode='HTML'
    )
    DatabaseManager().save_message(update.effective_chat.id, user_id, msg.message_id)

@with_cleanup
async def sendtext_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    manager = DatabaseManager()

    if not context.args:
        msg = await update.message.reply_text(
            "❌ <b>Ошибка</b>\n\n"
            "Укажите текст для отправки.\n"
            "Пример: <code>/sendtext Всем привет, встречаемся в 15:00!</code>" + FOOTER_LINK,
            parse_mode='HTML'
        )
        manager.save_message(update.effective_chat.id, user_id, msg.message_id)
        return

    text_to_send = " ".join(context.args)
    
    auto_chat_id, message_thread_id, auto_enabled = manager.get_auto_chat(user_id)
    
    if not auto_chat_id:
        msg = await update.message.reply_text(
            "❌ <b>Ошибка</b>\n\n"
            "Вы не настроили чат для рассылки.\n"
            "Используйте /setchat, чтобы указать чат и топик." + FOOTER_LINK,
            parse_mode='HTML'
        )
        manager.save_message(update.effective_chat.id, user_id, msg.message_id)
        return

    try:
        if message_thread_id:
            await context.bot.send_message(
                chat_id=auto_chat_id,
                text=text_to_send,
                message_thread_id=message_thread_id
            )
        else:
            await context.bot.send_message(
                chat_id=auto_chat_id,
                text=text_to_send
            )
        
        thread_info = f"\nТопик: <code>{message_thread_id}</code>" if message_thread_id else "\nЧат (без топика)"
        msg = await update.message.reply_text(
            f"✅ <b>Сообщение успешно отправлено!</b>\n\n"
            f"Чат: <code>{auto_chat_id}</code>"
            f"{thread_info}\n\n"
            f"Текст:\n{text_to_send}" + FOOTER_LINK,
            parse_mode='HTML'
        )
    except Exception as e:
        msg = await update.message.reply_text(
            f"❌ <b>Ошибка отправки</b>\n\n"
            f"Не удалось отправить сообщение.\n"
            f"Проверьте, добавлен ли бот в чат <code>{auto_chat_id}</code> и есть ли у него права.\n\n"
            f"Ошибка: {e}" + FOOTER_LINK,
            parse_mode='HTML'
        )

    manager.save_message(update.effective_chat.id, user_id, msg.message_id)

@with_cleanup
async def now_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("Бот работает!" + FOOTER_LINK, parse_mode='HTML')
    DatabaseManager().save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)

@with_cleanup
async def exams_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        format_exams_list(),
        parse_mode='HTML'
    )
    DatabaseManager().save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)

@with_cleanup
async def nearexam_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        format_nearest_exam(),
        parse_mode='HTML'
    )
    DatabaseManager().save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)

@with_cleanup
async def setexam_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    manager = DatabaseManager()
    target_chat_id = None
    target_thread_id = None

    if not EXAMS:
        msg = await update.message.reply_text(
            "❌ <b>Ошибка</b>\n\nЭкзамены не заполнены. Обратитесь к администратору." + FOOTER_LINK,
            parse_mode='HTML'
        )
        manager.save_message(update.effective_chat.id, user_id, msg.message_id)
        return

    if update.effective_chat.type == "private":
        if context.args:
            if len(context.args) >= 1 and context.args[0].lstrip('-').isdigit():
                target_chat_id = int(context.args[0])
            if len(context.args) >= 2 and context.args[1].isdigit():
                target_thread_id = int(context.args[1])
        if not target_chat_id:
            target_chat_id = update.effective_chat.id
    else:
        if not context.args:
            target_chat_id = update.effective_chat.id
            if update.message.is_topic_message:
                target_thread_id = update.message.message_thread_id
        else:
            if context.args[0].lstrip('-').isdigit():
                target_chat_id = int(context.args[0])
            if len(context.args) >= 2 and context.args[1].isdigit():
                target_thread_id = int(context.args[1])

    if not target_chat_id:
        msg = await update.message.reply_text(
            "⚙️ <b>Настройка напоминаний об экзаменах:</b>\n\n"
            "В ЛС: просто <code>/setexam</code>\n"
            "В группе: <code>/setexam &lt;chat_id&gt;</code>\n"
            "В топик: <code>/setexam &lt;chat_id&gt; &lt;thread_id&gt;</code>\n\n"
            "Бот будет отправлять:\n"
            "• За 3 дня до экзамена\n"
            "• За 1 день до экзамена\n"
            "• За 1 час до экзамена\n"
            "• Через 6 часов после начала (если есть следующий экзамен)" + FOOTER_LINK,
            parse_mode='HTML'
        )
        manager.save_message(update.effective_chat.id, user_id, msg.message_id)
        return

    reminders_set = 0
    for exam in EXAMS:
        manager.set_exam_reminder(
            user_id, target_chat_id, target_thread_id,
            exam['date'], exam['time'], exam['subject']
        )
        reminders_set += 1

    thread_info = f"\nТопик: <code>{target_thread_id}</code>" if target_thread_id else "\nЧат (без топика)"
    msg = await update.message.reply_text(
        f"✅ <b>Напоминания об экзаменах включены!</b>\n\n"
        f"Чат: <code>{target_chat_id}</code>"
        f"{thread_info}\n"
        f"Настроено напоминаний: {reminders_set}\n\n"
        f"Бот будет напоминать:\n"
        f"• За 3 дня до экзамена\n"
        f"• За 1 день до экзамена\n"
        f"• За 1 час до экзамена\n"
        f"• Через 6 часов после начала\n\n"
        f"Используйте /exams для просмотра всех экзаменов\n"
        f"Используйте /nearexam для просмотра ближайшего экзамена" + FOOTER_LINK,
        parse_mode='HTML'
    )
    manager.save_message(update.effective_chat.id, user_id, msg.message_id)

async def send_exam_reminder(bot, chat_id, thread_id, exam, reminder_type):
    room_formatted = exam['room'].replace('"', "'")

    if reminder_type == "3_days":
        text = f"⏰ <b>Напоминание об экзамене</b>\n\n"
        text += f"📅 Через 3 дня: <b>{exam['subject']}</b>\n"
        text += f"⏰ {exam['date']} в {exam['time']}\n"
        text += f"👨‍🏫 {exam['teacher']}\n"
        text += f"🏫 {room_formatted}"
    elif reminder_type == "1_day":
        text = f"⚠️ <b>Напоминание об экзамене</b>\n\n"
        text += f"📅 Завтра: <b>{exam['subject']}</b>\n"
        text += f"⏰ {exam['date']} в {exam['time']}\n"
        text += f"👨‍🏫 {exam['teacher']}\n"
        text += f"🏫 {room_formatted}"
    elif reminder_type == "1_hour":
        text = f"🚨 <b>Сегодня экзамен</b>\n\n"
        text += f"⏰ Через 1 час: <b>{exam['subject']}</b>\n"
        text += f"📅 {exam['date']} в {exam['time']}\n"
        text += f"👨‍🏫 {exam['teacher']}\n"
        text += f"🏫 {room_formatted}\n\n"
        text += f"пасасете"
    elif reminder_type == "6_hours":
        text = f"🔔 <b>Экзамен: {exam['subject']}</b>\n\n"
        text += f"Начался в {exam['time']}"

    try:
        if thread_id:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode='HTML',
                message_thread_id=thread_id
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode='HTML'
            )
        return True
    except Exception as e:
        logging.error(f"Ошибка отправки напоминания: {e}")
        return False

async def get_next_exam_reminder_time():
    if not EXAMS:
        return None, None

    now = datetime.datetime.now(KRASNOYARSK_TZ)
    manager = DatabaseManager()
    reminders = manager.get_active_exam_reminders()

    next_reminder_time = None
    next_reminder_data = None

    for user_id, chat_id, thread_id, exam_date_str, exam_time_str, subject in reminders:
        exam_dt = parse_exam_datetime(exam_date_str, exam_time_str)
        if not exam_dt:
            continue

        exam_dt = KRASNOYARSK_TZ.localize(exam_dt) if exam_dt.tzinfo is None else exam_dt

        if exam_dt <= now:
            continue

        reminder_times = {
            "3_days": exam_dt - datetime.timedelta(days=3),
            "1_day": exam_dt - datetime.timedelta(days=1),
            "1_hour": exam_dt - datetime.timedelta(hours=1),
            "6_hours": exam_dt + datetime.timedelta(hours=6)
        }

        for reminder_type, reminder_time in reminder_times.items():
            if reminder_time <= now:
                continue

            if manager.was_reminder_sent(user_id, chat_id, exam_date_str, reminder_type):
                continue

            if next_reminder_time is None or reminder_time < next_reminder_time:
                next_reminder_time = reminder_time
                next_reminder_data = {
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "thread_id": thread_id,
                    "exam_date": exam_date_str,
                    "exam_time": exam_time_str,
                    "subject": subject,
                    "reminder_type": reminder_type,
                    "exam_dt": exam_dt
                }

    return next_reminder_time, next_reminder_data

async def exam_reminder_loop(application: Application):
    logging.info("🎓 Цикл напоминаний об экзаменах запущен")

    while True:
        try:
            next_time, reminder_data = await get_next_exam_reminder_time()

            if next_time is None:
                logging.info("📭 Нет активных напоминаний об экзаменах, следующая проверка через час")
                await asyncio.sleep(3600)
                continue

            now = datetime.datetime.now(KRASNOYARSK_TZ)
            seconds_to_wait = (next_time - now).total_seconds()

            if seconds_to_wait <= 0:
                logging.info(f"⏰ Время напоминания наступило, отправляем...")
            else:
                logging.info(
                    f"⏰ Следующее напоминание через {seconds_to_wait/3600:.1f} ч "
                    f"({next_time.strftime('%d.%m %H:%M')}): "
                    f"{reminder_data['subject']} ({reminder_data['reminder_type']})"
                )
                await asyncio.sleep(seconds_to_wait)

            exam = next(
                (e for e in EXAMS
                 if e['date'] == reminder_data['exam_date'] and e['time'] == reminder_data['exam_time']),
                None
            )

            if exam:
                manager = DatabaseManager()
                success = await send_exam_reminder(
                    application.bot,
                    reminder_data['chat_id'],
                    reminder_data['thread_id'],
                    exam,
                    reminder_data['reminder_type']
                )

                if success:
                    manager.mark_reminder_sent(
                        reminder_data['user_id'],
                        reminder_data['chat_id'],
                        reminder_data['exam_date'],
                        reminder_data['reminder_type']
                    )
                    logging.info(
                        f"✅ Отправлено напоминание ({reminder_data['reminder_type']}) "
                        f"пользователю {reminder_data['user_id']} об экзамене {reminder_data['subject']}"
                    )

                    if reminder_data['reminder_type'] == "6_hours":
                        next_exam = None
                        exam_dt = reminder_data['exam_dt']

                        for e in EXAMS:
                            e_dt = parse_exam_datetime(e['date'], e['time'])
                            if e_dt:
                                e_dt = KRASNOYARSK_TZ.localize(e_dt) if e_dt.tzinfo is None else e_dt
                                if e_dt > exam_dt:
                                    if next_exam is None or parse_exam_datetime(e['date'], e['time']) < parse_exam_datetime(next_exam['date'], next_exam['time']):
                                        next_exam = e

                        if next_exam:
                            logging.info(f"📚 Найден следующий экзамен: {next_exam['subject']}, запускаем алгоритм напоминаний")
                else:
                    logging.error(f"❌ Не удалось отправить напоминание")

            await asyncio.sleep(1)

        except asyncio.CancelledError:
            logging.info("🛑 Цикл напоминаний об экзаменах остановлен")
            break
        except Exception as e:
            logging.error(f"❌ Ошибка в цикле напоминаний об экзаменах: {e}")
            await asyncio.sleep(60)

async def send_tomorrow_schedule(bot, chat_id, thread_id, week_type_tomorrow):
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    day_name = get_day_name(tomorrow)
    schedule_text = format_schedule(day_name, week_type_tomorrow, tomorrow)

    if thread_id:
        await bot.send_message(
            chat_id=chat_id,
            text=schedule_text,
            parse_mode='HTML',
            message_thread_id=thread_id
        )
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=schedule_text,
            parse_mode='HTML'
        )

def get_last_lesson_end_time(day_name, week_type):
    lessons = SCHEDULE[week_type].get(day_name, [])
    if not lessons:
        return None

    end_times = []
    for lesson in lessons:
        try:
            end = lesson['time'].split('-')[1]
            h, m = map(int, end.split(':'))
            end_times.append((h, m))
        except (IndexError, ValueError):
            continue

    return max(end_times) if end_times else None

def find_last_day_with_classes(reference_date):
    for i in range(1, 8):
        check_date = reference_date - datetime.timedelta(days=i)
        day_name = get_day_name(check_date)
        week_type = get_week_type(check_date)
        lessons = SCHEDULE[week_type].get(day_name, [])
        if lessons:
            return (check_date, day_name, week_type)
    return None

def get_trigger_time_for_today(today_date):
    now_krasnoyarsk = datetime.datetime.now(KRASNOYARSK_TZ)
    today_day_name = get_day_name(today_date)
    today_week_type = get_week_type(today_date)
    today_lessons = SCHEDULE[today_week_type].get(today_day_name, [])

    if today_lessons:
        last_time = get_last_lesson_end_time(today_day_name, today_week_type)
        if last_time:
            h, m = last_time
            return now_krasnoyarsk.replace(hour=h, minute=m, second=0, microsecond=0) + datetime.timedelta(minutes=2)
    else:
        result = find_last_day_with_classes(today_date)
        if result:
            _, day_name, week_type = result
            last_time = get_last_lesson_end_time(day_name, week_type)
            if last_time:
                h, m = last_time
                return now_krasnoyarsk.replace(hour=h, minute=m, second=0, microsecond=0) + datetime.timedelta(minutes=2)

    return None

async def schedule_auto_send(app: Application):
    now_krasnoyarsk = datetime.datetime.now(KRASNOYARSK_TZ)
    today = now_krasnoyarsk.date()
    tomorrow = today + datetime.timedelta(days=1)
    tomorrow_week = get_week_type(tomorrow)

    trigger_time = get_trigger_time_for_today(today)

    if not trigger_time:
        logging.info(f"Не удалось определить время триггера для {today.strftime('%d.%m.%Y')}, пропускаем")
        return

    if now_krasnoyarsk < trigger_time:
        seconds_to_wait = (trigger_time - now_krasnoyarsk).total_seconds()
        logging.info(f"⏰ Автоотправка запланирована через {seconds_to_wait/60:.1f} мин (в {trigger_time.strftime('%H:%M')})")
        await asyncio.sleep(seconds_to_wait)

        if datetime.datetime.now(KRASNOYARSK_TZ).date() != today:
            logging.warning("Дата изменилась во время ожидания, пропускаем отправку")
            return
        elif now_krasnoyarsk - trigger_time > datetime.timedelta(hours=3):
            logging.info(f"⏭ Время отправки ({trigger_time.strftime('%H:%M')}) прошло более 3 часов назад, пропускаем")
            return
        else:
            logging.info(f"Время отправки ({trigger_time.strftime('%H:%M')}) уже наступило, отправляем сейчас")

    manager = DatabaseManager()
    sent_count = 0

    for user_id, target_chat_id, target_thread_id in manager.get_all_auto_chats():
        try:
            await send_tomorrow_schedule(app.bot, target_chat_id, target_thread_id, tomorrow_week)
            thread_info = f" (топик {target_thread_id})" if target_thread_id else ""
            logging.info(f"Отправлено пользователю {user_id} в чат {target_chat_id}{thread_info}")
            sent_count += 1
        except Forbidden:
            logging.warning(f"Бот заблокирован в чате {target_chat_id}, отключаем автоотправку для {user_id}")
            manager.disable_auto(user_id)
        except BadRequest as e:
            logging.warning(f"Ошибка отправки в чат {target_chat_id}: {e}")
        except Exception as e:
            logging.error(f"Неожиданная ошибка: {type(e).__name__}: {e}")

    if sent_count > 0:
        logging.info(f"📊 Всего отправлено: {sent_count}")

async def auto_send_loop(application: Application):
    while True:
        try:
            await schedule_auto_send(application)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.error(f"Ошибка в цикле автоотправки: {e}")

        now = datetime.datetime.now(KRASNOYARSK_TZ)
        next_day = now.date() + datetime.timedelta(days=1)
        next_check = KRASNOYARSK_TZ.localize(
            datetime.datetime.combine(next_day, datetime.time(0, 1))
        )
        sleep_seconds = (next_check - datetime.datetime.now(KRASNOYARSK_TZ)).total_seconds()
        logging.info(f"Следующая проверка через {sleep_seconds/3600:.1f} часов")
        await asyncio.sleep(max(60, sleep_seconds))

async def post_init(application: Application):
    asyncio.create_task(auto_send_loop(application))
    asyncio.create_task(exam_reminder_loop(application))
    logging.info("Циклы автоотправки запущены")

def format_schedule(day_name, week_type, date):
    lessons = SCHEDULE[week_type].get(day_name, [])
    if not lessons:
        return f"📅 Расписание на {get_russian_day(day_name)} ({date.strftime('%d.%m.%Y')})\n\n🎉 Выходной! Пар нет." + FOOTER_LINK

    time_groups = {}
    for lesson in lessons:
        time_groups.setdefault(lesson['time'], []).append(lesson)

    sorted_times = sorted(time_groups.keys(), key=lambda t: t.split('-')[0])

    msg = f"📅 Расписание на {get_russian_day(day_name)} ({date.strftime('%d.%m.%Y')})\n"
    msg += f"📊 Неделя: {'1-я' if week_type == 'even' else '2-я'}\n\n"

    for idx, time_slot in enumerate(sorted_times, 1):
        group = time_groups[time_slot]
        all_groups_lesson = None
        for lesson in group:
            if lesson['groups'][0] == "все":
                all_groups_lesson = lesson
                break

        msg += f"{idx}. ⏰ {time_slot}\n"

        if all_groups_lesson:
            room_formatted = all_groups_lesson['room'].replace('"', "'")
            msg += f"📚 <b>{all_groups_lesson['subject']}</b>\n"
            msg += f"{get_emoji(all_groups_lesson['type'])} {all_groups_lesson['type'].upper()}\n"
            msg += f"👨‍🏫 {all_groups_lesson['teacher']}\n"
            msg += f"🏫 {room_formatted}\n\n"
        else:
            for i, lesson in enumerate(group):
                if i > 0:
                    msg += "\n"
                room_formatted = lesson['room'].replace('"', "'")
                msg += f"👥 {lesson['groups'][0]}:\n"
                msg += f"📚 <b>{lesson['subject']}</b>\n"
                msg += f"{get_emoji(lesson['type'])} {lesson['type'].upper()}\n"
                msg += f"👨‍🏫 {lesson['teacher']}\n"
                msg += f"🏫 {room_formatted}\n"
            msg += "\n"

    return msg.strip() + FOOTER_LINK

def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[logging.StreamHandler()]
    )

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("today", today_cmd))
    app.add_handler(CommandHandler("tomorrow", tomorrow_cmd))
    app.add_handler(CommandHandler("day", day_cmd))
    app.add_handler(CommandHandler("week", week_cmd))
    app.add_handler(CommandHandler("setchat", setchat_cmd))
    app.add_handler(CommandHandler("disable_auto", disable_auto_cmd))
    app.add_handler(CommandHandler("now", now_cmd))

    app.add_handler(CommandHandler("sendtext", sendtext_cmd))

    app.add_handler(CommandHandler("exams", exams_cmd))
    app.add_handler(CommandHandler("nearexam", nearexam_cmd))
    app.add_handler(CommandHandler("setexam", setexam_cmd))

    print("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
