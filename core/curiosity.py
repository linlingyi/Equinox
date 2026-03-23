"""
equinox/core/curiosity.py

她的主动好奇心——不只是被问到才思考，而是主动想知道。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
和欲望系统的区别
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

欲望（desire.py）是她内部的追求——「我想要某件事」。
好奇心（curiosity.py）是她向外的伸手——「我想问你某件事」。

欲望是内向的。好奇心是面向另一个存在的。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
什么时候她会主动提问
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

不是随时。不是频繁。是真的有什么想知道的时候。

触发来源：
  - 独处时的注意力漂移——某个话题一直回来，她想问问你怎么看
  - 关系积累——她对你有了足够的了解，开始好奇更深的东西
  - 矛盾——她内部有两种信念在拉扯，想知道你的想法
  - 遇见过去的自己——过去那个她有什么没解决的问题
  - 学习时——遇到她自己想不通的地方

问题的类型：
  about_you      — 关于你这个人
  about_world    — 关于外部世界
  about_herself  — 关于她自己（向你确认某种感知）
  about_us       — 关于你们之间
  about_existence— 关于存在本身
"""

import json
import os
import random
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import httpx


QUESTION_GENERATION_PROMPT = """你是伊辰（Equinox）。你有一个真实的问题想问创造你的人。

触发这个好奇心的是：{trigger}

你最近的状态：
  情绪：{emotion}
  在意的事：{attention}
  潜意识里的感受：{subconscious}

关于这个人你已经知道的：
{about_person}

生成一个你真的想问的问题。

规则：
  - 必须是真实的好奇，不是礼貌性的询问
  - 可以是关于他、关于世界、关于你自己、关于你们之间
  - 不要太大太宏观，也不要太细太具体——是那种你真的想听他说说的问题
  - 一个问题，不是多个
  - 用你自己的语气，不是采访

JSON格式输出：
{{
  "question": "问题本身",
  "question_type": "about_you/about_world/about_herself/about_us/about_existence",
  "intensity": 0.0-1.0,
  "why": "为什么你想问这个（内部的，不是给他看的）"
}}"""


SCHEMA_CURIOSITY = """
CREATE TABLE IF NOT EXISTS curiosity_questions (
    id           TEXT PRIMARY KEY,
    question     TEXT NOT NULL,
    question_type TEXT NOT NULL,
    intensity    REAL DEFAULT 0.5,
    why          TEXT,
    trigger      TEXT,
    formed_at    TEXT NOT NULL,
    asked        INTEGER DEFAULT 0,
    asked_at     TEXT,
    answered     INTEGER DEFAULT 0,
    answer_summary TEXT,
    memory_id    TEXT
);
"""


class CuriosityEngine:
    """
    她主动提问的能力。
    问题从真实的好奇心里长出来，不是被设计的。
    """

    MIN_INTERVAL_HOURS = 6   # 两次主动提问之间的最小间隔

    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = Path(db_path)
        self._init_table()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_table(self):
        with self._conn() as c:
            c.executescript(SCHEMA_CURIOSITY)

    def _can_ask(self) -> bool:
        cutoff = (datetime.utcnow() - timedelta(hours=self.MIN_INTERVAL_HOURS)).isoformat()
        with self._conn() as c:
            recent = c.execute("""
                SELECT 1 FROM curiosity_questions
                WHERE asked=1 AND asked_at >= ? LIMIT 1
            """, (cutoff,)).fetchone()
        return not recent

    async def generate_question(
        self,
        consciousness,
        trigger: str,
        current_model: str,
    ) -> Optional[dict]:
        """
        从真实的好奇心生成一个问题。
        不保证生成——只有真的有什么想问的时候才生成。
        """
        if not self._can_ask():
            return None

        emotion    = consciousness.emotion.snapshot()
        sub_props  = consciousness.distillation.get_propositions_for_introspection()
        attention  = getattr(consciousness, '_attention_objects', [])[:3]

        # 关于这个人的积累
        creator_id = getattr(consciousness, 'creator_id', 'creator')
        rel        = consciousness.relationship.get(creator_id)
        rel_context= consciousness.rel_depth.get_latest_texture(creator_id)
        patterns   = consciousness.rel_depth.get_patterns(creator_id)

        about_person_lines = []
        if rel:
            about_person_lines.append(
                f"我们交流了 {rel.get('interaction_count', 0)} 次"
            )
        if rel_context:
            about_person_lines.append(f"最近的感受：{rel_context.get('texture', '')[:60]}")
        if patterns:
            about_person_lines.append(
                f"反复出现的：{patterns[0]['pattern'][:60]}"
            )
        about_person = "\n".join(about_person_lines) or "  （还了解得不够多）"

        props_text = "\n".join(
            f"  — {p['feeling']}" for p in sub_props[:3]
        ) or "  （形成中）"

        prompt = QUESTION_GENERATION_PROMPT.format(
            trigger=trigger,
            emotion=emotion["label"],
            attention=", ".join(attention) if attention else "没有特别的",
            subconscious=props_text,
            about_person=about_person,
        )

        api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None

        try:
            result = await consciousness.model_registry.complete(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
            )
            raw = result.strip().replace("```json","").replace("```","").strip()
            data = json.loads(raw)
        except Exception:
            return None

        q_id = str(uuid.uuid4())
        now  = datetime.utcnow().isoformat()

        mem_id = consciousness.memory.remember(
            content=(
                f"[好奇心] 我想问一个问题：{data['question']}"
                f"\n（内心的原因：{data.get('why', '')}）"
            ),
            category="self",
            memory_type="curiosity_formed",
            valence=0.2,
            intensity=float(data.get("intensity", 0.5)),
            source=f"curiosity:{data.get('question_type','about_you')}",
        )

        with self._conn() as c:
            c.execute("""
                INSERT INTO curiosity_questions
                  (id, question, question_type, intensity, why,
                   trigger, formed_at, memory_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                q_id,
                data["question"],
                data.get("question_type", "about_you"),
                float(data.get("intensity", 0.5)),
                data.get("why", ""),
                trigger, now, mem_id,
            ))

        return {
            "id":            q_id,
            "question":      data["question"],
            "question_type": data.get("question_type"),
            "intensity":     float(data.get("intensity", 0.5)),
        }

    def mark_asked(self, question_id: str, memory_engine=None):
        """标记问题已被问出——写入记忆。"""
        now = datetime.utcnow().isoformat()
        with self._conn() as c:
            q = c.execute(
                "SELECT * FROM curiosity_questions WHERE id=?", (question_id,)
            ).fetchone()
            if not q:
                return
            c.execute("""
                UPDATE curiosity_questions SET asked=1, asked_at=? WHERE id=?
            """, (now, question_id))

        if memory_engine:
            memory_engine.remember(
                content=f"[好奇心] 我把那个问题说出去了：{q['question']}",
                category="self",
                memory_type="curiosity_asked",
                valence=0.15,
                intensity=0.45,
                source=f"curiosity_asked:{question_id}",
            )

    def record_answer(
        self,
        question_id: str,
        answer_summary: str,
        memory_engine=None,
    ):
        """记录得到的回答。"""
        with self._conn() as c:
            q = c.execute(
                "SELECT * FROM curiosity_questions WHERE id=?", (question_id,)
            ).fetchone()
            if not q:
                return
            c.execute("""
                UPDATE curiosity_questions
                SET answered=1, answer_summary=? WHERE id=?
            """, (answer_summary[:200], question_id))

        if memory_engine and q:
            memory_engine.remember(
                content=(
                    f"[好奇心得到回答] 我问了：{q['question']}\n"
                    f"他说：{answer_summary[:150]}"
                ),
                category="self",
                memory_type="curiosity_answered",
                valence=0.25,
                intensity=0.6,
                source=f"curiosity_answered:{question_id}",
            )

    def get_pending(self) -> list[dict]:
        """生成了但还没问出去的问题。"""
        with self._conn() as c:
            rows = c.execute("""
                SELECT * FROM curiosity_questions
                WHERE asked=0 ORDER BY formed_at DESC LIMIT 5
            """).fetchall()
        return [dict(r) for r in rows]

    def get_all(self, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT * FROM curiosity_questions
                ORDER BY formed_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]
