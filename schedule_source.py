import re
import time
import json
import threading
import datetime

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://timetable.pallada.sibsau.ru"
SEARCH_URL = BASE_URL + "/ajax/search_schedule"
GROUP_URL = BASE_URL + "/timetable/group/{group_id}"
GROUP_PAGE_RE = re.compile(r"/timetable/group/(\d+)")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAYS_RU = {
    "monday": "Понедельник",
    "tuesday": "Вторник",
    "wednesday": "Среда",
    "thursday": "Четверг",
    "friday": "Пятница",
    "saturday": "Суббота",
    "sunday": "Воскресенье",
}

REQUEST_TIMEOUT = 15
CACHE_TTL = 3600

_cache = {}
_cache_lock = threading.Lock()


class ScheduleError(Exception):
    pass


def _session():
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def _clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def search_groups(query, session=None):
    query = (query or "").strip()
    session = session or _session()
    payload = {"jsonrpc": "2.0", "method": "call", "params": {"query": query}, "id": 1}
    try:
        response = session.post(SEARCH_URL, json=payload, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        body = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ScheduleError("Не удалось обратиться к поиску групп: %s" % exc) from exc

    raw = body.get("result")
    if not raw:
        return []
    try:
        groups = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ScheduleError("Неожиданный ответ поиска групп") from exc
    return [{"id": int(g["id"]), "name": _clean(g["name"])} for g in groups]


def group_page_id(search_id, query, session=None):
    session = session or _session()
    try:
        page = session.get(BASE_URL + "/timetable", timeout=REQUEST_TIMEOUT)
        page.raise_for_status()
        token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.text)
        csrf = token.group(1) if token else ""
        response = session.post(
            BASE_URL + "/timetable",
            data={"query": query, "id": str(search_id), "csrf_token": csrf},
            allow_redirects=False,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ScheduleError("Не удалось определить страницу группы %s: %s" % (search_id, exc)) from exc

    location = response.headers.get("Location", "")
    found = GROUP_PAGE_RE.search(location)
    if not found:
        raise ScheduleError("Сайт не сообщил страницу группы %s" % search_id)
    return int(found.group(1))


def find_group(query):
    matches = search_groups(query)
    needle = _clean(query).upper()
    exact = next((g for g in matches if g["name"].upper() == needle), None)
    if exact:
        exact = dict(exact)
        exact["page_id"] = group_page_id(exact["id"], exact["name"])
    return exact, matches


def fetch_group_html(group_id, session=None):
    session = session or _session()
    url = GROUP_URL.format(group_id=group_id)
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ScheduleError("Не удалось загрузить страницу группы %s: %s" % (group_id, exc)) from exc
    return response.text


def _parse_lesson(ul):
    subject = ""
    lesson_type = ""
    teacher = ""
    room = ""
    address = ""
    subgroup = "все"

    name_span = ul.find("span", class_="name")
    if name_span:
        subject = _clean(name_span.get_text())
        type_match = re.search(r"\(([^)]*)\)", ul.get_text())
        if type_match:
            lesson_type = _clean(type_match.group(1))

    user_icon = ul.find("i", class_=lambda c: c and "fa-user" in c)
    if user_icon:
        parent_li = user_icon.find_parent("li")
        if parent_li:
            teacher = _clean(", ".join(a.get_text() for a in parent_li.find_all("a")))

    compass_icon = ul.find("i", class_=lambda c: c and "fa-compass" in c)
    if compass_icon:
        parent_li = compass_icon.find_parent("li")
        link = parent_li.find("a") if parent_li else None
        if link:
            room = _clean(link.get_text())
            address = _clean(link.get("title"))

    subgroup_li = ul.find("li", class_="num_pdgrp")
    if subgroup_li:
        subgroup = _clean(subgroup_li.get_text())
    else:
        clip_icon = ul.find("i", class_=lambda c: c and "fa-paperclip" in c)
        if clip_icon:
            parent_li = clip_icon.find_parent("li")
            if parent_li:
                subgroup = _clean(parent_li.get_text())

    return {
        "time": "",
        "subject": subject,
        "type": lesson_type,
        "teacher": teacher,
        "room": room,
        "address": address,
        "subgroup": subgroup,
    }


def parse_group_html(html):
    soup = BeautifulSoup(html, "lxml")

    group_id = None
    active_input = soup.find("input", id="active_id")
    if active_input and active_input.get("value", "").isdigit():
        group_id = int(active_input["value"])

    group_name = ""
    h3 = soup.find("h3", class_="bold")
    if h3:
        raw = _clean(h3.get_text(" "))
        name_match = re.search(r"[\"«“]\s*([^\"»”]+?)\s*[\"»”]", raw)
        if name_match:
            group_name = _clean(name_match.group(1))

    semester = ""
    if h3:
        semester_match = re.search(r"(\d+\s*семестр[^(]*)", _clean(h3.get_text(" ")))
        if semester_match:
            semester = _clean(semester_match.group(1))

    ref_date = None
    ref_week = None
    h4 = soup.find("h4", class_="bold")
    if h4:
        week_match = re.search(r"(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d+)\s*недел", _clean(h4.get_text(" ")))
        if week_match:
            ref_date = datetime.datetime.strptime(week_match.group(1), "%d.%m.%Y").date()
            ref_week = int(week_match.group(2))

    weeks = {}
    for panel in soup.find_all("div", id=re.compile(r"^week_(\d+)_tab$")):
        week_no = re.match(r"^week_(\d+)_tab$", panel["id"]).group(1)
        week_days = {day: [] for day in WEEKDAYS}

        for day_div in panel.find_all("div", class_="day"):
            classes = day_div.get("class") or []
            weekday = next((d for d in WEEKDAYS if d in classes), None)
            if not weekday:
                continue

            body = day_div.find("div", class_="body")
            if not body:
                continue

            for line in body.find_all("div", class_="line", recursive=False):
                time_div = line.find("div", class_="time")
                time_text = _clean(time_div.get_text(" ")) if time_div else ""
                time_match = re.search(r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}", time_text)
                time_value = time_match.group(0).replace(" ", "") if time_match else time_text

                for ul in line.find_all("ul", class_="list-unstyled"):
                    lesson = _parse_lesson(ul)
                    if not lesson["subject"]:
                        continue
                    lesson["time"] = time_value
                    week_days[weekday].append(lesson)

        weeks[week_no] = week_days

    return {
        "group_id": group_id,
        "group_name": group_name,
        "semester": semester,
        "ref_date": ref_date.isoformat() if ref_date else None,
        "ref_week": ref_week,
        "weeks": weeks,
    }


def load_schedule(group_id, session=None):
    return parse_group_html(fetch_group_html(group_id, session=session))


def check_site():
    try:
        groups = search_groups("")
    except Exception as exc:
        return "недоступен (%s)" % exc
    return "доступен, групп получено: %d" % len(groups)


def get_schedule(group_id, force=False, ttl=CACHE_TTL):
    now = time.time()
    with _cache_lock:
        entry = _cache.get(group_id)

    if entry and not force and (now - entry["ts"]) < ttl:
        return entry["data"]

    try:
        data = load_schedule(group_id)
    except Exception:
        if entry:
            return entry["data"]
        raise

    with _cache_lock:
        _cache[group_id] = {"ts": now, "data": data}
    return data


def clear_cache():
    with _cache_lock:
        _cache.clear()


def week_number_for(date, schedule):
    ref_date = schedule.get("ref_date")
    ref_week = schedule.get("ref_week")
    if not ref_date or not ref_week:
        return 1 if date.isocalendar()[1] % 2 else 2

    ref = datetime.date.fromisoformat(ref_date)
    m_ref = ref - datetime.timedelta(days=ref.weekday())
    m_cur = date - datetime.timedelta(days=date.weekday())
    weeks_delta = round((m_cur - m_ref).days / 7)
    return ((ref_week - 1 + weeks_delta) % 2) + 1


def lessons_for(schedule, date):
    week_no = str(week_number_for(date, schedule))
    weekday = WEEKDAYS[date.weekday()]
    return schedule.get("weeks", {}).get(week_no, {}).get(weekday, [])


def last_lesson_end_time(lessons):
    ends = []
    for lesson in lessons:
        match = re.search(r"-\s*(\d{1,2}):(\d{2})", lesson.get("time", ""))
        if match:
            ends.append((int(match.group(1)), int(match.group(2))))
    return max(ends) if ends else None
