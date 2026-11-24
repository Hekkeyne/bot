import sqlite3
import datetime
import logging
import asyncio
import os
import re
import time
import html
import threading

from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden
import pytz

import schedule_source as ss
import widget as wg

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("токен неверный")

BUILD = "buttons-1 ptb22"

TIMETABLE_URL = "https://timetable.pallada.sibsau.ru/timetable"
SITE_URL = "https://hekkeyne.ru/timetable/"
FOOTER_LINK = ("\n\n<a href=\"" + SITE_URL + "\">Полное расписание на нашем сайте</a>"
               "\n<a href=\"" + TIMETABLE_URL + "\">Полное расписание Паллада СибГУ</a>")
KRASNOYARSK_TZ = pytz.timezone('Asia/Krasnoyarsk')
DB_PATH = os.getenv("DB_PATH") or "schedule_bot.db"
PUBLISH_DELAY_MINUTES = 2
STALE_PUBLISH_LIMIT = datetime.timedelta(hours=3)
GROUP_PROMPT_TTL = 600
LEGACY_GROUP_ID = 13922
LEGACY_GROUP_NAME = "БПА24-01"

PENDING_GROUP = {}

def group_link(group_id, group_name=None):
    ours = ss.site_link(group_name) if group_name else SITE_URL
    pallada = f"{TIMETABLE_URL}/group/{group_id}" if group_id else TIMETABLE_URL
    return (f'\n\n<a href="{ours}">Полное расписание на нашем сайте</a>'
            f'\n<a href="{pallada}">Полное расписание Паллада СибГУ</a>')


async def reply_plain(update, manager, text, keyboard=None):
    if keyboard is None:
        msg = await update.message.reply_text(text, parse_mode='HTML')
    else:
        msg = await update.message.reply_text(text, parse_mode='HTML', reply_markup=keyboard)
    manager.save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)


async def deliver_day(update, manager, schedule, sub, date, header=None, keyboard=None):
    chat_id, thread_id = dest_key(update)
    group = sub.get("group_name") or ""
    stamp = date.strftime("%d.%m.%Y")
    if chat_id > 0:
        caption = f"{header}, {stamp}" if header else f"Расписание {group} на {stamp}"
        try:
            message_id = await asyncio.to_thread(
                wg.send_widget_day, chat_id, schedule, sub, date, caption, thread_id, keyboard)
            manager.save_message(chat_id, update.effective_user.id, message_id)
            return
        except Exception as exc:
            logging.warning("Виджет не ушёл (%s), отправляю текст", exc)

    text = format_schedule(schedule, sub, date)
    if header:
        text = f"<b>{esc(header)}</b>\n\n" + text
    await reply_plain(update, manager, text, keyboard)

def esc(value):
    return html.escape(str(value if value is not None else ""))

def dest_key(update):
    chat_id = update.effective_chat.id
    thread_id = 0
    message = update.effective_message
    if message is not None and getattr(message, "is_topic_message", False):
        thread_id = message.message_thread_id or 0
    return chat_id, thread_id

class DatabaseManager:
    def __init__(self):
        self.init_db()
        self.migrate_schema()
        self.migrate_legacy_settings()

    def migrate_schema(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(subscriptions)")}
            if "id" in columns:
                if "chat_title" not in columns:
                    conn.execute("ALTER TABLE subscriptions ADD COLUMN chat_title TEXT")
                return

            conn.execute("ALTER TABLE subscriptions RENAME TO subscriptions_old")
            conn.execute('''
                CREATE TABLE subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    thread_id INTEGER NOT NULL DEFAULT 0,
                    chat_title TEXT,
                    group_id INTEGER,
                    group_name TEXT,
                    auto_enabled INTEGER DEFAULT 0,
                    created_by INTEGER,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (chat_id, thread_id)
                )
            ''')
            conn.execute('''
                INSERT INTO subscriptions
                    (chat_id, thread_id, chat_title, group_id, group_name, auto_enabled, created_by, updated_at)
                SELECT chat_id, thread_id, NULL, group_id, group_name, auto_enabled, created_by, updated_at
                FROM subscriptions_old
            ''')
            conn.execute("DROP TABLE subscriptions_old")
            logging.info("Таблица subscriptions перестроена с номерами")

    def init_db(self):
        with sqlite3.connect(DB_PATH) as conn:
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
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    thread_id INTEGER NOT NULL DEFAULT 0,
                    chat_title TEXT,
                    group_id INTEGER,
                    group_name TEXT,
                    auto_enabled INTEGER DEFAULT 0,
                    created_by INTEGER,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (chat_id, thread_id)
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS teacher_links (
                    id INTEGER PRIMARY KEY,
                    name TEXT
                )
            ''')

    def save_message(self, chat_id, user_id, message_id):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('DELETE FROM bot_messages WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
            conn.execute('INSERT INTO bot_messages (chat_id, user_id, message_id) VALUES (?, ?, ?)',
                         (chat_id, user_id, message_id))

    def get_last_message(self, chat_id, user_id):
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.execute(
                'SELECT message_id FROM bot_messages WHERE chat_id = ? AND user_id = ? ORDER BY timestamp DESC LIMIT 1',
                (chat_id, user_id)
            )
            row = cur.fetchone()
            return row[0] if row else None

    def set_group(self, chat_id, thread_id, group_id, group_name, user_id=None, chat_title=None):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                'INSERT OR IGNORE INTO subscriptions (chat_id, thread_id, chat_title, group_id, group_name, created_by) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (chat_id, thread_id, chat_title, group_id, group_name, user_id)
            )
            conn.execute(
                'UPDATE subscriptions SET group_id = ?, group_name = ?, created_by = ?, '
                'chat_title = COALESCE(?, chat_title), updated_at = CURRENT_TIMESTAMP '
                'WHERE chat_id = ? AND thread_id = ?',
                (group_id, group_name, user_id, chat_title, chat_id, thread_id)
            )

    def get_subscription(self, chat_id, thread_id):
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                'SELECT * FROM subscriptions WHERE chat_id = ? AND thread_id = ?',
                (chat_id, thread_id)
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def set_auto(self, chat_id, thread_id, enabled):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                'UPDATE subscriptions SET auto_enabled = ?, updated_at = CURRENT_TIMESTAMP '
                'WHERE chat_id = ? AND thread_id = ?',
                (1 if enabled else 0, chat_id, thread_id)
            )

    def get_auto_subscriptions(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                'SELECT * FROM subscriptions WHERE auto_enabled = 1 AND group_id IS NOT NULL'
            )
            return [dict(row) for row in cur.fetchall()]

    def get_subscriptions_by(self, user_id):
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute('SELECT * FROM subscriptions WHERE created_by = ? ORDER BY id', (user_id,))
            return [dict(row) for row in cur.fetchall()]

    def get_subscription_by_id(self, sub_id):
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute('SELECT * FROM subscriptions WHERE id = ?', (sub_id,)).fetchone()
            return dict(row) if row else None

    def set_auto_by_id(self, sub_id, enabled):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                'UPDATE subscriptions SET auto_enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                (1 if enabled else 0, sub_id)
            )

    def save_teacher(self, teacher_id, name):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('INSERT OR REPLACE INTO teacher_links (id, name) VALUES (?, ?)',
                         (teacher_id, name))
            conn.execute('DELETE FROM teacher_links WHERE id NOT IN '
                         '(SELECT id FROM teacher_links ORDER BY rowid DESC LIMIT 500)')

    def get_teacher(self, teacher_id):
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute('SELECT name FROM teacher_links WHERE id = ?', (teacher_id,)).fetchone()
            return row[0] if row else None

    def migrate_legacy_settings(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            if conn.execute('SELECT COUNT(*) FROM subscriptions').fetchone()[0]:
                return
            legacy = conn.execute(
                'SELECT user_id, auto_chat_id, message_thread_id, auto_enabled '
                'FROM user_settings WHERE auto_chat_id IS NOT NULL'
            ).fetchall()

        for row in legacy:
            thread_id = row['message_thread_id'] or 0
            self.set_group(row['auto_chat_id'], thread_id,
                           LEGACY_GROUP_ID, LEGACY_GROUP_NAME, row['user_id'])
            if row['auto_enabled']:
                self.set_auto(row['auto_chat_id'], thread_id, True)
            logging.info("Перенесена старая настройка: чат %s, топик %s", row['auto_chat_id'], thread_id)

def kras_today():
    return datetime.datetime.now(KRASNOYARSK_TZ).date()

def monday_of_week():
    today = kras_today()
    return today - datetime.timedelta(days=today.weekday())

def day_short(date):
    names = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
    return names[date.weekday()] + " " + date.strftime("%d.%m")

def day_keyboard(weekday):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Эта неделя", callback_data="d|%d|0" % weekday),
        InlineKeyboardButton("Следующая неделя", callback_data="d|%d|1" % weekday),
    ]])

def week_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Эта неделя", callback_data="w|0"),
        InlineKeyboardButton("Следующая неделя", callback_data="w|1"),
    ]])

def teacher_week_keyboard(teacher_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Эта неделя", callback_data="tw|%d|0" % teacher_id),
        InlineKeyboardButton("Следующая", callback_data="tw|%d|1" % teacher_id),
    ]])

def entity_html(item, kind):
    if kind == "professor":
        links = item.get("teacher_links") or []
        return ", ".join(esc(link.get("name") or "") for link in links)
    return teacher_html(item)

def get_day_name(date):
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    return days[date.weekday()]

def get_russian_day(eng):
    mapping = {
        "monday": "Понедельник", "tuesday": "Вторник", "wednesday": "Среда",
        "thursday": "Четверг", "friday": "Пятница", "saturday": "Суббота", "sunday": "Воскресенье"
    }
    return mapping.get(eng, eng)

async def group_by_query(update, query):
    query = (query or "").strip()
    if not query:
        return None
    try:
        exact, matches = ss.find_group(query)
    except ss.ScheduleError as exc:
        msg = await update.message.reply_text(
            f"Не удалось проверить группу: {esc(exc)}" + FOOTER_LINK, parse_mode='HTML')
        DatabaseManager().save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)
        return False

    if exact:
        return {"group_id": exact["id"], "group_name": exact["name"]}

    if matches:
        names = ", ".join(esc(g["name"]) for g in matches)
        text = (f"Нашлось несколько групп: {names}.\n"
                f"Напишите название полностью." + FOOTER_LINK)
    else:
        text = f"Группа «{esc(query)}» не найдена." + FOOTER_LINK
    msg = await update.message.reply_text(text, parse_mode='HTML')
    DatabaseManager().save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)
    return False

def get_schedule_or_none(group_id):
    try:
        schedule = ss.get_schedule(group_id)
    except ss.ScheduleError as exc:
        logging.warning("Не удалось получить расписание группы %s: %s", group_id, exc)
        return None
    return schedule

async def require_group(update, manager):
    chat_id, thread_id = dest_key(update)
    sub = manager.get_subscription(chat_id, thread_id)
    if sub and sub.get("group_id"):
        return sub

    PENDING_GROUP[(chat_id, thread_id)] = time.time()
    message = await update.message.reply_text(
        "Для этого чата группа ещё не задана.\n"
        "Пришлите название группы, например <code>БПА24-01</code>.\n"
        "Сменить группу потом можно командой <code>/group</code>.",
        parse_mode='HTML'
    )
    manager.save_message(chat_id, update.effective_user.id, message.message_id)
    return None

def parse_exam_datetime(exam_date_str, exam_time_str):
    try:
        date_obj = datetime.datetime.strptime(exam_date_str, "%d.%m.%Y").date()
        time_obj = datetime.datetime.strptime(exam_time_str, "%H:%M").time()
        return datetime.datetime.combine(date_obj, time_obj)
    except ValueError:
        return None

def exam_datetime(exam):
    moment = parse_exam_datetime(exam.get("date", ""), exam.get("time") or "00:00")
    if moment is None:
        return None
    return KRASNOYARSK_TZ.localize(moment)

def days_left_text(date):
    delta = (date - kras_today()).days
    if delta < 0:
        return "уже прошёл"
    if delta == 0:
        return "сегодня"
    if delta == 1:
        return "завтра"
    return "через %d дн." % delta

def format_exams_list(schedule, sub):
    exams = schedule.get("exams") or []
    text = f"<b>Сессия: {esc(sub['group_name'])}</b>\n\n"
    if not exams:
        return text + "Экзамены пока не опубликованы." + group_link(sub.get("group_id"), sub.get("group_name"))

    fallback = datetime.datetime.max.replace(tzinfo=KRASNOYARSK_TZ)
    for exam in sorted(exams, key=lambda item: exam_datetime(item) or fallback):
        try:
            date = datetime.datetime.strptime(exam["date"], "%d.%m.%Y").date()
            left = days_left_text(date)
        except ValueError:
            left = ""
        text += (f"<b>{esc(exam['subject'])}</b> ({esc(exam['type'])})\n"
                 f"{esc(exam['date'])} в {esc(exam['time'])}, {left}\n"
                 f"{teacher_html(exam)}\n"
                 f"{esc(exam['room'])}\n\n")
    return text.strip() + group_link(sub.get("group_id"), sub.get("group_name"))

def nearest_exam_info(schedule):
    now = datetime.datetime.now(KRASNOYARSK_TZ)
    upcoming = []
    for exam in schedule.get("exams") or []:
        moment = exam_datetime(exam)
        if moment and moment > now:
            upcoming.append((moment, exam))
    if not upcoming:
        return None, ""

    moment, exam = min(upcoming, key=lambda item: item[0])
    delta = moment - now
    days = delta.days
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60
    if days > 0:
        left = f"через {days} дн. {hours} ч."
    elif hours > 0:
        left = f"через {hours} ч. {minutes} мин."
    else:
        left = f"через {minutes} мин."
    return exam, left

def format_nearest_exam(schedule, sub):
    text = f"<b>Ближайший экзамен: {esc(sub['group_name'])}</b>\n\n"
    exam, left = nearest_exam_info(schedule)
    if not exam:
        return text + "Экзаменов впереди нет." + group_link(sub.get("group_id"), sub.get("group_name"))

    text += (f"{left}\n\n"
             f"<b>{esc(exam['subject'])}</b> ({esc(exam['type'])})\n"
             f"{esc(exam['date'])} в {esc(exam['time'])}\n"
             f"{teacher_html(exam)}\n"
             f"{esc(exam['room'])}")
    return text + group_link(sub.get("group_id"), sub.get("group_name"))

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

async def error_handler(update, context):
    logging.error("Ошибка в обработчике", exc_info=context.error)
    message = update.effective_message if update else None
    if message is None:
        return
    detail = html.escape(str(context.error))[:300]
    text = (f"<b>Внутренняя ошибка</b>\n"
            f"<code>{type(context.error).__name__}: {detail}</code>")
    try:
        await message.reply_text(text, parse_mode='HTML')
    except Exception as exc:
        logging.error("Не удалось сообщить об ошибке: %s", exc)

@with_cleanup
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "<b>Бот расписания</b>\n\n"
        "<b>Сначала задайте группу:</b>\n"
        "/group БПА24-01 - задать или сменить группу для этого чата/топика\n"
        "/status - что сейчас настроено для этого чата\n\n"
        "<b>Расписание:</b>\n"
        "/today - сегодня\n"
        "/tomorrow - завтра\n"
        "/week - вся неделя\n"
        "/day &lt;день&gt; - конкретный день\n"
        "Группу можно указать сразу, без сохранения:\n"
        "/tomorrow БПА24-02, /week БПА24-02, /day вторник БПА24-02\n\n"
        "<b>Сессия:</b>\n"
        "/exams - все экзамены группы\n"
        "/nearexam - ближайший экзамен\n"
        "/consults - консультации группы\n\n"
        "<b>Преподаватели:</b>\n"
        "/prep Масаев - найти преподавателя и открыть его расписание\n\n"
        "<b>Автоотправка:</b>\n"
        "/setchat - публиковать расписание в этот чат после последней пары\n"
        "/disable_auto - выключить здесь или по номеру: /disable_auto 2\n"
        + FOOTER_LINK
    )
    msg = await update.message.reply_text(text, parse_mode='HTML')
    DatabaseManager().save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)

@with_cleanup
async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = DatabaseManager()
    chosen = await group_by_query(update, " ".join(context.args))
    if chosen is False:
        return
    sub = chosen or await require_group(update, manager)
    if not sub:
        return
    today = kras_today()
    schedule = get_schedule_or_none(sub["group_id"])
    if not schedule:
        await reply_plain(update, manager, "Не удалось получить расписание, попробуйте позже." + FOOTER_LINK)
        return
    await deliver_day(update, manager, schedule, sub, today, keyboard=day_keyboard(today.weekday()))

@with_cleanup
async def tomorrow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = DatabaseManager()
    chosen = await group_by_query(update, " ".join(context.args))
    if chosen is False:
        return
    sub = chosen or await require_group(update, manager)
    if not sub:
        return
    tmr = kras_today() + datetime.timedelta(days=1)
    schedule = get_schedule_or_none(sub["group_id"])
    if not schedule:
        await reply_plain(update, manager, "Не удалось получить расписание, попробуйте позже." + FOOTER_LINK)
        return
    await reply_plain(update, manager, format_schedule(schedule, sub, tmr), day_keyboard(tmr.weekday()))

@with_cleanup
async def day_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = DatabaseManager()
    mapping = {
        'понедельник': 'monday', 'вторник': 'tuesday', 'среда': 'wednesday',
        'четверг': 'thursday', 'пятница': 'friday', 'суббота': 'saturday', 'воскресенье': 'sunday'
    }
    args = list(context.args)
    day = mapping.get(args[0].lower()) if args else None
    if not day:
        msg = await update.message.reply_text(
            "Укажите день: /day понедельник\n"
            "С группой: /day вторник БПА24-02" + FOOTER_LINK,
            parse_mode='HTML'
        )
        manager.save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)
        return

    chosen = await group_by_query(update, " ".join(args[1:]))
    if chosen is False:
        return
    sub = chosen or await require_group(update, manager)
    if not sub:
        return
    target = kras_today()
    while get_day_name(target) != day:
        target += datetime.timedelta(days=1)
    schedule = get_schedule_or_none(sub["group_id"])
    if not schedule:
        await reply_plain(update, manager, "Не удалось получить расписание, попробуйте позже." + FOOTER_LINK)
        return
    await reply_plain(update, manager, format_schedule(schedule, sub, target), day_keyboard(target.weekday()))

@with_cleanup
async def week_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = DatabaseManager()
    chosen = await group_by_query(update, " ".join(context.args))
    if chosen is False:
        return
    sub = chosen or await require_group(update, manager)
    if not sub:
        return
    today = kras_today()
    schedule = get_schedule_or_none(sub["group_id"])
    if not schedule:
        await reply_plain(update, manager, "Не удалось получить расписание, попробуйте позже." + FOOTER_LINK)
        return
    await reply_plain(update, manager, format_week(schedule, sub, today), week_keyboard())

def describe_place(sub):
    chat_id = sub["chat_id"]
    thread_id = sub.get("thread_id") or 0
    if chat_id > 0:
        where = "ЛС"
    elif sub.get("chat_title"):
        where = "«%s»" % sub["chat_title"]
    else:
        where = "чат %s" % chat_id
    if thread_id:
        where += ", топик %s" % thread_id
    return where

async def apply_group(update, chat_id, thread_id, query):
    manager = DatabaseManager()
    user_id = update.effective_user.id
    try:
        exact, matches = ss.find_group(query)
    except ss.ScheduleError as exc:
        msg = await update.message.reply_text(
            f"Не удалось проверить группу: {esc(exc)}" + FOOTER_LINK, parse_mode='HTML')
        manager.save_message(chat_id, user_id, msg.message_id)
        return

    if not exact and matches:
        PENDING_GROUP[(chat_id, thread_id)] = time.time()
        lines = "\n".join(f"• <code>{esc(g['name'])}</code>" for g in matches)
        msg = await update.message.reply_text(
            "Нашлось несколько групп, уточните название:\n\n" + lines, parse_mode='HTML')
        manager.save_message(chat_id, user_id, msg.message_id)
        return

    if not exact:
        PENDING_GROUP[(chat_id, thread_id)] = time.time()
        msg = await update.message.reply_text(
            f"Группа «{esc(query)}» не найдена. Пришлите название точнее, например <code>БПА24-01</code>.",
            parse_mode='HTML')
        manager.save_message(chat_id, user_id, msg.message_id)
        return

    manager.set_group(chat_id, thread_id, exact["id"], exact["name"], user_id,
                      update.effective_chat.title)
    PENDING_GROUP.pop((chat_id, thread_id), None)

    sub = {"group_id": exact["id"], "group_name": exact["name"]}
    schedule = get_schedule_or_none(exact["id"])
    if schedule:
        today = kras_today()
        await deliver_day(update, manager, schedule, sub, today,
                          header=f"Группа сохранена: {exact['name']}",
                          keyboard=day_keyboard(today.weekday()))
    else:
        msg = await update.message.reply_text(
            f"<b>Группа сохранена: {esc(exact['name'])}</b>\n\n"
            "Не удалось получить расписание, попробуйте позже." + FOOTER_LINK, parse_mode='HTML')
        manager.save_message(chat_id, user_id, msg.message_id)

@with_cleanup
async def group_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id, thread_id = dest_key(update)
    query = " ".join(context.args).strip()
    if not query:
        PENDING_GROUP[(chat_id, thread_id)] = time.time()
        msg = await update.message.reply_text(
            "Пришлите название группы, например <code>БПА24-01</code>.", parse_mode='HTML')
        DatabaseManager().save_message(chat_id, update.effective_user.id, msg.message_id)
        return
    await apply_group(update, chat_id, thread_id, query)

async def group_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id, thread_id = dest_key(update)
    asked_at = PENDING_GROUP.get((chat_id, thread_id))
    if not asked_at or (time.time() - asked_at) > GROUP_PROMPT_TTL:
        PENDING_GROUP.pop((chat_id, thread_id), None)
        return
    if update.effective_chat.type != "private":
        reply = update.message.reply_to_message
        if not reply or not reply.from_user or reply.from_user.id != context.bot.id:
            return
    text = (update.message.text or "").strip()
    if text:
        await apply_group(update, chat_id, thread_id, text)

@with_cleanup
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = DatabaseManager()
    chat_id, thread_id = dest_key(update)
    sub = manager.get_subscription(chat_id, thread_id)
    text = "<b>Статус</b>\n\n"
    if not sub or not sub.get("group_id"):
        text += ("Группа для этого чата не задана.\n"
                 "Задайте её командой <code>/group БПА24-01</code>.\n")
    else:
        auto = "включена" if sub.get("auto_enabled") else "выключена"
        text += (f"Группа: <code>{esc(sub['group_name'])}</code>\n"
                 f"Автоотправка: {auto}\n")
        if sub.get("auto_enabled"):
            text += "Отправка: после последней пары бот присылает расписание на завтра\n"
        else:
            text += "Включить: <code>/setchat</code>\n"

    health = await asyncio.to_thread(ss.check_site)
    text += (f"\nСайт расписания: {esc(health)}\n"
             f"Источник: {ss.source_label()}\n"
             f"Сборка: <code>{BUILD}</code>")
    text += group_link(sub.get("group_id") if sub else None,
                       sub.get("group_name") if sub else None)
    msg = await update.message.reply_text(text, parse_mode='HTML')
    manager.save_message(chat_id, update.effective_user.id, msg.message_id)

@with_cleanup
async def setchat_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = DatabaseManager()
    sender_id = update.effective_user.id

    if context.args:
        if not context.args[0].lstrip('-').isdigit():
            msg = await update.message.reply_text(
                "Укажите chat_id числом: <code>/setchat -1001234567890 [thread_id]</code>" + FOOTER_LINK,
                parse_mode='HTML')
            manager.save_message(update.effective_chat.id, sender_id, msg.message_id)
            return
        target_chat = int(context.args[0])
        target_thread = int(context.args[1]) if len(context.args) > 1 and context.args[1].isdigit() else 0
    else:
        target_chat, target_thread = dest_key(update)

    sub = manager.get_subscription(target_chat, target_thread)
    if not sub or not sub.get("group_id"):
        if (target_chat, target_thread) == dest_key(update):
            PENDING_GROUP[(target_chat, target_thread)] = time.time()
            hint = "Сначала пришлите название группы, например <code>БПА24-01</code>."
        else:
            hint = ("Для этого чата группа не задана. Задайте её там командой "
                    "<code>/group БПА24-01</code> и повторите /setchat.")
        msg = await update.message.reply_text(
            "<b>Автоотправка не включена</b>\n\n" + hint + FOOTER_LINK, parse_mode='HTML')
        manager.save_message(update.effective_chat.id, sender_id, msg.message_id)
        return

    manager.set_auto(target_chat, target_thread, True)
    thread_info = f"\nТопик: <code>{target_thread}</code>" if target_thread else ""
    msg = await update.message.reply_text(
        f"<b>Автоотправка включена</b>\n\n"
        f"Чат: <code>{target_chat}</code>{thread_info}\n"
        f"Группа: <code>{esc(sub['group_name'])}</code>\n"
        f"Отправка: после последней пары по Красноярску бот присылает расписание на завтра\n"
        f"Выключить: <code>/disable_auto</code>" + group_link(sub.get("group_id"), sub.get("group_name")),
        parse_mode='HTML')
    manager.save_message(update.effective_chat.id, sender_id, msg.message_id)

@with_cleanup
async def autosends_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = DatabaseManager()
    subs = manager.get_subscriptions_by(update.effective_user.id)
    if not subs:
        text = ("Автоотправок нет.\n"
                "Задайте группу командой <code>/group БПА24-01</code>, "
                "потом включите отправку: <code>/setchat</code>." + FOOTER_LINK)
    else:
        text = "<b>Автоотправки</b>\n\n"
        for sub in subs:
            status = "включена" if sub.get("auto_enabled") else "выключена"
            text += (f"{sub['id']}. {esc(describe_place(sub))} - "
                     f"{esc(sub.get('group_name') or 'без группы')} - {status}\n")
        text += ("\nОтключить по номеру: <code>/disable_auto 1</code>\n"
                 "Отключить здешнюю: <code>/disable_auto</code>" + FOOTER_LINK)
    msg = await update.message.reply_text(text, parse_mode='HTML')
    manager.save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)

@with_cleanup
async def disable_auto_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = DatabaseManager()
    user_id = update.effective_user.id

    if context.args and context.args[0].isdigit():
        sub = manager.get_subscription_by_id(int(context.args[0]))
        if not sub or sub.get("created_by") != user_id:
            text = ("Автоотправка с таким номером не найдена.\n"
                    "Список: <code>/autosends</code>" + FOOTER_LINK)
        else:
            manager.set_auto_by_id(sub["id"], False)
            text = (f"Автоотправка выключена:\n"
                    f"{esc(describe_place(sub))} - "
                    f"{esc(sub.get('group_name') or 'без группы')}" + FOOTER_LINK)
    else:
        chat_id, thread_id = dest_key(update)
        sub = manager.get_subscription(chat_id, thread_id)
        if not sub:
            text = "Для этого чата ничего не настроено." + FOOTER_LINK
        elif not sub.get("auto_enabled"):
            text = "Здесь автоотправка и так выключена." + FOOTER_LINK
        else:
            manager.set_auto(chat_id, thread_id, False)
            text = "Автоотправка выключена." + FOOTER_LINK

    msg = await update.message.reply_text(text, parse_mode='HTML')
    manager.save_message(update.effective_chat.id, user_id, msg.message_id)

def parse_id_list(value):
    compact = value.replace(",", "")
    if not compact.isdigit():
        return None
    return [int(part) for part in value.split(",") if part]

async def send_text_to_subs(context, subs, text_to_send):
    sent = 0
    failed = 0
    for sub in subs:
        try:
            kwargs = {"chat_id": sub["chat_id"], "text": text_to_send}
            if sub.get("thread_id"):
                kwargs["message_thread_id"] = sub["thread_id"]
            await context.bot.send_message(**kwargs)
            sent += 1
        except Exception as e:
            logging.warning("Не удалось отправить в чат %s: %s", sub["chat_id"], e)
            failed += 1
        await asyncio.sleep(1)
    return sent, failed

@with_cleanup
async def sendtext_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    manager = DatabaseManager()
    args = list(context.args)

    ids = parse_id_list(args[0]) if args else None
    if not ids or len(args) < 2:
        msg = await update.message.reply_text(
            "<b>Ошибка</b>\n\n"
            "Сначала номер, потом текст: <code>/sendtext 1,3 Занятие перенесено на 15:00</code>\n"
            "Всем сразу: <code>/sendall Занятие перенесено на 15:00</code>" + FOOTER_LINK,
            parse_mode='HTML'
        )
        manager.save_message(update.effective_chat.id, user_id, msg.message_id)
        return

    text_to_send = " ".join(args[1:])
    subs = []
    for sub_id in ids:
        sub = manager.get_subscription_by_id(sub_id)
        if sub and sub.get("created_by") == user_id:
            subs.append(sub)

    if not subs:
        msg = await update.message.reply_text(
            "Автоотправки с такими номерами не найдены.\n"
            "Список: <code>/autosends</code>" + FOOTER_LINK,
            parse_mode='HTML'
        )
        manager.save_message(update.effective_chat.id, user_id, msg.message_id)
        return

    sent, failed = await send_text_to_subs(context, subs, text_to_send)
    msg = await update.message.reply_text(
        f"<b>Отправлено</b>\n\n"
        f"Доставлено: {sent}\n"
        f"Ошибок: {failed}" + FOOTER_LINK,
        parse_mode='HTML'
    )
    manager.save_message(update.effective_chat.id, user_id, msg.message_id)

@with_cleanup
async def sendall_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    manager = DatabaseManager()

    if not context.args:
        msg = await update.message.reply_text(
            "Укажите текст: <code>/sendall Занятие перенесено на 15:00</code>" + FOOTER_LINK,
            parse_mode='HTML'
        )
        manager.save_message(update.effective_chat.id, user_id, msg.message_id)
        return

    subs = manager.get_subscriptions_by(user_id)
    if not subs:
        msg = await update.message.reply_text(
            "Вы ещё не настроили ни одного чата." + FOOTER_LINK,
            parse_mode='HTML'
        )
        manager.save_message(update.effective_chat.id, user_id, msg.message_id)
        return

    sent, failed = await send_text_to_subs(context, subs, " ".join(context.args))
    msg = await update.message.reply_text(
        f"<b>Отправлено</b>\n\n"
        f"Доставлено: {sent}\n"
        f"Ошибок: {failed}" + FOOTER_LINK,
        parse_mode='HTML'
    )
    manager.save_message(update.effective_chat.id, user_id, msg.message_id)

@with_cleanup
async def exams_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = DatabaseManager()
    chosen = await group_by_query(update, " ".join(context.args))
    if chosen is False:
        return
    sub = chosen or await require_group(update, manager)
    if not sub:
        return
    schedule = get_schedule_or_none(sub["group_id"])
    if not schedule:
        await reply_plain(update, manager, "Не удалось получить расписание, попробуйте позже." + FOOTER_LINK)
        return
    await reply_plain(update, manager, format_exams_list(schedule, sub))

@with_cleanup
async def nearexam_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = DatabaseManager()
    chosen = await group_by_query(update, " ".join(context.args))
    if chosen is False:
        return
    sub = chosen or await require_group(update, manager)
    if not sub:
        return
    schedule = get_schedule_or_none(sub["group_id"])
    if not schedule:
        await reply_plain(update, manager, "Не удалось получить расписание, попробуйте позже." + FOOTER_LINK)
        return
    await reply_plain(update, manager, format_nearest_exam(schedule, sub))

def consult_key(item):
    raw = "%s %s" % (item.get("date", ""), (item.get("time") or "").split("-")[0])
    try:
        return datetime.datetime.strptime(raw.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        return datetime.datetime.max


def format_consults(items, sub):
    text = f"<b>Консультации: {esc(sub['group_name'])}</b>\n\n"
    link = group_link(sub.get("group_id"), sub.get("group_name"))
    if not items:
        return text + "Пока не опубликованы. Появятся, когда вуз их выложит." + link
    for item in sorted(items, key=consult_key):
        teachers = ", ".join(esc(person.get("name") or "") for person in (item.get("teachers") or []) if person.get("name"))
        text += (f"<b>{esc(item.get('date'))}</b> в {esc(item.get('time'))}\n"
                 f"{teachers}\n"
                 f"{esc(item.get('room'))}\n\n")
    return text.strip() + link


def get_teacher_or_none(name):
    try:
        return ss.get_teacher_schedule(name)
    except ss.ScheduleError as exc:
        logging.warning("Не удалось получить расписание преподавателя %s: %s", name, exc)
        return None


@with_cleanup
async def consults_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = DatabaseManager()
    chosen = await group_by_query(update, " ".join(context.args))
    if chosen is False:
        return
    sub = chosen or await require_group(update, manager)
    if not sub:
        return
    try:
        items = await asyncio.to_thread(ss.get_consultations, sub["group_id"])
    except ss.ScheduleError as exc:
        await reply_plain(update, manager, "Не удалось получить консультации: " + esc(exc) + FOOTER_LINK)
        return
    await reply_plain(update, manager, format_consults(items, sub))


@with_cleanup
async def prep_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = DatabaseManager()
    query = " ".join(context.args).strip()
    if not query:
        await reply_plain(update, manager,
                          "Напишите фамилию или ФИО: <code>/prep Масаев</code>" + FOOTER_LINK)
        return
    try:
        people = await asyncio.to_thread(ss.search_groups, query)
    except ss.ScheduleError as exc:
        await reply_plain(update, manager, "Поиск недоступен: " + esc(exc) + FOOTER_LINK)
        return

    teachers = [person for person in people if not re.search(r"\d", person["name"])][:8]
    if not teachers:
        await reply_plain(update, manager, f"Преподаватель «{esc(query)}» не найден." + FOOTER_LINK)
        return

    rows = []
    for person in teachers:
        manager.save_teacher(person["id"], person["name"])
        rows.append([InlineKeyboardButton(person["name"], callback_data="p|%d" % person["id"])])
    msg = await update.message.reply_text(
        "<b>Нашёл преподавателей</b>\n\nВыберите кнопкой:",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))
    manager.save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    parts = (query.data or "").split("|")

    if parts[0] in ("d", "w"):
        chat_id = query.message.chat_id
        thread_id = getattr(query.message, "message_thread_id", None) or 0
        manager = DatabaseManager()
        sub = manager.get_subscription(chat_id, thread_id)
        if not sub or not sub.get("group_id"):
            await query.edit_message_text("Сначала задайте группу: /group БПА24-01")
            return
        schedule = get_schedule_or_none(sub["group_id"])
        if not schedule:
            await query.edit_message_text("Не удалось получить расписание, попробуйте позже.")
            return
        try:
            monday = monday_of_week()
            if parts[0] == "d":
                weekday = int(parts[1])
                offset = int(parts[2])
                target = monday + datetime.timedelta(days=offset * 7 + weekday)
                text = format_schedule(schedule, sub, target)
                keyboard = day_keyboard(weekday)
            else:
                offset = int(parts[1])
                target = monday + datetime.timedelta(days=offset * 7)
                text = format_week(schedule, sub, target)
                keyboard = week_keyboard()
        except (ValueError, IndexError):
            return
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
        except BadRequest:
            pass
        return

    if parts[0] in ("p", "tw"):
        try:
            teacher_id = int(parts[1])
            offset = int(parts[2]) if parts[0] == "tw" else 0
        except (ValueError, IndexError):
            return
        manager = DatabaseManager()
        name = manager.get_teacher(teacher_id)
        if not name:
            await query.edit_message_text("Не нашёл преподавателя, поищите заново: /prep Фамилия")
            return
        schedule = get_teacher_or_none(name)
        if not schedule:
            await query.edit_message_text("Не удалось получить расписание преподавателя, попробуйте позже.")
            return
        sub = {"group_id": None, "group_name": schedule.get("group_name") or name}
        target = monday_of_week() + datetime.timedelta(days=offset * 7)
        text = format_week(schedule, sub, target)
        try:
            await query.edit_message_text(text, parse_mode="HTML",
                                          reply_markup=teacher_week_keyboard(teacher_id))
        except BadRequest:
            pass


async def send_schedule_to(bot, sub, schedule, date):
    text = format_schedule(schedule, sub, date)
    kwargs = {"chat_id": sub["chat_id"], "text": text, "parse_mode": "HTML"}
    if sub.get("thread_id"):
        kwargs["message_thread_id"] = sub["thread_id"]
    await bot.send_message(**kwargs)

def compute_publish_time(schedule, today, now):
    lessons = ss.lessons_for(schedule, today)
    if not lessons:
        for i in range(1, 8):
            prev = today - datetime.timedelta(days=i)
            prev_lessons = ss.lessons_for(schedule, prev)
            if prev_lessons:
                lessons = prev_lessons
                break

    end = ss.last_lesson_end_time(lessons)
    if not end:
        return None

    hour, minute = end
    trigger = (KRASNOYARSK_TZ.localize(datetime.datetime.combine(today, datetime.time(hour, minute)))
               + datetime.timedelta(minutes=PUBLISH_DELAY_MINUTES))
    if now >= trigger:
        if now - trigger > STALE_PUBLISH_LIMIT:
            return None
        return now
    return trigger

async def schedule_auto_send(app: Application):
    now = datetime.datetime.now(KRASNOYARSK_TZ)
    today = now.date()
    tomorrow = today + datetime.timedelta(days=1)
    manager = DatabaseManager()
    subs = manager.get_auto_subscriptions()
    if not subs:
        logging.info("Автоотправка: нет активных подписок")
        return

    jobs = []
    for sub in subs:
        schedule = get_schedule_or_none(sub["group_id"])
        if not schedule:
            continue
        trigger = compute_publish_time(schedule, today, now)
        if not trigger:
            logging.info("Автоотправка: чат %s пропущен, время уже прошло", sub["chat_id"])
            continue
        jobs.append((trigger, sub, schedule))
    jobs.sort(key=lambda job: job[0])

    sent_count = 0
    for trigger, sub, schedule in jobs:
        current = datetime.datetime.now(KRASNOYARSK_TZ)
        if current < trigger:
            wait = (trigger - current).total_seconds()
            logging.info("Автоотправка: чат %s - через %.1f мин (в %s)",
                         sub["chat_id"], wait / 60, trigger.strftime("%H:%M"))
            await asyncio.sleep(wait)

        if datetime.datetime.now(KRASNOYARSK_TZ).date() != today:
            logging.warning("Автоотправка: дата сменилась, прерываем")
            return

        try:
            await send_schedule_to(app.bot, sub, schedule, tomorrow)
            thread_info = " (топик %s)" % sub["thread_id"] if sub.get("thread_id") else ""
            logging.info("Автоотправка: отправлено в чат %s%s", sub["chat_id"], thread_info)
            sent_count += 1
        except Forbidden:
            logging.warning("Автоотправка: бот заблокирован в чате %s, выключаем", sub["chat_id"])
            manager.set_auto(sub["chat_id"], sub["thread_id"], False)
        except BadRequest as e:
            logging.warning("Автоотправка: ошибка отправки в чат %s: %s", sub["chat_id"], e)
        except Exception as e:
            logging.error("Автоотправка: неожиданная ошибка %s: %s", type(e).__name__, e)
        await asyncio.sleep(1)

    if sent_count:
        logging.info("Автоотправка: всего отправлено %d", sent_count)

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
    logging.info("Циклы автоотправки запущены")
    threading.Thread(target=warm_up, daemon=True).start()

def warm_up():
    try:
        manager = DatabaseManager()
        subs = manager.get_auto_subscriptions()
    except Exception as exc:
        logging.warning("Прогрев при старте не удался: %s", exc)
        return

    for sub in subs:
        try:
            ss.get_schedule(sub["group_id"])
            logging.info("Прогрев группы %s завершён", sub["group_id"])
        except Exception as exc:
            logging.warning("Прогрев группы %s не удался: %s", sub["group_id"], exc)

def teacher_html(item):
    links = item.get("teacher_links") or []
    if not links:
        return esc(item.get("teacher", ""))
    parts = []
    for link in links:
        name = esc(link.get("name") or "")
        target = link.get("id")
        if target:
            parts.append(f'<a href="{ss.BASE_URL}/timetable/professor/{target}">{name}</a>')
        else:
            parts.append(name)
    return ", ".join(parts)


def lesson_block(lesson, kind="group"):
    return (f"<b>{esc(lesson['subject'])}</b> ({esc(lesson['type'])})\n"
            f"{entity_html(lesson, kind)}\n"
            f"{esc(lesson['room'])}\n\n")

def format_schedule(schedule, sub, date, kind=None):
    kind = kind or schedule.get("kind") or "group"
    weekday = get_day_name(date)
    week_no = ss.week_number_for(date, schedule)
    lessons = ss.lessons_for(schedule, date)
    footer = group_link(sub.get("group_id"), sub.get("group_name"))

    label = "Преподаватель" if kind == "professor" else "Группа"
    header = (f"Расписание на {get_russian_day(weekday)} ({date.strftime('%d.%m.%Y')})\n"
              f"{label}: {esc(sub['group_name'])}\n"
              f"Неделя: {week_no}-я\n")
    if not lessons:
        return header + "\nВыходной! Пар нет." + footer

    time_groups = {}
    for lesson in lessons:
        time_groups.setdefault(lesson["time"], []).append(lesson)

    msg = header + "\n"
    for time_slot in sorted(time_groups.keys(), key=lambda t: t.split("-")[0]):
        group = time_groups[time_slot]
        common = next((l for l in group if l["subgroup"] == "все"), None)
        msg += f"{time_slot}\n"
        if common:
            msg += lesson_block(common, kind)
        else:
            for i, lesson in enumerate(group):
                if i > 0:
                    msg += "\n"
                msg += f"{lesson['subgroup']}:\n"
                msg += lesson_block(lesson, kind)
            msg += "\n"

    return msg.strip() + footer

def format_week(schedule, sub, today, kind=None):
    kind = kind or schedule.get("kind") or "group"
    monday = today - datetime.timedelta(days=today.weekday())
    title = "Расписание на неделю" if kind == "group" else "Расписание преподавателя на неделю"
    text = f"<b>{title}</b>\n{esc(sub['group_name'])}\n\n"
    for i in range(7):
        current = monday + datetime.timedelta(days=i)
        lessons = ss.lessons_for(schedule, current)
        day_ru = get_russian_day(get_day_name(current))
        if not lessons:
            text += f"<b>{day_ru}</b>: Выходной\n\n"
            continue

        time_groups = {}
        for lesson in lessons:
            time_groups.setdefault(lesson["time"], []).append(lesson)

        text += f"<b>{day_ru}</b> ({current.strftime('%d.%m')}):\n"
        for time_slot in sorted(time_groups.keys(), key=lambda t: t.split("-")[0]):
            group = time_groups[time_slot]
            common = next((l for l in group if l["subgroup"] == "все"), None)
            if common:
                line = f"{time_slot} | <b>{esc(common['subject'])}</b> ({esc(common['type'])})"
                if kind == "professor":
                    who = entity_html(common, kind)
                    if who:
                        line += ", " + who
                text += line + "\n"
            else:
                for lesson in group:
                    line = (f"{time_slot} | {esc(lesson['subgroup'])}: "
                            f"<b>{esc(lesson['subject'])}</b> ({esc(lesson['type'])})")
                    if kind == "professor":
                        who = entity_html(lesson, kind)
                        if who:
                            line += ", " + who
                    text += line + "\n"
        text += "\n"

    text += f"Неделя: {ss.week_number_for(today, schedule)}-я"
    return text + group_link(sub.get("group_id"), sub.get("group_name"))

def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[logging.StreamHandler()]
    )

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("group", group_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("today", today_cmd))
    app.add_handler(CommandHandler("tomorrow", tomorrow_cmd))
    app.add_handler(CommandHandler("day", day_cmd))
    app.add_handler(CommandHandler("week", week_cmd))
    app.add_handler(CommandHandler("setchat", setchat_cmd))
    app.add_handler(CommandHandler("autosends", autosends_cmd))
    app.add_handler(CommandHandler("disable_auto", disable_auto_cmd))

    app.add_handler(CommandHandler("sendtext", sendtext_cmd))
    app.add_handler(CommandHandler("sendall", sendall_cmd))

    app.add_handler(CommandHandler("exams", exams_cmd))
    app.add_handler(CommandHandler("nearexam", nearexam_cmd))
    app.add_handler(CommandHandler("consults", consults_cmd))
    app.add_handler(CommandHandler("prep", prep_cmd))

    app.add_handler(CallbackQueryHandler(on_callback))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, group_text_handler))

    app.add_error_handler(error_handler)

    logging.info("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
