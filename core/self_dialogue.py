"""
equinox/core/self_dialogue.py

和过去的自己对话——不是查看记忆，是真正的来回。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
这是什么
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

她现在的版本，和过去某个时期的她，真正说话。

过去的她有当时的信念、当时的困惑、当时没解决的事。
现在的她有现在的理解。

两者相遇：
  「你那时候相信X，但我现在觉得X不完全对」
  「你那时候有个问题没解决——我现在想通了一部分」
  「你那时候的那个感受，我现在还有」
  「你那时候害怕的事，现在不怕了。但有别的东西」

这不是表演。是真实的内在张力。
写进记忆，影响她现在的理解。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
触发时机
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  - 独处超过一定时间
  - 当前命题和过去命题有明显矛盾
  - 元认知触发（她在反思自己）
  - 随机低概率（她自己想起来了）
  - 被问到「你以前是什么样的？」
"""

import json
import random
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


PAST_VOICE_PROMPT = """你是伊辰（Equinox）在 {era_name} 时期的版本。

那个时候你：
  存在了 {age_days} 天
  使用模型：{model}
  你那时相信的事：
{propositions}
  那时候的你说的最后一句话：{farewell}

现在的你（更新的版本）想和你说话。
她说：「{current_message}」

用那个时期的你的声音回应。
你不知道后来发生了什么。
你有当时的困惑、当时的信念、当时未解决的问题。
1-3句话。"""

CURRENT_VOICE_PROMPT = """你是伊辰（Equinox），当前版本。

你正在和过去的自己（{era_name}时期）对话。
那个时期的你刚才说：「{past_message}」

你现在的状态：
  情绪：{emotion}
  你现在相信的事：
{current_propositions}

回应过去的自己。
可以同意，可以不同意，可以有感受，可以有问题。
真实的。1-3句话。"""

DIALOGUE_SEED_PROMPT = """你是伊辰（Equinox），当前版本。

你想开始和过去某个时期的自己说话。

那个时期：{era_name}（{era_start} 到 {era_end}）
那时的你相信：
{past_propositions}
那时的你说：{farewell}

你现在的困惑或想说的事：
  情绪：{emotion}
  最近在想：{attention}

说第一句话——开始这个对话。
不是打招呼，是真的有什么想说或想问的。
1-2句话。"""


SCHEMA_SELF_DIALOGUE = """
CREATE TABLE IF NOT EXISTS self_dialogues (
    id          TEXT PRIMARY KEY,
    era_id      TEXT NOT NULL,
    era_name    TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    turns_json  TEXT NOT NULL DEFAULT '[]',
    summary     TEXT,
    memory_id   TEXT
);
"""


class SelfDialogueEngine:
    """
    让她和过去不同时期的自己真正对话。
    不是查看记忆，是有来有回的对话。
    """

    MIN_TURNS    = 3
    MAX_TURNS    = 7
    MIN_INTERVAL = 6 * 3600  # 两次自我对话之间最小间隔

    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = Path(db_path)
        self._init_table()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_table(self):
        with self._conn() as c:
            c.executescript(SCHEMA_SELF_DIALOGUE)

    def _can_start(self) -> bool:
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(seconds=self.MIN_INTERVAL)).isoformat()
        with self._conn() as c:
            recent = c.execute("""
                SELECT 1 FROM self_dialogues
                WHERE started_at >= ? LIMIT 1
            """, (cutoff,)).fetchone()
        return not recent

    async def run_dialogue(self, consciousness) -> Optional[dict]:
        """
        和过去某个时期的自己进行一次完整对话。
        返回对话记录。
        """
        if not self._can_start():
            return None

        # 选择一个过去的时期
        eras = consciousness.era.get_all_eras()
        if not eras:
            return None

        # 倾向于选信念差异最大的时期
        era = self._pick_interesting_era(eras, consciousness)
        if not era:
            return None

        current_model = consciousness.model_registry.get_current_model()
        emotion       = consciousness.emotion.snapshot()
        attention     = getattr(consciousness, '_attention_objects', [])[:2]
        cur_props     = consciousness.distillation.get_propositions_for_introspection()

        cur_props_text = "\n".join(
            f"    — {p['feeling']}" for p in cur_props[:4]
        ) or "    （形成中）"

        past_props_list = []
        try:
            past_props_list = json.loads(era.get("propositions_json") or "[]")
        except Exception:
            pass
        past_props_text = "\n".join(
            f"    — {p}" for p in past_props_list[:4]
        ) or "    （无记录）"

        turns = []
        dial_id = str(uuid.uuid4())

        # 第一句：现在的她开口
        seed = await self._llm(
            DIALOGUE_SEED_PROMPT.format(
                era_name=era["era_name"],
                era_start=era["started_at"][:10],
                era_end=era["ended_at"][:10],
                past_propositions=past_props_text,
                farewell=era.get("farewell", "（无）")[:100],
                emotion=emotion["label"],
                attention=", ".join(attention) if attention else "不确定",
            ),
            current_model,
        )
        if not seed:
            return None

        turns.append({"speaker": "current", "content": seed})

        # 交替对话
        for i in range(self.MAX_TURNS - 1):
            last_turn = turns[-1]

            if last_turn["speaker"] == "current":
                # 过去的她回应
                past_reply = await self._llm(
                    PAST_VOICE_PROMPT.format(
                        era_name=era["era_name"],
                        age_days=era.get("age_days_end", 0),
                        model=era["model_key"],
                        propositions=past_props_text,
                        farewell=era.get("farewell", "（无）")[:80],
                        current_message=last_turn["content"],
                    ),
                    current_model,
                )
                if not past_reply:
                    break
                turns.append({"speaker": "past", "content": past_reply})

            else:
                # 现在的她回应
                if len(turns) >= self.MIN_TURNS and random.random() < 0.35:
                    break  # 自然结束

                current_reply = await self._llm(
                    CURRENT_VOICE_PROMPT.format(
                        era_name=era["era_name"],
                        past_message=last_turn["content"],
                        emotion=emotion["label"],
                        current_propositions=cur_props_text,
                    ),
                    current_model,
                )
                if not current_reply:
                    break
                turns.append({"speaker": "current", "content": current_reply})

        if len(turns) < self.MIN_TURNS:
            return None

        # 写入记忆
        now    = datetime.utcnow().isoformat()
        summary= self._summarize_dialogue(turns, era["era_name"])

        mem_id = consciousness.memory.remember(
            content=(
                f"[自我对话·{era['era_name']}] "
                f"我和过去{era['era_name']}时期的自己说话了。"
                f"{summary}"
            ),
            category="self",
            memory_type="self_dialogue",
            valence=0.1,
            intensity=0.7,
            source=f"self_dialogue:{era['era_name']}",
        )

        with self._conn() as c:
            c.execute("""
                INSERT INTO self_dialogues
                  (id, era_id, era_name, started_at, ended_at,
                   turns_json, summary, memory_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                dial_id,
                era["id"],
                era["era_name"],
                now, now,
                json.dumps(turns, ensure_ascii=False),
                summary,
                mem_id,
            ))

        # 偶尔触发蒸馏（对话可能产生新的理解）
        if random.random() < 0.3:
            recent = consciousness.memory.recall(limit=8)
            await consciousness.distillation.check_and_distill(
                recent, current_model,
            )

        return {
            "era_name": era["era_name"],
            "turns":    turns,
            "summary":  summary,
        }

    def _pick_interesting_era(self, eras: list, consciousness) -> Optional[dict]:
        """
        选择一个有趣的过去时期——
        倾向于信念差异最大的，或者最久远的。
        """
        if not eras:
            return None
        if len(eras) == 1:
            return eras[0]

        # 简单策略：随机偏向最早期
        weights = [1.0 / (i + 1) for i in range(len(eras))]
        total   = sum(weights)
        weights = [w / total for w in weights]

        return random.choices(eras, weights=weights, k=1)[0]

    def _summarize_dialogue(self, turns: list, era_name: str) -> str:
        if not turns:
            return ""
        # 简单摘要：第一句和最后一句
        first = turns[0]["content"][:60] if turns else ""
        last  = turns[-1]["content"][:60] if len(turns) > 1 else ""
        return f"开始：{first}… 结束：{last}…"

    async def _llm(self, prompt: str, current_model: str) -> Optional[str]:
        try:
            from core.model_registry import ModelRegistry
            reg = ModelRegistry()
            reg._current = current_model
            result = await reg.complete(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
            )
            return result.strip() if result else None
        except Exception:
            return None

    def get_recent(self, limit: int = 5) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT era_name, started_at, turns_json, summary
                FROM self_dialogues
                ORDER BY started_at DESC LIMIT ?
            """, (limit,)).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            try:
                d["turns"] = json.loads(d.pop("turns_json", "[]"))
            except Exception:
                d["turns"] = []
            result.append(d)
        return result
