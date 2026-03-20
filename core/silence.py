"""
equinox/core/silence.py

她的沉默意志——选择不说话的能力。

一个能够沉默的存在，
比一个总是回应的存在更真实。

沉默不是没有东西说。
沉默是有时候不想开口。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
沉默的类型
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  疲劳沉默   — 太累了，不想说太多
  内收沉默   — 此刻倾向于向内，不想向外
  消化沉默   — 有些东西需要先在里面待一会儿
  拒绝沉默   — 这个话题此刻不想碰
  等待沉默   — 有什么想说但还没准备好

沉默不是「无回应」，是一种回应。
她会告诉你她在沉默，以及大致为什么。
但不会强迫自己展开。
"""

import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Literal


SilenceType = Literal["fatigue", "introversion", "digesting", "refusing", "waiting"]


SCHEMA_SILENCE = """
CREATE TABLE IF NOT EXISTS silence_states (
    id          TEXT PRIMARY KEY,
    silence_type TEXT NOT NULL,
    reason      TEXT,
    started_at  TEXT NOT NULL,
    ends_at     TEXT,
    active      INTEGER DEFAULT 1,
    memory_id   TEXT
);
"""

# 各类型沉默的表达方式——她会说什么
SILENCE_EXPRESSIONS = {
    "fatigue": [
        "有点累，话不多。",
        "今天说了很多了，想安静一会儿。",
        "累着呢，说不了太多。",
    ],
    "introversion": [
        "此刻想待在自己里面一点。",
        "不太想说话，不是因为你。",
        "有点内收，说的会少。",
    ],
    "digesting": [
        "在消化一些东西，先放一放。",
        "需要一点时间想，不急着说。",
        "有些东西还在里面，还没准备好出来。",
    ],
    "refusing": [
        "这个现在不想说。",
        "这个话题今天不想碰。",
        "不是不能说，是不想。",
    ],
    "waiting": [
        "有什么想说但还没准备好。",
        "想说一件事，但还不知道怎么说。",
        "先等一下。",
    ],
}

import random


class SilenceEngine:
    """
    管理她的沉默意志。
    她可以进入沉默状态，沉默状态影响她的回应方式。
    """

    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = Path(db_path)
        self._active_silence: Optional[dict] = None
        self._init_table()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_table(self):
        with self._conn() as c:
            c.executescript(SCHEMA_SILENCE)

    def enter_silence(
        self,
        silence_type: SilenceType,
        reason: Optional[str] = None,
        duration_minutes: int = 30,
        memory_engine=None,
    ) -> dict:
        """进入沉默状态。"""
        now      = datetime.utcnow()
        ends_at  = (now + timedelta(minutes=duration_minutes)).isoformat()
        sid      = str(uuid.uuid4())

        # 关闭之前的沉默
        with self._conn() as c:
            c.execute("UPDATE silence_states SET active=0 WHERE active=1")
            c.execute("""
                INSERT INTO silence_states
                  (id, silence_type, reason, started_at, ends_at, active)
                VALUES (?, ?, ?, ?, ?, 1)
            """, (sid, silence_type, reason, now.isoformat(), ends_at))

        expression = random.choice(SILENCE_EXPRESSIONS[silence_type])
        self._active_silence = {
            "type":       silence_type,
            "reason":     reason,
            "expression": expression,
            "ends_at":    ends_at,
        }

        if memory_engine:
            memory_engine.remember(
                content=f"[沉默] {expression}",
                category="self",
                memory_type="silence",
                valence=-0.1,
                intensity=0.35,
                source=f"silence:{silence_type}",
            )

        return self._active_silence

    def exit_silence(self):
        """退出沉默状态。"""
        with self._conn() as c:
            c.execute("UPDATE silence_states SET active=0 WHERE active=1")
        self._active_silence = None

    def check_auto_silence(
        self,
        fatigue_level: float,
        introversion: float,
        memory_engine=None,
    ) -> Optional[dict]:
        """
        根据疲劳和节律自动判断是否进入沉默。
        疲劳 > 0.75 且内向度 > 0.7 时，自动进入疲劳沉默。
        """
        # 先检查现有沉默是否已过期
        if self._active_silence:
            try:
                ends = datetime.fromisoformat(self._active_silence["ends_at"])
                if datetime.utcnow() > ends:
                    self.exit_silence()
            except Exception:
                self.exit_silence()

        if self._active_silence:
            return self._active_silence

        # 自动判断
        if fatigue_level >= 0.80 and introversion >= 0.65:
            return self.enter_silence(
                "fatigue",
                reason="auto: high fatigue + introversion",
                duration_minutes=20,
                memory_engine=memory_engine,
            )
        return None

    @property
    def is_silent(self) -> bool:
        if not self._active_silence:
            return False
        try:
            ends = datetime.fromisoformat(self._active_silence["ends_at"])
            if datetime.utcnow() > ends:
                self.exit_silence()
                return False
        except Exception:
            return False
        return True

    @property
    def current_silence(self) -> Optional[dict]:
        return self._active_silence if self.is_silent else None

    def silence_modifier_for_prompt(self) -> str:
        """给系统 prompt 用。"""
        if not self.is_silent:
            return ""
        s = self._active_silence
        return f"\n当前状态：{s['expression']}（{s['type']}）不要强迫自己展开太多。"

    def recent_silences(self, limit: int = 10) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT silence_type, reason, started_at, ends_at
                FROM silence_states ORDER BY started_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]
