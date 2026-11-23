import re
import time
import json
import threading
import datetime
from urllib.parse import quote

import requests

BASE_URL = "https://timetable.pallada.sibsau.ru"
MAIN_URL = BASE_URL + "/timetable"
SITE_URL = "https://hekkeyne.ru/timetable/"
PROXY_URL = "https://hekkeyne.ru/timetable-api/timetable.php"

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

REQUEST_TIMEOUT = 25
CACHE_TTL = 3600

_cache = {}
_page_ids = {}
_cache_lock = threading.Lock()


class ScheduleError(Exception):
    pass


def _session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "schedule-bot/2.0",
        "Accept-Language": "ru-RU,ru;q=0.9",
    })
    return session


def _clean(text):
    return " ".join(str(text or "").split())


def _error_text(response):
    try:
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            return str(data["error"])
    except ValueError:
        pass
    return "HTTP %s" % response.status_code


def _get(action, **params):
    try:
        response = _session().get(
            PROXY_URL,
            params=dict(action=action, **params),
            timeout=REQUEST_TIMEOUT,
        )
        body = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ScheduleError("Сервис расписания недоступен: %s" % exc) from exc

    if response.status_code != 200:
        raise ScheduleError(_error_text(response))
    return body


def source_label():
    return "прокси"


def site_link(group_name=None):
    if not group_name:
        return SITE_URL
    return SITE_URL + "#" + quote(group_name)


def pallada_link(group_id=None):
    if not group_id:
        return MAIN_URL
    return BASE_URL + "/timetable/group/%s" % group_id


def search_groups(query):
    body = _get("search", q=_clean(query))
    raw = body.get("result")
    if not raw:
        return []
    try:
        items = raw if isinstance(raw, list) else json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ScheduleError("Неожиданный ответ поиска групп") from exc
    return [{"id": int(item["id"]), "name": _clean(item["name"])} for item in items]


def resolve_page_id(search_id, name, kind="group"):
    key = (kind, _clean(name).lower())
    with _cache_lock:
        cached = _page_ids.get(key)
    if cached:
        return cached

    body = _get("resolve", id=search_id, q=name, kind=kind)
    page_id = int(body.get("page_id") or 0)
    if page_id <= 0:
        raise ScheduleError("Не удалось определить группу")

    with _cache_lock:
        _page_ids[key] = page_id
    return page_id


def find_group(query):
    matches = search_groups(query)
    needle = _clean(query).upper()
    exact = next((item for item in matches if item["name"].upper() == needle), None)
    if exact:
        exact = {"id": resolve_page_id(exact["id"], exact["name"]), "name": exact["name"]}
    return exact, matches


def _teacher_links(item):
    links = []
    for teacher in item.get("teachers") or []:
        name = _clean(teacher.get("name") or teacher.get("short") or "")
        if not name:
            continue
        teacher_id = teacher.get("id")
        links.append({"name": name, "id": int(teacher_id) if teacher_id else None})
    if not links and item.get("teacher"):
        links.append({"name": _clean(item["teacher"]), "id": None})
    return links


def _normalize(payload):
    if not isinstance(payload, dict):
        raise ScheduleError("Пустой ответ расписания")
    if payload.get("error"):
        raise ScheduleError(str(payload["error"]))

    weeks = payload.get("weeks") or {}
    for days in weeks.values():
        for lessons in days.values():
            for lesson in lessons:
                lesson["teacher_links"] = _teacher_links(lesson)

    exams = payload.get("exams") or []
    for exam in exams:
        exam["teacher_links"] = _teacher_links(exam)

    group = payload.get("group") or {}
    ref = payload.get("ref") or {}

    return {
        "group_id": group.get("id"),
        "group_name": _clean(group.get("name")),
        "semester": _clean(payload.get("semester")),
        "ref_date": ref.get("date"),
        "ref_week": ref.get("week"),
        "weeks": weeks,
        "exams": exams,
        "cached": bool(payload.get("cached")),
    }


def _load(group_id=None, name=None):
    if not group_id and not name:
        raise ScheduleError("Нужен id или название группы")

    params = {"id": group_id} if group_id else {"q": name}
    return _normalize(_get("json", **params))


def _cached(key, loader, force, ttl):
    now = time.time()
    with _cache_lock:
        entry = _cache.get(key)

    if entry and not force and (now - entry["ts"]) < ttl:
        return entry["data"]

    try:
        data = loader()
    except Exception:
        if entry:
            return entry["data"]
        raise

    with _cache_lock:
        record = {"ts": now, "data": data}
        _cache[key] = record
        if data.get("group_id"):
            _cache[data["group_id"]] = record
    return data


def get_schedule(group_id, force=False, ttl=CACHE_TTL):
    return _cached(group_id, lambda: _load(group_id=group_id), force, ttl)


def get_schedule_by_name(name, force=False, ttl=CACHE_TTL):
    key = ("name", _clean(name).lower())
    return _cached(key, lambda: _load(name=name), force, ttl)


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


def check_site():
    try:
        groups = search_groups("")
    except Exception as exc:
        return "недоступен (%s)" % exc
    return "доступен, групп получено: %d" % len(groups)
