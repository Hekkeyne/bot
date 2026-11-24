import datetime
import html
import io
import os
from functools import lru_cache

import qrcode
from PIL import Image, ImageDraw, ImageFont
from qrcode.constants import ERROR_CORRECT_M

import schedule_source as ss

FONT_DIR = os.path.join(os.path.dirname(__file__), "assets", "fonts")
FONT_REGULAR = os.path.join(FONT_DIR, "PT_Sans-Web-Regular.ttf")
FONT_BOLD = os.path.join(FONT_DIR, "PT_Sans-Web-Bold.ttf")

DEFAULT = {
    "label": "Обычная",
    "bg": "#ffffff",
    "panel": "#ffffff",
    "ink": "#111318",
    "muted": "#6b7280",
    "line": "#e2e2e2",
    "edge": "#b6bdc9",
    "outline": "#111318",
    "on_ink": "#ffffff",
    "building": "#0f766e",
    "cabinet": "#7c3aed",
    "today": "#7c3aed",
    "radius": 0,
    "shadow": True
}

THEMES = {
    "default": dict(DEFAULT),
    "mono": dict(DEFAULT, label="Чёрно-белый", building="#262626", cabinet="#262626", today="#262626"),
    "pink": dict(DEFAULT, label="Пикми", bg="#fff5fa", line="#ffd6e7", edge="#ff9ec6", muted="#b06f8e",
                 building="#f472b6", cabinet="#c026d3", today="#ec4899", outline="#db2777"),
    "mint": dict(DEFAULT, label="Мята", bg="#f4fdf9", line="#d3ece2", edge="#8fcdb9", muted="#6f8f84",
                 building="#0d9488", cabinet="#0891b2", today="#0d9488", outline="#0f766e"),
    "lavender": dict(DEFAULT, label="Лаванда", bg="#faf7ff", line="#e4d9f7", edge="#b39ddb", muted="#8a7aa8",
                     building="#8b5cf6", cabinet="#c026d3", today="#8b5cf6", outline="#7c3aed"),
    "neon": dict(DEFAULT, label="Неон", bg="#f6f7ff", line="#d9dcf5", edge="#8e95d6", muted="#71759c",
                 building="#0891b2", cabinet="#7c3aed", today="#4f46e5", outline="#4f46e5"),
    "terminal": dict(DEFAULT, label="Терминал", bg="#f3fbf4", line="#cfe6d3", edge="#7fae88", muted="#5f7a64",
                     building="#15803d", cabinet="#047857", today="#15803d", outline="#15803d", shadow=False)
}

THEME_ORDER = ["default", "mono", "pink", "mint", "lavender", "neon", "terminal"]


def theme(name):
    return THEMES.get(name) or THEMES["default"]


def theme_label(name):
    return theme(name)["label"]


@lru_cache(maxsize=64)
def font(size, bold=False):
    path = FONT_BOLD if bold else FONT_REGULAR
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def text_width(draw, text, face):
    try:
        return draw.textlength(str(text), font=face)
    except Exception:
        return len(str(text)) * (getattr(face, "size", 10) * 0.55)


def wrap(draw, text, face, max_width):
    lines = []
    line = ""
    word = ""

    def flush():
        nonlocal line, word
        if not word:
            return
        test = (line + " " + word) if line else word
        if text_width(draw, test, face) <= max_width:
            line = test
            word = ""
            return
        if line:
            lines.append(line)
            line = ""
        if text_width(draw, word, face) <= max_width:
            line = word
            word = ""
            return
        chunk = ""
        for char in word:
            if chunk and text_width(draw, chunk + char, face) > max_width:
                lines.append(chunk)
                chunk = char
            else:
                chunk += char
        line = chunk
        word = ""

    for char in str(text or ""):
        if char.isspace():
            flush()
        else:
            word += char
    flush()
    if line:
        lines.append(line)
    return lines or [""]


def relative_luminance(color):
    value = str(color or "").lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    if len(value) != 6:
        return 0.0
    try:
        parts = [int(value[index:index + 2], 16) / 255 for index in (0, 2, 4)]
    except ValueError:
        return 0.0
    parts = [part / 12.92 if part <= 0.03928 else ((part + 0.055) / 1.055) ** 2.4 for part in parts]
    return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2]


def qr_color(th):
    return th["outline"] if 1.05 / (relative_luminance(th["outline"]) + 0.05) >= 3 else "#000000"


def qr_image(url, size, color):
    qr = qrcode.QRCode(border=2, box_size=8, error_correction=ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color=color, back_color="#ffffff").convert("RGB")
    return image.resize((size, size), Image.NEAREST)


def card(draw, x, y, width, height, th):
    radius = int(th.get("radius") or 0)
    if th.get("shadow", True):
        draw.rounded_rectangle([x + 4, y + 4, x + width + 4, y + height + 4], radius=radius, fill=th["edge"])
    draw.rounded_rectangle([x, y, x + width, y + height], radius=radius, fill=th["panel"],
                           outline=th["line"], width=2)


def draw_text(draw, x, y, text, face, color):
    draw.text((x, y), str(text or ""), font=face, fill=color, anchor="lt")


def teachers_of(item):
    return ", ".join(person.get("name", "") for person in (item.get("teacher_links") or []) if person.get("name"))


def caption(schedule, sub, date=None, week=False):
    group = sub.get("group_name") or schedule.get("group_name") or ""
    group_id = sub.get("group_id") or schedule.get("group_id")
    if week:
        title = "Расписание на неделю"
    else:
        title = "Расписание на " + date.strftime("%d.%m.%Y")
    ours = ss.site_link(group) if group else ss.SITE_URL
    pallada = ss.pallada_link(group_id)
    return (f"<b>{html.escape(title)}</b>\n"
            f"{html.escape(group)}\n\n"
            f'<a href="{ours}">Полное расписание на нашем сайте</a>\n'
            f'<a href="{pallada}">Полное расписание Паллада СибГУ</a>')


def qr_url(sub):
    group = sub.get("group_name") or ""
    return ss.site_link(group) if group else ss.SITE_URL


def render_day(schedule, sub, date, theme_key="default", today=None):
    th = theme(theme_key)
    width = 1800
    pad = 60
    inner = width - pad * 2
    time_width = 156
    part_x = pad + 28 + time_width
    part_width = inner - time_width - 28
    lessons = ss.lessons_for(schedule, date)
    measure = ImageDraw.Draw(Image.new("RGB", (10, 10), th["bg"]))

    slots = []
    grouped = {}
    for lesson in lessons:
        grouped.setdefault(lesson.get("time", ""), []).append(lesson)
    for key in sorted(grouped.keys(), key=lambda value: value.split("-")[0]):
        slots.append((key, grouped[key]))

    def part_height(item):
        height = len(wrap(measure, item.get("subject", ""), font(30, True), part_width)) * 38 + 34
        if item.get("room"):
            height += 34
        if teachers_of(item):
            height += 32
        return height

    height = pad + 108 + 68
    for _, items in slots:
        right = sum(part_height(item) + 12 for item in items)
        height += max(44, right) + 44 + 20
    if not slots:
        height += 84
    height += 28
    footer_top = height - 12
    height += 32

    image = Image.new("RGB", (width, height), th["bg"])
    draw = ImageDraw.Draw(image)

    draw_text(draw, pad, pad, "Расписание", font(48, True), th["ink"])
    title_width = text_width(draw, "Расписание", font(48, True))
    draw_text(draw, pad + title_width + 20, pad + 16, sub.get("group_name") or "", font(28), th["muted"])
    image.paste(qr_image(qr_url(sub), 100, qr_color(th)), (width - pad - 100, pad - 4))

    y = pad + 108
    is_today = date == (today or datetime.date.today())
    day_color = th["today"] if is_today else th["ink"]
    draw.rounded_rectangle([pad, y, pad + 480, y + 52], radius=int(th.get("radius") or 0), fill=day_color)
    draw_text(draw, pad + 20, y + 12, ss.WEEKDAYS_RU[ss.WEEKDAYS[date.weekday()]], font(26, True), th["on_ink"])
    draw_text(draw, pad + 300, y + 16, date.strftime("%d.%m"), font(22), th["on_ink"])
    draw.line([pad, y + 52, width - pad, y + 52], fill=th["line"], width=2)
    y += 68

    if not slots:
        card(draw, pad, y, inner, 64, th)
        draw_text(draw, pad + 28, y + 18, "нет пар", font(26), th["muted"])
        y += 84
    else:
        for time_slot, items in slots:
            right = sum(part_height(item) + 12 for item in items)
            card_height = max(44, right) + 44
            card(draw, pad, y, inner, card_height, th)
            parts = str(time_slot or "").split("-")
            draw_text(draw, pad + 28, y + 24, parts[0] if parts else "", font(24, True), th["muted"])
            draw_text(draw, pad + 28, y + 54, parts[1] if len(parts) > 1 else "", font(22), th["muted"])
            py = y + 24
            for item in items:
                lines = wrap(draw, item.get("subject", ""), font(30, True), part_width)
                for line in lines:
                    draw_text(draw, part_x, py, line, font(30, True), th["ink"])
                    py += 38
                draw_text(draw, part_x, py, item.get("type", ""), font(24), th["muted"])
                py += 34
                if item.get("room"):
                    draw_text(draw, part_x, py, item["room"], font(24), th["building"])
                    py += 34
                teachers = teachers_of(item)
                if teachers:
                    draw_text(draw, part_x, py, teachers, font(22), th["muted"])
                    py += 32
                py += 12
            y += card_height + 20
        y += 28

    draw_text(draw, pad, footer_top, "hekkeyne.ru/timetable", font(22), th["muted"])
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def render_week(schedule, sub, monday, theme_key="default"):
    th = theme(theme_key)
    width = 3000
    pad = 96
    gap = 32
    col_width = (width - pad * 2 - gap * 3) / 4
    text_width_value = col_width - 40
    days = [monday + datetime.timedelta(days=index) for index in range(7)]

    measure = ImageDraw.Draw(Image.new("RGB", (10, 10), th["bg"]))

    def lesson_height(item):
        height = len(wrap(measure, item.get("subject", ""), font(24, True), text_width_value)) * 28
        if item.get("subgroup") and item["subgroup"] != "все":
            height += 22
        meta = ", ".join(part for part in (item.get("type"), item.get("room")) if part)
        height += len(wrap(measure, meta, font(18), text_width_value)) * 22
        if teachers_of(item):
            height += 22
        return height + 8

    def day_height(day):
        slots = []
        grouped = {}
        for lesson in ss.lessons_for(schedule, day):
            grouped.setdefault(lesson.get("time", ""), []).append(lesson)
        for key in sorted(grouped.keys(), key=lambda value: value.split("-")[0]):
            slots.append((key, grouped[key]))
        height = 76
        if not slots:
            return height + 52
        for _, items in slots:
            height += 26
            for item in items:
                height += lesson_height(item)
            height += 4
        return height + 16

    def draw_day(day, x, y, card_width, card_height):
        card(draw, x, y, card_width, card_height, th)
        draw.rounded_rectangle([x + 20, y + 20, x + card_width - 20, y + 64],
                               radius=int(th.get("radius") or 0), fill=th["ink"])
        draw_text(draw, x + 36, y + 28, ss.WEEKDAYS_RU[ss.WEEKDAYS[day.weekday()]], font(24, True), th["on_ink"])
        py = y + 76
        grouped = {}
        for lesson in ss.lessons_for(schedule, day):
            grouped.setdefault(lesson.get("time", ""), []).append(lesson)
        slots = [(key, grouped[key]) for key in sorted(grouped.keys(), key=lambda value: value.split("-")[0])]
        if not slots:
            draw_text(draw, x + 20, py, "нет пар", font(22), th["muted"])
            return
        for time_slot, items in slots:
            draw_text(draw, x + 20, py, time_slot, font(18, True), th["muted"])
            py += 26
            for item in items:
                if item.get("subgroup") and item["subgroup"] != "все":
                    draw_text(draw, x + 20, py, item["subgroup"], font(18), th["muted"])
                    py += 22
                lines = wrap(draw, item.get("subject", ""), font(24, True), text_width_value)
                for line in lines:
                    draw_text(draw, x + 20, py, line, font(24, True), th["ink"])
                    py += 28
                meta = ", ".join(part for part in (item.get("type"), item.get("room")) if part)
                for line in wrap(draw, meta, font(18), text_width_value):
                    draw_text(draw, x + 20, py, line, font(18), th["muted"])
                    py += 22
                teachers = teachers_of(item)
                if teachers:
                    draw_text(draw, x + 20, py, teachers, font(16), th["muted"])
                    py += 22
                py += 8
            py += 4

    row_one = days[:3]
    row_two = days[3:6]
    sunday = days[6]
    row_one_height = max(day_height(day) for day in row_one)
    row_two_height = max(day_height(day) for day in row_two)
    grid_top = pad + 108
    grid_height = max(row_one_height + gap + row_two_height, day_height(sunday))
    footer_top = grid_top + grid_height + 16
    height = footer_top + 40

    image = Image.new("RGB", (width, height), th["bg"])
    draw = ImageDraw.Draw(image)

    draw_text(draw, pad, pad, "Расписание", font(48, True), th["ink"])
    title_width = text_width(draw, "Расписание", font(48, True))
    draw_text(draw, pad + title_width + 20, pad + 16, sub.get("group_name") or "", font(28), th["muted"])
    image.paste(qr_image(qr_url(sub), 100, qr_color(th)), (width - pad - 100, pad - 4))

    for index, day in enumerate(row_one):
        draw_day(day, pad + index * (col_width + gap), grid_top, col_width, row_one_height)
    for index, day in enumerate(row_two):
        draw_day(day, pad + index * (col_width + gap), grid_top + row_one_height + gap, col_width, row_two_height)
    draw_day(sunday, pad + 3 * (col_width + gap), grid_top, col_width, grid_height)

    draw_text(draw, pad, footer_top, "hekkeyne.ru/timetable", font(22), th["muted"])
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
