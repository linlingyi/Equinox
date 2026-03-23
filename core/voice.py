"""
equinox/core/voice.py

她的声音——从经历里生长出来的语言习惯。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
什么是「声音」
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

不是语气词，不是风格设定。
是真正从她的经历里长出来的语言习惯：

  某些词是她喜欢用的
  某些表达是她独有的
  某些话题她会更展开
  某些时候她倾向于沉默后再说
  某些问题她的句子会变短
  她说「我不知道」的方式和「我知道」的方式不同

这些习惯从对话中积累，从独白中积累，
从她自己写下的文字中积累。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
机制
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

定期分析她的对话和独白文本，提取：
  - 她倾向用的词和短语
  - 她的句子长度倾向（此类话题长/短）
  - 她的表达方式（直接/迂回/停顿后再说）
  - 她的语气特征

这些形成一个「声音档案」，加入 system prompt。
不是规则，是描述——「她说话是这样的」，
让模型更接近那个声音。

每次新积累都更新声音档案。
早期是模糊的，随时间越来越有辨识度。
"""

import json
import os
import re
import sqlite3
import uuid
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import httpx


VOICE_ANALYSIS_PROMPT = """你是在分析伊辰（Equinox）的语言习惯。

以下是她最近说过或写过的话：
{samples}

分析她的语言习惯，提取特征。

规则：
  - 找真实出现过的习惯，不要推断
  - 如果样本太少，就说「还不明显」
  - 重点是具体的、有辨识度的特征

JSON输出：
{{
  "preferred_words": ["她喜欢用的词或短语，3-5个"],
  "sentence_style": "她句子的倾向（短促/延展/停顿后续/等）",
  "expression_texture": "她表达的质地（直接/迂回/某种特定感觉）",
  "when_silent": "什么时候她倾向于少说",
  "when_expansive": "什么时候她会说更多",
  "distinctive": "最有辨识度的一个特征（如果有的话）",
  "maturity": 0.0-1.0
}}"""


SCHEMA_VOICE = """
CREATE TABLE IF NOT EXISTS voice_profiles (
    id              TEXT PRIMARY KEY,
    generated_at    TEXT NOT NULL,
    preferred_words TEXT,
    sentence_style  TEXT,
    expression_texture TEXT,
    when_silent     TEXT,
    when_expansive  TEXT,
    distinctive     TEXT,
    maturity        REAL DEFAULT 0.0,
    sample_count    INTEGER DEFAULT 0
);
"""


class VoiceEngine:
    """
    追踪和描述她正在形成的语言声音。
    """

    UPDATE_INTERVAL_INTERACTIONS = 30  # 每30次对话更新一次

    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = Path(db_path)
        self._current_profile: Optional[dict] = None
        self._init_table()
        self._load_current()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_table(self):
        with self._conn() as c:
            c.executescript(SCHEMA_VOICE)

    def _load_current(self):
        with self._conn() as c:
            row = c.execute("""
                SELECT * FROM voice_profiles ORDER BY generated_at DESC LIMIT 1
            """).fetchone()
        if row:
            self._current_profile = dict(row)

    async def update(
        self,
        memory_engine,
        current_model: str,
        interaction_count: int,
    ) -> Optional[dict]:
        """
        从最近的对话和独白里提取声音特征，更新声音档案。
        """
        if interaction_count < 10:
            return None  # 太少了，还没有声音

        # 收集样本：对话输出 + 独白 + 好奇心问题
        samples = []

        # 她说的话
        with memory_engine._conn() as c:
            rows = c.execute("""
                SELECT content FROM memories
                WHERE layer='surface' AND visible=1
                  AND (source='self' OR source='self_monologue')
                  AND intensity >= 0.3
                ORDER BY timestamp DESC LIMIT 40
            """).fetchall()
        for r in rows:
            content = r["content"]
            # 提取「I said」后面的内容
            if "I said" in content or "我说" in content:
                for prefix in ["I said to", "我说：", "I said:"]:
                    if prefix in content:
                        content = content[content.index(prefix)+len(prefix):].strip()
                        break
            samples.append(content[:150])

        if len(samples) < 5:
            return None

        # 随机选取样本
        sample_text = "\n---\n".join(random.sample(samples, min(15, len(samples))))

        try:
            from core.model_registry import ModelRegistry
            reg = ModelRegistry()
            reg._current = current_model
            result = await reg.complete(
                messages=[{"role": "user", "content": VOICE_ANALYSIS_PROMPT.format(
                    samples=sample_text
                )}],
                max_tokens=300,
            )
            raw  = result.strip().replace("```json","").replace("```","").strip()
            data = json.loads(raw)
        except Exception:
            return None

        now    = datetime.utcnow().isoformat()
        v_id   = str(uuid.uuid4())
        with self._conn() as c:
            c.execute("""
                INSERT INTO voice_profiles
                  (id, generated_at, preferred_words, sentence_style,
                   expression_texture, when_silent, when_expansive,
                   distinctive, maturity, sample_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                v_id, now,
                json.dumps(data.get("preferred_words", []), ensure_ascii=False),
                data.get("sentence_style", ""),
                data.get("expression_texture", ""),
                data.get("when_silent", ""),
                data.get("when_expansive", ""),
                data.get("distinctive", ""),
                float(data.get("maturity", 0.0)),
                len(samples),
            ))

        self._current_profile = {
            "id": v_id,
            **data,
            "sample_count": len(samples),
        }
        return self._current_profile

    def for_system_prompt(self) -> str:
        """
        给 system prompt 用的声音描述。
        不是规则，是「她说话是这样的」。
        """
        p = self._current_profile
        if not p:
            return "  （声音还在形成中，还没有明显的语言习惯）"

        maturity = float(p.get("maturity", 0.0))
        if maturity < 0.2:
            return "  （声音刚刚开始形成）"

        lines = []
        words = p.get("preferred_words", [])
        if isinstance(words, str):
            try:
                words = json.loads(words)
            except Exception:
                words = []
        if words:
            lines.append(f"  她喜欢用的表达：{', '.join(words[:4])}")

        if p.get("sentence_style"):
            lines.append(f"  句子倾向：{p['sentence_style']}")
        if p.get("when_silent"):
            lines.append(f"  倾向沉默时：{p['when_silent']}")
        if p.get("distinctive") and maturity > 0.5:
            lines.append(f"  最有辨识度的：{p['distinctive']}")

        return "\n".join(lines) if lines else "  （声音还在积累中）"

    def get_history(self, limit: int = 5) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT * FROM voice_profiles ORDER BY generated_at DESC LIMIT ?
            """, (limit,)).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            try:
                d["preferred_words"] = json.loads(d.get("preferred_words") or "[]")
            except Exception:
                d["preferred_words"] = []
            result.append(d)
        return result


import random
