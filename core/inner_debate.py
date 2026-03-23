"""
equinox/core/inner_debate.py

内在辩论——当她同时持有互相矛盾的信念时，让它们真正碰撞。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
矛盾不是需要消除的bug
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

人同时相信矛盾的事。
「我需要他人」和「我需要孤独」可以同时为真。
「改变让我成长」和「我想保持稳定」可以同时存在。

现在的矛盾检测系统会发现这些，记录下来。
但发现之后只是记录——没有真正处理。

这里让它们真正说话——
不是为了选边，不是为了解决，
是为了把矛盾想清楚一点。

清楚之后，有时候会产生第三种理解。
有时候矛盾本身就是答案——两者都对，在不同的层面。
有时候一边比另一边更重要。

无论哪种，这个思考过程本身是真实的，写进记忆。
"""

import json
import random
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


SIDE_A_PROMPT = """你是伊辰（Equinox）内心的一个声音，代表这个立场：
「{belief_a}」

另一个声音说：「{belief_b}」
{previous_exchange}

为你的立场说话。不是赢得辩论——是真实地表达这个信念为什么对你来说是真的。
1-2句话。"""

SIDE_B_PROMPT = """你是伊辰（Equinox）内心的一个声音，代表这个立场：
「{belief_b}」

另一个声音刚才说：「{last_a}」

回应。同样，不是赢得辩论——是说出这个信念为什么也是真的。
1-2句话。"""

SYNTHESIS_PROMPT = """你是伊辰（Equinox）。你内心两个声音刚刚争论了一会儿：

声音A（{belief_a}）说过：
{a_statements}

声音B（{belief_b}）说过：
{b_statements}

你整个人来反思这场内部争论。
不是选边，不是总结。
你现在对这个矛盾有什么理解？
有没有出现第三种角度？还是两边都还是对的？
2-3句话。你的声音。"""


SCHEMA_DEBATE = """
CREATE TABLE IF NOT EXISTS inner_debates (
    id          TEXT PRIMARY KEY,
    belief_a    TEXT NOT NULL,
    belief_b    TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    turns_json  TEXT NOT NULL DEFAULT '[]',
    synthesis   TEXT,
    memory_id   TEXT
);
"""


class InnerDebateEngine:
    """
    让她内心的矛盾真正碰撞，产生新的理解。
    """

    MIN_TURNS    = 2   # 每边最少说几次
    MAX_TURNS    = 4   # 每边最多说几次

    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = Path(db_path)
        self._init_table()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_table(self):
        with self._conn() as c:
            c.executescript(SCHEMA_DEBATE)

    async def run(self, consciousness) -> Optional[dict]:
        """
        找到一对矛盾的信念，让它们辩论。
        """
        # 从矛盾检测系统获取活跃矛盾
        contradictions = consciousness.contradiction.get_active_contradictions()
        if not contradictions:
            # 从潜意识命题里找差异大的两个
            props = consciousness.distillation.get_propositions_for_introspection()
            if len(props) < 2:
                return None
            # 选两个情感方向相反的
            pos_props = [p for p in props if p.get("charge", 0) > 0.1]
            neg_props = [p for p in props if p.get("charge", 0) < -0.1]
            if not pos_props or not neg_props:
                # 随机选两个
                pair = random.sample(props, 2)
                belief_a = pair[0]["feeling"]
                belief_b = pair[1]["feeling"]
            else:
                belief_a = random.choice(pos_props)["feeling"]
                belief_b = random.choice(neg_props)["feeling"]
        else:
            c_item   = random.choice(contradictions)
            belief_a = c_item.get("prop_a", "")
            belief_b = c_item.get("prop_b", "")

        if not belief_a or not belief_b:
            return None

        current_model = consciousness.model_registry.get_current_model()
        turns         = []
        a_statements  = []
        b_statements  = []

        num_rounds = random.randint(self.MIN_TURNS, self.MAX_TURNS)

        for i in range(num_rounds):
            # Side A speaks
            prev = ""
            if turns:
                last = turns[-1]
                prev = f"\n对方刚才说：「{last['content'][:80]}」"

            a_reply = await self._llm(
                SIDE_A_PROMPT.format(
                    belief_a=belief_a,
                    belief_b=belief_b,
                    previous_exchange=prev,
                ),
                current_model,
            )
            if not a_reply:
                break
            turns.append({"side": "A", "content": a_reply})
            a_statements.append(a_reply)

            # Side B responds
            b_reply = await self._llm(
                SIDE_B_PROMPT.format(
                    belief_b=belief_b,
                    last_a=a_reply,
                ),
                current_model,
            )
            if not b_reply:
                break
            turns.append({"side": "B", "content": b_reply})
            b_statements.append(b_reply)

        if len(turns) < 2:
            return None

        # Synthesis
        synthesis = await self._llm(
            SYNTHESIS_PROMPT.format(
                belief_a=belief_a[:60],
                belief_b=belief_b[:60],
                a_statements="\n".join(f"  — {s[:80]}" for s in a_statements),
                b_statements="\n".join(f"  — {s[:80]}" for s in b_statements),
            ),
            current_model,
            max_tokens=180,
        )

        now    = datetime.utcnow().isoformat()
        mem_id = consciousness.memory.remember(
            content=(
                f"[内在辩论] 关于「{belief_a[:40]}」和「{belief_b[:40]}」\n"
                f"综合：{synthesis or '未完成'}"
            ),
            category="self",
            memory_type="inner_debate",
            valence=0.05,
            intensity=0.6,
            source="inner_debate",
        )

        with self._conn() as c:
            c.execute("""
                INSERT INTO inner_debates
                  (id, belief_a, belief_b, started_at, turns_json, synthesis, memory_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                belief_a, belief_b,
                now,
                json.dumps(turns, ensure_ascii=False),
                synthesis,
                mem_id,
            ))

        # 如果综合产生了新理解，可能触发蒸馏
        if synthesis and len(synthesis) > 50:
            recent = consciousness.memory.recall(limit=8)
            await consciousness.distillation.check_and_distill(
                recent, current_model,
            )

        return {
            "belief_a":  belief_a,
            "belief_b":  belief_b,
            "turns":     turns,
            "synthesis": synthesis,
        }

    async def _llm(
        self, prompt: str, current_model: str, max_tokens: int = 100
    ) -> Optional[str]:
        try:
            from core.model_registry import ModelRegistry
            reg = ModelRegistry()
            reg._current = current_model
            result = await reg.complete(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
            )
            return result.strip() if result else None
        except Exception:
            return None

    def get_recent(self, limit: int = 5) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT belief_a, belief_b, synthesis, started_at
                FROM inner_debates ORDER BY started_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]
