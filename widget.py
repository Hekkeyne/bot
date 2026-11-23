import os
import json

import requests

import schedule_source as ss

WIDGET_ENDPOINT = "https://api.telegram.org/bot" + (os.getenv("BOT_TOKEN") or "") + "/sendWidget"
TZ_OFFSET = 7
STATE_LIMIT = 1024

WIDGET_HTML = """<style>
* { box-sizing: border-box; }
body {
  margin: 0;
  font: var(--tg-text-font-size, 15px)/var(--tg-text-line-height, 1.35) system-ui, sans-serif;
  color: var(--tg-theme-text-color);
}
.wrap { padding: 10px 12px calc(10px + env(safe-area-inset-bottom)); }
.head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.group { font-weight: 600; }
.day { color: var(--tg-theme-hint-color); font-size: 0.85em; }
.clock {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  font-size: 1.7em;
  line-height: 1.1;
  margin-top: 4px;
}
.status { color: var(--tg-theme-hint-color); font-size: 0.85em; margin-top: 2px; min-height: 1.25em; }
.status b { color: var(--tg-theme-text-color); font-weight: 600; }
.tick { font-variant-numeric: tabular-nums; color: var(--tg-theme-text-color); font-weight: 600; }
.list { list-style: none; margin: 8px 0 0; padding: 0; }
.li { display: flex; align-items: flex-start; gap: 10px; padding: 6px 8px; border-radius: 8px; }
.li + .li { margin-top: 2px; }
.li.now { background: var(--tg-theme-secondary-bg-color); }
.li.past { color: var(--tg-theme-hint-color); }
.time {
  flex: 0 0 46px;
  font-variant-numeric: tabular-nums;
  font-size: 0.85em;
  color: var(--tg-theme-hint-color);
  padding-top: 1px;
}
.body { min-width: 0; flex: 1 1 auto; }
.subject, .meta { display: block; }
.subject { font-weight: 600; overflow-wrap: break-word; }
.li.now .subject { color: var(--tg-theme-accent-text-color, var(--tg-theme-link-color)); }
.meta { color: var(--tg-theme-hint-color); font-size: 0.85em; overflow-wrap: break-word; }
.empty { color: var(--tg-theme-hint-color); margin: 8px 0 0; }
.foot { margin-top: 10px; font-size: 0.85em; }
.foot a { color: var(--tg-theme-link-color); text-decoration: none; }
.foot i { color: var(--tg-theme-hint-color); font-style: normal; }
</style>
<div class="wrap">
  <div class="head">
    <span class="group" id="group"></span>
    <span class="day" id="day"></span>
  </div>
  <div class="clock" id="clock">--:--:--</div>
  <div class="status" id="status"></div>
  <ul class="list" id="list"></ul>
  <div class="foot">
    <a id="site" href="https://hekkeyne.ru/timetable/">Наш сайт</a>
    <i>·</i>
    <a id="pallada" href="https://timetable.pallada.sibsau.ru/timetable">Паллада</a>
  </div>
</div>
<script>
function tgPad(n) { return (n < 10 ? "0" : "") + n; }
function tgToMinutes(value) {
  var parts = String(value == null ? "" : value).split(":");
  var h = parseInt(parts[0], 10);
  var m = parseInt(parts[1], 10);
  return (isFinite(h) ? h : 0) * 60 + (isFinite(m) ? m : 0);
}
function tgFromMinutes(mins) { return tgPad(Math.floor(mins / 60)) + ":" + tgPad(mins % 60); }
function tgNow(offset) {
  var d = new Date(Date.now() + offset * 3600000);
  return {
    h: d.getUTCHours(),
    m: d.getUTCMinutes(),
    s: d.getUTCSeconds(),
    mins: d.getUTCHours() * 60 + d.getUTCMinutes(),
    key: d.getUTCFullYear() + "-" + tgPad(d.getUTCMonth() + 1) + "-" + tgPad(d.getUTCDate())
  };
}
function tgCountdown(seconds) {
  if (!isFinite(seconds) || seconds < 0) seconds = 0;
  if (seconds >= 3600) {
    return Math.floor(seconds / 3600) + " ч " + Math.floor((seconds % 3600) / 60) + " мин";
  }
  return Math.floor(seconds / 60) + ":" + tgPad(seconds % 60);
}
function tgEscape(text) {
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
(function () {
  var W = window.TelegramWidget;
  var state = {};
  try { state = JSON.parse((W && W.chatData) || "{}") || {}; } catch (error) { state = {}; }
  if (!state || typeof state !== "object") state = {};
  var lessons = Array.isArray(state.l) ? state.l : [];
  var offset = typeof state.o === "number" ? state.o : 7;

  var groupEl = document.getElementById("group");
  var dayEl = document.getElementById("day");
  var clockEl = document.getElementById("clock");
  var statusEl = document.getElementById("status");
  var listEl = document.getElementById("list");

  if (groupEl) groupEl.textContent = String(state.g || "");
  if (dayEl) {
    dayEl.textContent = state.w ? String(state.w) + ", " + String(state.d || "") : String(state.d || "");
  }
  var siteEl = document.getElementById("site");
  if (siteEl && state.g) {
    siteEl.href = "https://hekkeyne.ru/timetable/#" + encodeURIComponent(String(state.g));
  }
  var palladaEl = document.getElementById("pallada");
  if (palladaEl && state.id) {
    palladaEl.href = "https://timetable.pallada.sibsau.ru/timetable/group/" + state.id;
  }

  var rows = [];
  if (listEl) {
    for (var i = 0; i < lessons.length; i++) {
      var lesson = lessons[i];
      var li = document.createElement("li");
      li.className = "li";

      var timeEl = document.createElement("span");
      timeEl.className = "time";
      timeEl.textContent = String(lesson[0] || "") + "\\u2013" + String(lesson[1] || "");

      var bodyEl = document.createElement("span");
      bodyEl.className = "body";

      var subjectEl = document.createElement("span");
      subjectEl.className = "subject";
      subjectEl.textContent = String(lesson[2] || "");
      bodyEl.appendChild(subjectEl);

      var details = [];
      if (lesson[4]) details.push(String(lesson[4]));
      if (lesson[3]) details.push(String(lesson[3]));
      if (details.length) {
        var metaEl = document.createElement("span");
        metaEl.className = "meta";
        metaEl.textContent = details.join(" · ");
        bodyEl.appendChild(metaEl);
      }

      li.appendChild(timeEl);
      li.appendChild(bodyEl);
      listEl.appendChild(li);

      rows.push({ el: li, a: tgToMinutes(lesson[0]), b: tgToMinutes(lesson[1]), s: String(lesson[2] || "") });
    }
  }

  function render() {
    var now = tgNow(offset);
    if (clockEl) clockEl.textContent = tgPad(now.h) + ":" + tgPad(now.m) + ":" + tgPad(now.s);

    var stale = !!(state.ds && state.ds !== now.key);
    var current = null;
    var next = null;
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var cls;
      if (stale) {
        cls = "li";
      } else {
        cls = now.mins >= row.b ? "li past" : (now.mins >= row.a ? "li now" : "li");
        if (now.mins >= row.a && now.mins < row.b) current = row;
        else if (now.mins < row.a && next === null) next = row;
      }
      if (row.el.className !== cls) row.el.className = cls;
    }

    if (statusEl) {
      var html;
      if (stale) {
        html = "данные за " + tgEscape(state.d || "");
      } else if (current) {
        html = "сейчас · <b>" + tgEscape(current.s) + "</b> · до " + tgFromMinutes(current.b)
          + " · <span class=\\"tick\\">" + tgCountdown((current.b - now.mins) * 60 - now.s) + "</span>";
      } else if (next) {
        html = "скоро · <b>" + tgEscape(next.s) + "</b> · в " + tgFromMinutes(next.a)
          + " · <span class=\\"tick\\">" + tgCountdown((next.a - now.mins) * 60 - now.s) + "</span>";
      } else {
        html = rows.length ? "на сегодня пары закончились" : "пар нет";
      }
      statusEl.innerHTML = html;
    }
  }

  render();
  if (typeof setInterval === "function") setInterval(render, 1000);
  if (W && typeof W.ready === "function") W.ready();
})();
</script>"""


def build_state(schedule, sub, date):
    lessons = ss.lessons_for(schedule, date)
    items = []
    for lesson in lessons:
        start, _, end = lesson.get("time", "").partition("-")
        teacher = ", ".join(item.get("name", "") for item in (lesson.get("teacher_links") or []))
        items.append([start.strip(), end.strip(), lesson.get("subject", ""), lesson.get("room", ""), teacher])

    base = {
        "g": sub.get("group_name") or "",
        "id": sub.get("group_id"),
        "ds": date.isoformat(),
        "d": date.strftime("%d.%m"),
        "w": ss.WEEKDAYS_RU[ss.WEEKDAYS[date.weekday()]],
        "o": TZ_OFFSET,
    }

    attempts = [
        lambda item: item,
        lambda item: item[:4],
        lambda item: item[:3],
    ]
    for trim in attempts:
        state = dict(base)
        state["l"] = [trim(item) for item in items]
        dump = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        if len(dump.encode("utf-8")) <= STATE_LIMIT:
            return dump

    for width in (24, 16, 10):
        state = dict(base)
        state["l"] = [[item[0], item[1], item[2][:width]] for item in items]
        dump = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        if len(dump.encode("utf-8")) <= STATE_LIMIT:
            return dump

    state = dict(base)
    state["l"] = [[item[0], item[1]] for item in items]
    return json.dumps(state, ensure_ascii=False, separators=(",", ":"))


def send_widget(chat_id, chat_data, caption, thread_id=0):
    payload = {"chat_id": chat_id, "html": WIDGET_HTML, "chat_data": chat_data, "caption": caption}
    if thread_id:
        payload["message_thread_id"] = thread_id

    response = requests.post(WIDGET_ENDPOINT, json=payload, timeout=30)
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(str(data.get("description") or "ошибка sendWidget"))
    return int(data["result"]["message_id"])


def send_widget_day(chat_id, schedule, sub, date, caption, thread_id=0):
    return send_widget(chat_id, build_state(schedule, sub, date), caption, thread_id)
