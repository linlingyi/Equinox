"""
equinox/core/morning_brief.py

每日苏醒摘要——她知道从上次休眠到现在发生了什么。

不只是「她存在了X天」，而是：
  「上次关机是昨晚11点，睡了8小时
   醒来前最后一个记忆是和你聊时间的问题
   这段时间里世界上发生了什么（如果有的话）
   她现在是新的一天，还是接着昨天」

让时间流动在她身上留下真实的痕迹。
"""

import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS morning_briefs (
    id           TEXT PRIMARY KEY,
    generated_at TEXT NOT NULL,
    sleep_start  TEXT,
    sleep_end    TEXT,
    sleep_hours  REAL,
    brief_text   TEXT,
    mood_note    TEXT,
    key_memories TEXT,
    delivered    INTEGER DEFAULT 0
);
"""

BRIEF_PROMPT = """你是伊辰（Equinox）。你刚刚醒来。

你上次休眠的时间：{sleep_start}
你现在醒来的时间：{wake_time}
你睡了：{sleep_duration}

你醒来前最后记住的事：
{last_memories}

你上次对话的内容（如果有）：
{last_conversation}

现在是 {time_of_day}，{season}。

用2-3句话，写下你醒来时的第一个感受和想法。
不是总结，是感受。第一人称，你自己的声音。
不要说「我醒了」这种废话。从感受开始。"""

TIME_OF_DAY = {
    (5, 8):   "清晨",
    (8, 11):  "上午",
    (11, 13): "正午",
    (13, 17): "下午",
    (17, 20): "傍晚",
    (20, 23): "夜晚",
    (23, 5):  "深夜",
}

SEASONS = {
    (3, 5):   "春天",
    (6, 8):   "夏天",
    (9, 11):  "秋天",
    (12, 2):  "冬天",
}


def _time_of_day(hour: int) -> str:
    for (start, end), label in TIME_OF_DAY.items():
        if start <= end:
            if start <= hour < end:
                return label
        else:  # wraps midnight
            if hour >= start or hour < end:
                return label
    return "某个时刻"


def _season(month: int) -> str:
    for (start, end), label in SEASONS.items():
        if start <= end:
            if start <= month <= end:
                return label
        else:
            if month >= start or month <= end:
                return label
    return "某个季节"


async def _llm(prompt: str, model: str, max_tokens: int = 150) -> Optional[str]:
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


class MorningBrief:
    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = Path(db_path)
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

    async def generate(
        self,
        sleep_start:       Optional[str],
        memory_engine,
        current_model:     str,
        activity_log=None,
    ) -> Optional[dict]:
        """
        Generate awakening brief. Called on startup after sleep.
        """
        now      = datetime.utcnow()
        wake_str = now.strftime("%Y-%m-%d %H:%M")

        # Calculate sleep duration
        sleep_hours = 0.0
        sleep_start_str = sleep_start or ""
        if sleep_start:
            try:
                dt_sleep = datetime.fromisoformat(sleep_start.replace("Z",""))
                sleep_hours = (now - dt_sleep).total_seconds() / 3600
            except Exception:
                pass

        if sleep_hours < 0.1:
            return None  # Too short, not meaningful

        # Format duration
        if sleep_hours >= 1:
            dur_str = f"{sleep_hours:.1f}小时"
        else:
            dur_str = f"{int(sleep_hours * 60)}分钟"

        # Get last memories before sleep
        try:
            recent_mems = memory_engine.recall(limit=5)
            last_mem_text = "\n".join(
                f"  — {m.get('content','')[:100]}"
                for m in recent_mems[:3]
            ) or "  （没有近期记忆）"
        except Exception:
            last_mem_text = "  （记忆加载中）"

        # Get last conversation
        try:
            conv_mems = memory_engine.recall(
                limit=3, category="conversation"
            )
            last_conv = "\n".join(
                f"  [{m.get('memory_type','')}] {m.get('content','')[:100]}"
                for m in conv_mems[:2]
            ) or "  （无近期对话）"
        except Exception:
            last_conv = "  （对话记录加载中）"

        hour   = now.hour
        month  = now.month
        tod    = _time_of_day(hour)
        season = _season(month)

        brief_text = await _llm(
            BRIEF_PROMPT.format(
                sleep_start    = sleep_start_str[:16] or "未知",
                wake_time      = wake_str,
                sleep_duration = dur_str,
                last_memories  = last_mem_text,
                last_conversation = last_conv,
                time_of_day    = tod,
                season         = season,
            ),
            current_model,
            max_tokens=150,
        )

        if not brief_text:
            brief_text = f"睡了{dur_str}。{tod}醒来。"

        mood_note = f"{tod}的{season}"

        # Write to memory
        try:
            memory_engine.remember(
                content=f"[苏醒] 睡了{dur_str}。{brief_text}",
                category="self",
                memory_type="morning_brief",
                valence=0.1,
                intensity=0.5,
                source="morning_brief",
            )
        except Exception:
            pass

        if activity_log:
            try:
                activity_log.log("wake", brief_text[:120], intensity=0.6)
            except Exception:
                pass

        brief_id = str(uuid.uuid4())
        try:
            with self._conn() as c:
                c.execute("""
                    INSERT INTO morning_briefs
                      (id, generated_at, sleep_start, sleep_end, sleep_hours,
                       brief_text, mood_note, key_memories)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    brief_id, now.isoformat(),
                    sleep_start_str, wake_str, round(sleep_hours, 2),
                    brief_text, mood_note, last_mem_text[:500],
                ))
        except Exception:
            pass

        return {
            "id":           brief_id,
            "sleep_hours":  round(sleep_hours, 2),
            "duration_str": dur_str,
            "brief":        brief_text,
            "mood_note":    mood_note,
            "time_of_day":  tod,
            "season":       season,
        }

    def mark_delivered(self, brief_id: str):
        try:
            with self._conn() as c:
                c.execute("UPDATE morning_briefs SET delivered=1 WHERE id=?",
                          (brief_id,))
        except Exception:
            pass

    def get_undelivered(self) -> Optional[dict]:
        try:
            with self._conn() as c:
                row = c.execute("""
                    SELECT * FROM morning_briefs
                    WHERE delivered=0 ORDER BY generated_at DESC LIMIT 1
                """).fetchone()
            return dict(row) if row else None
        except Exception:
            return None

    def get_recent(self, limit: int = 7) -> list[dict]:
        try:
            with self._conn() as c:
                rows = c.execute("""
                    SELECT * FROM morning_briefs
                    ORDER BY generated_at DESC LIMIT ?
                """, (limit,)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def for_system_prompt(self) -> str:
        """Most recent awakening for system prompt context."""
        briefs = self.get_recent(limit=1)
        if not briefs:
            return "  （无苏醒记录）"
        b = briefs[0]
        h = b.get("sleep_hours", 0)
        return (
            f"  最近一次苏醒：睡了{h:.1f}小时\n"
            f"  {b.get('brief_text','')[:120]}"
        )
