import datetime
import logging
import asyncio
import os
import re
import time
import html
import threading

from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.error import BadRequest, Forbidden
import pytz

import storage
import schedule_source as ss
import render as rn
import theme_import as ti

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("токен неверный")

BUILD = "theme-qr-1 ptb22"

TIMETABLE_URL = "https://timetable.pallada.sibsau.ru/timetable"
SITE_URL = "https://hekkeyne.ru/timetable/"
FOOTER_LINK = ("\n\n<a href=\"" + SITE_URL + "\">Полное расписание на нашем сайте</a>"
               "\n<a href=\"" + TIMETABLE_URL + "\">Полное расписание Паллада СибГУ</a>")
KRASNOYARSK_TZ = pytz.timezone('Asia/Krasnoyarsk')
PUBLISH_DELAY_MINUTES = 0
STALE_PUBLISH_LIMIT = datetime.timedelta(hours=3)
GROUP_PROMPT_TTL = 600
FORMATS = {"photo": "картинкой", "text": "текстом"}
DEFAULT_FORMAT = "text"
MODES = {"light": "светлая", "dark": "тёмная"}

PENDING_GROUP = {}
PENDING_QR = {}
AUTO_WAKE = None


def wake_auto():
    if AUTO_WAKE is not None:
        AUTO_WAKE.set()

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


async def send_day_message(bot, chat_id, thread_id, schedule, sub, date, fmt, theme_key,
                           mode="light", custom=None, keyboard=None, header=None):
    fmt = fmt if fmt in FORMATS else DEFAULT_FORMAT
    if fmt == "photo":
        try:
            png = await asyncio.to_thread(rn.render_day, schedule, sub, date, theme_key,
                                          kras_today(), mode, custom)
            caption = rn.caption(schedule, sub, date)
            if header:
                caption = f"<b>{esc(header)}</b>\n" + caption
            kwargs = {"chat_id": chat_id, "photo": png, "caption": caption, "parse_mode": "HTML"}
            if thread_id:
                kwargs["message_thread_id"] = thread_id
            if keyboard is not None:
                kwargs["reply_markup"] = keyboard
            return await bot.send_photo(**kwargs)
        except Exception as exc:
            logging.warning("Картинка дня не отправлена (%s), отправляю текст", exc)

    text = format_schedule(schedule, sub, date)
    if header:
        text = f"<b>{esc(header)}</b>\n\n" + text
    kwargs = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if thread_id:
        kwargs["message_thread_id"] = thread_id
    if keyboard is not None:
        kwargs["reply_markup"] = keyboard
    return await bot.send_message(**kwargs)


async def send_week_message(bot, chat_id, thread_id, schedule, sub, monday, fmt, theme_key,
                            mode="light", custom=None, keyboard=None):
    fmt = fmt if fmt in FORMATS else DEFAULT_FORMAT
    if fmt == "photo":
        try:
            png = await asyncio.to_thread(rn.render_week, schedule, sub, monday, theme_key, mode, custom)
            kwargs = {"chat_id": chat_id, "photo": png, "caption": rn.caption(schedule, sub, week=True),
                      "parse_mode": "HTML"}
            if thread_id:
                kwargs["message_thread_id"] = thread_id
            if keyboard is not None:
                kwargs["reply_markup"] = keyboard
            return await bot.send_photo(**kwargs)
        except Exception as exc:
            logging.warning("Картинка недели не отправлена (%s), отправляю текст", exc)

    kwargs = {"chat_id": chat_id, "text": format_week(schedule, sub, monday), "parse_mode": "HTML"}
    if thread_id:
        kwargs["message_thread_id"] = thread_id
    if keyboard is not None:
        kwargs["reply_markup"] = keyboard
    return await bot.send_message(**kwargs)


def format_choice_keyboard(action):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Картинкой", callback_data="f|photo|" + action),
        InlineKeyboardButton("Текстом", callback_data="f|text|" + action)
    ]])


async def prompt_format(update, manager, action):
    msg = await update.message.reply_text(
        "Как присылать расписание?",
        reply_markup=format_choice_keyboard(action))
    manager.save_message(update.effective_chat.id, update.effective_user.id, msg.message_id)


def current_format(manager, chat_id, thread_id):
    value = manager.get_settings(chat_id, thread_id).get("format")
    return value if value in FORMATS else None


def current_theme(manager, chat_id, thread_id):
    settings = manager.get_settings(chat_id, thread_id)
    value = settings.get("theme")
    if value == "custom" and isinstance(settings.get("custom_theme"), dict):
        return "custom"
    return value if value in rn.THEMES else "default"


def current_mode(manager, chat_id, thread_id):
    value = manager.get_settings(chat_id, thread_id).get("mode")
    return value if value in MODES else "light"


def current_custom(manager, chat_id, thread_id):
    value = manager.get_settings(chat_id, thread_id).get("custom_theme")
    return value if isinstance(value, dict) else None


def theme_title(manager, chat_id, thread_id):
    settings = manager.get_settings(chat_id, thread_id)
    return rn.theme_label(current_theme(manager, chat_id, thread_id), settings.get("custom_theme"))


def settings_text(manager, chat_id, thread_id):
    fmt = current_format(manager, chat_id, thread_id)
    format_text = FORMATS[fmt] if fmt else "не выбран"
    return ("<b>Настройки</b>\n\n"
            f"Формат: {format_text}\n"
            f"Фон: {MODES[current_mode(manager, chat_id, thread_id)]}\n"
            f"Тема картинки: {theme_title(manager, chat_id, thread_id)}\n\n"
            "Светлая или тёмная - фон картинок.\n"
            "Свою тему можно импортировать по QR из настроек сайта.")


def settings_keyboard(manager, chat_id, thread_id):
    fmt = current_format(manager, chat_id, thread_id)
    theme_key = current_theme(manager, chat_id, thread_id)
    mode = current_mode(manager, chat_id, thread_id)
    settings = manager.get_settings(chat_id, thread_id)
    custom = settings.get("custom_theme")
    rows = [[
        InlineKeyboardButton(("✓ " if fmt == "photo" else "") + "Картинкой", callback_data="s|f|photo"),
        InlineKeyboardButton(("✓ " if fmt == "text" else "") + "Текстом", callback_data="s|f|text")
    ]]
    rows.append([
        InlineKeyboardButton(("✓ " if mode == "light" else "") + "Светлая", callback_data="s|m|light"),
        InlineKeyboardButton(("✓ " if mode == "dark" else "") + "Тёмная", callback_data="s|m|dark")
    ])
    themes = []
    keys = list(rn.THEME_ORDER)
    if isinstance(custom, dict):
        keys.append("custom")
    for key in keys:
        label = ("✓ " if key == theme_key else "") + rn.theme_label(key, custom)
        themes.append(InlineKeyboardButton(label, callback_data="s|t|" + key))
    for index in range(0, len(themes), 2):
        rows.append(themes[index:index + 2])
    rows.append([InlineKeyboardButton("Импорт темы по QR", callback_data="s|q|0")])
    return InlineKeyboardMarkup(rows)


async def edit_day_view(query, bot, manager, chat_id, thread_id, schedule, sub, date):
    fmt = current_format(manager, chat_id, thread_id) or DEFAULT_FORMAT
    theme_key = current_theme(manager, chat_id, thread_id)
    mode = current_mode(manager, chat_id, thread_id)
    custom = current_custom(manager, chat_id, thread_id)
    if fmt == "photo":
        try:
            png = await asyncio.to_thread(rn.render_day, schedule, sub, date, theme_key,
                                          kras_today(), mode, custom)
            await query.edit_message_media(
                media=InputMediaPhoto(png, caption=rn.caption(schedule, sub, date), parse_mode="HTML"),
                reply_markup=day_keyboard(date))
            return
        except BadRequest:
            pass
        except Exception as exc:
            logging.warning("Не удалось обновить картинку дня: %s", exc)
        await send_day_message(bot, chat_id, thread_id, schedule, sub, date, fmt, theme_key,
                               mode, custom, keyboard=day_keyboard(date))
        return
    try:
        await query.edit_message_text(format_schedule(schedule, sub, date), parse_mode="HTML",
                                      reply_markup=day_keyboard(date))
        return
    except BadRequest:
        pass
    await send_day_message(bot, chat_id, thread_id, schedule, sub, date, fmt, theme_key,
                           mode, custom, keyboard=day_keyboard(date))


async def edit_week_view(query, bot, manager, chat_id, thread_id, schedule, sub, monday):
    fmt = current_format(manager, chat_id, thread_id) or DEFAULT_FORMAT
    theme_key = current_theme(manager, chat_id, thread_id)
    mode = current_mode(manager, chat_id, thread_id)
    custom = current_custom(manager, chat_id, thread_id)
    if fmt == "photo":
        try:
            png = await asyncio.to_thread(rn.render_week, schedule, sub, monday, theme_key, mode, custom)
            await query.edit_message_media(
                media=InputMediaPhoto(png, caption=rn.caption(schedule, sub, week=True), parse_mode="HTML"),
                reply_markup=week_keyboard())
            return
        except BadRequest:
            pass
        except Exception as exc:
            logging.warning("Не удалось обновить картинку недели: %s", exc)
        await send_week_message(bot, chat_id, thread_id, schedule, sub, monday, fmt, theme_key,
                                mode, custom, keyboard=week_keyboard())
        return
    try:
        await query.edit_message_text(format_week(schedule, sub, monday), parse_mode="HTML",
                                      reply_markup=week_keyboard())
        return
    except BadRequest:
        pass
    await send_week_message(bot, chat_id, thread_id, schedule, sub, monday, fmt, theme_key,
                            mode, custom, keyboard=week_keyboard())

def esc(value):
    return html.escape(str(value if value is not None else ""))

def dest_key(update):
    chat_id = update.effective_chat.id
    thread_id = 0
    message = update.effective_message
    if message is not None and getattr(message, "is_topic_message", False):
        thread_id = message.message_thread_id or 0
    return chat_id, thread_id

STORE = storage.StateStore()


def now_stamp():
    return datetime.datetime.now(KRASNOYARSK_TZ).isoformat()


def send_key(chat_id, thread_id, day):
    return "%s:%s:%s" % (chat_id, thread_id or 0, day)


class DatabaseManager:
    def __init__(self):
        STORE.ensure_loaded()

    def save_message(self, chat_id, user_id, message_id):
        with STORE.lock:
            messages = STORE.data["messages"]
            messages["%s:%s" % (chat_id, user_id)] = message_id
            extra = len(messages) - 2000
            if extra > 0:
                for key in list(messages.keys())[:extra]:
                    messages.pop(key, None)
            STORE.dirty = True

    def get_last_message(self, chat_id, user_id):
        with STORE.lock:
            return STORE.data["messages"].get("%s:%s" % (chat_id, user_id))

    def _find_sub(self, chat_id, thread_id):
        for sub in STORE.data["subscriptions"]:
            if int(sub.get("chat_id") or 0) == int(chat_id) and int(sub.get("thread_id") or 0) == int(thread_id or 0):
                return sub
        return None

    def set_group(self, chat_id, thread_id, group_id, group_name, user_id=None, chat_title=None):
        with STORE.lock:
            sub = self._find_sub(chat_id, thread_id)
            if sub is None:
                sub = {"id": STORE.data["next_sub_id"], "chat_id": chat_id, "thread_id": thread_id or 0,
                       "chat_title": chat_title, "group_id": None, "group_name": None,
                       "auto_enabled": 0, "created_by": user_id, "updated_at": now_stamp()}
                STORE.data["next_sub_id"] += 1
                STORE.data["subscriptions"].append(sub)
            sub["group_id"] = group_id
            sub["group_name"] = group_name
            if user_id is not None:
                sub["created_by"] = user_id
            if chat_title:
                sub["chat_title"] = chat_title
            sub["updated_at"] = now_stamp()
            STORE.dirty = True
        wake_auto()

    def get_subscription(self, chat_id, thread_id):
        with STORE.lock:
            sub = self._find_sub(chat_id, thread_id)
            return dict(sub) if sub else None

    def _settings_key(self, chat_id, thread_id):
        return "%s:%s" % (int(chat_id), int(thread_id or 0))

    def get_settings(self, chat_id, thread_id):
        with STORE.lock:
            settings = STORE.data.setdefault("settings", {})
            return dict(settings.get(self._settings_key(chat_id, thread_id)) or {})

    def set_setting(self, chat_id, thread_id, key, value):
        with STORE.lock:
            settings = STORE.data.setdefault("settings", {})
            name = self._settings_key(chat_id, thread_id)
            item = dict(settings.get(name) or {})
            item[key] = value
            settings[name] = item
            STORE.dirty = True

    def set_auto(self, chat_id, thread_id, enabled):
        with STORE.lock:
            sub = self._find_sub(chat_id, thread_id)
            if sub is None:
                return
            sub["auto_enabled"] = 1 if enabled else 0
            sub["updated_at"] = now_stamp()
            STORE.dirty = True
        wake_auto()

    def get_auto_subscriptions(self):
        with STORE.lock:
            return [dict(sub) for sub in STORE.data["subscriptions"]
                    if sub.get("auto_enabled") and sub.get("group_id")]

    def get_subscriptions_by(self, user_id):
        with STORE.lock:
            items = [sub for sub in STORE.data["subscriptions"] if sub.get("created_by") == user_id]
            items.sort(key=lambda sub: int(sub.get("id") or 0))
            return [dict(sub) for sub in items]

    def get_subscription_by_id(self, sub_id):
        with STORE.lock:
            for sub in STORE.data["subscriptions"]:
                if int(sub.get("id") or 0) == int(sub_id):
                    return dict(sub)
        return None

    def set_auto_by_id(self, sub_id, enabled):
        with STORE.lock:
            for sub in STORE.data["subscriptions"]:
                if int(sub.get("id") or 0) == int(sub_id):
                    sub["auto_enabled"] = 1 if enabled else 0
                    sub["updated_at"] = now_stamp()
                    STORE.dirty = True
                    wake_auto()
                    return

    def save_teacher(self, teacher_id, name):
        with STORE.lock:
            teachers = STORE.data["teachers"]
            teachers[str(teacher_id)] = name
            extra = len(teachers) - 500
            if extra > 0:
                for key in list(teachers.keys())[:extra]:
                    teachers.pop(key, None)
            STORE.dirty = True

    def get_teacher(self, teacher_id):
        with STORE.lock:
            return STORE.data["teachers"].get(str(teacher_id))

    def was_sent(self, chat_id, thread_id, day):
        with STORE.lock:
            return send_key(chat_id, thread_id, day) in STORE.data["sent"]

    def mark_sent(self, chat_id, thread_id, day):
        with STORE.lock:
            sent = STORE.data["sent"]
            sent[send_key(chat_id, thread_id, day)] = now_stamp()
            extra = len(sent) - 1000
            if extra > 0:
                for key in list(sent.keys())[:extra]:
                    sent.pop(key, None)
            STORE.dirty = True

def kras_today():
    return datetime.datetime.now(KRASNOYARSK_TZ).date()

def monday_of_week():
    today = kras_today()
    return today - datetime.timedelta(days=today.weekday())

def relative_day_label(date):
    delta = (date - kras_today()).days
    if delta == -1:
        word = "вчера"
    elif delta == 0:
        word = "сегодня"
    elif delta == 1:
        word = "завтра"
    else:
        word = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"][date.weekday()]
    return word + " " + date.strftime("%d.%m")

def day_keyboard(date):
    before = date - datetime.timedelta(days=1)
    after = date + datetime.timedelta(days=1)
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(relative_day_label(before), callback_data="d|" + before.isoformat()),
        InlineKeyboardButton(relative_day_label(after), callback_data="d|" + after.isoformat()),
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
        PENDING_GROUP[dest_key(update)] = time.time()
        rows = [[InlineKeyboardButton(g["name"], callback_data="g|" + g["name"])] for g in matches[:10]]
        msg = await update.message.reply_text(
            "Нашлось несколько групп, выберите кнопкой:",
            parse_mode='HTML', reply_markup=InlineKeyboardMarkup(rows))
    else:
        msg = await update.message.reply_text(
            f"Группа «{esc(query)}» не найдена." + FOOTER_LINK, parse_mode='HTML')
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
        "/sendnow N - принудительно отправить по номеру из /autosends\n"
        "/settings - формат, светлая или тёмная тема и картинка\n"
        "/theme_qr - импорт своей темы по QR из настроек сайта\n"
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
    chat_id, thread_id = dest_key(update)
    fmt = current_format(manager, chat_id, thread_id)
    if not fmt:
        await prompt_format(update, manager, "d|%s|%s" % (today.isoformat(), sub["group_id"]))
        return
    message = await send_day_message(context.bot, chat_id, thread_id, schedule, sub, today, fmt,
                                     current_theme(manager, chat_id, thread_id),
                                     current_mode(manager, chat_id, thread_id),
                                     current_custom(manager, chat_id, thread_id),
                                     keyboard=day_keyboard(today))
    manager.save_message(chat_id, update.effective_user.id, message.message_id)

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
    chat_id, thread_id = dest_key(update)
    fmt = current_format(manager, chat_id, thread_id)
    if not fmt:
        await prompt_format(update, manager, "d|%s|%s" % (tmr.isoformat(), sub["group_id"]))
        return
    message = await send_day_message(context.bot, chat_id, thread_id, schedule, sub, tmr, fmt,
                                     current_theme(manager, chat_id, thread_id),
                                     current_mode(manager, chat_id, thread_id),
                                     current_custom(manager, chat_id, thread_id),
                                     keyboard=day_keyboard(tmr))
    manager.save_message(chat_id, update.effective_user.id, message.message_id)

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
    chat_id, thread_id = dest_key(update)
    fmt = current_format(manager, chat_id, thread_id)
    if not fmt:
        await prompt_format(update, manager, "d|%s|%s" % (target.isoformat(), sub["group_id"]))
        return
    message = await send_day_message(context.bot, chat_id, thread_id, schedule, sub, target, fmt,
                                     current_theme(manager, chat_id, thread_id),
                                     current_mode(manager, chat_id, thread_id),
                                     current_custom(manager, chat_id, thread_id),
                                     keyboard=day_keyboard(target))
    manager.save_message(chat_id, update.effective_user.id, message.message_id)

@with_cleanup
async def week_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    chat_id, thread_id = dest_key(update)
    fmt = current_format(manager, chat_id, thread_id)
    if not fmt:
        await prompt_format(update, manager, "w|0|%s" % sub["group_id"])
        return
    message = await send_week_message(context.bot, chat_id, thread_id, schedule, sub, monday_of_week(), fmt,
                                      current_theme(manager, chat_id, thread_id),
                                      current_mode(manager, chat_id, thread_id),
                                      current_custom(manager, chat_id, thread_id),
                                      keyboard=week_keyboard())
    manager.save_message(chat_id, update.effective_user.id, message.message_id)

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
        rows = []
        for candidate in matches[:10]:
            rows.append([InlineKeyboardButton(candidate["name"], callback_data="g|" + candidate["name"])])
        msg = await update.message.reply_text(
            "Нашлось несколько групп, выберите кнопкой:",
            parse_mode='HTML', reply_markup=InlineKeyboardMarkup(rows))
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
        chat_id, thread_id = dest_key(update)
        fmt = current_format(manager, chat_id, thread_id) or DEFAULT_FORMAT
        message = await send_day_message(update.get_bot(), chat_id, thread_id, schedule, sub, today, fmt,
                                         current_theme(manager, chat_id, thread_id),
                                         current_mode(manager, chat_id, thread_id),
                                         current_custom(manager, chat_id, thread_id),
                                         keyboard=day_keyboard(today),
                                         header=f"Группа сохранена: {exact['name']}")
        manager.save_message(chat_id, update.effective_user.id, message.message_id)
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


def qr_file_of(message):
    if message.photo:
        return message.photo[-1]
    document = message.document
    if document and (document.mime_type or "").startswith("image/"):
        return document
    return None


@with_cleanup
async def theme_qr_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = DatabaseManager()
    chat_id, thread_id = dest_key(update)
    PENDING_QR[(chat_id, thread_id)] = time.time()
    msg = await update.message.reply_text(
        "<b>Импорт темы</b>\n\n"
        "Пришлите фото QR-кода темы. Его можно показать в настройках сайта кнопкой «QR темы».",
        parse_mode="HTML")
    manager.save_message(chat_id, update.effective_user.id, msg.message_id)


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id, thread_id = dest_key(update)
    asked_at = PENDING_QR.get((chat_id, thread_id))
    if not asked_at or (time.time() - asked_at) > GROUP_PROMPT_TTL:
        PENDING_QR.pop((chat_id, thread_id), None)
        return
    file = qr_file_of(update.message)
    if file is None:
        return
    manager = DatabaseManager()
    theme = None
    try:
        telegram_file = await file.get_file()
        data = await telegram_file.download_as_bytearray()
        theme = await asyncio.to_thread(ti.theme_from_qr, bytes(data))
    except Exception as exc:
        logging.warning("Не удалось прочитать QR темы: %s", exc)
    if not theme:
        msg = await update.message.reply_text(
            "QR не распознан или это не тема. Пришлите фото QR из настроек сайта ближе и без наклона.")
        manager.save_message(chat_id, update.effective_user.id, msg.message_id)
        return
    manager.set_setting(chat_id, thread_id, "custom_theme", theme)
    manager.set_setting(chat_id, thread_id, "theme", "custom")
    PENDING_QR.pop((chat_id, thread_id), None)
    msg = await update.message.reply_text(
        "<b>Тема из QR применена</b>\n\n" + settings_text(manager, chat_id, thread_id),
        parse_mode="HTML",
        reply_markup=settings_keyboard(manager, chat_id, thread_id))
    manager.save_message(chat_id, update.effective_user.id, msg.message_id)

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

    fmt = current_format(manager, chat_id, thread_id)
    text += f"Формат: {FORMATS[fmt] if fmt else 'спросим при первом запросе'}\n"
    text += f"Тема картинки: {rn.theme_label(current_theme(manager, chat_id, thread_id))}\n"

    health = await asyncio.to_thread(ss.check_site)
    text += (f"\nСайт расписания: {esc(health)}\n"
             f"Источник: {ss.source_label()}\n"
             f"Сборка: <code>{BUILD}</code>")
    text += group_link(sub.get("group_id") if sub else None,
                       sub.get("group_name") if sub else None)
    msg = await update.message.reply_text(text, parse_mode='HTML')
    manager.save_message(chat_id, update.effective_user.id, msg.message_id)

@with_cleanup
async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = DatabaseManager()
    chat_id, thread_id = dest_key(update)
    msg = await update.message.reply_text(
        settings_text(manager, chat_id, thread_id),
        parse_mode='HTML',
        reply_markup=settings_keyboard(manager, chat_id, thread_id))
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

    thread_info = f"\nТопик: <code>{target_thread}</code>" if target_thread else ""
    rows = [[
        InlineKeyboardButton("Картинкой", callback_data="sc|photo|%s|%s" % (target_chat, target_thread)),
        InlineKeyboardButton("Текстом", callback_data="sc|text|%s|%s" % (target_chat, target_thread))
    ]]
    msg = await update.message.reply_text(
        f"<b>Автоотправка</b>\n\n"
        f"Чат: <code>{target_chat}</code>{thread_info}\n"
        f"Группа: <code>{esc(sub['group_name'])}</code>\n\n"
        f"Как присылать расписание после последней пары?",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(rows))
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
            fmt = current_format(manager, sub["chat_id"], sub.get("thread_id") or 0)
            fmt_text = FORMATS[fmt] if fmt else "текстом"
            text += (f"{sub['id']}. {esc(describe_place(sub))} - "
                     f"{esc(sub.get('group_name') or 'без группы')} - {status} - {fmt_text}\n")
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
async def sendnow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager = DatabaseManager()
    user_id = update.effective_user.id
    args = list(context.args)
    if not args or not args[0].isdigit():
        msg = await update.message.reply_text(
            "Принудительная отправка по номеру из <code>/autosends</code>:\n"
            "<code>/sendnow 1</code> - расписание на завтра\n"
            "<code>/sendnow 1 today</code> - на сегодня" + FOOTER_LINK,
            parse_mode='HTML')
        manager.save_message(update.effective_chat.id, user_id, msg.message_id)
        return

    sub = manager.get_subscription_by_id(int(args[0]))
    if not sub or sub.get("created_by") != user_id:
        msg = await update.message.reply_text(
            "Автоотправка с таким номером не найдена.\n"
            "Список: <code>/autosends</code>" + FOOTER_LINK, parse_mode='HTML')
        manager.save_message(update.effective_chat.id, user_id, msg.message_id)
        return

    if not sub.get("group_id"):
        await reply_plain(update, manager, "У этой автоотправки не задана группа.")
        return

    mode = args[1].lower() if len(args) > 1 else "tomorrow"
    days = 0 if mode in ("today", "сегодня") else 1
    target = kras_today() + datetime.timedelta(days=days)

    schedule = get_schedule_or_none(sub["group_id"])
    if not schedule:
        await reply_plain(update, manager, "Не удалось получить расписание, попробуйте позже.")
        return

    try:
        await send_schedule_to(context.bot, sub, schedule, target)
    except Forbidden:
        await reply_plain(update, manager, "Бот заблокирован в том чате, отправить нельзя.")
        return
    except BadRequest as error:
        await reply_plain(update, manager, "Ошибка отправки: " + esc(error))
        return
    except Exception as error:
        await reply_plain(update, manager, "Ошибка отправки: " + esc(type(error).__name__ + ": " + str(error)))
        return

    thread_info = " (топик %s)" % sub["thread_id"] if sub.get("thread_id") else ""
    await reply_plain(update, manager,
                      "Отправлено в чат %s%s за %s.\nГруппа: %s" % (
                          sub["chat_id"], thread_info, target.strftime("%d.%m.%Y"),
                          esc(sub.get("group_name") or "")))

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

    if parts[0] == "s" and len(parts) >= 3:
        chat_id = query.message.chat_id
        thread_id = getattr(query.message, "message_thread_id", None) or 0
        manager = DatabaseManager()
        if parts[1] == "f" and parts[2] in FORMATS:
            manager.set_setting(chat_id, thread_id, "format", parts[2])
        elif parts[1] == "m" and parts[2] in MODES:
            manager.set_setting(chat_id, thread_id, "mode", parts[2])
        elif parts[1] == "t" and (parts[2] in rn.THEMES or
                                  (parts[2] == "custom" and manager.get_settings(chat_id, thread_id).get("custom_theme"))):
            manager.set_setting(chat_id, thread_id, "theme", parts[2])
        elif parts[1] == "q":
            PENDING_QR[(chat_id, thread_id)] = time.time()
            try:
                await query.edit_message_text(
                    "<b>Импорт темы</b>\n\n"
                    "Пришлите фото QR-кода темы. Его можно показать в настройках сайта кнопкой «QR темы».",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("Назад", callback_data="s|b|0")
                    ]]))
            except BadRequest:
                pass
            return
        elif parts[1] == "b":
            pass
        try:
            await query.edit_message_text(
                settings_text(manager, chat_id, thread_id),
                parse_mode="HTML",
                reply_markup=settings_keyboard(manager, chat_id, thread_id))
        except BadRequest:
            pass
        return

    if parts[0] == "f" and len(parts) >= 5:
        fmt = parts[1]
        kind = parts[2]
        value = parts[3]
        if fmt not in FORMATS:
            return
        try:
            group_id = int(parts[4])
        except ValueError:
            return
        chat_id = query.message.chat_id
        thread_id = getattr(query.message, "message_thread_id", None) or 0
        manager = DatabaseManager()
        manager.set_setting(chat_id, thread_id, "format", fmt)
        try:
            await query.edit_message_text("Формат: " + FORMATS[fmt])
        except BadRequest:
            pass
        schedule = get_schedule_or_none(group_id)
        if not schedule:
            await context.bot.send_message(chat_id, "Не удалось получить расписание, попробуйте позже.")
            return
        sub = manager.get_subscription(chat_id, thread_id) or {}
        if int(sub.get("group_id") or 0) != group_id:
            sub = {"group_id": group_id, "group_name": schedule.get("group_name") or ""}
        theme_key = current_theme(manager, chat_id, thread_id)
        mode = current_mode(manager, chat_id, thread_id)
        custom = current_custom(manager, chat_id, thread_id)
        try:
            if kind == "w":
                monday = monday_of_week() + datetime.timedelta(weeks=int(value))
                message = await send_week_message(context.bot, chat_id, thread_id, schedule, sub, monday,
                                                  fmt, theme_key, mode, custom, keyboard=week_keyboard())
            else:
                target = datetime.date.fromisoformat(value)
                message = await send_day_message(context.bot, chat_id, thread_id, schedule, sub, target,
                                                 fmt, theme_key, mode, custom, keyboard=day_keyboard(target))
        except Exception as exc:
            logging.warning("Не удалось отправить расписание после выбора формата: %s", exc)
            return
        user_id = query.from_user.id if query.from_user else 0
        manager.save_message(chat_id, user_id, message.message_id)
        return

    if parts[0] == "sc" and len(parts) >= 4:
        fmt = parts[1]
        if fmt not in FORMATS:
            return
        try:
            target_chat = int(parts[2])
            target_thread = int(parts[3])
        except ValueError:
            return
        manager = DatabaseManager()
        sub = manager.get_subscription(target_chat, target_thread)
        if not sub or not sub.get("group_id"):
            try:
                await query.edit_message_text("Для этого чата группа не задана.")
            except BadRequest:
                pass
            return
        if sub.get("created_by") and sub["created_by"] != query.from_user.id:
            try:
                await query.edit_message_text("Включить автоотправку может только тот, кто настроил этот чат.")
            except BadRequest:
                pass
            return
        manager.set_setting(target_chat, target_thread, "format", fmt)
        manager.set_auto(target_chat, target_thread, True)
        thread_info = f"\nТопик: <code>{target_thread}</code>" if target_thread else ""
        try:
            await query.edit_message_text(
                f"<b>Автоотправка включена</b>\n\n"
                f"Чат: <code>{target_chat}</code>{thread_info}\n"
                f"Группа: <code>{esc(sub['group_name'])}</code>\n"
                f"Формат: {FORMATS[fmt]}\n"
                f"Отправка: после последней пары бот присылает расписание на завтра\n"
                f"Выключить: <code>/disable_auto</code>"
                + group_link(sub.get("group_id"), sub.get("group_name")),
                parse_mode="HTML")
        except BadRequest:
            pass
        return

    if parts[0] == "d":
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
            target = datetime.date.fromisoformat(parts[1])
        except (ValueError, IndexError):
            return
        await edit_day_view(query, context.bot, manager, chat_id, thread_id, schedule, sub, target)
        return

    if parts[0] == "w":
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
            offset = int(parts[1])
        except (ValueError, IndexError):
            return
        target = monday_of_week() + datetime.timedelta(days=offset * 7)
        await edit_week_view(query, context.bot, manager, chat_id, thread_id, schedule, sub, target)
        return

    if parts[0] == "g":
        name = "|".join(parts[1:]).strip()
        chat_id = query.message.chat_id
        thread_id = getattr(query.message, "message_thread_id", None) or 0
        manager = DatabaseManager()
        try:
            exact, _ = await asyncio.to_thread(ss.find_group, name)
        except ss.ScheduleError:
            await query.edit_message_text("Не получилось проверить группу, попробуйте позже.")
            return
        if not exact:
            await query.edit_message_text("Группа не найдена. Напишите название точнее.")
            return
        title = getattr(query.message.chat, "title", None)
        manager.set_group(chat_id, thread_id, exact["id"], exact["name"], query.from_user.id, title)
        PENDING_GROUP.pop((chat_id, thread_id), None)
        schedule = get_schedule_or_none(exact["id"])
        if not schedule:
            await query.edit_message_text(
                f"<b>Группа сохранена: {esc(exact['name'])}</b>\n\nНе удалось получить расписание.",
                parse_mode="HTML")
            return
        today = kras_today()
        sub = {"group_id": exact["id"], "group_name": exact["name"]}
        text = (f"<b>Группа сохранена: {esc(exact['name'])}</b>\n\n"
                + format_schedule(schedule, sub, today))
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=day_keyboard(today))
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
    manager = DatabaseManager()
    chat_id = sub["chat_id"]
    thread_id = sub.get("thread_id") or 0
    fmt = current_format(manager, chat_id, thread_id) or DEFAULT_FORMAT
    theme_key = current_theme(manager, chat_id, thread_id)
    mode = current_mode(manager, chat_id, thread_id)
    custom = current_custom(manager, chat_id, thread_id)
    await send_day_message(bot, chat_id, thread_id, schedule, sub, date, fmt, theme_key, mode, custom)

def publish_trigger(schedule, day):
    end = ss.last_lesson_end_time(ss.lessons_for(schedule, day))
    if not end:
        for i in range(1, 8):
            prev = day - datetime.timedelta(days=i)
            prev_end = ss.last_lesson_end_time(ss.lessons_for(schedule, prev))
            if prev_end:
                end = prev_end
                break
    if not end:
        return None
    hour, minute = end
    return (KRASNOYARSK_TZ.localize(datetime.datetime.combine(day, datetime.time(hour, minute)))
            + datetime.timedelta(minutes=PUBLISH_DELAY_MINUTES))

async def auto_send_pass(app: Application):
    now = datetime.datetime.now(KRASNOYARSK_TZ)
    today = now.date()
    tomorrow = today + datetime.timedelta(days=1)
    manager = DatabaseManager()
    subs = manager.get_auto_subscriptions()
    if not subs:
        return None

    next_at = None
    retry_at = None
    for sub in subs:
        schedule = get_schedule_or_none(sub["group_id"])
        if not schedule:
            retry_at = now + datetime.timedelta(minutes=5)
            continue

        target = tomorrow.isoformat()
        if not manager.was_sent(sub["chat_id"], sub.get("thread_id"), target):
            trigger = publish_trigger(schedule, today)
            if trigger and now >= trigger:
                if now - trigger <= STALE_PUBLISH_LIMIT:
                    try:
                        await send_schedule_to(app.bot, sub, schedule, tomorrow)
                        manager.mark_sent(sub["chat_id"], sub.get("thread_id"), target)
                        thread_info = " (топик %s)" % sub["thread_id"] if sub.get("thread_id") else ""
                        logging.info("Автоотправка: отправлено в чат %s%s", sub["chat_id"], thread_info)
                    except Forbidden:
                        logging.warning("Автоотправка: бот заблокирован в чате %s, выключаем", sub["chat_id"])
                        manager.set_auto(sub["chat_id"], sub.get("thread_id"), False)
                    except BadRequest as e:
                        logging.warning("Автоотправка: ошибка отправки в чат %s: %s", sub["chat_id"], e)
                        retry_at = now + datetime.timedelta(minutes=5)
                    except Exception as e:
                        logging.error("Автоотправка: неожиданная ошибка %s: %s", type(e).__name__, e)
                        retry_at = now + datetime.timedelta(minutes=5)
                    await asyncio.sleep(1)
            elif trigger:
                next_at = trigger if next_at is None else min(next_at, trigger)

        future = publish_trigger(schedule, tomorrow)
        if future and future > now:
            next_at = future if next_at is None else min(next_at, future)

    if retry_at:
        next_at = retry_at if next_at is None else min(next_at, retry_at)
    return next_at

async def auto_send_loop(application: Application):
    while True:
        try:
            next_at = await auto_send_pass(application)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.error("Ошибка в цикле автоотправки: %s", e)
            next_at = None

        if next_at is None:
            pause = 3600
        else:
            seconds = (next_at - datetime.datetime.now(KRASNOYARSK_TZ)).total_seconds()
            pause = max(10, min(seconds, 43200))
            logging.info("Автоотправка: следующая отправка в %s (через %.0f мин)",
                         next_at.strftime("%d.%m %H:%M"), pause / 60)

        try:
            if AUTO_WAKE is None:
                await asyncio.sleep(pause)
            else:
                await asyncio.wait_for(AUTO_WAKE.wait(), timeout=pause)
        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            break
        if AUTO_WAKE is not None:
            AUTO_WAKE.clear()

async def post_init(application: Application):
    global AUTO_WAKE
    AUTO_WAKE = asyncio.Event()
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
        surname = (link.get("name") or "").split(" ")[0]
        if surname:
            parts.append(f'<a href="{ss.site_link(surname)}">{name}</a>')
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
                    if common.get("room"):
                        line += ", " + esc(common["room"])
                text += line + "\n"
            else:
                for lesson in group:
                    line = (f"{time_slot} | {esc(lesson['subgroup'])}: "
                            f"<b>{esc(lesson['subject'])}</b> ({esc(lesson['type'])})")
                    if kind == "professor":
                        who = entity_html(lesson, kind)
                        if who:
                            line += ", " + who
                        if lesson.get("room"):
                            line += ", " + esc(lesson["room"])
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
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("theme_qr", theme_qr_cmd))
    app.add_handler(CommandHandler("today", today_cmd))
    app.add_handler(CommandHandler("tomorrow", tomorrow_cmd))
    app.add_handler(CommandHandler("day", day_cmd))
    app.add_handler(CommandHandler("week", week_cmd))
    app.add_handler(CommandHandler("setchat", setchat_cmd))
    app.add_handler(CommandHandler("autosends", autosends_cmd))
    app.add_handler(CommandHandler("disable_auto", disable_auto_cmd))

    app.add_handler(CommandHandler("sendtext", sendtext_cmd))
    app.add_handler(CommandHandler("sendall", sendall_cmd))
    app.add_handler(CommandHandler(["sendnow", "testsend"], sendnow_cmd))

    app.add_handler(CommandHandler("exams", exams_cmd))
    app.add_handler(CommandHandler("nearexam", nearexam_cmd))
    app.add_handler(CommandHandler("consults", consults_cmd))
    app.add_handler(CommandHandler("prep", prep_cmd))

    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, photo_handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, group_text_handler))

    app.add_error_handler(error_handler)

    logging.info("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
