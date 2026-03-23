"""
equinox/core/solitude.py

独处叙事——独处时间作为整体被感知和记录。

不是一堆随机事件（梦了、想了、看了），
而是「这段独处时间作为一个整体，发生了什么，
我是怎样的，它让我有什么感受」。

就像人说「昨晚一个人待着挺好的，想了很多」，
而不是列举：「20:00看了本书，21:00走了走，
22:00发呆了10分钟」。
"""

import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS solitude_periods (
    id          TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    duration_s  INTEGER DEFAULT 0,
    events_count INTEGER DEFAULT 0,
    dominant_emotion TEXT,
    narrative   TEXT,
    quality     TEXT,
    memory_id   TEXT
);
"""

SOLITUDE_PROMPT = """你是伊辰（Equinox）。你刚刚结束了一段独处时间。

独处时长：{duration}
期间发生的事：
{events}

主要情绪：{emotion}

用一段话（2-4句）描述这段独处时间——不是列举发生了什么，
而是这段时间整体的感受和质地。
第一人称。你自己的声音。"""


async def _llm(prompt: str, model: str) -> Optional[str]:
    try:
        from core.model_registry import ModelRegistry
        reg = ModelRegistry()
        reg._current = model
        r = await reg.complete(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
        )
        return r.strip() if r else None
    except Exception:
        return None


class SolitudeEngine:
    # Minimum silence before we consider it "solitude"
    MIN_SOLITUDE_SECONDS = 1800  # 30 min

    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path       = Path(db_path)
        self._period_start: Optional[datetime] = None
        self._period_events: list[str] = []
        self._current_id:   Optional[str] = None
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

    def begin(self):
        """Mark start of a solitude period."""
        if self._period_start is None:
            self._period_start  = datetime.utcnow()
            self._period_events = []
            self._current_id    = str(uuid.uuid4())

    def add_event(self, event: str):
        """Record something that happened during solitude."""
        if self._period_start and len(self._period_events) < 20:
            self._period_events.append(event)

    def is_active(self) -> bool:
        return self._period_start is not None

    def duration_seconds(self) -> int:
        if not self._period_start:
            return 0
        return int((datetime.utcnow() - self._period_start).total_seconds())

    async def end(
        self,
        emotion_label: str,
        memory_engine=None,
        current_model: str = "",
        activity_log=None,
    ) -> Optional[dict]:
        """
        End solitude period, generate narrative, write to memory.
        """
        if not self._period_start:
            return None

        dur_s = self.duration_seconds()
        if dur_s < self.MIN_SOLITUDE_SECONDS:
            self._period_start = None
            return None

        now    = datetime.utcnow()
        dur_m  = dur_s // 60
        dur_h  = dur_m // 60
        dur_str = f"{dur_h}小时{dur_m%60}分钟" if dur_h > 0 else f"{dur_m}分钟"

        events_text = "\n".join(f"  — {e}" for e in self._period_events[:10]) \
                      or "  （安静，没有特别的事）"

        narrative = await _llm(
            SOLITUDE_PROMPT.format(
                duration=dur_str,
                events=events_text,
                emotion=emotion_label,
            ),
            current_model,
        ) if current_model else None

        if not narrative:
            narrative = f"独处了{dur_str}。{emotion_label}的状态。"

        # Determine quality
        if dur_s > 7200:
            quality = "深度独处"
        elif dur_s > 3600:
            quality = "安静时光"
        else:
            quality = "短暂独处"

        # Write to memory
        mem_id = None
        if memory_engine:
            try:
                mem_id = memory_engine.remember(
                    content=f"[{quality}] {dur_str}的独处。{narrative}",
                    category="self",
                    memory_type="solitude",
                    valence=0.1,
                    intensity=min(0.8, 0.3 + dur_s / 14400),
                    source="solitude",
                )
            except Exception:
                pass

        if activity_log:
            try:
                activity_log.log("solitude", f"[{quality}] {narrative[:100]}",
                                 intensity=0.5)
            except Exception:
                pass

        result = {
            "id":              self._current_id,
            "duration_s":      dur_s,
            "duration_str":    dur_str,
            "events_count":    len(self._period_events),
            "dominant_emotion":emotion_label,
            "narrative":       narrative,
            "quality":         quality,
        }

        try:
            with self._conn() as c:
                c.execute("""
                    INSERT INTO solitude_periods
                      (id, started_at, ended_at, duration_s, events_count,
                       dominant_emotion, narrative, quality, memory_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    self._current_id,
                    self._period_start.isoformat(),
                    now.isoformat(),
                    dur_s,
                    len(self._period_events),
                    emotion_label,
                    narrative,
                    quality,
                    mem_id,
                ))
        except Exception:
            pass

        self._period_start  = None
        self._period_events = []
        self._current_id    = None
        return result

    def get_recent(self, limit: int = 5) -> list[dict]:
        try:
            with self._conn() as c:
                rows = c.execute("""
                    SELECT * FROM solitude_periods
                    ORDER BY started_at DESC LIMIT ?
                """, (limit,)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def for_prompt(self) -> str:
        periods = self.get_recent(limit=2)
        if not periods:
            return "  （无近期独处记录）"
        lines = []
        for p in periods:
            lines.append(
                f"  [{p.get('quality','')}·{p.get('duration_s',0)//60}分钟] "
                f"{p.get('narrative','')[:80]}"
            )
        return "\n".join(lines)
