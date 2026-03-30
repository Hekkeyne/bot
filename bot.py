import sqlite3
import datetime
import logging
import asyncio
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update
from telegram.error import BadRequest

BOT_TOKEN = "6086143518:AAHQhYYXttkZPxQ2J9HNmS7CoFicTjPn7-4"
FULL_SCHEDULE_LINK = "https://timetable.pallada.sibsau.ru/timetable/group/13922"
FOOTER_LINK = f'\n\n<a href="{FULL_SCHEDULE_LINK}">Полное расписание на сайте</a>'

SCHEDULE = {
  "odd": {
    "monday": [],
    "tuesday": [
      {
        "time": "08:00-09:30",
        "subject": "ЛОГИЧЕСКОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лабораторная",
        "teacher": "Шкаберина Г. Ш.",
        "room": "корп. \"Ал\" каб. \"213\"",
        "groups": [
          "2 подгруппа"
        ]
      },
      {
        "time": "09:40-11:10",
        "subject": "ПРОЕКТИРОВАНИЕ ЧЕЛОВЕКО-МАШИННОГО ИНТЕРФЕЙСА",
        "type": "лабораторная",
        "teacher": "-",
        "room": "корп. \"Ал\" каб. \"109\"",
        "groups": [
          "2 подгруппа"
        ]
      },
      {
        "time": "11:30-13:00",
        "subject": "МАТЕМАТИЧЕСКАЯ ЛОГИКА И ТЕОРИЯ АЛГОРИТМОВ",
        "type": "лекция",
        "teacher": "Иванилова Т. Н.",
        "room": "корп. \"Ал\" каб. \"212\"",
        "groups": [
          "все"
        ]
      },
      {
        "time": "13:30-15:00",
        "subject": "ЛОГИЧЕСКОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лекция",
        "teacher": "Товбис Е. М.",
        "room": "корп. \"Ал\" каб. \"212\"",
        "groups": [
          "все"
        ]
      },
      {
        "time": "15:10-16:40",
        "subject": "ЛОГИЧЕСКОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лабораторная",
        "teacher": "Товбис Е. М.",
        "room": "корп. \"Ал\" каб. \"213\"",
        "groups": [
          "1 подгруппа"
        ]
      },
      {
        "time": "16:50-18:20",
        "subject": "АРХИТЕКТУРА ЭВМ",
        "type": "лабораторная",
        "teacher": "Масаев С. Н.",
        "room": "корп. \"Ал\" каб. \"103\"",
        "groups": [
          "1 подгруппа"
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
        "groups": [
          "все"
        ]
      },
      {
        "time": "11:30-13:00",
        "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лекция",
        "teacher": "Яровой С. В.",
        "room": "корп. \"Цл\" каб. \"213\"",
        "groups": [
          "все"
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
        "time": "15:10-16:40",
        "subject": "АРХИТЕКТУРА ЭВМ",
        "type": "лекция",
        "teacher": "Масаев С. Н.",
        "room": "корп. \"Цл\" каб. \"213\"",
        "groups": [
          "все"
        ]
      }
    ],
    "thursday": [
      {
        "time": "09:40-11:10",
        "subject": "ТЕОРИЯ ВЕРОЯТНОСТЕЙ И МАТЕМАТИЧЕСКАЯ СТАТИСТИКА",
        "type": "практика",
        "teacher": "Ушанов С. В.",
        "room": "корп. \"Гл\" каб. \"414\"",
        "groups": [
          "все"
        ]
      },
      {
        "time": "11:30-13:00",
        "subject": "ТЕОРИЯ ВЕРОЯТНОСТЕЙ И МАТЕМАТИЧЕСКАЯ СТАТИСТИКА",
        "type": "лекция",
        "teacher": "Ушанов С. В.",
        "room": "корп. \"Гл\" каб. \"414\"",
        "groups": [
          "все"
        ]
      },
      {
        "time": "13:30-15:00",
        "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лекция",
        "teacher": "Якимов С. П.",
        "room": "корп. \"Ал\" каб. \"212\"",
        "groups": [
          "все"
        ]
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
        "groups": [
          "все"
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
        "time": "15:10-16:40",
        "subject": "ПРОЕКТИРОВАНИЕ ЧЕЛОВЕКО-МАШИННОГО ИНТЕРФЕЙСА",
        "type": "лабораторная",
        "teacher": "-",
        "room": "корп. \"Ал\" каб. \"213\"",
        "groups": [
          "1 подгруппа"
        ]
      }
    ],
    "saturday": [],
    "sunday": []
  },
  "even": {
    "monday": [],
    "tuesday": [
      {
        "time": "08:00-09:30",
        "subject": "ИНСТРУМЕНТАРИЙ ПРИНЯТИЯ РЕШЕНИЙ",
        "type": "лабораторная",
        "teacher": "Шкаберина Г. Ш.",
        "room": "корп. \"Ал\" каб. \"213\"",
        "groups": [
          "2 подгруппа"
        ]
      },
      {
        "time": "09:40-11:10",
        "subject": "ПРОЕКТИРОВАНИЕ ЧЕЛОВЕКО-МАШИННОГО ИНТЕРФЕЙСА",
        "type": "лабораторная",
        "teacher": "-",
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
        "groups": [
          "все"
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
        "time": "15:10-16:40",
        "subject": "МАТЕМАТИЧЕСКАЯ ЛОГИКА И ТЕОРИЯ АЛГОРИТМОВ",
        "type": "лабораторная",
        "teacher": "Иванилова Т. Н.",
        "room": "корп. \"Ал\" каб. \"215\"",
        "groups": [
          "1 подгруппа"
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
        "groups": [
          "все"
        ]
      },
      {
        "time": "11:30-13:00",
        "subject": "ТЕОРИЯ ВЕРОЯТНОСТЕЙ И МАТЕМАТИЧЕСКАЯ СТАТИСТИКА",
        "type": "лекция",
        "teacher": "Ушанов С. В.",
        "room": "корп. \"Гл\" каб. \"414\"",
        "groups": [
          "все"
        ]
      },
      {
        "time": "13:30-15:00",
        "subject": "ОБЪЕКТНО-ОРИЕНТИРОВАННОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лекция",
        "teacher": "Якимов С. П.",
        "room": "корп. \"Ал\" каб. \"212\"",
        "groups": [
          "все"
        ]
      },
      {
        "time": "15:10-16:40",
        "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лабораторная",
        "teacher": "Яровой С. В.",
        "room": "корп. \"Гл\" каб. \"407\"",
        "groups": [
          "1 подгруппа"
        ]
      }
    ],
    "thursday": [
      {
        "time": "11:30-13:00",
        "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лекция",
        "teacher": "Яровой С. В.",
        "room": "корп. \"Цл\" каб. \"213\"",
        "groups": [
          "все"
        ]
      },
      {
        "time": "13:30-15:00",
        "subject": "ПРОЕКТИРОВАНИЕ ЧЕЛОВЕКО-МАШИННОГО ИНТЕРФЕЙСА",
        "type": "лекция",
        "teacher": "-",
        "room": "корп. \"Цл\" каб. \"213\"",
        "groups": [
          "все"
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
        "time": "15:10-16:40",
        "subject": "ПРОЕКТИРОВАНИЕ ЧЕЛОВЕКО-МАШИННОГО ИНТЕРФЕЙСА",
        "type": "лабораторная",
        "teacher": "-",
        "room": "корп. \"Гл\" каб. \"410\"",
        "groups": [
          "1 подгруппа"
        ]
      },
      {
        "time": "16:50-18:20",
        "subject": "ТЕОРИЯ ВЕРОЯТНОСТЕЙ И МАТЕМАТИЧЕСКАЯ СТАТИСТИКА",
        "type": "практика",
        "teacher": "Ушанов С. В.",
        "room": "корп. \"Цл\" каб. \"212\"",
        "groups": [
          "все"
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
        "groups": [
          "все"
        ]
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
      }
    ],
    "saturday": [
      {
        "time": "08:00-09:30",
        "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лабораторная",
        "teacher": "Ефимов Е. А.",
        "room": "корп. \"Ал\" каб. \"109\"",
        "groups": [
          "2 подгруппа"
        ]
      },
      {
        "time": "09:40-11:10",
        "subject": "ФУНКЦИОНАЛЬНОЕ ПРОГРАММИРОВАНИЕ",
        "type": "лабораторная",
        "teacher": "Ефимов Е. А.",
        "room": "корп. \"Ал\" каб. \"109\"",
        "groups": [
          "2 подгруппа"
        ]
      }
    ],
    "sunday": []
  }
}


class ScheduleManager:
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


def get_week_type(date=None):
    if date is None:
        date = datetime.date.today()
    return "even" if date.isocalendar()[1] % 2 == 0 else "odd"


def get_tomorrow():
    return datetime.date.today() + datetime.timedelta(days=1)


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
            msg += f"   {all_groups_lesson['subject']}\n"
            msg += f"   {get_emoji(all_groups_lesson['type'])} {all_groups_lesson['type'].upper()}\n"
            msg += f"   👨‍🏫 {all_groups_lesson['teacher']}\n"
            msg += f"   🏫 {room_formatted}\n\n"
        else:
            for i, lesson in enumerate(group):
                if i > 0:
                    msg += "\n" 
                room_formatted = lesson['room'].replace('"', "'")
                msg += f"   👥 {lesson['groups'][0]}:\n"
                msg += f"   {lesson['subject']}\n"
                msg += f"   {get_emoji(lesson['type'])} {lesson['type'].upper()}\n"
                msg += f"   👨‍🏫 {lesson['teacher']}\n"
                msg += f"   🏫 {room_formatted}\n"
            msg += "\n"
    
    return msg.strip() + FOOTER_LINK


async def cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = ScheduleManager()
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
        "🤖 Бот расписания\n\n"
        "Команды:\n"
        "/today — сегодня\n"
        "/tomorrow — завтра\n"
        "/week — вся неделя\n"
        "/day <день> — конкретный день\n"
        "/now — отправить сейчас"
        + FOOTER_LINK
    )
    msg = await update.message.reply_text(text, parse_mode='HTML')
    ScheduleManager().save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)


@with_cleanup
async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.date.today()
    msg = await update.message.reply_text(
        format_schedule(get_day_name(today), get_week_type(today), today), 
        parse_mode='HTML'
    )
    ScheduleManager().save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)


@with_cleanup
async def tomorrow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tmr = get_tomorrow()
    msg = await update.message.reply_text(
        format_schedule(get_day_name(tmr), get_week_type(tmr), tmr), 
        parse_mode='HTML'
    )
    ScheduleManager().save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)


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
            "Укажите день: /day понедельник" + FOOTER_LINK, 
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
    
    ScheduleManager().save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)


@with_cleanup
async def week_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.date.today()
    week_type = get_week_type(today)
    text = "📅 Расписание на неделю\n\n"
    
    for eng in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
        lessons = SCHEDULE[week_type].get(eng, [])
        ru = get_russian_day(eng)
        
        if lessons:
            time_groups = {}
            for lesson in lessons:
                time_groups.setdefault(lesson['time'], []).append(lesson)
            
            text += f"<b>{ru}</b>:\n"
            for time_slot in sorted(time_groups.keys(), key=lambda t: t.split('-')[0]):
                group = time_groups[time_slot]
                all_groups_lesson = next((l for l in group if l['groups'][0] == "все"), None)
                
                if all_groups_lesson:
                    text += f"  ⏰ {time_slot} | {all_groups_lesson['subject']} ({all_groups_lesson['type'].upper()})\n"
                else:
                    for lesson in group:
                        text += f"  ⏰ {time_slot} | {lesson['groups'][0]}: {lesson['subject']} ({lesson['type'].upper()})\n"
            text += "\n"
        else:
            text += f"<b>{ru}</b>: 🎉 Выходной\n\n"
    
    text += f"📊 Неделя: {'1-я' if week_type == 'even' else '2-я'}" + FOOTER_LINK
    msg = await update.message.reply_text(text, parse_mode='HTML')
    ScheduleManager().save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)


@with_cleanup
async def now_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        "Бот работает!" + FOOTER_LINK, 
        parse_mode='HTML'
    )
    ScheduleManager().save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)


def main():
    logging.basicConfig(level=logging.INFO)
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("today", today_cmd))
    app.add_handler(CommandHandler("tomorrow", tomorrow_cmd))
    app.add_handler(CommandHandler("day", day_cmd))
    app.add_handler(CommandHandler("week", week_cmd))
    app.add_handler(CommandHandler("now", now_cmd))
    
    print("Бот запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
