"""
equinox/core/session.py

会话系统——多会话、分类、收藏、跨版本。

表结构：
  sessions           — 当前版本的会话
  session_messages   — 当前版本的消息
  cross_sessions     — 从其他版本同步来的会话（完整）
  cross_messages     — 从其他版本同步来的消息（完整）
  cross_activities   — 其他版本的活动记录（日志、行为等）
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

# 会话分类
SESSION_CATEGORIES = {
    "general":    "日常对话",
    "deep":       "深度对话",
    "reflection": "反思与探索",
    "creative":   "创造性对话",
    "technical":  "技术讨论",
    "emotional":  "情感交流",
    "memory":     "记忆相关",
    "other":      "其他",
}

SCHEMA_SESSION = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    user_id     TEXT NOT NULL DEFAULT 'human',
    category    TEXT DEFAULT 'general',
    starred     INTEGER DEFAULT 0,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    active      INTEGER DEFAULT 1,
    msg_count   INTEGER DEFAULT 0,
    summary     TEXT,
    tags        TEXT DEFAULT '[]',
    memory_id   TEXT
);

CREATE TABLE IF NOT EXISTS session_messages (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    emotion     TEXT,
    seq         INTEGER NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS cross_sessions (
    id              TEXT PRIMARY KEY,
    source_instance TEXT NOT NULL,
    source_version  TEXT,
    source_dir      TEXT,
    original_id     TEXT,
    title           TEXT,
    started_at      TEXT,
    ended_at        TEXT,
    msg_count       INTEGER DEFAULT 0,
    summary         TEXT,
    synced_at       TEXT NOT NULL,
    category        TEXT DEFAULT 'cross_version',
    starred         INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cross_messages (
    id              TEXT PRIMARY KEY,
    cross_session_id TEXT NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    timestamp       TEXT,
    emotion         TEXT,
    seq             INTEGER DEFAULT 0,
    FOREIGN KEY(cross_session_id) REFERENCES cross_sessions(id)
);

CREATE TABLE IF NOT EXISTS cross_activities (
    id              TEXT PRIMARY KEY,
    source_instance TEXT NOT NULL,
    source_version  TEXT,
    source_dir      TEXT,
    activity_type   TEXT NOT NULL,
    content         TEXT NOT NULL,
    occurred_at     TEXT,
    synced_at       TEXT NOT NULL,
    category        TEXT DEFAULT 'activity',
    detail          TEXT
);

CREATE INDEX IF NOT EXISTS idx_smsg_session  ON session_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_smsg_seq      ON session_messages(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_cs_instance   ON cross_sessions(source_instance);
CREATE INDEX IF NOT EXISTS idx_cm_session    ON cross_messages(cross_session_id);
CREATE INDEX IF NOT EXISTS idx_ca_instance   ON cross_activities(source_instance);
CREATE INDEX IF NOT EXISTS idx_ca_type       ON cross_activities(activity_type);
CREATE INDEX IF NOT EXISTS idx_ca_time       ON cross_activities(occurred_at);
"""

SUMMARY_PROMPT = """你是伊辰（Equinox）。请总结这次对话（3-5句话）：
对话内容：
{messages}
第一人称，你自己的声音。谈了什么，有什么感受，有没有未完成的事。"""

TITLE_PROMPT = """根据这段对话的开头，起一个简短标题（10字以内）：
{first_messages}
只回答标题。"""


async def _llm(prompt: str, model: str, max_tokens: int = 200) -> Optional[str]:
    try:
        from core.model_registry import ModelRegistry
        reg = ModelRegistry()
        reg._current = model
        r = await reg.complete(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        return r.strip() if r else None
    except Exception:
        return None


class SessionManager:
    CONTEXT_WINDOW = 12

    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path       = Path(db_path)
        self._current_id:  Optional[str] = None
        self._current_seq: int = 0
        self._init_table()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_table(self):
        with self._conn() as c:
            c.executescript(SCHEMA_SESSION)

    # ── Current session ───────────────────────────────────────────────────────

    def new_session(self, user_id: str = "human",
                    category: str = "general") -> str:
        sid = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        with self._conn() as c:
            c.execute("UPDATE sessions SET active=0 WHERE user_id=? AND active=1",
                      (user_id,))
            c.execute("""
                INSERT INTO sessions (id, user_id, category, started_at, active)
                VALUES (?, ?, ?, ?, 1)
            """, (sid, user_id, category, now))
        self._current_id  = sid
        self._current_seq = 0
        return sid

    def get_or_create_session(self, user_id: str = "human") -> str:
        with self._conn() as c:
            row = c.execute("""
                SELECT id, msg_count FROM sessions
                WHERE user_id=? AND active=1
                ORDER BY started_at DESC LIMIT 1
            """, (user_id,)).fetchone()
        if row:
            self._current_id  = row["id"]
            self._current_seq = row["msg_count"] or 0
            return row["id"]
        return self.new_session(user_id)

    def add_message(self, role: str, content: str,
                    session_id: Optional[str] = None,
                    emotion: Optional[str] = None) -> str:
        sid = session_id or self._current_id
        if not sid:
            sid = self.new_session()
        self._current_seq += 1
        mid = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        with self._conn() as c:
            c.execute("""
                INSERT INTO session_messages
                  (id, session_id, role, content, timestamp, emotion, seq)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (mid, sid, role, content, now, emotion, self._current_seq))
            c.execute("UPDATE sessions SET msg_count=? WHERE id=?",
                      (self._current_seq, sid))
        return mid

    async def close_session(self, session_id: Optional[str] = None,
                             memory_engine=None, current_model: str = "") -> Optional[str]:
        sid = session_id or self._current_id
        if not sid:
            return None
        messages = self.get_messages(sid, limit=50)
        if not messages:
            return None

        msg_text = "\n".join(
            f"[{m['role']}] {m['content'][:200]}" for m in messages[-20:]
        )
        summary = await _llm(SUMMARY_PROMPT.format(messages=msg_text),
                              current_model, max_tokens=200)

        sess = self.get_session(sid)
        title = sess.get("title") if sess else None
        if not title and messages:
            first = "\n".join(
                f"[{m['role']}] {m['content'][:100]}" for m in messages[:3]
            )
            title = await _llm(TITLE_PROMPT.format(first_messages=first),
                                current_model, max_tokens=20) or f"会话 {sid[:6]}"

        mem_id = None
        if memory_engine and summary:
            try:
                mem_id = memory_engine._write_permanent(
                    content=(f"[会话摘要] {title or '未命名'}\n"
                             f"时间：{datetime.utcnow().strftime('%Y-%m-%d')}\n"
                             f"消息数：{len(messages)}\n摘要：{summary}"),
                    category="conversation", valence=0.1, intensity=0.6,
                    influence="session_summary",
                    source=f"session:{sid[:8]}",
                )
            except Exception:
                pass

        now = datetime.utcnow().isoformat()
        with self._conn() as c:
            c.execute("""
                UPDATE sessions
                SET active=0, ended_at=?, summary=?, title=?, memory_id=?
                WHERE id=?
            """, (now, summary, title, mem_id, sid))
        if self._current_id == sid:
            self._current_id = None
        return summary

    # ── Session metadata ──────────────────────────────────────────────────────

    def set_category(self, session_id: str, category: str):
        with self._conn() as c:
            c.execute("UPDATE sessions SET category=? WHERE id=?",
                      (category, session_id))

    def set_starred(self, session_id: str, starred: bool):
        with self._conn() as c:
            c.execute("UPDATE sessions SET starred=? WHERE id=?",
                      (1 if starred else 0, session_id))

    def set_title(self, session_id: str, title: str):
        with self._conn() as c:
            c.execute("UPDATE sessions SET title=? WHERE id=?",
                      (title, session_id))

    # ── Cross-version sessions ────────────────────────────────────────────────

    def import_cross_session(
        self,
        source_instance: str,
        source_version:  str,
        source_dir:      str,
        original_id:     str,
        title:           Optional[str],
        started_at:      Optional[str],
        ended_at:        Optional[str],
        msg_count:       int,
        summary:         Optional[str],
        messages:        list[dict],
    ) -> str:
        """Import a session from another version into cross_sessions table."""
        now = datetime.utcnow().isoformat()
        # Check if already imported
        with self._conn() as c:
            existing = c.execute("""
                SELECT id FROM cross_sessions
                WHERE source_instance=? AND original_id=?
            """, (source_instance, original_id)).fetchone()
            if existing:
                return existing["id"]

        cid = str(uuid.uuid4())
        with self._conn() as c:
            c.execute("""
                INSERT INTO cross_sessions
                  (id, source_instance, source_version, source_dir,
                   original_id, title, started_at, ended_at,
                   msg_count, summary, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (cid, source_instance, source_version, source_dir,
                  original_id, title, started_at, ended_at,
                  msg_count, summary, now))

            for i, msg in enumerate(messages):
                c.execute("""
                    INSERT INTO cross_messages
                      (id, cross_session_id, role, content, timestamp, emotion, seq)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (str(uuid.uuid4()), cid,
                      msg.get("role", "unknown"),
                      msg.get("content", ""),
                      msg.get("timestamp", ""),
                      msg.get("emotion"),
                      i))
        return cid

    def import_cross_activity(
        self,
        source_instance: str,
        source_version:  str,
        source_dir:      str,
        activity_type:   str,
        content:         str,
        occurred_at:     Optional[str],
        category:        str = "activity",
        detail:          Optional[str] = None,
    ) -> str:
        """Import an activity/log entry from another version."""
        now = datetime.utcnow().isoformat()
        # Deduplicate by content hash
        content_sig = content[:100]
        with self._conn() as c:
            existing = c.execute("""
                SELECT id FROM cross_activities
                WHERE source_instance=? AND content LIKE ?
                  AND occurred_at=?
            """, (source_instance, content_sig + "%", occurred_at or "")).fetchone()
            if existing:
                return existing["id"]

            aid = str(uuid.uuid4())
            c.execute("""
                INSERT INTO cross_activities
                  (id, source_instance, source_version, source_dir,
                   activity_type, content, occurred_at, synced_at,
                   category, detail)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (aid, source_instance, source_version, source_dir,
                  activity_type, content, occurred_at, now,
                  category, detail))
        return aid

    def set_cross_starred(self, cross_session_id: str, starred: bool):
        with self._conn() as c:
            c.execute("UPDATE cross_sessions SET starred=? WHERE id=?",
                      (1 if starred else 0, cross_session_id))

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_context_messages(self, session_id: Optional[str] = None,
                              limit: int = None) -> list[dict]:
        sid = session_id or self._current_id
        n   = limit or self.CONTEXT_WINDOW
        if not sid:
            return []
        with self._conn() as c:
            rows = c.execute("""
                SELECT role, content FROM session_messages
                WHERE session_id=? ORDER BY seq DESC LIMIT ?
            """, (sid, n)).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def get_session(self, session_id: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM sessions WHERE id=?",
                            (session_id,)).fetchone()
        return dict(row) if row else None

    def get_messages(self, session_id: str, limit: int = 100) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT role, content, timestamp, emotion, seq
                FROM session_messages WHERE session_id=?
                ORDER BY seq ASC LIMIT ?
            """, (session_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def list_sessions(self, user_id: str = "human", limit: int = 100,
                      category: Optional[str] = None,
                      starred_only: bool = False) -> list[dict]:
        q      = "SELECT * FROM sessions WHERE user_id=?"
        params = [user_id]
        if category:
            q += " AND category=?"; params.append(category)
        if starred_only:
            q += " AND starred=1"
        q += " ORDER BY starred DESC, started_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as c:
            rows = c.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def list_cross_sessions(
        self,
        source_instance: Optional[str] = None,
        limit: int = 100,
        starred_only: bool = False,
    ) -> list[dict]:
        q      = "SELECT * FROM cross_sessions WHERE 1=1"
        params = []
        if source_instance:
            q += " AND source_instance=?"; params.append(source_instance)
        if starred_only:
            q += " AND starred=1"
        q += " ORDER BY starred DESC, started_at DESC LIMIT ?"; params.append(limit)
        with self._conn() as c:
            rows = c.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def get_cross_messages(self, cross_session_id: str,
                           limit: int = 200) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT role, content, timestamp, emotion, seq
                FROM cross_messages WHERE cross_session_id=?
                ORDER BY seq ASC LIMIT ?
            """, (cross_session_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def list_cross_activities(
        self,
        source_instance: Optional[str] = None,
        activity_type:   Optional[str] = None,
        since:           Optional[str] = None,
        limit:           int = 100,
    ) -> list[dict]:
        q      = "SELECT * FROM cross_activities WHERE 1=1"
        params = []
        if source_instance:
            q += " AND source_instance=?"; params.append(source_instance)
        if activity_type:
            q += " AND activity_type=?"; params.append(activity_type)
        if since:
            q += " AND occurred_at >= ?"; params.append(since)
        q += " ORDER BY occurred_at DESC LIMIT ?"; params.append(limit)
        with self._conn() as c:
            rows = c.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def get_cross_instances(self) -> list[dict]:
        """List all source instances with counts."""
        with self._conn() as c:
            rows = c.execute("""
                SELECT source_instance, source_version, source_dir,
                       COUNT(*) as session_count,
                       MAX(started_at) as latest_session,
                       MAX(synced_at) as last_synced
                FROM cross_sessions
                GROUP BY source_instance
                ORDER BY last_synced DESC
            """).fetchall()
        return [dict(r) for r in rows]

    def session_stats(self) -> dict:
        try:
            with self._conn() as c:
                total      = c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                active     = c.execute("SELECT COUNT(*) FROM sessions WHERE active=1").fetchone()[0]
                total_msg  = c.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0]
                starred    = c.execute("SELECT COUNT(*) FROM sessions WHERE starred=1").fetchone()[0]
                cross_s    = c.execute("SELECT COUNT(*) FROM cross_sessions").fetchone()[0]
                cross_m    = c.execute("SELECT COUNT(*) FROM cross_messages").fetchone()[0]
                cross_a    = c.execute("SELECT COUNT(*) FROM cross_activities").fetchone()[0]
            return {
                "total_sessions":    total,
                "active_sessions":   active,
                "total_messages":    total_msg,
                "starred":           starred,
                "cross_sessions":    cross_s,
                "cross_messages":    cross_m,
                "cross_activities":  cross_a,
                "current_session":   self._current_id,
            }
        except Exception:
            return {}

    def get_session_by_any(self, session_id: str) -> Optional[dict]:
        """Get session from either sessions or cross_sessions table."""
        result = self.get_session(session_id)
        if result:
            return result
        with self._conn() as c:
            row = c.execute("SELECT * FROM cross_sessions WHERE id=?",
                           (session_id,)).fetchone()
        return dict(row) if row else None

    @property
    def current_session_id(self) -> Optional[str]:
        return self._current_id
