import sqlite3
import datetime
import logging
import requests
from bs4 import BeautifulSoup
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update
from telegram.error import BadRequest

# === Настройки бота ===
CHAT_ID = -1002148833759
TOPIC_ID = 29
BOT_TOKEN = "6086143518:AAHQhYYXttkZPxQ2J9HNmS7CoFicTjPn7-4"

# === Настройки расписания ===
GROUP_ID = 13922
URL = f"https://timetable.pallada.sibsau.ru/timetable/group/{GROUP_ID}"

# === Словари перевода (БЕЗ ПРОБЕЛОВ!) ===
DAY_RU_TO_EN = {
    "Понедельник": "monday",
    "Вторник": "tuesday",
    "Среда": "wednesday",
    "Четверг": "thursday",
    "Пятница": "friday",
    "Суббота": "saturday",
    "Воскресенье": "sunday"
}

DAY_EN_TO_RU = {v: k for k, v in DAY_RU_TO_EN.items()}

TYPE_MAP = {
    "Лекция": "лекция",
    "Практика": "практика",
    "Лабораторная работа": "лабораторная"
}

# === Глобальная переменная ===
SCHEDULE = None


def parse_timetable_from_html(html_text):
    """Парсит HTML-страницу расписания"""
    soup = BeautifulSoup(html_text, 'lxml')
    schedule = {"even": {}, "odd": {}}
    
    # Ищем вкладки недель: week_1_tab (нечётная), week_2_tab (чётная)
    week_tabs = soup.select('div[id^="week_"][id$="_tab"]')
    if not week_tabs:
        raise ValueError("Не найдены вкладки недель на странице")
    
    for tab in week_tabs:
        # Определяем тип недели: week_1 = odd, week_2 = even
        week_num = tab['id'].split('_')[1]
        key = "odd" if week_num == "2" else "even"
        
        # Инициализируем все дни недели
        for day_en in DAY_RU_TO_EN.values():
            schedule[key][day_en] = []
        
        # Обрабатываем каждый день
        days = tab.select('div.day')
        for day in days:
            # Получаем название дня (убираем "сегодня")
            name_elem = day.select_one('.name')
            if not name_elem:
                continue
            day_name_ru = name_elem.get_text(strip=True).replace("сегодня", "").strip()
            
            if day_name_ru not in DAY_RU_TO_EN:
                continue
            day_en = DAY_RU_TO_EN[day_name_ru]
            
            lessons = []
            lines = day.select('.line')
            
            for line in lines:
                # Время
                time_elem = line.select_one('.time')
                if not time_elem:
                    continue
                time_str = time_elem.get_text(strip=True).replace('\n', ' ')
                # Берём первую часть (08:00-09:30)
                time_clean = time_str.split()[0] if ' ' in time_str else time_str
                if len(time_clean) > 11:
                    time_clean = time_clean[:11]
                
                # Блоки с парами (исправленный селектор)
                blocks = line.select('.col-md-6, .col-md-12')
                if not blocks:
                    blocks = [line]
                
                for block in blocks:
                    # Предмет
                    subject_elem = block.select_one('span.name')
                    if not subject_elem:
                        continue
                    subject = subject_elem.get_text(strip=True)
                    
                    # Тип занятия
                    block_text = block.get_text()
                    if "(Лекция)" in block_text:
                        lesson_type = "лекция"
                    elif "(Практика)" in block_text:
                        lesson_type = "практика"
                    else:
                        lesson_type = "лабораторная"
                    
                    # Преподаватель
                    teacher_elem = block.select_one('a[href^="/timetable/professor/"]')
                    teacher = teacher_elem.get_text(strip=True) if teacher_elem else "—"
                    
                    # Аудитория
                    room_elem = block.select_one('a[title]')
                    room = room_elem.get_text(strip=True) if room_elem else "—"
                    
                    # === ПОДГРУППЫ: два формата ===
                    groups = []
                    
                    # Формат 1: <li class="bold num_pdgrp">1 подгруппа</li>
                    subgroup_elem = block.select_one('li.num_pdgrp')
                    if subgroup_elem:
                        subgroup_text = subgroup_elem.get_text(strip=True)
                        groups = [subgroup_text]
                    else:
                        # Формат 2: <li><i class="fa fa-paperclip"></i>2 подгруппа</li>
                        paperclip = block.select_one('i.fa-paperclip')
                        if paperclip and paperclip.parent:
                            parent_text = paperclip.parent.get_text(strip=True)
                            if parent_text and "подгруппа" in parent_text.lower():
                                groups = [parent_text]
                    
                    # Если подгруппа не найдена — пара для всех
                    if not groups:
                        groups = ["все"]
                    
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
    """Загружает расписание с сайта"""
    global SCHEDULE
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    print("📥 Загрузка расписания...")
    response = requests.get(URL, headers=headers)
    if response.status_code != 200:
        raise Exception(f"HTTP {response.status_code}")
    SCHEDULE = parse_timetable_from_html(response.text)
    print("✅ Расписание загружено!")


# === Менеджер базы данных ===
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
    
    def save_schedule_msg(self, date, msg_id, chat_id, thread_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO schedule_messages 
            (date, message_id, chat_id, message_thread_id)
            VALUES (?, ?, ?, ?)
        ''', (date, msg_id, chat_id, thread_id))
        conn.commit()
        conn.close()
    
    def get_schedule_msg(self, date):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT message_id, chat_id, message_thread_id FROM schedule_messages WHERE date = ?',
            (date,)
        )
        result = cursor.fetchone()
        conn.close()
        return result
    
    def delete_schedule_record(self, date):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM schedule_messages WHERE date = ?', (date,))
        conn.commit()
        conn.close()
    
    def save_bot_msg(self, chat_id, user_id, msg_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            'DELETE FROM bot_messages WHERE chat_id = ? AND user_id = ?',
            (chat_id, user_id)
        )
        cursor.execute(
            'INSERT INTO bot_messages (chat_id, user_id, message_id) VALUES (?, ?, ?)',
            (chat_id, user_id, msg_id)
        )
        conn.commit()
        conn.close()
    
    def get_last_bot_msg(self, chat_id, user_id):
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
    """Возвращает дату ближайшего указанного дня недели"""
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    target_idx = days.index(weekday)
    today = datetime.date.today()
    current_idx = today.weekday()
    days_ahead = target_idx - current_idx
    if days_ahead < 0 or (days_ahead == 0 and not include_today):
        days_ahead += 7
    return today + datetime.timedelta(days=days_ahead)


def get_week_type(date=None):
    """Возвращает 'even' для чётной недели, 'odd' для нечётной"""
    if date is None:
        date = datetime.date.today()
    week_num = date.isocalendar()[1]
    return "even" if week_num % 2 == 0 else "odd"


def get_tomorrow():
    return datetime.date.today() + datetime.timedelta(days=1)


def get_type_emoji(lesson_type):
    return {"лекция": "📚", "практика": "✏️", "лабораторная": "🔬"}.get(lesson_type, "📖")


def get_russian_day(eng):
    return DAY_EN_TO_RU.get(eng, eng)


def get_day_name(date):
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    return days[date.weekday()]


def format_schedule_message(day_name, week_type, date):
    """Форматирует расписание на один день"""
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
    
    # Группируем по времени
    by_time = {}
    for lesson in lessons:
        by_time.setdefault(lesson['time'], []).append(lesson)
    
    msg = f"📅 Расписание на {day_ru} ({date_str})\n"
    msg += f"📊 Неделя: {'1-я' if week_type == 'even' else '2-я'}\n\n"
    
    num = 1
    for time_slot in sorted(by_time.keys(), key=lambda t: t.split('-')[0]):
        group = by_time[time_slot]
        msg += f"{num}. ⏰ {time_slot}\n"
        
        # Если одна пара для всех
        if len(group) == 1 and group[0]['groups'][0] == "все":
            l = group[0]
            msg += f"   {l['subject']}\n"
            msg += f"   {get_type_emoji(l['type'])} {l['type'].upper()}\n"
            msg += f"   👨‍🏫 {l['teacher']}\n"
            msg += f"   🏫 {l['room']}\n\n"
        else:
            # Несколько подгрупп
            for i, l in enumerate(group):
                if i > 0:
                    msg += "\n"
                g = l['groups'][0] if l['groups'][0] != "все" else ""
                prefix = f"👥 {g}:\n" if g else ""
                msg += f"   {prefix}   {l['subject']}\n"
                msg += f"   {get_type_emoji(l['type'])} {l['type'].upper()}\n"
                msg += f"   👨‍🏫 {l['teacher']}\n"
                msg += f"   🏫 {l['room']}\n"
            msg += "\n"
        num += 1
    
    return msg.strip()


# === Декоратор для очистки старых сообщений ===
async def cleanup_bot_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        mgr = ScheduleManager()
        last = mgr.get_last_bot_msg(update.effective_chat.id, update.effective_user.id)
        if last:
            await context.bot.delete_message(chat_id=last[1], message_id=last[0])
    except BadRequest as e:
        if "message to delete not found" not in str(e):
            print(f"⚠️ Ошибка удаления: {e}")
    except Exception as e:
        print(f"⚠️ Ошибка: {e}")


def with_cleanup(handler):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await cleanup_bot_msg(update, context)
        return await handler(update, context)
    return wrapper


# === Обработчики команд ===
@with_cleanup
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 Бот расписания\n\n"
        "Команды:\n"
        "/today — сегодня\n"
        "/tomorrow — завтра\n"
        "/week — вся неделя\n"
        "/day <день> — конкретный день\n"
        "/now — отправить сейчас\n"
        "/update — принудительная отправка в группу"
    )
    msg = await update.message.reply_text(text)
    ScheduleManager().save_bot_msg(update.effective_chat.id, update.effective_user.id, msg.message_id)


@with_cleanup
async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.date.today()
    msg = await update.message.reply_text(
        format_schedule_message(get_day_name(today), get_week_type(today), today)
    )
    ScheduleManager().save_bot_msg(update.effective_chat.id, update.effective_user.id, msg.message_id)


@with_cleanup
async def tomorrow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tmr = get_tomorrow()
    msg = await update.message.reply_text(
        format_schedule_message(get_day_name(tmr), get_week_type(tmr), tmr)
    )
    ScheduleManager().save_bot_msg(update.effective_chat.id, update.effective_user.id, msg.message_id)


@with_cleanup
async def day_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mapping = {
        'понедельник': 'monday', 'вторник': 'tuesday', 'среда': 'wednesday',
        'четверг': 'thursday', 'пятница': 'friday', 'суббота': 'saturday', 'воскресенье': 'sunday'
    }
    arg = " ".join(context.args).lower() if context.args else ""
    day = mapping.get(arg)
    
    if not day:
        msg = await update.message.reply_text("❌ Укажите день: /day понедельник")
    else:
        target = get_next_weekday(day)
        msg = await update.message.reply_text(
            format_schedule_message(day, get_week_type(target), target)
        )
    ScheduleManager().save_bot_msg(update.effective_chat.id, update.effective_user.id, msg.message_id)


@with_cleanup
async def week_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.date.today()
    week_type = get_week_type(today)
    text = "📅 Расписание на неделю\n\n"
    
    for eng in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
        lessons = SCHEDULE[week_type].get(eng, []) if SCHEDULE else []
        ru = get_russian_day(eng)
        date_obj = get_next_weekday(eng, include_today=True)
        
        if lessons:
            text += f"*{ru}* ({date_obj.strftime('%d.%m.%Y')}):\n"
            by_time = {}
            for l in lessons:
                by_time.setdefault(l['time'], []).append(l)
            
            for t_slot in sorted(by_time.keys(), key=lambda t: t.split('-')[0]):
                grp = by_time[t_slot]
                if len(grp) == 1 and grp[0]['groups'][0] == "все":
                    l = grp[0]
                    text += f"  ⏰ {t_slot} | {l['subject']} ({l['type'].upper()})\n"
                else:
                    for l in grp:
                        g = l['groups'][0] if l['groups'][0] != "все" else "все"
                        text += f"  ⏰ {t_slot} | {g}: {l['subject']}\n"
            text += "\n"
        else:
            text += f"*{ru}*: 🎉 Выходной\n\n"
    
    text += f"📊 Неделя: {'1-я' if week_type == 'even' else '2-я'}"
    
    msg = await update.message.reply_text(text, parse_mode='Markdown')
    ScheduleManager().save_bot_msg(update.effective_chat.id, update.effective_user.id, msg.message_id)


@with_cleanup
async def now_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("✅ Бот работает!")
    ScheduleManager().save_bot_msg(update.effective_chat.id, update.effective_user.id, msg.message_id)


@with_cleanup
async def update_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await send_tomorrow_schedule(context)
        msg = await update.message.reply_text("✅ Расписание отправлено в группу!")
    except Exception as e:
        msg = await update.message.reply_text(f"❌ Ошибка: {e}")
    ScheduleManager().save_bot_msg(update.effective_chat.id, update.effective_user.id, msg.message_id)


# === Автоотправка ===
async def delete_prev_schedule(context, mgr, date_str):
    prev = mgr.get_schedule_msg(date_str)
    if prev:
        try:
            await context.bot.delete_message(chat_id=prev[1], message_id=prev[0])
            print(f"✅ Удалено старое расписание для {date_str}")
        except Exception as e:
            print(f"⚠️ Не удалось удалить: {e}")
        finally:
            mgr.delete_schedule_record(date_str)


async def send_tomorrow_schedule(context: ContextTypes.DEFAULT_TYPE):
    try:
        print(f"🕕 [{datetime.datetime.now()}] Автоотправка...")
        mgr = ScheduleManager()
        tomorrow = get_tomorrow()
        date_str = tomorrow.strftime("%Y-%m-%d")
        day_name = get_day_name(tomorrow)
        week_type = get_week_type(tomorrow)
        
        text = format_schedule_message(day_name, week_type, tomorrow)
        
        await delete_prev_schedule(context, mgr, date_str)
        
        message = await context.bot.send_message(
            chat_id=CHAT_ID,
            message_thread_id=TOPIC_ID,
            text=text
        )
        mgr.save_schedule_msg(date_str, message.message_id, CHAT_ID, TOPIC_ID)
        print(f"✅ Отправлено для {tomorrow}")
    except Exception as e:
        print(f"❌ Ошибка автоотправки: {e}")


def setup_job_queue(application):
    job_queue = application.job_queue
    if job_queue is None:
        print("❌ JobQueue недоступен")
        return
    target = datetime.time(hour=10, minute=0, second=0)
    job_queue.run_daily(
        callback=send_tomorrow_schedule,
        time=target,
        days=tuple(range(7)),
        name="daily_schedule"
    )
    print(f"✅ JobQueue настроен на {target}")


# === Запуск ===
def main():
    global SCHEDULE
    logging.basicConfig(level=logging.INFO)
    
    try:
        load_schedule()
    except Exception as e:
        print(f"⚠️ Не удалось загрузить расписание: {e}")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("today", today_cmd))
    app.add_handler(CommandHandler("tomorrow", tomorrow_cmd))
    app.add_handler(CommandHandler("day", day_cmd))
    app.add_handler(CommandHandler("week", week_cmd))
    app.add_handler(CommandHandler("now", now_cmd))
    app.add_handler(CommandHandler("update", update_cmd))
    
    setup_job_queue(app)
    
    print("✅ Бот запущен!")
    print(f"📍 Чат: {CHAT_ID}, Топик: {TOPIC_ID}")
    app.run_polling()


if __name__ == "__main__":
    main()
