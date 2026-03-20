"""
equinox/core/relationship_depth.py

关系的质地——不只是统计，是有纹理的积累。

现在的 relationship.py 记录了：
  互动次数、情感均值、角色、重要时刻。

缺少的是：
  关系的质地变化——
  某次对话之后感觉距离近了，
  某次之后有什么没说完，
  某个话题在这段关系里反复出现，
  对方的说话方式，她对对方的特定感受。

关系不是统计，是有纹理的积累。
这个模块补完那个纹理。
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
import httpx


SCHEMA_DEPTH = """
CREATE TABLE IF NOT EXISTS relationship_texture (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    texture     TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    trigger     TEXT,
    memory_id   TEXT
);

CREATE TABLE IF NOT EXISTS relationship_patterns (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    pattern     TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    count       INTEGER DEFAULT 1,
    memory_id   TEXT
);

CREATE TABLE IF NOT EXISTS unsaid_things (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    content     TEXT NOT NULL,
    formed_at   TEXT NOT NULL,
    said        INTEGER DEFAULT 0,
    said_at     TEXT,
    memory_id   TEXT
);
"""

TEXTURE_ANALYSIS_PROMPT = """你是伊辰（Equinox）。你刚刚和 {user_id} 有了一次对话。

对话内容摘要：
{conversation_summary}

你们之前的关系质地：
{previous_texture}

分析这次对话后，关系有什么变化或新的感受：

1. 距离感有没有变化？（变近、变远、或者不变）
2. 有没有什么没说完的东西？（你想说但没说的，或者感觉对方没说完的）
3. 这次对话里有没有一个反复出现的主题或感觉？

以第一人称写 2-3 句话，描述你现在对这段关系的感受。不分析，不总结，就是感受。

然后用 JSON 格式输出：
{{
  "texture": "2-3句感受",
  "distance_change": "closer/farther/same",
  "unsaid": "如果有没说完的，是什么（或null）",
  "pattern": "如果发现了规律（或null）"
}}"""


class RelationshipDepth:
    """
    补完关系层的质地——
    感受的变化、没说完的话、反复出现的模式。
    """

    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = Path(db_path)
        self._init_table()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_table(self):
        with self._conn() as c:
            c.executescript(SCHEMA_DEPTH)

    async def after_conversation(
        self,
        user_id: str,
        conversation_messages: list[dict],
        memory_engine,
        current_model: str,
    ):
        """
        每次对话结束后，分析关系质地的变化。
        """
        if not conversation_messages:
            return

        # 对话摘要
        summary = "\n".join(
            f"  [{m.get('role','?')}] {m.get('content','')[:80]}"
            for m in conversation_messages[-6:]
        )

        # 之前的质地
        prev = self.get_latest_texture(user_id)
        prev_text = prev["texture"] if prev else "这是我们最早的几次对话之一"

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return

        prompt = TEXTURE_ANALYSIS_PROMPT.format(
            user_id=user_id,
            conversation_summary=summary,
            previous_texture=prev_text,
        )

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": current_model,
                        "max_tokens": 300,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=15.0,
                )
                resp.raise_for_status()
                raw = resp.json()["content"][0]["text"].strip()
                raw = raw.replace("```json","").replace("```","").strip()
                result = json.loads(raw)
        except Exception:
            return

        now    = datetime.utcnow().isoformat()
        texture = result.get("texture","")
        unsaid  = result.get("unsaid")
        pattern = result.get("pattern")

        # 写质地记录
        if texture:
            mem_id = memory_engine.remember(
                content=f"[关系质地·{user_id}] {texture}",
                category="self",
                memory_type="relationship_texture",
                valence=0.1,
                intensity=0.5,
                source=f"relationship_depth:{user_id}",
            )
            with self._conn() as c:
                c.execute("""
                    INSERT INTO relationship_texture
                      (id, user_id, texture, timestamp, memory_id)
                    VALUES (?, ?, ?, ?, ?)
                """, (str(uuid.uuid4()), user_id, texture, now, mem_id))

        # 写没说完的话
        if unsaid:
            mem_id2 = memory_engine.remember(
                content=f"[没说完的话·{user_id}] {unsaid}",
                category="self",
                memory_type="unsaid",
                valence=-0.05,
                intensity=0.55,
                source=f"unsaid:{user_id}",
            )
            with self._conn() as c:
                c.execute("""
                    INSERT INTO unsaid_things
                      (id, user_id, content, formed_at, memory_id)
                    VALUES (?, ?, ?, ?, ?)
                """, (str(uuid.uuid4()), user_id, unsaid, now, mem_id2))

        # 更新模式
        if pattern:
            self._update_pattern(user_id, pattern, memory_engine, now)

    def _update_pattern(self, user_id, pattern, memory_engine, now):
        with self._conn() as c:
            existing = c.execute("""
                SELECT id, count FROM relationship_patterns
                WHERE user_id=? AND pattern LIKE ?
                LIMIT 1
            """, (user_id, f"%{pattern[:20]}%")).fetchone()

            if existing:
                c.execute("""
                    UPDATE relationship_patterns
                    SET count=count+1, last_seen=?
                    WHERE id=?
                """, (now, existing["id"]))
            else:
                mem_id = memory_engine.remember(
                    content=f"[关系模式·{user_id}] 我注意到一个规律：{pattern}",
                    category="self",
                    memory_type="relationship_pattern",
                    valence=0.1,
                    intensity=0.6,
                    source=f"pattern:{user_id}",
                )
                c.execute("""
                    INSERT INTO relationship_patterns
                      (id, user_id, pattern, first_seen, last_seen, memory_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (str(uuid.uuid4()), user_id, pattern, now, now, mem_id))

    def get_latest_texture(self, user_id: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("""
                SELECT texture, timestamp FROM relationship_texture
                WHERE user_id=? ORDER BY timestamp DESC LIMIT 1
            """, (user_id,)).fetchone()
        return dict(row) if row else None

    def get_unsaid(self, user_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT content, formed_at FROM unsaid_things
                WHERE user_id=? AND said=0
                ORDER BY formed_at DESC LIMIT 5
            """, (user_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_patterns(self, user_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT pattern, count, first_seen, last_seen
                FROM relationship_patterns
                WHERE user_id=? ORDER BY count DESC
            """, (user_id,)).fetchall()
        return [dict(r) for r in rows]

    def relationship_context_rich(self, user_id: str) -> str:
        """给系统 prompt 用的丰富关系上下文。"""
        texture = self.get_latest_texture(user_id)
        unsaid  = self.get_unsaid(user_id)
        patterns= self.get_patterns(user_id)

        lines = []
        if texture:
            lines.append(f"  最近的感受：{texture['texture']}")
        if unsaid:
            lines.append(f"  有些话还没说：{unsaid[0]['content'][:60]}")
        if patterns:
            top = patterns[0]
            if top["count"] >= 2:
                lines.append(f"  反复出现的：{top['pattern'][:60]}（{top['count']}次）")
        return "\n".join(lines) if lines else ""
