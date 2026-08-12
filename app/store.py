import json, re, sqlite3, threading
from datetime import datetime, timezone
from pathlib import Path

_BAD = re.compile(r"[^A-Za-z0-9_-]")

class Store:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.msg_dir = self.data_dir / "messages"
        self.media_root = self.data_dir / "media"
        self.db_path = self.data_dir / "state.sqlite"
        self.msg_dir.mkdir(parents=True, exist_ok=True)
        self.media_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._db.execute("""CREATE TABLE IF NOT EXISTS seen_messages (
            chat_id TEXT, message_id TEXT, ts INTEGER, source TEXT,
            PRIMARY KEY(chat_id, message_id))""")
        self._db.execute("""CREATE TABLE IF NOT EXISTS chat_progress (
            chat_id TEXT PRIMARY KEY, last_seen_id TEXT, last_seen_ts INTEGER)""")
        self._db.commit()

    @staticmethod
    def safe_name(chat_id: str) -> str:
        return _BAD.sub("_", chat_id)

    @staticmethod
    def _date_str(ts: int) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")

    def _event_path(self, chat_id: str, ts: int) -> Path:
        return self.msg_dir / self.safe_name(chat_id) / f"{self._date_str(ts)}.jsonl"

    def media_dir(self, chat_id: str, date_str: str) -> Path:
        d = self.media_root / self.safe_name(chat_id) / date_str
        d.mkdir(parents=True, exist_ok=True)
        return d

    def is_seen(self, chat_id: str, message_id: str) -> bool:
        with self._lock:
            cur = self._db.execute(
                "SELECT 1 FROM seen_messages WHERE chat_id=? AND message_id=?",
                (chat_id, message_id))
            return cur.fetchone() is not None

    def record_seen(self, chat_id: str, message_id: str, ts: int, source: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO seen_messages(chat_id,message_id,ts,source) VALUES(?,?,?,?)",
                (chat_id, message_id, ts, source))
            self._db.commit()

    def get_last_seen(self, chat_id: str) -> tuple[str | None, int | None]:
        with self._lock:
            cur = self._db.execute(
                "SELECT last_seen_id, last_seen_ts FROM chat_progress WHERE chat_id=?",
                (chat_id,))
            row = cur.fetchone()
        return (row[0], row[1]) if row else (None, None)

    def set_last_seen(self, chat_id: str, message_id: str, ts: int) -> None:
        with self._lock:
            self._db.execute(
                """INSERT INTO chat_progress(chat_id,last_seen_id,last_seen_ts) VALUES(?,?,?)
                   ON CONFLICT(chat_id) DO UPDATE SET last_seen_id=excluded.last_seen_id,
                   last_seen_ts=excluded.last_seen_ts""",
                (chat_id, message_id, ts))
            self._db.commit()

    def _append(self, path: Path, record: dict) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return path

    def append_event(self, chat_id: str, ts: int, record: dict) -> str:
        return str(self._append(self._event_path(chat_id, ts), record))

    def append_media_record(self, chat_id: str, ts: int, record: dict) -> None:
        self._append(self._event_path(chat_id, ts), record)
