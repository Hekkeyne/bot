import threading
import time

import requests

import schedule_source as ss

TTL = 15
_lock = threading.Lock()
_state = {"ts": 0.0, "changes": {}}


def fetch(force=False):
    with _lock:
        if not force and time.time() - _state["ts"] < TTL:
            return _state["changes"]
    try:
        response = requests.get(ss.PROXY_URL, params={"action": "changes"}, timeout=20)
        payload = response.json()
        changes = {}
        for item in payload.get("changes") or []:
            if isinstance(item, dict) and item.get("key"):
                changes[item["key"]] = item
    except Exception:
        changes = _state["changes"]
    with _lock:
        _state["ts"] = time.time()
        _state["changes"] = changes
    return changes


def day_change(schedule, date, kind="group", changes=None):
    changes = fetch() if changes is None else changes
    key = "%s|%s|%s" % (kind, schedule.get("group_id"), date.isoformat())
    return changes.get(key)


def patch_for(patches, index, lesson):
    for patch in patches:
        if patch.get("index") == index and patch.get("op") != "add":
            return patch
    for patch in patches:
        old = patch.get("old") or {}
        if (old.get("time") == lesson.get("time")
                and old.get("subject") == lesson.get("subject")
                and patch.get("op") != "add"):
            return patch
    return None


def day_view(schedule, date, kind="group", changes=None):
    change = day_change(schedule, date, kind, changes)
    original = (change or {}).get("original") or ss.lessons_for(schedule, date)
    patches = (change or {}).get("patches") or []
    entries = []
    used = set()
    for index, lesson in enumerate(original):
        patch = patch_for(patches, index, lesson)
        if patch:
            used.add(id(patch))
            entries.append({
                "op": patch.get("op") or "replace",
                "old": lesson,
                "new": patch.get("new"),
                "comment": patch.get("comment") or "",
                "partial": bool(patch.get("partial")),
                "fields": patch.get("fields") or [],
            })
        else:
            entries.append({
                "op": "normal",
                "old": None,
                "new": lesson,
                "comment": "",
                "partial": False,
                "fields": [],
            })
    for patch in patches:
        if patch.get("op") == "add" and id(patch) not in used:
            entries.append({
                "op": "add",
                "old": None,
                "new": patch.get("new"),
                "comment": patch.get("comment") or "",
                "partial": False,
                "fields": [],
            })
    return {
        "removed": bool((change or {}).get("removed")),
        "comment": (change or {}).get("comment") or "",
        "entries": entries,
    }


def entry_time(entry):
    if entry["op"] in ("replace", "add") and entry.get("new") and entry["new"].get("time"):
        return entry["new"]["time"]
    if entry["op"] == "remove" and entry.get("old"):
        return entry["old"].get("time") or ""
    return (entry.get("new") or entry.get("old") or {}).get("time") or ""


def slots(view):
    grouped = {}
    for entry in view["entries"]:
        grouped.setdefault(entry_time(entry), []).append(entry)
    return [(key, grouped[key]) for key in sorted(grouped.keys(), key=lambda value: value.split("-")[0])]


def iso_date(value):
    parts = str(value or "").strip().split(".")
    if len(parts) != 3:
        return ""
    return "%s-%s-%s" % (parts[2], parts[1].zfill(2), parts[0].zfill(2))


def item_change(changes, kind, scope, target_id, iso, item_kind, index):
    key = "%s|%s|%s|%s:%d" % (scope, target_id, iso, item_kind, index)
    return changes.get(key) or {}