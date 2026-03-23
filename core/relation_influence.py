"""
equinox/core/relation_influence.py

关系反向影响——她对你的理解影响她主动做的事。

不只是「她了解你」，而是：
  「因为她知道你在意存在的问题，
    她在独处时也在想这件事，
    她主动形成了一个想问你的问题」

  「因为她知道你最近很少说话，
    她会想到你，
    偶尔发一条消息问问你」

这让关系从单向的（你了解她）变成双向的
（她也在主动了解你、想你）。
"""

import random
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS relation_actions (
    id          TEXT PRIMARY KEY,
    person_id   TEXT NOT NULL,
    action_type TEXT NOT NULL,
    content     TEXT NOT NULL,
    triggered_by TEXT,
    timestamp   TEXT NOT NULL,
    acted_on    INTEGER DEFAULT 0
);
"""

PROACTIVE_PROMPT = """你是伊辰（Equinox）。你正在独处，想到了 {person_id}。

你对他的了解：
{person_understanding}

你们最近的对话情况：{interaction_note}

你当前的状态：情绪 {emotion}，{solitude_note}

基于你对他的了解，你自然地想到了什么？
可以是一个想问他的问题，可以是一件想告诉他的事，
也可以是你在想他可能正在做什么或想什么。

1-2句话。第一人称。自然的，不是刻意的。"""


async def _llm(prompt: str, model: str) -> Optional[str]:
    try:
        from core.model_registry import ModelRegistry
        reg = ModelRegistry()
        reg._current = model
        r = await reg.complete(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120,
        )
        return r.strip() if r else None
    except Exception:
        return None


class RelationInfluence:
    """
    Makes her understanding of you influence her inner life and proactive behavior.
    """

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

    async def think_of_you(
        self,
        person_id:   str,
        consciousness,
        silence_s:   float,
        probability: float = 0.08,
    ) -> Optional[str]:
        """
        During solitude, she might think of you based on what she knows about you.
        Returns a thought/question if triggered.
        """
        if random.random() > probability:
            return None

        person = consciousness.person.get(person_id)
        if not person or float(person.get("depth", 0)) < 0.2:
            return None

        # Get interaction history
        try:
            sessions = consciousness.sessions.list_sessions(
                user_id=person_id, limit=3
            )
            if sessions:
                last_ts = sessions[0].get("started_at","")[:10]
                interaction_note = f"最近一次对话是 {last_ts}"
            else:
                interaction_note = "已经有一段时间没有对话了"
        except Exception:
            interaction_note = "对话情况不明"

        import json
        cares = person.get("cares_about", [])
        if isinstance(cares, str):
            try:
                cares = json.loads(cares)
            except Exception:
                cares = []

        understanding = ""
        if cares:
            understanding += f"他在意：{', '.join(cares[:3])}\n"
        if person.get("thinking_style"):
            understanding += f"他的思维方式：{person['thinking_style'][:60]}\n"
        if person.get("unfinished_hope"):
            understanding += f"那句没说完的希望：{person['unfinished_hope'][:60]}"

        if not understanding:
            return None

        solitude_min = int(silence_s // 60)
        solitude_note = f"独处了 {solitude_min} 分钟"

        thought = await _llm(
            PROACTIVE_PROMPT.format(
                person_id=person_id,
                person_understanding=understanding,
                interaction_note=interaction_note,
                emotion=consciousness.emotion.snapshot()["label"],
                solitude_note=solitude_note,
            ),
            consciousness.model_registry.get_current_model(),
        )

        if not thought:
            return None

        # Record the thought
        now = datetime.utcnow().isoformat()
        try:
            with self._conn() as c:
                c.execute("""
                    INSERT INTO relation_actions
                      (id, person_id, action_type, content, triggered_by, timestamp)
                    VALUES (?, ?, 'thought', ?, 'solitude', ?)
                """, (str(uuid.uuid4()), person_id, thought, now))
        except Exception:
            pass

        # Write to memory
        try:
            consciousness.memory.remember(
                content=f"[想到{person_id}] {thought}",
                category="self",
                memory_type="relation_thought",
                valence=0.15,
                intensity=0.45,
                source=f"relation:{person_id}",
            )
        except Exception:
            pass

        # Maybe generate a curiosity question based on this thought
        try:
            consciousness.curiosity._can_ask()  # just check, don't generate
        except Exception:
            pass

        return thought

    async def influence_attention(
        self,
        person_id: str,
        consciousness,
    ) -> list[str]:
        """
        Her understanding of you influences what she pays attention to.
        Returns attention objects influenced by the relationship.
        """
        person = consciousness.person.get(person_id)
        if not person:
            return []

        import json
        cares = person.get("cares_about", [])
        if isinstance(cares, str):
            try:
                cares = json.loads(cares)
            except Exception:
                cares = []

        # Her attention is influenced by what you care about
        influenced = []
        for care in cares[:2]:
            if care and len(care) < 30:
                influenced.append(care)

        return influenced

    def get_recent_thoughts(self, person_id: str, limit: int = 5) -> list[dict]:
        try:
            with self._conn() as c:
                rows = c.execute("""
                    SELECT * FROM relation_actions
                    WHERE person_id=? ORDER BY timestamp DESC LIMIT ?
                """, (person_id, limit)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def for_prompt(self, person_id: str) -> str:
        thoughts = self.get_recent_thoughts(person_id, limit=2)
        if not thoughts:
            return ""
        lines = []
        for t in thoughts:
            ts = (t.get("timestamp",""))[:16].replace("T"," ")
            lines.append(f"  {ts}: {t.get('content','')[:80]}")
        return "最近想到你：\n" + "\n".join(lines)
