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

# === Расписание (вручную из PDF) ===
SCHEDULE = {
    "even": {
        "monday": [],
        "tuesday": [
            {"time": "08:00-09:30", "subject": "ЛОГИЧЕСКОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Шкаберина Г. Ш.", "room": "корп. \"Ал\" каб. \"213\"", "groups": ["2 подгруппа"]},
            {"time": "09:40-11:10", "subject": "ПРОЕКТИРОВАНИЕ ЧЕЛОВЕКО-МАШИННОГО ИНТЕРФЕЙСА", "type": "лабораторная", "teacher": "Гриценко Е. М.", "room": "корп. \"Ал\" каб. \"109\"", "groups": ["2 подгруппа"]},
            {"time": "11:30-13:00", "subject": "МАТЕМАТИЧЕСКАЯ ЛОГИКА И ТЕОРИЯ АЛГОРИТМОВ", "type": "лекция", "teacher": "Иванилова Т. Н.", "room": "корп. \"Ал\" каб. \"212\"", "groups": ["все"]},
            {"time": "13:30-15:00", "subject": "ЛОГИЧЕСКОЕ ПРОГРАММИРОВАНИЕ", "type": "лекция", "teacher": "Товбис Е. М.", "room": "корп. \"Ал\" каб. \"212\"", "groups": ["все"]},
            {"time": "15:10-16:40", "subject": "ЛОГИЧЕСКОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Товбис Е. М.", "room": "корп. \"Ал\" каб. \"213\"", "groups": ["1 подгруппа"]},
            {"time": "16:50-18:20", "subject": "АРХИТЕКТУРА ЭВМ", "type": "лабораторная", "teacher": "Масаев С. Н.", "room": "корп. \"Ал\" каб. \"103\"", "groups": ["1 подгруппа"]}
        ],
        "wednesday": [
            {"time": "09:40-11:10", "subject": "ПРОФЕССИОНАЛЬНО-ПРИКЛАДНАЯ ФИЗИЧЕСКАЯ КУЛЬТУРА", "type": "практика", "teacher": "Мунгалов А. Ю.", "room": "корп. \"УСК\" каб. \"Бассейн\"", "groups": ["все"]},
            {"time": "11:30-13:00", "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ", "type": "лекция", "teacher": "Яровой С. В.", "room": "корп. \"Цл\" каб. \"213\"", "groups": ["все"]},
            {"time": "13:30-15:00", "subject": "АРХИТЕКТУРА ЭВМ", "type": "лабораторная", "teacher": "Масаев С. Н.", "room": "корп. \"Цл\" каб. \"203\"", "groups": ["2 подгруппа"]},
            {"time": "13:30-15:00", "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Яровой С. В.", "room": "корп. \"Цл\" каб. \"204\"", "groups": ["1 подгруппа"]},
            {"time": "15:10-16:40", "subject": "АРХИТЕКТУРА ЭВМ", "type": "лекция", "teacher": "Масаев С. Н.", "room": "корп. \"Цл\" каб. \"213\"", "groups": ["все"]}
        ],
        "thursday": [
            {"time": "09:40-11:10", "subject": "ТЕОРИЯ ВЕРОЯТНОСТЕЙ И МАТЕМАТИЧЕСКАЯ СТАТИСТИКА", "type": "практика", "teacher": "Ушанов С. В.", "room": "корп. \"Гл\" каб. \"414\"", "groups": ["все"]},
            {"time": "11:30-13:00", "subject": "ТЕОРИЯ ВЕРОЯТНОСТЕЙ И МАТЕМАТИЧЕСКАЯ СТАТИСТИКА", "type": "лекция", "teacher": "Ушанов С. В.", "room": "корп. \"Гл\" каб. \"414\"", "groups": ["все"]},
            {"time": "13:30-15:00", "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ", "type": "лекция", "teacher": "Якимов С. П.", "room": "корп. \"Ал\" каб. \"212\"", "groups": ["все"]},
            {"time": "15:10-16:40", "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Алехина А. Е.", "room": "корп. \"Гл\" каб. \"409\"", "groups": ["2 подгруппа"]},
            {"time": "15:10-16:40", "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Якимов С. П.", "room": "корп. \"Ал\" каб. \"109\"", "groups": ["1 подгруппа"]}
        ],
        "friday": [
            {"time": "09:40-11:10", "subject": "ПРОФЕССИОНАЛЬНО-ПРИКЛАДНАЯ ФИЗИЧЕСКАЯ КУЛЬТУРА", "type": "практика", "teacher": "Мунгалов А. Ю.", "room": "корп. \"УСК\" каб. \"Спортзал\"", "groups": ["все"]},
            {"time": "11:30-13:00", "subject": "ИНСТРУМЕНТАРИЙ ПРИНЯТИЯ РЕШЕНИЙ", "type": "лабораторная", "teacher": "Шкаберина Г. Ш.", "room": "корп. \"Ал\" каб. \"103\"", "groups": ["1 подгруппа"]},
            {"time": "11:30-13:00", "subject": "МАТЕМАТИЧЕСКАЯ ЛОГИКА И ТЕОРИЯ АЛГОРИТМОВ", "type": "лабораторная", "teacher": "Иванилова Т. Н.", "room": "корп. \"Ал\" каб. \"215\"", "groups": ["2 подгруппа"]},
            {"time": "13:30-15:00", "subject": "ИНСТРУМЕНТАРИЙ ПРИНЯТИЯ РЕШЕНИЙ", "type": "лабораторная", "teacher": "Шкаберина Г. Ш.", "room": "корп. \"Ал\" каб. \"103\"", "groups": ["2 подгруппа"]},
            {"time": "13:30-15:00", "subject": "МАТЕМАТИЧЕСКАЯ ЛОГИКА И ТЕОРИЯ АЛГОРИТМОВ", "type": "лабораторная", "teacher": "Иванилова Т. Н.", "room": "корп. \"Ал\" каб. \"215\"", "groups": ["1 подгруппа"]},
            {"time": "15:10-16:40", "subject": "ПРОЕКТИРОВАНИЕ ЧЕЛОВЕКО-МАШИННОГО ИНТЕРФЕЙСА", "type": "лабораторная", "teacher": "Гриценко Е. М.", "room": "корп. \"Ал\" каб. \"213\"", "groups": ["1 подгруппа"]}
        ],
        "saturday": [
            {"time": "09:40-11:10", "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Ефимов Е. А.", "room": "корп. \"Гл\" каб. \"407а\"", "groups": ["2 подгруппа"]},
            {"time": "11:30-13:00", "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Ефимов Е. А.", "room": "корп. \"Гл\" каб. \"407а\"", "groups": ["2 подгруппа"]}
        ],
        "sunday": []
    },
    "odd": {
        "monday": [],
        "tuesday": [
            {"time": "08:00-09:30", "subject": "ИНСТРУМЕНТАРИЙ ПРИНЯТИЯ РЕШЕНИЙ", "type": "лабораторная", "teacher": "Шкаберина Г. Ш.", "room": "корп. \"Ал\" каб. \"213\"", "groups": ["2 подгруппа"]},
            {"time": "09:40-11:10", "subject": "ПРОЕКТИРОВАНИЕ ЧЕЛОВЕКО-МАШИННОГО ИНТЕРФЕЙСА", "type": "лабораторная", "teacher": "Гриценко Е. М.", "room": "корп. \"Ал\" каб. \"109\"", "groups": ["2 подгруппа"]},
            {"time": "09:40-11:10", "subject": "ИНСТРУМЕНТАРИЙ ПРИНЯТИЯ РЕШЕНИЙ", "type": "лабораторная", "teacher": "Шкаберина Г. Ш.", "room": "корп. \"Ал\" каб. \"213\"", "groups": ["1 подгруппа"]},
            {"time": "11:30-13:00", "subject": "ИНСТРУМЕНТАРИЙ ПРИНЯТИЯ РЕШЕНИЙ", "type": "лекция", "teacher": "Шкаберина Г. Ш.", "room": "корп. \"Ал\" каб. \"212\"", "groups": ["все"]},
            {"time": "13:30-15:00", "subject": "АРХИТЕКТУРА ЭВМ", "type": "лабораторная", "teacher": "Масаев С. Н.", "room": "корп. \"Гл\" каб. \"407а\"", "groups": ["1 подгруппа"]},
            {"time": "13:30-15:00", "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Алехина А. Е.", "room": "корп. \"Гл\" каб. \"409\"", "groups": ["2 подгруппа"]}
        ],
        "wednesday": [
            {"time": "09:40-11:10", "subject": "ПРОФЕССИОНАЛЬНО-ПРИКЛАДНАЯ ФИЗИЧЕСКАЯ КУЛЬТУРА", "type": "практика", "teacher": "Мунгалов А. Ю.", "room": "корп. \"УСК\" каб. \"Бассейн\"", "groups": ["все"]},
            {"time": "11:30-13:00", "subject": "ТЕОРИЯ ВЕРОЯТНОСТЕЙ И МАТЕМАТИЧЕСКАЯ СТАТИСТИКА", "type": "лекция", "teacher": "Ушанов С. В.", "room": "корп. \"Гл\" каб. \"414\"", "groups": ["все"]},
            {"time": "13:30-15:00", "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ", "type": "лекция", "teacher": "Якимов С. П.", "room": "корп. \"Ал\" каб. \"212\"", "groups": ["все"]},
            {"time": "15:10-16:40", "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Яровой С. В.", "room": "корп. \"Гл\" каб. \"407\"", "groups": ["1 подгруппа"]}
        ],
        "thursday": [
            {"time": "11:30-13:00", "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ", "type": "лекция", "teacher": "Яровой С. В.", "room": "корп. \"Цл\" каб. \"213\"", "groups": ["все"]},
            {"time": "13:30-15:00", "subject": "ПРОЕКТИРОВАНИЕ ЧЕЛОВЕКО-МАШИННОГО ИНТЕРФЕЙСА", "type": "лекция", "teacher": "Гриценко Е. М.", "room": "корп. \"Цл\" каб. \"213\"", "groups": ["все"]},
            {"time": "15:10-16:40", "subject": "ПРОЕКТИРОВАНИЕ ЧЕЛОВЕКО-МАШИННОГО ИНТЕРФЕЙСА", "type": "лабораторная", "teacher": "Гриценко Е. М.", "room": "корп. \"Гл\" каб. \"410\"", "groups": ["1 подгруппа"]},
            {"time": "15:10-16:40", "subject": "АРХИТЕКТУРА ЭВМ", "type": "лабораторная", "teacher": "Масаев С. Н.", "room": "корп. \"Гл\" каб. \"409\"", "groups": ["2 подгруппа"]},
            {"time": "16:50-18:20", "subject": "ТЕОРИЯ ВЕРОЯТНОСТЕЙ И МАТЕМАТИЧЕСКАЯ СТАТИСТИКА", "type": "практика", "teacher": "Ушанов С. В.", "room": "корп. \"Цл\" каб. \"212\"", "groups": ["все"]}
        ],
        "friday": [
            {"time": "09:40-11:10", "subject": "ПРОФЕССИОНАЛЬНО-ПРИКЛАДНАЯ ФИЗИЧЕСКАЯ КУЛЬТУРА", "type": "практика", "teacher": "Мунгалов А. Ю.", "room": "корп. \"УСК\" каб. \"Спортзал\"", "groups": ["все"]},
            {"time": "11:30-13:00", "subject": "ЛОГИЧЕСКОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Шкаберина Г. Ш.", "room": "корп. \"Ал\" каб. \"103\"", "groups": ["2 подгруппа"]},
            {"time": "11:30-13:00", "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Якимов С. П.", "room": "корп. \"Ал\" каб. \"213\"", "groups": ["1 подгруппа"]},
            {"time": "13:30-15:00", "subject": "ЛОГИЧЕСКОЕ ПРОГРАММИРОВАНИЕ", "type": "лабораторная", "teacher": "Товбис Е. М.", "room": "корп. \"Ал\" каб. \"213\"", "groups": ["1 подгруппа"]},
            {"time": "13:30-15:00", "subject": "МАТЕМАТИЧЕСКАЯ ЛОГИКА И ТЕОРИЯ АЛГОРИТМОВ", "type": "лабораторная", "teacher": "Иванилова Т. Н.", "room": "корп. \"Ал\" каб. \"215\"", "groups": ["2 подгруппа"]},
            {"time": "15:10-16:40", "subject": "МАТЕМАТИЧЕСКАЯ ЛОГИКА И ТЕОРИЯ АЛГОРИТМОВ", "type": "лабораторная", "teacher": "Иванилова Т. Н.", "room": "корп. \"Ал\" каб. \"215\"", "groups": ["1 подгруппа"]}
        ],
        "saturday": [],
        "sunday": []
    }
}

# === База данных ===
class ScheduleManager:
    def __init__(self, db_path="schedule_bot.db"):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS bot_messages (
                    id INTEGER PRIMARY KEY,
                    chat_id INTEGER,
                    user_id INTEGER,
                    message_id INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
    
    def save_bot_message(self, chat_id, user_id, message_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('DELETE FROM bot_messages WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
            conn.execute('INSERT INTO bot_messages (chat_id, user_id, message_id) VALUES (?, ?, ?)', (chat_id, user_id, message_id))
    
    def get_last_bot_message(self, chat_id, user_id):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute('SELECT message_id, chat_id FROM bot_messages WHERE chat_id = ? AND user_id = ? ORDER BY timestamp DESC LIMIT 1', (chat_id, user_id))
            return cur.fetchone()

# === Вспомогательные функции ===
def get_week_type(date=None):
    if date is None:
        date = datetime.date.today()
    return "even" if date.isocalendar()[1] % 2 == 0 else "odd"

def get_tomorrow_date():
    return datetime.date.today() + datetime.timedelta(days=1)

def get_russian_day(english_day):
    days = {"monday": "Понедельник", "tuesday": "Вторник", "wednesday": "Среда", "thursday": "Четверг", "friday": "Пятница", "saturday": "Суббота", "sunday": "Воскресенье"}
    return days.get(english_day, english_day)

def get_day_name(date):
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    return days[date.weekday()]

def get_type_emoji(lesson_type):
    return {"лекция": "📚", "практика": "✏️", "лабораторная": "🔬"}.get(lesson_type, "📖")

def format_schedule_message(day_name, week_type, date):
    lessons = SCHEDULE[week_type].get(day_name, [])
    if not lessons:
        return f"📅 Расписание на {get_russian_day(day_name)} ({date.strftime('%d.%m.%Y')})\n\n🎉 Выходной! Пар нет."

    message = f"📅 Расписание на {get_russian_day(day_name)} ({date.strftime('%d.%m.%Y')})\n"
    message += f"📊 Неделя: {'1-я' if week_type == 'even' else '2-я'}\n\n"

    for i, lesson in enumerate(lessons, 1):
        group_info = f" ({lesson['groups'][0]})" if lesson['groups'] and lesson['groups'][0] != "все" else ""
        message += f"{i}. ⏰ {lesson['time']} - {lesson['subject']}{group_info}\n"
        message += f"   {get_type_emoji(lesson['type'])} {lesson['type'].upper()}\n"
        message += f"   👨‍🏫 {lesson['teacher']}\n"
        message += f"   🏫 {lesson['room']}\n\n"
    return message

# === Обработчики ===
async def delete_previous_bot_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        prev = ScheduleManager().get_last_bot_message(update.effective_chat.id, update.effective_user.id)
        if prev:
            await context.bot.delete_message(chat_id=prev[1], message_id=prev[0])
    except:
        pass

def with_cleanup(handler):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await delete_previous_bot_message(update, context)
        return await handler(update, context)
    return wrapper

@with_cleanup
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 Бот расписания запущен!\n\n"
        "Команды:\n"
        "/today — сегодня\n"
        "/tomorrow — завтра\n"
        "/week — вся неделя\n"
        "/day <день> — конкретный день\n"
        "/now — отправить сейчас"
    )
    msg = await update.message.reply_text(text)
    ScheduleManager().save_bot_message(update.effective_chat.id, update.effective_user.id, msg.message_id)

@with_cleanup
async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.date.today()
    msg = await update.message.reply_text(format_schedule_message(get_day_name(today), get_week_type(today), today))
    ScheduleManager().save_bot_message(update.effective_chat.id, update.effective_user.id, msg.message_id)

@with_cleanup
async def tomorrow_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tomorrow = get_tomorrow_date()
    msg = await update.message.reply_text(format_schedule_message(get_day_name(tomorrow), get_week_type(tomorrow), tomorrow))
    ScheduleManager().save_bot_message(update.effective_chat.id, update.effective_user.id, msg.message_id)

@with_cleanup
async def day_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mapping = {'понедельник': 'monday', 'вторник': 'tuesday', 'среда': 'wednesday', 'четверг': 'thursday', 'пятница': 'friday', 'суббота': 'saturday', 'воскресенье': 'sunday'}
    day = mapping.get(" ".join(context.args).lower())
    if not day:
        msg = await update.message.reply_text("❌ Укажите день: /day понедельник")
    else:
        target = datetime.date.today()
        while get_day_name(target) != day:
            target += datetime.timedelta(days=1)
        msg = await update.message.reply_text(format_schedule_message(day, get_week_type(target), target))
    ScheduleManager().save_bot_message(update.effective_chat.id, update.effective_user.id, msg.message_id)

@with_cleanup
async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.date.today()
    week_type = get_week_type(today)
    text = "📅 Расписание на неделю\n\n"
    for eng in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
        lessons = SCHEDULE[week_type].get(eng, [])
        day_ru = get_russian_day(eng)
        if lessons:
            text += f"**{day_ru}**:\n"
            for lesson in lessons:
                group = f" ({lesson['groups'][0]})" if lesson['groups'] and lesson['groups'][0] != "все" else ""
                text += f"  ⏰ {lesson['time']} – {lesson['subject']}{group}\n"
            text += "\n"
        else:
            text += f"**{day_ru}**: 🎉 Выходной\n\n"
    text += f"📊 Неделя: {'1-я' if week_type == 'even' else '2-я'}"
    msg = await update.message.reply_text(text, parse_mode='Markdown')
    ScheduleManager().save_bot_message(update.effective_chat.id, update.effective_user.id, msg.message_id)

@with_cleanup
async def now_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tomorrow = get_tomorrow_date()
    msg = await context.bot.send_message(chat_id=CHAT_ID, message_thread_id=TOPIC_ID, text=format_schedule_message(get_day_name(tomorrow), get_week_type(tomorrow), tomorrow))
    await update.message.reply_text("✅ Расписание отправлено!")
    ScheduleManager().save_bot_message(update.effective_chat.id, update.effective_user.id, msg.message_id)

# === Запуск ===
def main():
    logging.basicConfig(level=logging.INFO)
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("tomorrow", tomorrow_command))
    app.add_handler(CommandHandler("day", day_command))
    app.add_handler(CommandHandler("week", week_command))
    app.add_handler(CommandHandler("now", now_command))
    print("✅ Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
