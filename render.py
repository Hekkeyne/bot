import datetime
import html
import io
import ipaddress
import os
import socket
from functools import lru_cache
from urllib.parse import urljoin, urlparse

import qrcode
import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps
from qrcode.constants import ERROR_CORRECT_M

import schedule_source as ss
import admin_changes as ac

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

DARK_THEMES = {
    "default": {
        "bg": "#17191d", "panel": "#17191d", "ink": "#e7e9ee", "muted": "#9aa2ad",
        "line": "#2b2f36", "edge": "#0d0f13", "outline": "#9aa2ad", "on_ink": "#14161a",
        "building": "#2dd4bf", "cabinet": "#a78bfa", "today": "#8b5cf6"
    },
    "mono": {
        "bg": "#111111", "panel": "#181818", "ink": "#f4f4f5", "muted": "#a1a1aa",
        "line": "#2e2e2e", "edge": "#000000", "outline": "#d4d4d8", "on_ink": "#111111",
        "building": "#d4d4d8", "cabinet": "#d4d4d8", "today": "#d4d4d8"
    },
    "pink": {
        "bg": "#1d1017", "panel": "#24131d", "ink": "#fbe7f2", "muted": "#c78fa8",
        "line": "#402231", "edge": "#120a0f", "outline": "#f9a8d4", "on_ink": "#1d1017",
        "building": "#f9a8d4", "cabinet": "#e879f9", "today": "#f472b6"
    },
    "mint": {
        "bg": "#0e1513", "panel": "#151f1c", "ink": "#e6f7f0", "muted": "#8fb3a8",
        "line": "#24352f", "edge": "#08100d", "outline": "#6ee7b7", "on_ink": "#0e1513",
        "building": "#2dd4bf", "cabinet": "#22d3ee", "today": "#2dd4bf"
    },
    "lavender": {
        "bg": "#120f19", "panel": "#1a1526", "ink": "#f1eaff", "muted": "#a89cc4",
        "line": "#2f2743", "edge": "#0b0911", "outline": "#c4b5fd", "on_ink": "#120f19",
        "building": "#c4b5fd", "cabinet": "#e879f9", "today": "#a78bfa"
    },
    "neon": {
        "bg": "#07070d", "panel": "#0d0d17", "ink": "#e7e9ff", "muted": "#8b8bb5",
        "line": "#1e1e33", "edge": "#030306", "outline": "#a3e635", "on_ink": "#07070d",
        "building": "#a3e635", "cabinet": "#e879f9", "today": "#a3e635"
    },
    "terminal": {
        "bg": "#000000", "panel": "#070b07", "ink": "#d8f5dd", "muted": "#5f9a5f",
        "line": "#122012", "edge": "#000000", "outline": "#4ade80", "on_ink": "#000000",
        "building": "#4ade80", "cabinet": "#86efac", "today": "#22c55e", "shadow": False
    }
}


def theme(name, mode="light", custom=None):
    if name == "custom" and isinstance(custom, dict):
        base = dict(DEFAULT)
        if mode == "dark":
            base.update(DARK_THEMES["default"])
        base.update(custom.get(mode) or {})
        base["label"] = custom.get("label") or "Своя"
        base["bgImage"] = base.get("bgImage") or custom.get("bgImage") or ""
        base["panelImage"] = base.get("panelImage") or custom.get("panelImage") or ""
        return base
    base = dict(THEMES.get(name) or THEMES["default"])
    if mode == "dark":
        base.update(DARK_THEMES.get(name) or DARK_THEMES["default"])
    return base


def theme_label(name, custom=None):
    if name == "custom" and isinstance(custom, dict):
        return custom.get("label") or "Своя"
    return THEMES.get(name, THEMES["default"])["label"]


BACKGROUND_CACHE = {}


def safe_image_url(url):
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, ValueError):
        return False
    if not infos:
        return False
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if address.version == 6 and address.ipv4_mapped:
            address = address.ipv4_mapped
        if (address.is_private or address.is_loopback or address.is_link_local
                or address.is_reserved or address.is_multicast or address.is_unspecified):
            return False
    return True


def fetch_image(url):
    current = str(url or "").strip()
    for _ in range(4):
        if not safe_image_url(current):
            return None
        try:
            with requests.get(current, timeout=6, stream=True, allow_redirects=False,
                              headers={"User-Agent": "Mozilla/5.0"}) as response:
                if response.is_redirect:
                    location = response.headers.get("Location")
                    if not location:
                        return None
                    current = urljoin(current, location)
                    continue
                if response.status_code != 200:
                    return None
                content_type = (response.headers.get("Content-Type") or "").lower()
                if not content_type.startswith("image/"):
                    return None
                data = bytearray()
                for chunk in response.iter_content(65536):
                    data.extend(chunk)
                    if len(data) > 8 * 1024 * 1024:
                        return None
                return bytes(data)
        except requests.RequestException:
            return None
    return None


def background_image(url):
    value = str(url or "").strip()
    if not value:
        return None
    if value in BACKGROUND_CACHE:
        return BACKGROUND_CACHE[value]
    data = fetch_image(value)
    if not data:
        return None
    try:
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > 40000000:
            return None
        image = image.convert("RGB")
        image.load()
    except Exception:
        return None
    if len(BACKGROUND_CACHE) >= 8:
        BACKGROUND_CACHE.pop(next(iter(BACKGROUND_CACHE)))
    BACKGROUND_CACHE[value] = image
    return image


def cover_image(image, width, height):
    return ImageOps.fit(image, (width, height), method=Image.LANCZOS, centering=(0.5, 0.5))


def canvas_for(th, width, height):
    background = background_image(th.get("bgImage"))
    if background is not None:
        return cover_image(background, width, height)
    return Image.new("RGB", (width, height), th["bg"])


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


def card(draw, x, y, width, height, th, image=None):
    radius = int(th.get("radius") or 0)
    if th.get("shadow", True):
        draw.rounded_rectangle([x + 4, y + 4, x + width + 4, y + height + 4], radius=radius, fill=th["edge"])
    draw.rounded_rectangle([x, y, x + width, y + height], radius=radius, fill=th["panel"],
                           outline=th["line"], width=2)
    panel_url = th.get("panelImage")
    if image is not None and panel_url:
        panel = background_image(panel_url)
        if panel is not None:
            box_width = max(1, int(round(width)))
            box_height = max(1, int(round(height)))
            fitted = cover_image(panel, box_width, box_height)
            mask = Image.new("L", (box_width, box_height), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, box_width, box_height], radius=radius, fill=255)
            image.paste(fitted, (int(round(x)), int(round(y))), mask)
            draw.rounded_rectangle([x, y, x + width, y + height], radius=radius, outline=th["line"], width=2)


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


def render_day(schedule, sub, date, theme_key="default", today=None, mode="light", custom=None):
    th = theme(theme_key, mode, custom)
    kind = schedule.get("kind") or "group"
    view = ac.day_view(schedule, date, kind)
    slots = ac.slots(view)
    width = 1800
    pad = 60
    inner = width - pad * 2
    time_width = 156
    part_x = pad + 28 + time_width
    part_width = inner - time_width - 28
    strike = "#f87171" if mode == "dark" else "#dc2626"
    added = "#4ade80" if mode == "dark" else "#16a34a"
    measure = ImageDraw.Draw(Image.new("RGB", (10, 10), th["bg"]))

    def teachers_line(item):
        return ", ".join(person.get("name") or "" for person in (item.get("teachers") or []) if person.get("name"))

    def lesson_height(item, subgroup_changed=False):
        height = len(wrap(measure, item.get("subject", ""), font(30, True), part_width)) * 38 + 34
        if (item.get("subgroup") and item["subgroup"] != "все") or subgroup_changed:
            height += 30
        if item.get("room"):
            height += 34
        if teachers_line(item):
            height += 32
        return height

    def old_height(item):
        height = len(wrap(measure, item.get("subject", ""), font(24, True), part_width)) * 30 + 8
        if item.get("subgroup") and item["subgroup"] != "все":
            height += 28
        meta = ", ".join(part for part in (item.get("type"), item.get("room")) if part)
        height += len(wrap(measure, meta, font(20), part_width)) * 26
        if teachers_line(item):
            height += 26
        return height + 10

    def comment_height(text):
        return len(wrap(measure, text, font(20), part_width - 20)) * 28 + 16 if text else 0

    def entry_height(entry):
        op = entry["op"]
        old = entry.get("old")
        new = entry.get("new")
        if op == "normal":
            return lesson_height(new)
        if op == "add":
            return lesson_height(new) + 30
        if op == "remove":
            return old_height(old) + comment_height(entry.get("comment"))
        if entry.get("partial"):
            fields = entry.get("fields") or []
            height = lesson_height(new, "subgroup" in fields)
            if any(field != "subgroup" for field in fields):
                height += 30
            return height + comment_height(entry.get("comment"))
        return old_height(old) + lesson_height(new) + comment_height(entry.get("comment"))

    def strike_text(target, x, y, text, face, color):
        line_width = text_width(target, text, face)
        size = getattr(face, "size", 20)
        target.line([x, y + size * 0.62, x + line_width, y + size * 0.62], fill=color, width=max(1, int(size / 14)))

    def draw_lesson(item, px, py, subgroup_changed=False, old_subgroup=""):
        subgroup = item.get("subgroup") if item.get("subgroup") and item["subgroup"] != "все" else ""
        if subgroup_changed:
            old = old_subgroup or "все"
            draw_text(draw, px, py, old, font(22), strike)
            strike_text(draw, px, py, old, font(22), strike)
            if subgroup:
                draw_text(draw, px + text_width(draw, old, font(22)) + 10, py, subgroup, font(22), th["ink"])
            py += 30
        elif subgroup:
            draw_text(draw, px, py, subgroup, font(22), th["muted"])
            py += 30
        lines = wrap(draw, item.get("subject", ""), font(30, True), part_width)
        for line in lines:
            draw_text(draw, px, py, line, font(30, True), th["ink"])
            py += 38
        draw_text(draw, px, py, item.get("type", ""), font(24), th["muted"])
        py += 34
        if item.get("room"):
            draw_text(draw, px, py, item["room"], font(24), th["building"])
            py += 34
        teachers = teachers_line(item)
        if teachers:
            draw_text(draw, px, py, teachers, font(22), th["muted"])
            py += 32
        return py + 12

    def draw_old(item, px, py):
        if item.get("subgroup") and item["subgroup"] != "все":
            draw_text(draw, px, py, item["subgroup"], font(20), strike)
            strike_text(draw, px, py, item["subgroup"], font(20), strike)
            py += 28
        for line in wrap(draw, item.get("subject", ""), font(24, True), part_width):
            draw_text(draw, px, py, line, font(24, True), strike)
            strike_text(draw, px, py, line, font(24, True), strike)
            py += 30
        meta = ", ".join(part for part in (item.get("type"), item.get("room")) if part)
        for line in wrap(draw, meta, font(20), part_width):
            draw_text(draw, px, py, line, font(20), strike)
            strike_text(draw, px, py, line, font(20), strike)
            py += 26
        teachers = teachers_line(item)
        if teachers:
            draw_text(draw, px, py, teachers, font(20), strike)
            strike_text(draw, px, py, teachers, font(20), strike)
            py += 26
        return py + 10

    def draw_comment(text, x, y):
        if not text:
            return y
        lines = wrap(draw, text, font(20), part_width - 20)
        height = len(lines) * 28 + 16
        draw.rounded_rectangle([x, y, x + part_width, y + height], radius=int(th.get("radius") or 0),
                               fill=th["panel"], outline=th["line"], width=2)
        py = y + 8
        for line in lines:
            draw_text(draw, x + 10, py, line, font(20), th["ink"])
            py += 28
        return y + height

    def draw_entry(entry, px, py):
        op = entry["op"]
        old = entry.get("old")
        new = entry.get("new")
        if op == "normal":
            return draw_lesson(new, px, py)
        if op == "add":
            draw_text(draw, px, py, "новая пара", font(22, True), added)
            py += 30
            return draw_lesson(new, px, py)
        if op == "remove":
            py = draw_old(old, px, py)
            if entry.get("comment"):
                py = draw_comment(entry["comment"], px, py) + 10
            return py
        if entry.get("partial"):
            fields = entry.get("fields") or []
            py = draw_lesson(new, px, py, "subgroup" in fields, (old or {}).get("subgroup") or "")
            parts = []
            if "time" in fields and old.get("time"):
                parts.append(old["time"])
            if "room" in fields and old.get("room"):
                parts.append(old["room"])
            if "teacher" in fields and old.get("teacher"):
                parts.append(old["teacher"])
            if parts:
                text = "было: " + ", ".join(parts)
                draw_text(draw, px, py, text, font(20), strike)
                strike_text(draw, px, py, text, font(20), strike)
                py += 30
            if entry.get("comment"):
                py = draw_comment(entry["comment"], px, py) + 10
            return py
        py = draw_old(old, px, py)
        py = draw_lesson(new, px, py)
        if entry.get("comment"):
            py = draw_comment(entry["comment"], px, py) + 10
        return py

    height = pad + 108 + 68
    if view["removed"]:
        height += 120 + comment_height(view["comment"])
    elif not slots:
        height += 84
    else:
        for _, entries in slots:
            right = sum(entry_height(entry) + 12 for entry in entries)
            height += max(44, right) + 44 + 20
    if view["comment"] and not view["removed"]:
        height += comment_height(view["comment"]) + 20
    height += 28
    footer_top = height - 12
    height += 32

    image = canvas_for(th, width, height)
    draw = ImageDraw.Draw(image)

    draw_text(draw, pad, pad, "Расписание", font(48, True), th["ink"])
    title_width = text_width(draw, "Расписание", font(48, True))
    draw_text(draw, pad + title_width + 20, pad + 16, sub.get("group_name") or "", font(28), th["muted"])
    image.paste(qr_image(qr_url(sub), 100, qr_color(th)), (width - pad - 100, pad - 4))

    y = pad + 108
    is_today = date == (today or datetime.date.today())
    day_color = th["today"] if is_today else th["ink"]
    draw.rounded_rectangle([pad, y, pad + 480, y + 52], radius=int(th.get("radius") or 0), fill=day_color)
    day_name = ss.WEEKDAYS_RU[ss.WEEKDAYS[date.weekday()]]
    draw_text(draw, pad + 20, y + 12, day_name, font(26, True), th["on_ink"])
    if view["removed"]:
        strike_text(draw, pad + 20, y + 12, day_name, font(26, True), strike)
    draw_text(draw, pad + 300, y + 16, date.strftime("%d.%m"), font(22), th["on_ink"])
    draw.line([pad, y + 52, width - pad, y + 52], fill=th["line"], width=2)
    y += 68

    if view["removed"]:
        card(draw, pad, y, inner, 64, th, image)
        draw_text(draw, pad + 28, y + 18, "пар нет", font(26), th["muted"])
        y += 84
        if view["comment"]:
            y = draw_comment(view["comment"], pad + 28, y) + 20
    elif not slots:
        card(draw, pad, y, inner, 64, th, image)
        draw_text(draw, pad + 28, y + 18, "нет пар", font(26), th["muted"])
        y += 84
    else:
        for time_slot, entries in slots:
            right = sum(entry_height(entry) + 12 for entry in entries)
            card_height = max(44, right) + 44
            card(draw, pad, y, inner, card_height, th, image)
            parts = str(time_slot or "").split("-")
            draw_text(draw, pad + 28, y + 24, parts[0] if parts else "", font(24, True), th["muted"])
            draw_text(draw, pad + 28, y + 54, parts[1] if len(parts) > 1 else "", font(22), th["muted"])
            py = y + 24
            for entry in entries:
                py = draw_entry(entry, part_x, py)
            y += card_height + 20
        if view["comment"]:
            y = draw_comment(view["comment"], pad + 28, y + 8) + 20
        y += 8

    draw_text(draw, pad, footer_top, "hekkeyne.ru/timetable", font(22), th["muted"])
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()

def render_week(schedule, sub, monday, theme_key="default", mode="light", custom=None):
    th = theme(theme_key, mode, custom)
    kind = schedule.get("kind") or "group"
    width = 3000
    pad = 96
    gap = 32
    col_width = (width - pad * 2 - gap * 3) / 4
    text_width_value = col_width - 40
    days = [monday + datetime.timedelta(days=index) for index in range(7)]
    strike = "#f87171" if mode == "dark" else "#dc2626"
    added = "#4ade80" if mode == "dark" else "#16a34a"
    measure = ImageDraw.Draw(Image.new("RGB", (10, 10), th["bg"]))

    def teachers_of(item):
        return ", ".join(person.get("name") or "" for person in (item.get("teachers") or []) if person.get("name"))

    def lesson_height(item, subgroup_changed=False):
        height = len(wrap(measure, item.get("subject", ""), font(24, True), text_width_value)) * 28
        if (item.get("subgroup") and item["subgroup"] != "все") or subgroup_changed:
            height += 22
        meta = ", ".join(part for part in (item.get("type"), item.get("room")) if part)
        height += len(wrap(measure, meta, font(18), text_width_value)) * 22
        if teachers_of(item):
            height += 22
        return height + 8

    def old_height(item):
        height = len(wrap(measure, item.get("subject", ""), font(20, True), text_width_value)) * 24
        if item.get("subgroup") and item["subgroup"] != "все":
            height += 18
        meta = ", ".join(part for part in (item.get("type"), item.get("room")) if part)
        height += len(wrap(measure, meta, font(16), text_width_value)) * 18
        if teachers_of(item):
            height += 18
        return height + 6

    def comment_height(text):
        return len(wrap(measure, text, font(16), text_width_value)) * 18 + 6 if text else 0

    def entry_height(entry):
        op = entry["op"]
        old = entry.get("old")
        new = entry.get("new")
        if op == "normal":
            return lesson_height(new)
        if op == "add":
            return lesson_height(new) + 18
        if op == "remove":
            return old_height(old) + comment_height(entry.get("comment"))
        if entry.get("partial"):
            fields = entry.get("fields") or []
            height = lesson_height(new, "subgroup" in fields)
            if any(field != "subgroup" for field in fields):
                height += 18
            return height + comment_height(entry.get("comment"))
        return old_height(old) + lesson_height(new) + comment_height(entry.get("comment"))

    def strike_line(target, x, y, text, face, color):
        line_width = text_width(target, text, face)
        size = getattr(face, "size", 18)
        target.line([x, y + size * 0.62, x + line_width, y + size * 0.62], fill=color, width=max(1, int(size / 16)))

    def draw_item(item, x, py, subgroup_changed=False, old_subgroup=""):
        subgroup = item.get("subgroup") if item.get("subgroup") and item["subgroup"] != "все" else ""
        if subgroup_changed:
            old = old_subgroup or "все"
            draw_text(draw, x, py, old, font(18), strike)
            strike_line(draw, x, py, old, font(18), strike)
            if subgroup:
                draw_text(draw, x + text_width(draw, old, font(18)) + 8, py, subgroup, font(18), th["ink"])
            py += 22
        elif subgroup:
            draw_text(draw, x, py, subgroup, font(18), th["muted"])
            py += 22
        for line in wrap(draw, item.get("subject", ""), font(24, True), text_width_value):
            draw_text(draw, x, py, line, font(24, True), th["ink"])
            py += 28
        meta = ", ".join(part for part in (item.get("type"), item.get("room")) if part)
        for line in wrap(draw, meta, font(18), text_width_value):
            draw_text(draw, x, py, line, font(18), th["muted"])
            py += 22
        teachers = teachers_of(item)
        if teachers:
            draw_text(draw, x, py, teachers, font(16), th["muted"])
            py += 22
        return py + 8

    def draw_old(item, x, py):
        if item.get("subgroup") and item["subgroup"] != "все":
            draw_text(draw, x, py, item["subgroup"], font(16), strike)
            strike_line(draw, x, py, item["subgroup"], font(16), strike)
            py += 18
        for line in wrap(draw, item.get("subject", ""), font(20, True), text_width_value):
            draw_text(draw, x, py, line, font(20, True), strike)
            strike_line(draw, x, py, line, font(20, True), strike)
            py += 24
        meta = ", ".join(part for part in (item.get("type"), item.get("room")) if part)
        for line in wrap(draw, meta, font(16), text_width_value):
            draw_text(draw, x, py, line, font(16), strike)
            strike_line(draw, x, py, line, font(16), strike)
            py += 18
        teachers = teachers_of(item)
        if teachers:
            draw_text(draw, x, py, teachers, font(16), strike)
            strike_line(draw, x, py, teachers, font(16), strike)
            py += 18
        return py + 6

    def draw_comment(text, x, py):
        if not text:
            return py
        for line in wrap(draw, text, font(16), text_width_value):
            draw_text(draw, x, py, line, font(16), th["ink"])
            py += 18
        return py + 4

    def draw_entry(entry, x, py):
        op = entry["op"]
        old = entry.get("old")
        new = entry.get("new")
        if op == "normal":
            return draw_item(new, x, py)
        if op == "add":
            draw_text(draw, x, py, "новая пара", font(16, True), added)
            py += 18
            return draw_item(new, x, py)
        if op == "remove":
            py = draw_old(old, x, py)
            return draw_comment(entry.get("comment"), x, py)
        if entry.get("partial"):
            fields = entry.get("fields") or []
            py = draw_item(new, x, py, "subgroup" in fields, (old or {}).get("subgroup") or "")
            parts = []
            if "time" in fields and old.get("time"):
                parts.append(old["time"])
            if "room" in fields and old.get("room"):
                parts.append(old["room"])
            if "teacher" in fields and old.get("teacher"):
                parts.append(old["teacher"])
            if parts:
                text = "было: " + ", ".join(parts)
                draw_text(draw, x, py, text, font(16), strike)
                strike_line(draw, x, py, text, font(16), strike)
                py += 18
            return draw_comment(entry.get("comment"), x, py)
        py = draw_old(old, x, py)
        py = draw_item(new, x, py)
        return draw_comment(entry.get("comment"), x, py)

    def day_height(day):
        view = ac.day_view(schedule, day, kind)
        height = 38
        if view["removed"]:
            return height + 26 + comment_height(view["comment"])
        slots = ac.slots(view)
        if not slots:
            return height + 26 + (comment_height(view["comment"]) if view["comment"] else 0)
        for _, entries in slots:
            height += 13 + sum(entry_height(entry) for entry in entries) + 2
        if view["comment"]:
            height += comment_height(view["comment"])
        return height + 8

    def draw_day(day, x, y, card_width, card_height):
        view = ac.day_view(schedule, day, kind)
        card(draw, x, y, card_width, card_height, th, image)
        draw.rounded_rectangle([x + 20, y + 20, x + card_width - 20, y + 64],
                               radius=int(th.get("radius") or 0), fill=th["ink"])
        day_name = ss.WEEKDAYS_RU[ss.WEEKDAYS[day.weekday()]]
        draw_text(draw, x + 36, y + 28, day_name, font(24, True), th["on_ink"])
        if view["removed"]:
            strike_line(draw, x + 36, y + 28, day_name, font(24, True), strike)
        py = y + 76
        if view["removed"]:
            draw_text(draw, x + 20, py, "день отменён", font(22), th["muted"])
            py += 26
            draw_comment(view["comment"], x + 20, py)
            return
        slots = ac.slots(view)
        if not slots:
            draw_text(draw, x + 20, py, "нет пар", font(22), th["muted"])
            py += 26
            draw_comment(view["comment"], x + 20, py)
            return
        for time_slot, entries in slots:
            draw_text(draw, x + 20, py, time_slot, font(18, True), th["muted"])
            py += 26
            for entry in entries:
                py = draw_entry(entry, x + 20, py)
            py += 4
        if view["comment"]:
            draw_comment(view["comment"], x + 20, py + 2)

    row_one = days[:3]
    row_two = days[3:6]
    sunday = days[6]
    row_one_height = max(day_height(day) for day in row_one)
    row_two_height = max(day_height(day) for day in row_two)
    grid_top = pad + 108
    grid_height = max(row_one_height + gap + row_two_height, day_height(sunday))
    footer_top = grid_top + grid_height + 16
    height = footer_top + 40

    image = canvas_for(th, width, height)
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
