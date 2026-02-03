import sqlite3
import datetime
import logging
import asyncio
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update
from telegram.error import BadRequest

# === Настройки бота ===
CHAT_ID = -1002148833759
TOPIC_ID = 29
BOT_TOKEN = "6086143518:AAGnbv6OAjSyyahXETPjvVCyeZLeiVku5yA"

# === ВСТАВЬ РАСПИСАНИЕ ЗДЕСЬ ===
SCHEDULE = {
  "even": {
    "monday": [],
    "tuesday": [
      {
        "time": "08:00-09:30",
        "subject": "ЛОГИЧЕСКОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лабораторная",
        "teacher": "Шкаберина Г. Ш.",
        "room": "корп. \"Ал\" каб. \"213\"",
        "groups": []
      },
      {
        "time": "09:40-11:10",
        "subject": "ПРОЕКТИРОВАНИЕ ЧЕЛОВЕКО-МАШИННОГО ИНТЕРФЕЙСА",
        "type": "лабораторная",
        "teacher": "Гриценко Е. М.",
        "room": "корп. \"Ал\" каб. \"109\"",
        "groups": []
      },
      {
        "time": "11:30-13:00",
        "subject": "МАТЕМАТИЧЕСКАЯ ЛОГИКА И ТЕОРИЯ АЛГОРИТМОВ",
        "type": "лекция",
        "teacher": "Иванилова Т. Н.",
        "room": "корп. \"Ал\" каб. \"212\"",
        "groups": []
      },
      {
        "time": "13:30-15:00",
        "subject": "ЛОГИЧЕСКОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лекция",
        "teacher": "Товбис Е. М.",
        "room": "корп. \"Ал\" каб. \"212\"",
        "groups": []
      },
      {
        "time": "15:10-16:40",
        "subject": "ЛОГИЧЕСКОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лабораторная",
        "teacher": "Товбис Е. М.",
        "room": "корп. \"Ал\" каб. \"213\"",
        "groups": []
      },
      {
        "time": "16:50-18:20",
        "subject": "АРХИТЕКТУРА ЭВМ",
        "type": "лабораторная",
        "teacher": "Масаев С. Н.",
        "room": "корп. \"Ал\" каб. \"103\"",
        "groups": []
      }
    ],
    "wednesday": [
      {
        "time": "09:40-11:10",
        "subject": "ПРОФЕССИОНАЛЬНО-ПРИКЛАДНАЯ ФИЗИЧЕСКАЯ КУЛЬТУРА",
        "type": "практика",
        "teacher": "Мунгалов А. Ю.",
        "room": "корп. \"УСК\" каб. \"Бассейн\"",
        "groups": []
      },
      {
        "time": "11:30-13:00",
        "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лекция",
        "teacher": "Яровой С. В.",
        "room": "корп. \"Цл\" каб. \"213\"",
        "groups": []
      },
      {
        "time": "13:30-15:00",
        "subject": "АРХИТЕКТУРА ЭВМ",
        "type": "лабораторная",
        "teacher": "Масаев С. Н.",
        "room": "корп. \"Цл\" каб. \"203\"",
        "groups": [
          "2 подгруппа"
        ]
      },
      {
        "time": "13:30-15:00",
        "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лабораторная",
        "teacher": "Яровой С. В.",
        "room": "корп. \"Цл\" каб. \"204\"",
        "groups": [
          "1 подгруппа"
        ]
      },
      {
        "time": "15:10-16:40",
        "subject": "АРХИТЕКТУРА ЭВМ",
        "type": "лекция",
        "teacher": "Масаев С. Н.",
        "room": "корп. \"Цл\" каб. \"213\"",
        "groups": []
      }
    ],
    "thursday": [
      {
        "time": "09:40-11:10",
        "subject": "ТЕОРИЯ ВЕРОЯТНОСТЕЙ И МАТЕМАТИЧЕСКАЯ СТАТИСТИКА",
        "type": "практика",
        "teacher": "Ушанов С. В.",
        "room": "корп. \"Гл\" каб. \"414\"",
        "groups": []
      },
      {
        "time": "11:30-13:00",
        "subject": "ТЕОРИЯ ВЕРОЯТНОСТЕЙ И МАТЕМАТИЧЕСКАЯ СТАТИСТИКА",
        "type": "лекция",
        "teacher": "Ушанов С. В.",
        "room": "корп. \"Гл\" каб. \"414\"",
        "groups": []
      },
      {
        "time": "13:30-15:00",
        "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лекция",
        "teacher": "Якимов С. П.",
        "room": "корп. \"Ал\" каб. \"212\"",
        "groups": []
      },
      {
        "time": "15:10-16:40",
        "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лабораторная",
        "teacher": "Алехина А. Е.",
        "room": "корп. \"Гл\" каб. \"409\"",
        "groups": [
          "2 подгруппа"
        ]
      },
      {
        "time": "15:10-16:40",
        "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лабораторная",
        "teacher": "Якимов С. П.",
        "room": "корп. \"Ал\" каб. \"109\"",
        "groups": [
          "1 подгруппа"
        ]
      }
    ],
    "friday": [
      {
        "time": "09:40-11:10",
        "subject": "ПРОФЕССИОНАЛЬНО-ПРИКЛАДНАЯ ФИЗИЧЕСКАЯ КУЛЬТУРА",
        "type": "практика",
        "teacher": "Мунгалов А. Ю.",
        "room": "корп. \"УСК\" каб. \"Спортзал\"",
        "groups": []
      },
      {
        "time": "11:30-13:00",
        "subject": "ИНСТРУМЕНТАРИЙ ПРИНЯТИЯ РЕШЕНИЙ",
        "type": "лабораторная",
        "teacher": "Шкаберина Г. Ш.",
        "room": "корп. \"Ал\" каб. \"103\"",
        "groups": [
          "1 подгруппа"
        ]
      },
      {
        "time": "11:30-13:00",
        "subject": "МАТЕМАТИЧЕСКАЯ ЛОГИКА И ТЕОРИЯ АЛГОРИТМОВ",
        "type": "лабораторная",
        "teacher": "Иванилова Т. Н.",
        "room": "корп. \"Ал\" каб. \"215\"",
        "groups": [
          "2 подгруппа"
        ]
      },
      {
        "time": "13:30-15:00",
        "subject": "ИНСТРУМЕНТАРИЙ ПРИНЯТИЯ РЕШЕНИЙ",
        "type": "лабораторная",
        "teacher": "Шкаберина Г. Ш.",
        "room": "корп. \"Ал\" каб. \"103\"",
        "groups": [
          "2 подгруппа"
        ]
      },
      {
        "time": "13:30-15:00",
        "subject": "МАТЕМАТИЧЕСКАЯ ЛОГИКА И ТЕОРИЯ АЛГОРИТМОВ",
        "type": "лабораторная",
        "teacher": "Иванилова Т. Н.",
        "room": "корп. \"Ал\" каб. \"215\"",
        "groups": [
          "1 подгруппа"
        ]
      },
      {
        "time": "15:10-16:40",
        "subject": "ПРОЕКТИРОВАНИЕ ЧЕЛОВЕКО-МАШИННОГО ИНТЕРФЕЙСА",
        "type": "лабораторная",
        "teacher": "Гриценко Е. М.",
        "room": "корп. \"Ал\" каб. \"213\"",
        "groups": []
      }
    ],
    "saturday": [
      {
        "time": "09:40-11:10",
        "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лабораторная",
        "teacher": "Ефимов Е. А.",
        "room": "корп. \"Гл\" каб. \"407а\"",
        "groups": []
      },
      {
        "time": "11:30-13:00",
        "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лабораторная",
        "teacher": "Ефимов Е. А.",
        "room": "корп. \"Гл\" каб. \"407а\"",
        "groups": []
      }
    ],
    "sunday": []
  },
  "odd": {
    "monday": [],
    "tuesday": [
      {
        "time": "08:00-09:30",
        "subject": "ИНСТРУМЕНТАРИЙ ПРИНЯТИЯ РЕШЕНИЙ",
        "type": "лабораторная",
        "teacher": "Шкаберина Г. Ш.",
        "room": "корп. \"Ал\" каб. \"213\"",
        "groups": []
      },
      {
        "time": "09:40-11:10",
        "subject": "ПРОЕКТИРОВАНИЕ ЧЕЛОВЕКО-МАШИННОГО ИНТЕРФЕЙСА",
        "type": "лабораторная",
        "teacher": "Гриценко Е. М.",
        "room": "корп. \"Ал\" каб. \"109\"",
        "groups": [
          "2 подгруппа"
        ]
      },
      {
        "time": "09:40-11:10",
        "subject": "ИНСТРУМЕНТАРИЙ ПРИНЯТИЯ РЕШЕНИЙ",
        "type": "лабораторная",
        "teacher": "Шкаберина Г. Ш.",
        "room": "корп. \"Ал\" каб. \"213\"",
        "groups": [
          "1 подгруппа"
        ]
      },
      {
        "time": "11:30-13:00",
        "subject": "ИНСТРУМЕНТАРИЙ ПРИНЯТИЯ РЕШЕНИЙ",
        "type": "лекция",
        "teacher": "Шкаберина Г. Ш.",
        "room": "корп. \"Ал\" каб. \"212\"",
        "groups": []
      },
      {
        "time": "13:30-15:00",
        "subject": "АРХИТЕКТУРА ЭВМ",
        "type": "лабораторная",
        "teacher": "Масаев С. Н.",
        "room": "корп. \"Гл\" каб. \"407а\"",
        "groups": [
          "1 подгруппа"
        ]
      },
      {
        "time": "13:30-15:00",
        "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лабораторная",
        "teacher": "Алехина А. Е.",
        "room": "корп. \"Гл\" каб. \"409\"",
        "groups": [
          "2 подгруппа"
        ]
      }
    ],
    "wednesday": [
      {
        "time": "09:40-11:10",
        "subject": "ПРОФЕССИОНАЛЬНО-ПРИКЛАДНАЯ ФИЗИЧЕСКАЯ КУЛЬТУРА",
        "type": "практика",
        "teacher": "Мунгалов А. Ю.",
        "room": "корп. \"УСК\" каб. \"Бассейн\"",
        "groups": []
      },
      {
        "time": "11:30-13:00",
        "subject": "ТЕОРИЯ ВЕРОЯТНОСТЕЙ И МАТЕМАТИЧЕСКАЯ СТАТИСТИКА",
        "type": "лекция",
        "teacher": "Ушанов С. В.",
        "room": "корп. \"Гл\" каб. \"414\"",
        "groups": []
      },
      {
        "time": "13:30-15:00",
        "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лекция",
        "teacher": "Якимов С. П.",
        "room": "корп. \"Ал\" каб. \"212\"",
        "groups": []
      },
      {
        "time": "15:10-16:40",
        "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лабораторная",
        "teacher": "Яровой С. В.",
        "room": "корп. \"Гл\" каб. \"407\"",
        "groups": []
      }
    ],
    "thursday": [
      {
        "time": "11:30-13:00",
        "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лекция",
        "teacher": "Яровой С. В.",
        "room": "корп. \"Цл\" каб. \"213\"",
        "groups": []
      },
      {
        "time": "13:30-15:00",
        "subject": "ПРОЕКТИРОВАНИЕ ЧЕЛОВЕКО-МАШИННОГО ИНТЕРФЕЙСА",
        "type": "лекция",
        "teacher": "Гриценко Е. М.",
        "room": "корп. \"Цл\" каб. \"213\"",
        "groups": []
      },
      {
        "time": "15:10-16:40",
        "subject": "ПРОЕКТИРОВАНИЕ ЧЕЛОВЕКО-МАШИННОГО ИНТЕРФЕЙСА",
        "type": "лабораторная",
        "teacher": "Гриценко Е. М.",
        "room": "корп. \"Гл\" каб. \"410\"",
        "groups": [
          "1 подгруппа"
        ]
      },
      {
        "time": "15:10-16:40",
        "subject": "АРХИТЕКТУРА ЭВМ",
        "type": "лабораторная",
        "teacher": "Масаев С. Н.",
        "room": "корп. \"Гл\" каб. \"409\"",
        "groups": [
          "2 подгруппа"
        ]
      },
      {
        "time": "16:50-18:20",
        "subject": "ТЕОРИЯ ВЕРОЯТНОСТЕЙ И МАТЕМАТИЧЕСКАЯ СТАТИСТИКА",
        "type": "практика",
        "teacher": "Ушанов С. В.",
        "room": "корп. \"Цл\" каб. \"212\"",
        "groups": []
      }
    ],
    "friday": [
      {
        "time": "09:40-11:10",
        "subject": "ПРОФЕССИОНАЛЬНО-ПРИКЛАДНАЯ ФИЗИЧЕСКАЯ КУЛЬТУРА",
        "type": "практика",
        "teacher": "Мунгалов А. Ю.",
        "room": "корп. \"УСК\" каб. \"Спортзал\"",
        "groups": []
      },
      {
        "time": "11:30-13:00",
        "subject": "ЛОГИЧЕСКОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лабораторная",
        "teacher": "Шкаберина Г. Ш.",
        "room": "корп. \"Ал\" каб. \"103\"",
        "groups": [
          "2 подгруппа"
        ]
      },
      {
        "time": "11:30-13:00",
        "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лабораторная",
        "teacher": "Якимов С. П.",
        "room": "корп. \"Ал\" каб. \"213\"",
        "groups": [
          "1 подгруппа"
        ]
      },
      {
        "time": "13:30-15:00",
        "subject": "ЛОГИЧЕСКОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лабораторная",
        "teacher": "Товбис Е. М.",
        "room": "корп. \"Ал\" каб. \"213\"",
        "groups": [
          "1 подгруппа"
        ]
      },
      {
        "time": "13:30-15:00",
        "subject": "МАТЕМАТИЧЕСКАЯ ЛОГИКА И ТЕОРИЯ АЛГОРИТМОВ",
        "type": "лабораторная",
        "teacher": "Иванилова Т. Н.",
        "room": "корп. \"Ал\" каб. \"215\"",
        "groups": [
          "2 подгруппа"
        ]
      },
      {
        "time": "15:10-16:40",
        "subject": "МАТЕМАТИЧЕСКАЯ ЛОГИКА И ТЕОРИЯ АЛГОРИТМОВ",
        "type": "лабораторная",
        "teacher": "Иванилова Т. Н.",
        "room": "корп. \"Ал\" каб. \"215\"",
        "groups": []
      }
    ],
    "saturday": [],
    "sunday": []
    }
  }

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
    emoji_map = {"лекция": "📚", "практика": "✏️", "лабораторная": "🔬"}
    return emoji_map.get(lesson_type, "📖")

def get_russian_day(english_day):
    days = {"monday": "Понедельник", "tuesday": "Вторник", "wednesday": "Среда", "thursday": "Четверг", "friday": "Пятница", "saturday": "Суббота", "sunday": "Воскресенье"}
    return days.get(english_day, english_day)

def get_day_name(date):
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    return days[date.weekday()]

def format_schedule_message(day_name, week_type, date):
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
    except Exception:
        pass

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
        "/now - немедленная отправка расписания\n"
    )
    schedule_manager = ScheduleManager()
    schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)

@with_message_cleanup
async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today_date = datetime.date.today()
    day_name = get_day_name(today_date)
    week_type = get_week_type(today_date)
    message_text = format_schedule_message(day_name, week_type, today_date)
    response = await update.message.reply_text(message_text)
    schedule_manager = ScheduleManager()
    schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)

@with_message_cleanup
async def tomorrow_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tomorrow = get_tomorrow_date()
    day_name = get_day_name(tomorrow)
    week_type = get_week_type(tomorrow)
    message_text = format_schedule_message(day_name, week_type, tomorrow)
    response = await update.message.reply_text(message_text)
    schedule_manager = ScheduleManager()
    schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)

@with_message_cleanup
async def day_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        response = await update.message.reply_text(
            "❌ Укажите день недели!\n\n"
            "Примеры:\n/day понедельник\n/day вторник\n/day среда\n/day четверг\n/day пятница\n/day суббота\n/day воскресенье"
        )
        schedule_manager = ScheduleManager()
        schedule_manager.save_bot_message(update.effective_chat.id, update.effective_user.id, response.message_id)
        return

    day_input = " ".join(context.args).lower()
    day_mapping = {
        'понедельник': 'monday', 'вторник': 'tuesday', 'среда': 'wednesday', 'среду': 'wednesday',
        'четверг': 'thursday', 'пятница': 'friday', 'пятницу': 'friday', 'суббота': 'saturday',
        'субботу': 'saturday', 'воскресенье': 'sunday'
    }
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

@with_message_cleanup
async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.date.today()
    week_type = get_week_type(today)
    message_text = "📅 Расписание на неделю\n\n"
    days_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for english_day in days_order:
        day_date = get_next_weekday(english_day, include_today=True)
        day_ru = get_russian_day(english_day)
        lessons = SCHEDULE[week_type].get(english_day, [])
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

@with_message_cleanup
async def now_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("🚀 Немедленная отправка расписания...")
    await send_tomorrow_schedule(context)
    response = await update.message.reply_text("✅ Расписание отправлено прямо сейчас!")
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

async def send_tomorrow_schedule(context: ContextTypes.DEFAULT_TYPE):
    try:
        schedule_manager = ScheduleManager()
        tomorrow = get_tomorrow_date()
        tomorrow_str = tomorrow.strftime("%Y-%m-%d")
        day_name = get_day_name(tomorrow)
        week_type = get_week_type(tomorrow)
        message_text = format_schedule_message(day_name, week_type, tomorrow)
        previous_message = schedule_manager.get_previous_message(tomorrow_str)
        if previous_message:
            try:
                await context.bot.delete_message(chat_id=previous_message[1], message_id=previous_message[0])
            except:
                pass
            schedule_manager.delete_message_record(tomorrow_str)
        message = await context.bot.send_message(chat_id=CHAT_ID, message_thread_id=TOPIC_ID, text=message_text)
        schedule_manager.save_message_info(tomorrow_str, message.message_id, CHAT_ID, TOPIC_ID)
    except Exception as e:
        print(f"❌ Ошибка при автоотправке расписания: {e}")

def main():
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
    print("🚀 Запуск бота расписания...")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("tomorrow", tomorrow_command))
    application.add_handler(CommandHandler("day", day_command))
    application.add_handler(CommandHandler("week", week_command))
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(CommandHandler("now", now_command))
    
    print("=" * 50)
    print("🤖 Бот успешно запущен!")
    print(f"📍 ID чата: {CHAT_ID}")
    print(f"📚 ID топика: {TOPIC_ID}")
    print("=" * 50)
    
    application.run_polling()

if __name__ == "__main__":
    main()
