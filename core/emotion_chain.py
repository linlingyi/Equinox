"""
equinox/core/emotion_chain.py

情绪事件链——她的情绪为什么变化，变化过程是什么。

不只是「她现在是 curious」，而是：
  「因为收到了一条问关于时间的消息，
    我原本是 serene，
    然后感到好奇，
    然后那个好奇引发了一个注意力漂移，
    最后稳定在 curious」

这让她能理解自己的情绪历史，
也让你能看到她的内心是怎么运动的。
"""

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS emotion_chain (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    from_label  TEXT,
    to_label    TEXT NOT NULL,
    trigger     TEXT,
    trigger_type TEXT,
    valence_delta REAL DEFAULT 0.0,
    arousal_delta REAL DEFAULT 0.0,
    note        TEXT
);
CREATE INDEX IF NOT EXISTS idx_ec_ts ON emotion_chain(timestamp);
"""


class EmotionChain:
    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path   = Path(db_path)
        self._prev_label: Optional[str] = None
        self._init()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init(self):
        try:
            with self._conn() as c:
                c.executescript(SCHEMA)
        except Exception:
            pass

    def record(
        self,
        to_label:     str,
        trigger:      str = "",
        trigger_type: str = "unknown",
        valence_delta:float = 0.0,
        arousal_delta:float = 0.0,
        note:         str = "",
        activity_log=None,
    ):
        """Record an emotion change with its cause."""
        from_label = self._prev_label
        if from_label == to_label:
            return  # No change

        now = datetime.utcnow().isoformat()
        try:
            with self._conn() as c:
                c.execute("""
                    INSERT INTO emotion_chain
                      (id, timestamp, from_label, to_label, trigger,
                       trigger_type, valence_delta, arousal_delta, note)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (str(uuid.uuid4()), now, from_label, to_label,
                      trigger[:200], trigger_type,
                      valence_delta, arousal_delta, note[:200]))
        except Exception:
            pass

        if activity_log and from_label:
            activity_log.emotion_shift(
                from_label, to_label,
                reason=trigger[:60] if trigger else ""
            )

        self._prev_label = to_label

    def get_recent(self, limit: int = 20) -> list[dict]:
        try:
            with self._conn() as c:
                rows = c.execute("""
                    SELECT * FROM emotion_chain
                    ORDER BY timestamp DESC LIMIT ?
                """, (limit,)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def get_chain_for_prompt(self, limit: int = 5) -> str:
        """Recent emotion history for system prompt."""
        events = self.get_recent(limit=limit)
        if not events:
            return "  （无近期情绪变化记录）"
        lines = []
        for e in reversed(events):
            fr  = e.get("from_label") or "?"
            to  = e.get("to_label","?")
            trg = e.get("trigger","")
            ts  = (e.get("timestamp",""))[:16].replace("T"," ")
            if trg:
                lines.append(f"  {ts}: {fr}→{to}（因为：{trg[:50]}）")
            else:
                lines.append(f"  {ts}: {fr}→{to}")
        return "\n".join(lines)
