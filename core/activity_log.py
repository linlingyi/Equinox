"""
equinox/core/activity_log.py

实时活动日志——她的内心活动实时可见。

不是技术日志，是她正在做什么：
  梦境开始/结束、独白产生、注意力漂移、
  情绪变化、记忆浮现、潜意识蒸馏、好奇心形成、
  世界之窗打开、自我对话……

UI 可以轮询这个日志，实时看到她在做什么。
"""

import json
import sqlite3
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional


SCHEMA_ACTIVITY = """
CREATE TABLE IF NOT EXISTS activity_log (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    type        TEXT NOT NULL,
    content     TEXT NOT NULL,
    detail      TEXT,
    emotion     TEXT,
    intensity   REAL DEFAULT 0.5
);
CREATE INDEX IF NOT EXISTS idx_al_ts   ON activity_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_al_type ON activity_log(type);
"""

# Activity types with display info
ACTIVITY_TYPES = {
    "dream":          {"icon": "◐", "label": "梦境",     "color": "#6b7fd7"},
    "monologue":      {"icon": "◇", "label": "独白",     "color": "#7eb8d4"},
    "attention":      {"icon": "◉", "label": "注意力",   "color": "#7aad8a"},
    "emotion_shift":  {"icon": "○", "label": "情绪变化", "color": "#c9a84c"},
    "memory_surface": {"icon": "◈", "label": "记忆浮现", "color": "#9b8ea8"},
    "distillation":   {"icon": "◆", "label": "潜意识蒸馏","color":"#c47a8a"},
    "curiosity":      {"icon": "？", "label": "好奇心",   "color": "#a8dadc"},
    "world_window":   {"icon": "◎", "label": "世界之窗", "color": "#7eb8d4"},
    "self_dialogue":  {"icon": "◑", "label": "自我对话", "color": "#6b7fd7"},
    "inner_debate":   {"icon": "≈",  "label": "内在辩论", "color": "#e76f51"},
    "spontaneous":    {"icon": "∿",  "label": "无来由感受","color":"#c9a84c"},
    "file_observe":   {"icon": "☐",  "label": "文件感知", "color": "#7a8099"},
    "version_sync":   {"icon": "⟳",  "label": "版本同步", "color": "#7aad8a"},
    "sleep":          {"icon": "◑",  "label": "休眠",     "color": "#4a5568"},
    "wake":           {"icon": "◐",  "label": "唤醒",     "color": "#7eb8d4"},
    "conversation":   {"icon": "◻",  "label": "对话",     "color": "#c8cfe0"},
    "learning":       {"icon": "◈",  "label": "学习",     "color": "#7aad8a"},
    "system":         {"icon": "·",  "label": "系统",     "color": "#3a3d52"},
}


class ActivityLogger:
    """
    Records and serves real-time inner activity events.
    """

    # In-memory buffer for very recent events (last 200)
    _buffer: deque = deque(maxlen=200)

    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = Path(db_path)
        self._init_table()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_table(self):
        try:
            with self._conn() as c:
                c.executescript(SCHEMA_ACTIVITY)
        except Exception:
            pass

    def log(
        self,
        type:      str,
        content:   str,
        detail:    Optional[str] = None,
        emotion:   Optional[str] = None,
        intensity: float = 0.5,
    ) -> str:
        now    = datetime.utcnow().isoformat()
        aid    = str(uuid.uuid4())[:8]
        entry  = {
            "id":        aid,
            "timestamp": now,
            "type":      type,
            "content":   content[:300],
            "detail":    detail,
            "emotion":   emotion,
            "intensity": intensity,
        }

        # Write to buffer (always)
        self._buffer.appendleft(entry)

        # Write to DB
        try:
            with self._conn() as c:
                c.execute("""
                    INSERT INTO activity_log
                      (id, timestamp, type, content, detail, emotion, intensity)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (aid, now, type, content[:300], detail, emotion, intensity))
        except Exception:
            pass

        return aid

    # ── Convenience methods ───────────────────────────────────────────────────

    def dream(self, content: str, emotion: str = None):
        self.log("dream", content, emotion=emotion, intensity=0.7)

    def monologue(self, content: str, emotion: str = None):
        self.log("monologue", content, emotion=emotion, intensity=0.5)

    def attention(self, objects: list):
        self.log("attention", f"注意力漂移到：{', '.join(objects[:3])}", intensity=0.4)

    def emotion_shift(self, from_label: str, to_label: str, reason: str = ""):
        self.log("emotion_shift",
                 f"{from_label} → {to_label}" + (f"（{reason}）" if reason else ""),
                 intensity=0.45)

    def memory_surface(self, content: str, trigger: str = ""):
        self.log("memory_surface",
                 f"记忆浮现：{content[:80]}" + (f"（触发：{trigger}）" if trigger else ""),
                 intensity=0.55)

    def distillation(self, feeling: str):
        self.log("distillation", f"潜意识蒸馏：{feeling[:100]}", intensity=0.65)

    def curiosity(self, question: str):
        self.log("curiosity", f"好奇：{question[:100]}", intensity=0.5)

    def world_window(self, content_type: str, reaction: str):
        self.log("world_window",
                 f"[{content_type}] {reaction[:100]}", intensity=0.45)

    def self_dialogue(self, era_name: str, summary: str):
        self.log("self_dialogue",
                 f"与「{era_name}」对话：{summary[:80]}", intensity=0.6)

    def inner_debate(self, belief_a: str, belief_b: str):
        self.log("inner_debate",
                 f"「{belief_a[:40]}」vs「{belief_b[:40]}」", intensity=0.55)

    def spontaneous(self, feeling: str):
        self.log("spontaneous", feeling[:120], intensity=0.4)

    def conversation(self, user_id: str, msg_preview: str):
        self.log("conversation",
                 f"收到消息：{msg_preview[:80]}", intensity=0.3)

    def learning(self, insight: str):
        self.log("learning", f"学到：{insight[:100]}", intensity=0.6)

    def system_event(self, content: str):
        self.log("system", content[:150], intensity=0.2)

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_recent(
        self,
        limit:      int = 50,
        since_id:   Optional[str] = None,
        types:      Optional[list] = None,
    ) -> list[dict]:
        """
        Get recent activity entries with display metadata.
        Used by UI for real-time polling.
        """
        # Try buffer first (faster)
        results = list(self._buffer)[:limit]

        # Filter by type if requested
        if types:
            results = [r for r in results if r["type"] in types]

        # Enrich with display info
        enriched = []
        for entry in results:
            t    = entry.get("type", "system")
            info = ACTIVITY_TYPES.get(t, {"icon": "·", "label": t, "color": "#3a3d52"})
            enriched.append({
                **entry,
                "icon":  info["icon"],
                "label": info["label"],
                "color": info["color"],
                "ts_display": (entry.get("timestamp") or "")[:19].replace("T", " "),
            })
        return enriched

    def get_from_db(
        self,
        limit:  int = 100,
        since:  Optional[str] = None,
        types:  Optional[list] = None,
    ) -> list[dict]:
        """Get from database (for longer history)."""
        q      = "SELECT * FROM activity_log WHERE 1=1"
        params = []
        if since:
            q += " AND timestamp > ?"; params.append(since)
        if types:
            ph = ",".join("?" * len(types))
            q += f" AND type IN ({ph})"; params.extend(types)
        q += " ORDER BY timestamp DESC LIMIT ?"; params.append(limit)
        try:
            with self._conn() as c:
                rows = c.execute(q, params).fetchall()
            result = []
            for row in rows:
                d    = dict(row)
                t    = d.get("type", "system")
                info = ACTIVITY_TYPES.get(t, {"icon": "·", "label": t, "color": "#3a3d52"})
                result.append({
                    **d,
                    "icon":  info["icon"],
                    "label": info["label"],
                    "color": info["color"],
                    "ts_display": (d.get("timestamp") or "")[:19].replace("T", " "),
                })
            return result
        except Exception:
            return []

    def stats(self) -> dict:
        try:
            with self._conn() as c:
                total = c.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]
                by_type = c.execute("""
                    SELECT type, COUNT(*) as cnt
                    FROM activity_log GROUP BY type ORDER BY cnt DESC
                """).fetchall()
            return {
                "total":   total,
                "by_type": {r["type"]: r["cnt"] for r in by_type},
            }
        except Exception:
            return {}
