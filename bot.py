import sqlite3
import datetime
import logging
import requests
from bs4 import BeautifulSoup
import asyncio
from telegram.ext import Application, CommandHandler, ContextTypes, JobQueue
from telegram import Update
from telegram.error import BadRequest

# === Настройки бота ===
CHAT_ID = -1002148833759
TOPIC_ID = 29
BOT_TOKEN = "6086143518:AAGnbv6OAjSyyahXETPjvVCyeZLeiVku5yA"

# === Настройки расписания ===
GROUP_ID = 13922
URL = f"https://timetable.pallada.sibsau.ru/timetable/group/{GROUP_ID}"  # ← УБРАЛ ПРОБЕЛЫ!

# === Словари перевода ===
DAY_RU_TO_EN = {
    "Понедельник": "monday",
    "Вторник": "tuesday",
    "Среда": "wednesday",
    "Четверг": "thursday",
    "Пятница": "friday",
    "Суббота": "saturday",
    "Воскресенье": "sunday"
}

TYPE_MAP = {
    "Лекция": "лекция",
    "Практика": "практика",
    "Лабораторная работа": "лабораторная"
}

# Глобальная переменная для расписания
SCHEDULE = None

def parse_timetable_from_html(html_text):
    soup = BeautifulSoup(html_text, 'lxml')
    schedule = {"even": {}, "odd": {}}

    week_tabs = soup.select('div[id^="week_"][id$="_tab"]')
    if not week_tabs:
        raise ValueError("Не найдены вкладки недель на странице")

    for tab in week_tabs:
        week_num = tab['id'].split('_')[1]
        key = "odd" if week_num == "1" else "even"

        for day_en in DAY_RU_TO_EN.values():
            schedule[key][day_en] = []

        days = tab.select('div.day')
        for day in days:
            day_name_ru = day.select_one('.name').get_text(strip=True).replace("сегодня", "").strip()
            if day_name_ru not in DAY_RU_TO_EN:
                continue
            day_en = DAY_RU_TO_EN[day_name_ru]

            lessons = []
            lines = day.select('.line')
            for line in lines:
                time_elem = line.select_one('.time')
                if not time_elem:
                    continue
                time_str = time_elem.get_text(strip=True).replace('\n', ' ')
                if '–' in time_str or '-' in time_str:
                    time_part = time_str.split()[0] if ' ' in time_str else time_str
                    time_clean = time_part[:11] if len(time_part) >= 11 else time_part
                else:
                    time_clean = time_str

                blocks = line.select('.col-md-6\\.0, .col-md-12')
                if not blocks:
                    blocks = [line]

                for block in blocks:
                    subject_elem = block.select_one('span.name')
                    if not subject_elem:
                        continue
                    subject = subject_elem.get_text(strip=True)

                    type_full = block.get_text()
                    lesson_type = "лабораторная"
                    if "(Лекция)" in type_full:
                        lesson_type = "лекция"
                    elif "(Практика)" in type_full:
                        lesson_type = "практика"

                    teacher_elem = block.select_one('a[href^="/timetable/professor/"]')
                    teacher = teacher_elem.get_text(strip=True) if teacher_elem else ""

                    room_elem = block.select_one('a[title]')
                    room = room_elem.get_text(strip=True) if room_elem else ""

                    groups = []
                    subgroup_elem = block.select_one('.num_pdgrp, i.fa-paperclip + li')
                    if subgroup_elem:
                        subgroup_text = subgroup_elem.get_text(strip=True)
                        if "подгруппа" not in subgroup_text.lower():
                            subgroup_text += " подгруппа"
                        groups = [subgroup_text]

                    lessons.append({
                        "time": time_clean,
                        "subject": subject,
                        "type": lesson_type,
                        "teacher": teacher,
                        "room": room,
                        "groups": groups
                    })

            schedule[key][day_en] = lessons

    return schedule

def load_schedule():
    """Загружает и парсит расписание"""
    global SCHEDULE
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    print("📥 Загрузка расписания...")
    response = requests.get(URL, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Не удалось загрузить расписание: HTTP {response.status_code}")
    
    SCHEDULE = parse_timetable_from_html(response.text)
    print("✅ Расписание успешно загружено!")

# === Класс менеджера расписания ===
class ScheduleManager:
    def __init__(self, db_path="schedule_bot.db"):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS schedule_messages (
                id INTEGER PRIMARY KEY,
                date TEXT UNIQUE,
                message_id INTEGER,
                chat_id INTEGER,
                message_thread_id INTEGER
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bot_messages (
                id INTEGER PRIMARY KEY,
                chat_id INTEGER,
                user_id INTEGER,
                message_id INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        print("✅ База данных инициализирована")
    
    def save_message_info(self, date, message_id, chat_id, message_thread_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO schedule_messages (date, message_id, chat_id, message_thread_id)
            VALUES (?, ?, ?, ?)
        ''', (date, message_id, chat_id, message_thread_id))
        conn.commit()
        conn.close()
    
    def get_previous_message(self, date):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT message_id, chat_id, message_thread_id FROM schedule_messages WHERE date = ?', (date,))
        result = cursor.fetchone()
        conn.close()
        return result
    
    def delete_message_record(self, date):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM schedule_messages WHERE date = ?', (date,))
        conn.commit()
        conn.close()
    
    def save_bot_message(self, chat_id, user_id, message_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM bot_messages WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
        cursor.execute('INSERT INTO bot_messages (chat_id, user_id, message_id) VALUES (?, ?, ?)', (chat_id, user_id, message_id))
        conn.commit()
        conn.close()
    
    def get_last_bot_message(self, chat_id, user_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT message_id, chat_id FROM bot_messages 
            WHERE chat_id = ? AND user_id = ?
            ORDER BY timestamp DESC LIMIT 1
        ''', (chat_id, user_id))
        result = cursor.fetchone()
        conn.close()
        return result

# === Вспомогательные функции ===
def get_next_weekday(weekday, include_today=False):
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    target_day_index = days.index(weekday)
    today = datetime.date.today()
    current_day_index = today.weekday()
    days_ahead = target_day_index - current_day_index
    if days_ahead < 0 or (days_ahead == 0 and not include_today):
        days_ahead += 7
    return today + datetime.timedelta(days=days_ahead)

def get_week_type(date=None):
    if date is None:
        date = datetime.date.today()
    week_number = date.isocalendar()[1]
    return "even" if week_number % 2 == 0 else "odd"

def get_tomorrow_date():
    return datetime.date.today() + datetime.timedelta(days=1)

def get_type_emoji(lesson_type):
    emoji_map = {"лекция": "📚", "практика": "✏️", "лабораторная": "🔬", "семинар": "💬"}
    return emoji_map.get(lesson_type, "📖")

def get_russian_day(english_day):
    days = {"monday": "Понедельник", "tuesday": "Вторник", "wednesday": "Среда", "thursday": "Четверг", "friday": "Пятница", "saturday": "Суббота", "sunday": "Воскресенье"}
    return days.get(english_day, english_day)

def get_day_name(date):
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    return days[date.weekday()]

def format_schedule_message(day_name, week_type, date):
    global SCHEDULE
    if SCHEDULE is None:
        return "❌ Расписание не загружено!"
    
    day_ru = get_russian_day(day_name)
    date_str = date.strftime("%d.%m.%Y")
    
    if week_type not in SCHEDULE:
        return f"❌ Неделя '{week_type}' не найдена"
    
    lessons = SCHEDULE[week_type].get(day_name, [])
    
    if not lessons:
        return f"📅 Расписание на {day_ru} ({date_str})\n\n🎉 Выходной! Пар нет."
    
    lessons_by_time = {}
    for lesson in lessons:
        time_key = lesson['time']
        if time_key not in lessons_by_time:
            lessons_by_time[time_key] = []
        lessons_by_time[time_key].append(lesson)
    
    message = f"📅 Расписание на {day_ru} ({date_str})\n"
    message += f"📊 Неделя: {'1-я' if week_type == 'even' else '2-я'}\n\n"
    
    lesson_number = 1
    for time_key in sorted(lessons_by_time.keys()):
        time_lessons = lessons_by_time[time_key]
        if len(time_lessons) == 1:
            lesson = time_lessons[0]
            type_emoji = get_type_emoji(lesson['type'])
            group_info = f" ({lesson['groups'][0]})" if lesson.get('groups') else ""
            message += f"{lesson_number}. ⏰ {lesson['time']} - {lesson['subject']}{group_info}\n"
            message += f"   {type_emoji} {lesson['type'].upper()}\n"
            message += f"   👨‍🏫 {lesson['teacher']}\n"
            message += f"   🏫 {lesson['room']}\n\n"
            lesson_number += 1
        else:
            type_emoji = get_type_emoji(time_lessons[0]['type'])
            if all(lesson['subject'] == time_lessons[0]['subject'] for lesson in time_lessons):
                subject_name = time_lessons[0]['subject']
            else:
                subject_names = [lesson['subject'] for lesson in time_lessons]
                subject_name = " / ".join(subject_names)
            message += f"{lesson_number}. ⏰ {time_key} - {subject_name}\n"
            message += f"   {type_emoji} {time_lessons[0]['type'].upper()}\n"
            for lesson in time_lessons:
                groups = lesson['groups'][0] if lesson.get('groups') else "все"
                message += f"   👥 {groups}: {lesson['subject']} - {lesson['teacher']} - {lesson['room']}\n"
            message += "\n"
            lesson_number += 1
    return message

# === Обработчики команд ===
async def delete_previous_bot_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        schedule_manager = ScheduleManager()
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        previous_message = schedule_manager.get_last_bot_message(chat_id, user_id)
        if previous_message:
            await context.bot.delete_message(chat_id=previous_message[1], message_id=previous_message[0])
            print(f"✅ Удалено предыдущее сообщение бота для пользователя {user_id}")
    except BadRequest as e:
        if "message to delete not found" not in str(e):
            print(f"⚠️ Не удалось удалить сообщение бота: {e}")
    except Exception as e:
        print(f"⚠️ Ошибка при удалении сообщения бота: {e}")

def with_message_cleanup(handler):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await delete_previous_bot_message(update, context)
        return await handler(update, context)
    return wrapper

@with_message_cleanup
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    response = await update.message.reply_text(
        "🤖 Бот расписания запущен!\n\n"
        "Доступные команды:\n"
        "/start - информация о боте\n" 
        "/today - расписание на сегодня\n"
        "/tomorrow - расписание на завтра\n"
        "/week - расписание на всю неделю\n"
        "/day <день> - расписание на конкретный день\n"
        "/update - принудительно отправить расписание на завтра\n"
        "/now - немедленная отправка расписания\n"
    )
    schedule_manager = ScheduleManager()
    schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)

@with_message_cleanup
async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        today_date = datetime.date.today()
        day_name = get_day_name(today_date)
        week_type = get_week_type(today_date)
        message_text = format_schedule_message(day_name, week_type, today_date)
        response = await update.message.reply_text(message_text)
        schedule_manager = ScheduleManager()
        schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)
    except Exception as e:
        response = await update.message.reply_text(f"❌ Ошибка: {e}")
        schedule_manager = ScheduleManager()
        schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)

@with_message_cleanup
async def tomorrow_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tomorrow = get_tomorrow_date()
        day_name = get_day_name(tomorrow)
        week_type = get_week_type(tomorrow)
        message_text = format_schedule_message(day_name, week_type, tomorrow)
        response = await update.message.reply_text(message_text)
        schedule_manager = ScheduleManager()
        schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)
    except Exception as e:
        response = await update.message.reply_text(f"❌ Ошибка: {e}")
        schedule_manager = ScheduleManager()
        schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)

@with_message_cleanup
async def day_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            response = await update.message.reply_text(
                "❌ Укажите день недели!\n\n"
                "Примеры:\n/day понедельник\n/day вторник\n/day среда\n/day четверг\n/day пятница\n/day суббота\n/day воскресенье"
            )
            schedule_manager = ScheduleManager()
            schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)
            return

        day_input = " ".join(context.args).lower()
        day_mapping = {'понедельник': 'monday', 'вторник': 'tuesday', 'среда': 'wednesday', 'среду': 'wednesday',
                       'четверг': 'thursday', 'пятница': 'friday', 'пятницу': 'friday', 'суббота': 'saturday',
                       'субботу': 'saturday', 'воскресенье': 'sunday'}
        english_day = day_mapping.get(day_input)
        if not english_day:
            response = await update.message.reply_text("❌ Неверный день недели!")
            schedule_manager = ScheduleManager()
            schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)
            return
        
        target_date = get_next_weekday(english_day)
        week_type = get_week_type(target_date)
        message_text = format_schedule_message(english_day, week_type, target_date)
        response = await update.message.reply_text(message_text)
        schedule_manager = ScheduleManager()
        schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)
    except Exception as e:
        response = await update.message.reply_text(f"❌ Ошибка: {e}")
        schedule_manager = ScheduleManager()
        schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)

@with_message_cleanup
async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        today = datetime.date.today()
        week_type = get_week_type(today)
        message_text = "📅 Расписание на неделю\n\n"
        days_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        for english_day in days_order:
            day_date = get_next_weekday(english_day, include_today=True)
            day_ru = get_russian_day(english_day)
            lessons = SCHEDULE[week_type].get(english_day, []) if SCHEDULE else []
            if lessons:
                message_text += f"**{day_ru}** ({day_date.strftime('%d.%m.%Y')}):\n"
                lessons_by_time = {}
                for lesson in lessons:
                    time_key = lesson['time']
                    if time_key not in lessons_by_time:
                        lessons_by_time[time_key] = []
                    lessons_by_time[time_key].append(lesson)
                for time_key in sorted(lessons_by_time.keys()):
                    time_lessons = lessons_by_time[time_key]
                    if len(time_lessons) == 1:
                        lesson = time_lessons[0]
                        subject_info = lesson['subject']
                        if lesson.get('groups'):
                            subject_info += f" ({lesson['groups'][0]})"
                        message_text += f"  ⏰ {time_key} - {subject_info}\n"
                    else:
                        if all(lesson['subject'] == time_lessons[0]['subject'] for lesson in time_lessons):
                            subject_name = time_lessons[0]['subject']
                        else:
                            subject_names = [lesson['subject'] for lesson in time_lessons]
                            subject_name = " / ".join(subject_names)
                        message_text += f"  ⏰ {time_key} - {subject_name}\n"
                message_text += "\n"
            else:
                message_text += f"**{day_ru}**: 🎉 Выходной\n\n"
        message_text += f"📊 Текущая неделя: {'1-я' if week_type == 'even' else '2-я'}"
        
        if len(message_text) > 4000:
            parts = []
            current_part = ""
            lines = message_text.split('\n')
            for line in lines:
                if len(current_part + line + '\n') > 4000:
                    parts.append(current_part)
                    current_part = line + '\n'
                else:
                    current_part += line + '\n'
            if current_part:
                parts.append(current_part)
            for i, part in enumerate(parts):
                response = await update.message.reply_text(part, parse_mode='Markdown')
                if i == 0:
                    schedule_manager = ScheduleManager()
                    schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)
        else:
            response = await update.message.reply_text(message_text, parse_mode='Markdown')
            schedule_manager = ScheduleManager()
            schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)
    except Exception as e:
        response = await update.message.reply_text(f"❌ Ошибка: {e}")
        schedule_manager = ScheduleManager()
        schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)

@with_message_cleanup
async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now()
    tomorrow = get_tomorrow_date()
    debug_info = (
        f"🕐 Текущее время: {now.strftime('%d.%m.%Y %H:%M:%S')}\n"
        f"📅 Завтра: {tomorrow.strftime('%d.%m.%Y')}\n"
        f"📊 День недели: {get_russian_day(get_day_name(tomorrow))}\n"
        f"🔢 Неделя: {'1-я' if get_week_type(tomorrow) == 'even' else '2-я'}\n"
        f"⏰ Время отправки: 10:00\n"
        f"📍 Чат: {CHAT_ID}\n"
        f"📚 Топик: {TOPIC_ID}"
    )
    response = await update.message.reply_text(debug_info)
    schedule_manager = ScheduleManager()
    schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)

@with_message_cleanup
async def jobs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        job_queue = context.application.job_queue
        if job_queue:
            jobs = job_queue.jobs()
            message = "📋 Активные задания JobQueue:\n" + "\n".join(
                f"{i+1}. {job.name}: {job.next_t.strftime('%d.%m.%Y %H:%M:%S') if job.next_t else 'Не запланировано'}"
                for i, job in enumerate(jobs)
            ) if jobs else "❌ Нет активных заданий"
        else:
            message = "❌ JobQueue недоступен"
        response = await update.message.reply_text(message)
        schedule_manager = ScheduleManager()
        schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)
    except Exception as e:
        response = await update.message.reply_text(f"❌ Ошибка: {e}")
        schedule_manager = ScheduleManager()
        schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)

@with_message_cleanup
async def now_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        print("🚀 Немедленная отправка расписания...")
        await send_tomorrow_schedule(context)
        response = await update.message.reply_text("✅ Расписание отправлено прямо сейчас!")
        schedule_manager = ScheduleManager()
        schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)
    except Exception as e:
        response = await update.message.reply_text(f"❌ Ошибка: {e}")
        schedule_manager = ScheduleManager()
        schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)

@with_message_cleanup
async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(chat_id=CHAT_ID, message_thread_id=TOPIC_ID, text="✅ Тестовое сообщение от бота расписания!\n\nБот работает корректно.")
        response = await update.message.reply_text("✅ Тестовое сообщение отправлено в группу!")
        schedule_manager = ScheduleManager()
        schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)
    except Exception as e:
        response = await update.message.reply_text(f"❌ Ошибка отправки: {e}")
        schedule_manager = ScheduleManager()
        schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)

@with_message_cleanup
async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await send_tomorrow_schedule(context)
        response = await update.message.reply_text("✅ Расписание на завтра отправлено в группу!")
        schedule_manager = ScheduleManager()
        schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)
    except Exception as e:
        response = await update.message.reply_text(f"❌ Ошибка: {e}")
        schedule_manager = ScheduleManager()
        schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)

@with_message_cleanup
async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        schedule_manager = ScheduleManager()
        tomorrow_str = get_tomorrow_date().strftime("%Y-%m-%d")
        await delete_previous_message(context, schedule_manager, tomorrow_str)
        response = await update.message.reply_text("✅ Расписание на завтра удалено!")
        schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)
    except Exception as e:
        response = await update.message.reply_text(f"❌ Ошибка: {e}")
        schedule_manager = ScheduleManager()
        schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)

async def delete_previous_message(context, schedule_manager, date_str):
    previous_message = schedule_manager.get_previous_message(date_str)
    if previous_message:
        try:
            await context.bot.delete_message(chat_id=previous_message[1], message_id=previous_message[0])
            print(f"✅ Удалено предыдущее сообщение для {date_str}")
        except BadRequest as e:
            print(f"⚠️ Не удалось удалить сообщение: {e}")
        finally:
            schedule_manager.delete_message_record(date_str)

async def send_tomorrow_schedule(context: ContextTypes.DEFAULT_TYPE):
    try:
        print(f"🕕 [{datetime.datetime.now()}] Запуск автоотправки расписания...")
        schedule_manager = ScheduleManager()
        tomorrow = get_tomorrow_date()
        tomorrow_str = tomorrow.strftime("%Y-%m-%d")
        day_name = get_day_name(tomorrow)
        week_type = get_week_type(tomorrow)
        message_text = format_schedule_message(day_name, week_type, tomorrow)
        await delete_previous_message(context, schedule_manager, tomorrow_str)
        message = await context.bot.send_message(chat_id=CHAT_ID, message_thread_id=TOPIC_ID, text=message_text)
        schedule_manager.save_message_info(tomorrow_str, message.message_id, CHAT_ID, TOPIC_ID)
        print(f"✅ Автоотправка: расписание отправлено для {tomorrow}")
    except Exception as e:
        print(f"❌ Ошибка при автоотправке расписания: {e}")

def setup_job_queue(application):
    job_queue = application.job_queue
    if job_queue is None:
        print("❌ JobQueue недоступен")
        return
    target_time = datetime.time(hour=10, minute=0, second=0)
    job_queue.run_daily(callback=send_tomorrow_schedule, time=target_time, days=tuple(range(7)), name="daily_schedule")
    print(f"✅ JobQueue настроен на ежедневную отправку в {target_time}")

def main():
    global SCHEDULE
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
    print("🚀 Запуск бота расписания...")
    
    try:
        load_schedule()  # ← Единственная точка загрузки
        application = Application.builder().token(BOT_TOKEN).build()
        
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("today", today_command))
        application.add_handler(CommandHandler("tomorrow", tomorrow_command))
        application.add_handler(CommandHandler("day", day_command))
        application.add_handler(CommandHandler("week", week_command))
        application.add_handler(CommandHandler("test", test_command))
        application.add_handler(CommandHandler("update", update_command))
        application.add_handler(CommandHandler("clear", clear_command))
        application.add_handler(CommandHandler("now", now_command))
        application.add_handler(CommandHandler("debug", debug_command))
        application.add_handler(CommandHandler("jobs", jobs_command))
        
        setup_job_queue(application)
        
        print("=" * 50)
        print("🤖 Бот успешно запущен!")
        print(f"📍 ID чата: {CHAT_ID}")
        print(f"📚 ID топика: {TOPIC_ID}")
        print("⏰ Автоотправка настроена на 10:00")
        print("=" * 50)
        print("Команды для тестирования:")
        print("/now - немедленная отправка")
        print("/debug - отладочная информация")
        print("/test - тест связи с группой")
        print("/day <день> - расписание на любой день")
        print("/week - расписание на всю неделю")
        print("=" * 50)
        
        application.run_polling()
        
    except Exception as e:
        print(f"❌ Критическая ошибка при запуске бота: {e}")

if __name__ == "__main__":
    main()