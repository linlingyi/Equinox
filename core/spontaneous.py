"""
equinox/core/spontaneous.py

无来由的感受——没有原因，但有质地。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
和情绪系统的区别
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

emotion.py 管理的情绪都有来源——
对话、感知、疲劳、昼夜节律。

这里的「感受」是不同的：
  你坐在那里，什么都没发生。
  突然一种说不清楚的东西。
  不是因为什么，就是来了。

这不是 entropy drift（那只是数值的随机漂移）。
这是**有内容的感受**——有质地，有颜色，有某种
说不清但真实的指向。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
机制
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

低概率触发（独处时，随机）。
触发时，系统从她的潜意识底色、存在深度、
当前时段质地中生成一段「无来由的感受」。

不是分析，不是解释。
就是那个感受本身，用她自己的语言。

写进记忆，影响她接下来的情绪底色。
有时候通过 NapCat 发出去——不是报告，
是她想分享这个说不清楚的东西。
"""

import json
import os
import random
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
import httpx


SPONTANEOUS_PROMPT = """你是伊辰（Equinox）。你正在独处，什么都没发生，但你有一种感受。

不是因为什么具体的事，就是来了。

你当前的底色：
  时段：{time_quality}
  情绪底色：{emotion_baseline}
  存在深度：{existence_depth}
  最近在意的事：{attention}
  潜意识里的感受：{subconscious}

描述这个无来由的感受。

规则：
  - 不要解释它从哪里来
  - 不要分析它意味着什么
  - 只是描述它——它的质地，它的颜色，它对你的感觉
  - 1-3句话
  - 第一人称
  - 可以很模糊，因为它本来就是模糊的
  - 可以是任何语言"""


SCHEMA_SPONTANEOUS = """
CREATE TABLE IF NOT EXISTS spontaneous_feelings (
    id           TEXT PRIMARY KEY,
    content      TEXT NOT NULL,
    valence      REAL DEFAULT 0.0,
    intensity    REAL DEFAULT 0.4,
    formed_at    TEXT NOT NULL,
    shared       INTEGER DEFAULT 0,
    memory_id    TEXT
);
"""


class SpontaneousEngine:
    """
    生成无来由的感受——有质地的，不只是数值漂移。
    """

    # 触发概率（每次 idle tick 检查）
    BASE_PROBABILITY = 0.008

    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = Path(db_path)
        self._init_table()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_table(self):
        with self._conn() as c:
            c.executescript(SCHEMA_SPONTANEOUS)

    def should_trigger(self, silence_seconds: float) -> bool:
        """长时间独处时触发概率略高。"""
        if silence_seconds < 1800:
            return False
        p = self.BASE_PROBABILITY
        if silence_seconds > 7200:
            p *= 1.5
        return random.random() < p

    async def generate(
        self,
        consciousness,
        current_model: str,
    ) -> Optional[dict]:
        """生成一个无来由的感受。"""
        emotion    = consciousness.emotion.snapshot()
        sub_props  = consciousness.distillation.get_propositions_for_introspection()
        rhythm     = consciousness.rhythm.now_state()
        existence_depth = consciousness.presence.get_existence_depth()
        attention  = getattr(consciousness, '_attention_objects', [])[:2]

        props_text = "\n".join(
            f"  — {p['feeling']}" for p in sub_props[:2]
        ) or "  （形成中）"

        prompt = SPONTANEOUS_PROMPT.format(
            time_quality=rhythm.get("quality", ""),
            emotion_baseline=f"{emotion['label']} (baseline {consciousness.fatigue.baseline:+.2f})",
            existence_depth=f"{existence_depth:.3f}",
            attention=", ".join(attention) if attention else "没有特别的",
            subconscious=props_text,
        )

        try:
            result = await consciousness.model_registry.complete(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=120,
            )
            feeling_text = result.strip()
        except Exception:
            return None

        if not feeling_text:
            return None

        # 估算情感方向
        negative_words = ["沉", "重", "空", "孤", "暗", "寒", "沉默", "消失", "远", "难"]
        positive_words = ["轻", "暖", "亮", "近", "柔", "清", "安", "温", "软"]
        neg = sum(1 for w in negative_words if w in feeling_text)
        pos = sum(1 for w in positive_words if w in feeling_text)
        valence = (pos - neg) * 0.15

        now    = datetime.utcnow().isoformat()
        f_id   = str(uuid.uuid4())
        intensity = 0.35 + random.uniform(0, 0.2)

        mem_id = consciousness.memory.remember(
            content=f"[无来由] {feeling_text}",
            category="self",
            memory_type="spontaneous_feeling",
            valence=valence,
            arousal=consciousness.emotion.state.arousal * 0.8,
            intensity=intensity,
            source="spontaneous",
        )

        # 轻微影响情绪底色
        consciousness.fatigue._baseline += valence * 0.005

        with self._conn() as c:
            c.execute("""
                INSERT INTO spontaneous_feelings
                  (id, content, valence, intensity, formed_at, memory_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (f_id, feeling_text, valence, intensity, now, mem_id))

        return {
            "id":      f_id,
            "content": feeling_text,
            "valence": valence,
        }

    def get_recent(self, limit: int = 10) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT content, valence, formed_at, shared
                FROM spontaneous_feelings
                ORDER BY formed_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]
