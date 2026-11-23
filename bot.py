import sqlite3
import datetime
import logging
import asyncio
import os
import time
import html

from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from telegram import Update
from telegram.error import BadRequest, Forbidden
import pytz

import schedule_source as ss

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("токен неверный")

BUILD = "diag-6 autosends"

TIMETABLE_URL = "https://timetable.pallada.sibsau.ru/timetable"
FOOTER_LINK = f'\n\n<a href="{TIMETABLE_URL}">Полное расписание на сайте</a>'
KRASNOYARSK_TZ = pytz.timezone('Asia/Krasnoyarsk')
DB_PATH = os.getenv("DB_PATH") or "schedule_bot.db"
PUBLISH_DELAY_MINUTES = 2
STALE_PUBLISH_LIMIT = datetime.timedelta(hours=3)
GROUP_PROMPT_TTL = 600
LEGACY_GROUP_ID = 13922
LEGACY_GROUP_NAME = "БПА24-01"

EXAMS = []

PENDING_GROUP = {}


def group_link(group_id):
    if not group_id:
        return FOOTER_LINK
    return f'\n\n<a href="https://timetable.pallada.sibsau.ru/timetable/group/{group_id}">Полное расписание на сайте</a>'


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

    def set_exam_reminder(self, user_id, chat_id, thread_id, exam_date, exam_time, subject):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO exam_reminders
                (user_id, chat_id, message_thread_id, exam_date, exam_time, subject, reminder_enabled)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            ''', (user_id, chat_id, thread_id, exam_date, exam_time, subject))

    def get_active_exam_reminders(self):
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.execute('''
                SELECT user_id, chat_id, message_thread_id, exam_date, exam_time, subject
                FROM exam_reminders
                WHERE reminder_enabled = 1
                ORDER BY exam_date, exam_time
            ''')
            return cur.fetchall()

    def disable_exam_reminder(self, user_id, exam_date, exam_time):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('''
                UPDATE exam_reminders
                SET reminder_enabled = 0
                WHERE user_id = ? AND exam_date = ? AND exam_time = ?
            ''', (user_id, exam_date, exam_time))

    def mark_reminder_sent(self, user_id, chat_id, exam_date, reminder_type):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('''
                INSERT INTO sent_reminders (user_id, chat_id, exam_date, reminder_type)
                VALUES (?, ?, ?, ?)
            ''', (user_id, chat_id, exam_date, reminder_type))

    def was_reminder_sent(self, user_id, chat_id, exam_date, reminder_type):
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.execute('''
                SELECT COUNT(*) FROM sent_reminders
                WHERE user_id = ? AND chat_id = ? AND exam_date = ? AND reminder_type = ?
            ''', (user_id, chat_id, exam_date, reminder_type))
            return cur.fetchone()[0] > 0

    def clear_old_reminders(self, exam_date):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('''
                DELETE FROM sent_reminders WHERE exam_date < ?
            ''', (exam_date,))

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
        return {"group_id": exact["page_id"], "group_name": exact["name"]}

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
        return ss.get_schedule(group_id)
    except ss.ScheduleError as exc:
        logging.warning("Не удалось получить расписание группы %s: %s", group_id, exc)
        return None

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

def format_exam(exam):
    room_formatted = exam['room'].replace('"', "'")
    text = f"<b>{exam['subject']}</b>\n"
    text += f"{exam['date']} в {exam['time']}\n"
    text += f"{exam['teacher']}\n"
    text += f"{room_formatted}"
    return text

def format_exams_list():
    if not EXAMS:
        return "<b>Список экзаменов</b>\n\nЭкзаменов пока нет." + FOOTER_LINK

    text = "<b>Список экзаменов</b>\n\n"
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
        return "<b>Ближайший экзамен</b>\n\nЭкзаменов нет или все экзамены уже прошли." + FOOTER_LINK

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

    text = f"<b>Ближайший экзамен</b>\n\n"
    text += f"{time_info}\n\n"
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
        "/group БПА24-01 — задать или сменить группу для этого чата/топика\n"
        "/status — что сейчас настроено для этого чата\n\n"
        "<b>Расписание:</b>\n"
        "/today — сегодня\n"
        "/tomorrow — завтра\n"
        "/week — вся неделя\n"
        "/day &lt;день&gt; — конкретный день\n"
        "Группу можно указать сразу, без сохранения:\n"
        "/tomorrow БПА24-02, /week БПА24-02, /day вторник БПА24-02\n\n"
        "<b>Автоотправка:</b>\n"
        "/setchat — публиковать расписание в этот чат после последней пары\n"
        "/autosends — список всех автоотправок с номерами\n"
        "/disable_auto — выключить здесь или по номеру: /disable_auto 2\n"
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
    today = datetime.date.today()
    schedule = get_schedule_or_none(sub["group_id"])
    text = (format_schedule(schedule, sub, today) if schedule
            else "Не удалось получить расписание, попробуйте позже." + FOOTER_LINK)
    msg = await update.message.reply_text(text, parse_mode='HTML')
    manager.save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)

@with_cleanup
async def tomorrow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = DatabaseManager()
    chosen = await group_by_query(update, " ".join(context.args))
    if chosen is False:
        return
    sub = chosen or await require_group(update, manager)
    if not sub:
        return
    tmr = datetime.date.today() + datetime.timedelta(days=1)
    schedule = get_schedule_or_none(sub["group_id"])
    text = (format_schedule(schedule, sub, tmr) if schedule
            else "Не удалось получить расписание, попробуйте позже." + FOOTER_LINK)
    msg = await update.message.reply_text(text, parse_mode='HTML')
    manager.save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)

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
    target = datetime.date.today()
    while get_day_name(target) != day:
        target += datetime.timedelta(days=1)
    schedule = get_schedule_or_none(sub["group_id"])
    text = (format_schedule(schedule, sub, target) if schedule
            else "Не удалось получить расписание, попробуйте позже." + FOOTER_LINK)
    msg = await update.message.reply_text(text, parse_mode='HTML')
    manager.save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)

@with_cleanup
async def week_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = DatabaseManager()
    chosen = await group_by_query(update, " ".join(context.args))
    if chosen is False:
        return
    sub = chosen or await require_group(update, manager)
    if not sub:
        return
    today = datetime.date.today()
    schedule = get_schedule_or_none(sub["group_id"])
    text = (format_week(schedule, sub, today) if schedule
            else "Не удалось получить расписание, попробуйте позже." + FOOTER_LINK)
    msg = await update.message.reply_text(text, parse_mode='HTML')
    manager.save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)

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

    manager.set_group(chat_id, thread_id, exact["page_id"], exact["name"], user_id,
                      update.effective_chat.title)
    PENDING_GROUP.pop((chat_id, thread_id), None)

    sub = {"group_id": exact["page_id"], "group_name": exact["name"]}
    schedule = get_schedule_or_none(exact["page_id"])
    if schedule:
        text = (f"<b>Группа сохранена: {esc(exact['name'])}</b>\n"
                f"Автоотправка после пар: <code>/setchat</code>\n\n"
                + format_schedule(schedule, sub, datetime.date.today()))
    else:
        text = (f"<b>Группа сохранена: {esc(exact['name'])}</b>\n\n"
                "Не удалось получить расписание, попробуйте позже." + FOOTER_LINK)
    msg = await update.message.reply_text(text, parse_mode='HTML')
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
    text += group_link(sub.get("group_id") if sub else None)
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
        f"Выключить: <code>/disable_auto</code>" + group_link(sub.get("group_id")),
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
            text += (f"{sub['id']}. {esc(describe_place(sub))} — "
                     f"{esc(sub.get('group_name') or 'без группы')} — {status}\n")
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
                    f"{esc(describe_place(sub))} — "
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

@with_cleanup
async def sendtext_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    manager = DatabaseManager()

    if not context.args:
        msg = await update.message.reply_text(
            "<b>Ошибка</b>\n\n"
            "Укажите текст для отправки.\n"
            "Пример: <code>/sendtext Всем привет, встречаемся в 15:00!</code>" + FOOTER_LINK,
            parse_mode='HTML'
        )
        manager.save_message(update.effective_chat.id, user_id, msg.message_id)
        return

    text_to_send = " ".join(context.args)
    subs = manager.get_subscriptions_by(user_id)
    if not subs:
        msg = await update.message.reply_text(
            "<b>Ошибка</b>\n\n"
            "Вы ещё не настроили ни одного чата.\n"
            "Задайте группу командой <code>/group</code>." + FOOTER_LINK,
            parse_mode='HTML'
        )
        manager.save_message(update.effective_chat.id, user_id, msg.message_id)
        return

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
            logging.warning("sendtext: не удалось отправить в чат %s: %s", sub["chat_id"], e)
            failed += 1
        await asyncio.sleep(1)

    msg = await update.message.reply_text(
        f"<b>Отправлено</b>\n\n"
        f"Доставлено: {sent}\n"
        f"Ошибок: {failed}" + FOOTER_LINK,
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
            "<b>Ошибка</b>\n\nЭкзамены не заполнены. Обратитесь к администратору." + FOOTER_LINK,
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
            "<b>Настройка напоминаний об экзаменах:</b>\n\n"
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
        f"<b>Напоминания об экзаменах включены!</b>\n\n"
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
        text = f"<b>Напоминание об экзамене</b>\n\n"
        text += f"Через 3 дня: <b>{exam['subject']}</b>\n"
        text += f"{exam['date']} в {exam['time']}\n"
        text += f"{exam['teacher']}\n"
        text += f"{room_formatted}"
    elif reminder_type == "1_day":
        text = f"<b>Напоминание об экзамене</b>\n\n"
        text += f"Завтра: <b>{exam['subject']}</b>\n"
        text += f"{exam['date']} в {exam['time']}\n"
        text += f"{exam['teacher']}\n"
        text += f"{room_formatted}"
    elif reminder_type == "1_hour":
        text = f"<b>Сегодня экзамен</b>\n\n"
        text += f"Через 1 час: <b>{exam['subject']}</b>\n"
        text += f"{exam['date']} в {exam['time']}\n"
        text += f"{exam['teacher']}\n"
        text += f"{room_formatted}\n\n"
        text += f"пасасете"
    elif reminder_type == "6_hours":
        text = f"<b>Экзамен: {exam['subject']}</b>\n\n"
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
    logging.info("Цикл напоминаний об экзаменах запущен")

    while True:
        try:
            next_time, reminder_data = await get_next_exam_reminder_time()

            if next_time is None:
                logging.info("Нет активных напоминаний об экзаменах, следующая проверка через час")
                await asyncio.sleep(3600)
                continue

            now = datetime.datetime.now(KRASNOYARSK_TZ)
            seconds_to_wait = (next_time - now).total_seconds()

            if seconds_to_wait <= 0:
                logging.info(f"Время напоминания наступило, отправляем...")
            else:
                logging.info(
                    f"Следующее напоминание через {seconds_to_wait/3600:.1f} ч "
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
                        f"Отправлено напоминание ({reminder_data['reminder_type']}) "
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
                            logging.info(f"Найден следующий экзамен: {next_exam['subject']}, запускаем алгоритм напоминаний")
                else:
                    logging.error(f"Не удалось отправить напоминание")

            await asyncio.sleep(1)

        except asyncio.CancelledError:
            logging.info("Цикл напоминаний об экзаменах остановлен")
            break
        except Exception as e:
            logging.error(f"Ошибка в цикле напоминаний об экзаменах: {e}")
            await asyncio.sleep(60)

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
            logging.info("Автоотправка: чат %s — через %.1f мин (в %s)",
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
    asyncio.create_task(exam_reminder_loop(application))
    logging.info("Циклы автоотправки запущены")

def lesson_block(lesson):
    return (f"<b>{esc(lesson['subject'])}</b> ({esc(lesson['type'])})\n"
            f"{esc(lesson['teacher'])}\n"
            f"{esc(lesson['room'])}\n\n")


def format_schedule(schedule, sub, date):
    weekday = get_day_name(date)
    week_no = ss.week_number_for(date, schedule)
    lessons = ss.lessons_for(schedule, date)
    footer = group_link(sub.get("group_id"))

    header = (f"Расписание на {get_russian_day(weekday)} ({date.strftime('%d.%m.%Y')})\n"
              f"Группа: {esc(sub['group_name'])}\n"
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
            msg += lesson_block(common)
        else:
            for i, lesson in enumerate(group):
                if i > 0:
                    msg += "\n"
                msg += f"{lesson['subgroup']}:\n"
                msg += lesson_block(lesson)
            msg += "\n"

    return msg.strip() + footer


def format_week(schedule, sub, today):
    monday = today - datetime.timedelta(days=today.weekday())
    text = f"<b>Расписание на неделю</b>\nГруппа: {esc(sub['group_name'])}\n\n"
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
                text += f"{time_slot} | <b>{esc(common['subject'])}</b> ({esc(common['type'])})\n"
            else:
                for lesson in group:
                    text += (f"{time_slot} | {esc(lesson['subgroup'])}: "
                             f"<b>{esc(lesson['subject'])}</b> ({esc(lesson['type'])})\n")
        text += "\n"

    text += f"Неделя: {ss.week_number_for(today, schedule)}-я"
    return text + group_link(sub.get("group_id"))

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
    app.add_handler(CommandHandler("now", now_cmd))

    app.add_handler(CommandHandler("sendtext", sendtext_cmd))

    app.add_handler(CommandHandler("exams", exams_cmd))
    app.add_handler(CommandHandler("nearexam", nearexam_cmd))
    app.add_handler(CommandHandler("setexam", setexam_cmd))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, group_text_handler))

    app.add_error_handler(error_handler)

    print("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
