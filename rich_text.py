import html
import datetime

import schedule_source as ss

PROFESSOR_URL = ss.BASE_URL + "/timetable/professor/%s"


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=False)


def teachers(item):
    links = item.get("teacher_links") or []
    if not links:
        return esc(item.get("teacher", ""))
    parts = []
    for link in links:
        name = esc(link.get("name") or "")
        target = link.get("id")
        if target:
            parts.append('<a href="%s">%s</a>' % (PROFESSOR_URL % target, name))
        else:
            parts.append(name)
    return ", ".join(parts)


def lesson_line(lesson):
    parts = ["<b>%s</b>" % esc(lesson.get("time", ""))]
    subject = esc(lesson.get("subject", ""))
    lesson_type = esc(lesson.get("type", ""))
    parts.append("%s (%s)" % (subject, lesson_type) if lesson_type else subject)
    teacher = teachers(lesson)
    if teacher:
        parts.append(teacher)
    room = esc(lesson.get("room", ""))
    if room:
        parts.append(room)
    return " · ".join(parts)


def by_time(lessons):
    slots = {}
    for lesson in lessons:
        slots.setdefault(lesson.get("time", ""), []).append(lesson)
    return [(slot, slots[slot]) for slot in sorted(slots, key=lambda item: item.split("-")[0])]


def lesson_items(lessons):
    items = []
    for slot, group in by_time(lessons):
        common = next((item for item in group if item.get("subgroup") == "все"), None)
        if common:
            items.append("<li>%s</li>" % lesson_line(common))
        else:
            for lesson in group:
                items.append("<li><b>%s</b> · %s</li>"
                             % (esc(lesson.get("subgroup", "")), lesson_line(lesson)))
    return items


def footer(sub):
    ours = ss.site_link(sub.get("group_name"))
    pallada = ss.pallada_link(sub.get("group_id"))
    return ('<footer><a href="%s">Полное расписание на нашем сайте</a> · '
            '<a href="%s">Полное расписание Паллада СибГУ</a></footer>' % (ours, pallada))


def day(schedule, sub, date):
    weekday = ss.WEEKDAYS_RU[ss.WEEKDAYS[date.weekday()]]
    week_no = ss.week_number_for(date, schedule)
    lessons = ss.lessons_for(schedule, date)

    out = ["<h3>%s, %s</h3>" % (weekday, date.strftime("%d.%m.%Y"))]
    out.append("<p><b>%s</b> · %d-я неделя</p>" % (esc(sub.get("group_name") or ""), week_no))
    if not lessons:
        out.append("<p>Выходной! Пар нет.</p>")
    else:
        out.append("<ul>")
        out.extend(lesson_items(lessons))
        out.append("</ul>")
    return "\n".join(out) + "\n" + footer(sub)


def week(schedule, sub, today):
    monday = today - datetime.timedelta(days=today.weekday())
    out = ["<h3>Расписание на неделю</h3>",
           "<p><b>%s</b></p>" % esc(sub.get("group_name") or "")]
    for index in range(7):
        current = monday + datetime.timedelta(days=index)
        weekday = ss.WEEKDAYS_RU[ss.WEEKDAYS[current.weekday()]]
        lessons = ss.lessons_for(schedule, current)
        out.append("<h4>%s, %s</h4>" % (weekday, current.strftime("%d.%m")))
        if not lessons:
            out.append("<p>Выходной</p>")
            continue
        out.append("<ul>")
        out.extend(lesson_items(lessons))
        out.append("</ul>")
    return "\n".join(out) + "\n" + footer(sub)


def exam_key(exam):
    raw = "%s %s" % (exam.get("date", ""), exam.get("time") or "00:00")
    try:
        return datetime.datetime.strptime(raw, "%d.%m.%Y %H:%M")
    except ValueError:
        return datetime.datetime.max


def exams(schedule, sub):
    items = schedule.get("exams") or []
    out = ["<h3>Сессия: %s</h3>" % esc(sub.get("group_name") or "")]
    if not items:
        out.append("<p>Экзамены пока не опубликованы.</p>")
        return "\n".join(out) + "\n" + footer(sub)

    out.append("<table bordered striped>")
    out.append("<tr><th>Дата</th><th>Время</th><th>Экзамен</th><th>Преподаватель</th><th>Кабинет</th></tr>")
    for exam in sorted(items, key=exam_key):
        subject = esc(exam.get("subject", ""))
        exam_type = esc(exam.get("type", ""))
        cell = "%s (%s)" % (subject, exam_type) if exam_type else subject
        out.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                   % (esc(exam.get("date", "")), esc(exam.get("time", "")), cell,
                      teachers(exam), esc(exam.get("room", ""))))
    out.append("</table>")
    return "\n".join(out) + "\n" + footer(sub)


def nearest_exam(schedule, sub, exam, left):
    out = ["<h3>Ближайший экзамен: %s</h3>" % esc(sub.get("group_name") or "")]
    if not exam:
        out.append("<p>Экзаменов впереди нет.</p>")
        return "\n".join(out) + "\n" + footer(sub)

    subject = esc(exam.get("subject", ""))
    exam_type = esc(exam.get("type", ""))
    out.append("<p>%s</p>" % esc(left))
    out.append("<p><b>%s</b>%s</p>" % (subject, " (%s)" % exam_type if exam_type else ""))
    out.append("<p>%s в %s</p>" % (esc(exam.get("date", "")), esc(exam.get("time", ""))))
    teacher = teachers(exam)
    if teacher:
        out.append("<p>%s</p>" % teacher)
    room = esc(exam.get("room", ""))
    if room:
        out.append("<p>%s</p>" % room)
    return "\n".join(out) + "\n" + footer(sub)
