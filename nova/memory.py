"""SQLite tabanlı kalıcı hafıza.

İki tablo tutulur:
    facts    : kullanıcının hatırlanmasını istediği kalıcı bilgiler
    messages : oturum bazlı konuşma geçmişi (bağlam için)

Ağır bir bağımlılık yok; standart kütüphane sqlite3 kullanılır.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from pathlib import Path

_TOKEN_RE = re.compile(r"[a-z0-9çğıöşü]+", re.IGNORECASE)
_STOPWORDS = {
    "bir", "bu", "şu", "ve", "ile", "için", "mi", "mı", "mu", "mü", "ne", "benim",
    "beni", "ben", "sen", "senin", "hakkımda", "hakkinda", "nedir", "neydi", "var", "yok",
    "çok", "daha", "en", "da", "de", "ki", "ama", "gibi", "olarak", "olan", "the", "and",
}


def _tokens(text: str) -> set[str]:
    return {t for t in (m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")) if len(t) > 1 and t not in _STOPWORDS}


class MemoryStore:
    """Konuşma geçmişi ve kalıcı notlar için ince bir SQLite sarmalayıcı."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._shared: sqlite3.Connection | None = None
        if self.path == ":memory:":
            # Bellek içi veritabanı bağlantı başına kaybolur; tek bağlantı paylaşılır.
            self._shared = sqlite3.connect(":memory:", check_same_thread=False)
            self._shared.row_factory = sqlite3.Row
        self._ensure_schema()

    # ------------------------------------------------------------ altyapı
    def _connect(self) -> sqlite3.Connection:
        if self._shared is not None:
            return self._shared
        conn = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL DEFAULT 'default',
                    text TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_facts_session ON facts(session_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL DEFAULT 'default',
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id DESC);
                """
            )
            conn.commit()
            if self._shared is None:
                conn.close()

    # ------------------------------------------------------------ notlar
    def add_fact(self, text: str, session_id: str = "default", tags: str = "") -> dict:
        clean = " ".join((text or "").split())
        if not clean:
            raise ValueError("Boş not kaydedilemez.")
        clean = clean[:600]
        # Aynı notu tekrar kaydetmeyi engelle
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT id FROM facts WHERE session_id = ? AND lower(text) = lower(?)",
                (session_id, clean),
            ).fetchone()
            if row:
                return {"id": row["id"], "text": clean, "duplicate": True}
            created = time.time()
            cur = conn.execute(
                "INSERT INTO facts (session_id, text, tags, created_at) VALUES (?, ?, ?, ?)",
                (session_id, clean, (tags or "")[:200], created),
            )
            conn.commit()
            fact_id = int(cur.lastrowid)
            if self._shared is None:
                conn.close()
        return {"id": fact_id, "text": clean, "duplicate": False}

    def list_facts(self, session_id: str = "default", limit: int = 100) -> list[dict]:
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT id, text, tags, created_at FROM facts WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, max(1, min(int(limit), 500))),
            ).fetchall()
            if self._shared is None:
                conn.close()
        return [dict(row) for row in rows]

    def search_facts(self, query: str, session_id: str = "default", limit: int = 5) -> list[dict]:
        """Anahtar kelime örtüşmesine göre en ilgili notları döndürür."""
        facts = self.list_facts(session_id, limit=500)
        if not facts:
            return []
        wanted = _tokens(query)
        if not wanted:
            return facts[:limit]
        scored: list[tuple[float, dict]] = []
        for fact in facts:
            haystack = _tokens(fact.get("text", "") + " " + fact.get("tags", ""))
            overlap = len(wanted & haystack)
            if overlap:
                scored.append((overlap / len(wanted), fact))
        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored and len(wanted) <= 2:
            # "Benim hakkımda ne biliyorsun?" gibi genel sorularda son notları döndür.
            return facts[:limit]
        return [fact for _, fact in scored[:limit]]

    def delete_fact(self, fact_id: int) -> bool:
        with self._lock:
            conn = self._connect()
            cur = conn.execute("DELETE FROM facts WHERE id = ?", (int(fact_id),))
            conn.commit()
            deleted = cur.rowcount > 0
            if self._shared is None:
                conn.close()
        return deleted

    def clear_facts(self, session_id: str = "default") -> int:
        with self._lock:
            conn = self._connect()
            cur = conn.execute("DELETE FROM facts WHERE session_id = ?", (session_id,))
            conn.commit()
            count = cur.rowcount
            if self._shared is None:
                conn.close()
        return int(count)

    # ------------------------------------------------------------ mesajlar
    def append_message(self, session_id: str, role: str, content: str) -> None:
        with self._lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, (content or "")[:6000], time.time()),
            )
            conn.execute(
                "DELETE FROM messages WHERE session_id = ? AND id NOT IN "
                "(SELECT id FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT 200)",
                (session_id, session_id),
            )
            conn.commit()
            if self._shared is None:
                conn.close()

    def recent_messages(self, session_id: str, limit: int = 10) -> list[dict]:
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, max(1, min(int(limit), 100))),
            ).fetchall()
            if self._shared is None:
                conn.close()
        return [dict(row) for row in reversed(rows)]

    def clear_session(self, session_id: str) -> int:
        with self._lock:
            conn = self._connect()
            cur = conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.commit()
            count = cur.rowcount
            if self._shared is None:
                conn.close()
        return int(count)

    def stats(self) -> dict:
        with self._lock:
            conn = self._connect()
            facts = conn.execute("SELECT COUNT(*) AS c FROM facts").fetchone()["c"]
            messages = conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
            sessions = conn.execute("SELECT COUNT(DISTINCT session_id) AS c FROM messages").fetchone()["c"]
            if self._shared is None:
                conn.close()
        return {"facts": int(facts), "messages": int(messages), "sessions": int(sessions)}
