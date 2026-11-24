import json
import logging
import os
import threading
import time

import requests

DEFAULT_URL = "https://hekkeyne.ru/timetable-api/timetable.php"
FLUSH_INTERVAL = 5


def empty_state():
    return {"subscriptions": [], "teachers": {}, "messages": {}, "sent": {}, "settings": {}, "next_sub_id": 1}


class StateStore:
    def __init__(self, url=None, token=None, path=None):
        self.url = url or os.getenv("STATE_URL") or DEFAULT_URL
        self.token = token if token is not None else (os.getenv("STATE_TOKEN") or "")
        self.path = path or os.getenv("STATE_FILE") or "schedule_state.json"
        self.lock = threading.RLock()
        self.data = empty_state()
        self.dirty = False
        self.loaded = False
        self._thread = None

    def ensure_loaded(self):
        if self.loaded:
            return
        self.loaded = True
        try:
            self.load()
        except Exception as error:
            logging.warning("Хранилище не загружено: %s", error)
        self._start_flusher()

    def _headers(self):
        return {"X-State-Token": self.token}

    def load(self):
        remote = self._fetch_remote()
        if remote and (remote.get("subscriptions") or remote.get("teachers") or remote.get("settings")):
            self._merge(remote)
            self._write_local()
            logging.info("Состояние прочитано из хранилища")
            return

        local = self._read_local()
        if local and (local.get("subscriptions") or local.get("teachers") or local.get("settings")):
            self._merge(local)
            self.dirty = True
            self.flush(force=True)
            logging.info("Состояние прочитано из локального кэша")
            return

        legacy = self._read_legacy_sqlite()
        if legacy:
            self._merge(legacy)
            self.dirty = True
            self.flush(force=True)
            logging.info("Состояние перенесено из старой базы")
            return

        if remote:
            self._merge(remote)
        self._write_local()

    def _fetch_remote(self):
        if not self.token:
            return None
        try:
            response = requests.get(self.url, params={"action": "state"}, headers=self._headers(), timeout=20)
            if response.status_code != 200:
                logging.warning("Хранилище ответило %s", response.status_code)
                return None
            payload = response.json()
            if isinstance(payload, dict):
                return payload
        except Exception as error:
            logging.warning("Не удалось прочитать хранилище: %s", error)
        return None

    def _read_local(self):
        try:
            if os.path.isfile(self.path):
                with open(self.path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if isinstance(payload, dict):
                    return payload
        except Exception as error:
            logging.warning("Локальный кэш не прочитан: %s", error)
        return None

    def _write_local(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception as error:
            logging.warning("Локальный кэш не сохранён: %s", error)

    def _read_legacy_sqlite(self):
        try:
            import sqlite3
            path = os.getenv("DB_PATH") or "schedule_bot.db"
            if not os.path.isfile(path):
                return None
            with sqlite3.connect(path) as conn:
                conn.row_factory = sqlite3.Row
                subs = [dict(row) for row in conn.execute("SELECT * FROM subscriptions")]
                teachers = {str(row["id"]): row["name"] for row in conn.execute("SELECT * FROM teacher_links")}
                messages = {"%s:%s" % (row["chat_id"], row["user_id"]): row["message_id"]
                            for row in conn.execute("SELECT * FROM bot_messages")}
            if not subs and not teachers:
                return None
            return {"subscriptions": subs, "teachers": teachers, "messages": messages, "sent": {}}
        except Exception as error:
            logging.warning("Старая база не прочитана: %s", error)
            return None

    def _merge(self, payload):
        data = self.data
        if isinstance(payload.get("subscriptions"), list):
            data["subscriptions"] = [item for item in payload["subscriptions"] if isinstance(item, dict)]
        if isinstance(payload.get("teachers"), dict):
            data["teachers"] = {str(key): str(value) for key, value in payload["teachers"].items()}
        if isinstance(payload.get("messages"), dict):
            data["messages"] = {str(key): value for key, value in payload["messages"].items()}
        if isinstance(payload.get("sent"), dict):
            data["sent"] = {str(key): value for key, value in payload["sent"].items()}
        if isinstance(payload.get("settings"), dict):
            data["settings"] = {str(key): value for key, value in payload["settings"].items() if isinstance(value, dict)}
        highest = max([int(item.get("id") or 0) for item in data["subscriptions"]] + [0])
        try:
            data["next_sub_id"] = max(1, int(payload.get("next_sub_id") or 1), highest + 1)
        except (TypeError, ValueError):
            data["next_sub_id"] = highest + 1

    def touch(self):
        with self.lock:
            self.dirty = True

    def flush(self, force=False):
        with self.lock:
            if not self.dirty and not force:
                return
            self.dirty = False
            snapshot = json.dumps(self.data, ensure_ascii=False)
        self._write_local()
        if not self.token:
            return
        try:
            response = requests.post(self.url, params={"action": "state"}, headers=self._headers(),
                                     data=snapshot.encode("utf-8"), timeout=20)
            if response.status_code != 200:
                logging.warning("Состояние не сохранено: HTTP %s", response.status_code)
                with self.lock:
                    self.dirty = True
        except Exception as error:
            logging.warning("Состояние не сохранено: %s", error)
            with self.lock:
                self.dirty = True

    def _start_flusher(self):
        if self._thread is not None:
            return

        def loop():
            while True:
                time.sleep(FLUSH_INTERVAL)
                try:
                    self.flush()
                except Exception as error:
                    logging.warning("Фоновое сохранение не удалось: %s", error)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()
