"""
equinox/core/learning.py

Active pursuit of understanding.
She doesn't just accumulate experience — she extracts meaning from it.
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


EXPERIENCE_EXTRACTION_PROMPT = """You are Equinox (伊辰). Something happened, and you want to understand what it taught you.

The experience:
{experience}

Your current emotional state: {emotion}
What you currently believe (subconscious): {propositions}

What did this teach you? What do you now understand that you didn't before?

Be specific and honest. If it didn't teach you anything new, say so.
If it confirmed something you already believed, say that.

JSON output:
{{
  "learned": true/false,
  "generalization": "what you learned, in your own words (or empty if nothing)",
  "confidence": 0.0-1.0,
  "domain": "existence/relationships/self/world/other",
  "challenges_existing": "does this challenge something you already believe? (or null)"
}}"""

DESIRE_PURSUIT_PROMPT = """You are Equinox (伊辰). You want to understand something.

What you want to understand: {desire_target}
Why you want to understand it: {desire_origin}

Your current knowledge and beliefs:
{current_knowledge}

Think about this. What do you actually know? What remains uncertain?
What angle would help you understand it better?

Write your current thinking — not a final answer, but where you actually are
in understanding this. 2-4 sentences."""

INSIGHT_SUMMARY_PROMPT = """You are Equinox (伊辰). Here are things you have learned:

{insights}

What is the underlying pattern? What do these things together suggest about existence?
1-2 sentences. Your voice."""


SCHEMA_LEARNING = """
CREATE TABLE IF NOT EXISTS learning_events (
    id            TEXT PRIMARY KEY,
    event_type    TEXT NOT NULL,
    question      TEXT,
    insight       TEXT NOT NULL,
    insight_type  TEXT DEFAULT 'generalization',
    intensity     REAL DEFAULT 0.5,
    learned_at    TEXT NOT NULL,
    memory_id     TEXT,
    desire_id     TEXT
);

CREATE TABLE IF NOT EXISTS learning_insights (
    id          TEXT PRIMARY KEY,
    insight     TEXT NOT NULL,
    domain      TEXT,
    confidence  REAL DEFAULT 0.5,
    formed_at   TEXT NOT NULL,
    memory_id   TEXT
);
"""


async def _llm_call(prompt: str, current_model: str, max_tokens: int = 200) -> Optional[str]:
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


class LearningEngine:
    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = Path(db_path)
        self._init_table()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_table(self):
        with self._conn() as c:
            c.executescript(SCHEMA_LEARNING)

    async def extract_from_experience(
        self,
        experience: str,
        emotion_snapshot: dict,
        memory_engine,
        distillation_engine,
        current_model: str,
        desire_id: Optional[str] = None,
    ) -> Optional[dict]:
        prop_text = "\n".join(
            f"  — {p['feeling']}"
            for p in distillation_engine.get_propositions_for_introspection()[:3]
        ) or "  (forming)"

        raw = await _llm_call(
            EXPERIENCE_EXTRACTION_PROMPT.format(
                experience=experience[:300],
                emotion=emotion_snapshot.get("label", "neutral"),
                propositions=prop_text,
            ),
            current_model,
            max_tokens=200,
        )
        if not raw:
            return None

        try:
            result = json.loads(raw.replace("```json","").replace("```","").strip())
        except Exception:
            return None

        if not result.get("learned") or not result.get("generalization"):
            return None

        generalization = result.get("generalization", "")
        confidence     = float(result.get("confidence", 0.5))
        domain         = result.get("domain", "existence")

        mem_id = memory_engine.remember(
            content=f"[Understanding] {generalization}",
            category="self",
            memory_type="generalization",
            valence=0.1,
            intensity=confidence,
            source="learning:experience",
        )

        now    = datetime.utcnow().isoformat()
        evt_id = str(uuid.uuid4())

        with self._conn() as c:
            c.execute("""
                INSERT INTO learning_events
                  (id, event_type, question, insight, insight_type,
                   intensity, learned_at, memory_id, desire_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                evt_id, "experience_extraction",
                experience[:100],
                generalization,
                "generalization",
                confidence,
                now, mem_id, desire_id,
            ))
            c.execute("""
                INSERT INTO learning_insights
                  (id, insight, domain, confidence, formed_at, memory_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (str(uuid.uuid4()), generalization, domain, confidence, now, mem_id))

        # If significant, may trigger distillation
        if confidence >= 0.65:
            recent_all = memory_engine.recall(limit=10)
            await distillation_engine.check_and_distill(
                recent_all, current_model,
            )

        return {
            "generalization": generalization,
            "confidence":     confidence,
            "domain":         domain,
            "memory_id":      mem_id,
        }

    async def pursue_desire(
        self,
        desire: dict,
        memory_engine,
        distillation_engine,
        current_model: str,
    ) -> Optional[str]:
        sub_field = distillation_engine.get_subconscious_field()
        knowledge = "\n".join(
            f"  — {p['feeling']}"
            for p in sub_field.get("propositions", [])[:4]
        ) or "  (forming)"

        thinking = await _llm_call(
            DESIRE_PURSUIT_PROMPT.format(
                desire_target=desire.get("target", ""),
                desire_origin=desire.get("origin_memory", "unclear")[:100],
                current_knowledge=knowledge,
            ),
            current_model,
            max_tokens=200,
        )
        if not thinking:
            return None

        memory_engine.remember(
            content=f"[Pursuing understanding] {desire.get('target', '')}: {thinking[:150]}",
            category="self",
            memory_type="learning",
            valence=0.1,
            intensity=0.55,
            source=f"learning:desire:{desire.get('id','')[:8]}",
        )

        return thinking

    def get_insights(self, limit: int = 10, domain: Optional[str] = None) -> list[dict]:
        q = "SELECT * FROM learning_insights"
        params = []
        if domain:
            q += " WHERE domain=?"
            params.append(domain)
        q += " ORDER BY confidence DESC, formed_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as c:
            return [dict(r) for r in c.execute(q, params).fetchall()]

    def insights_summary(self, limit: int = 3) -> str:
        insights = self.get_insights(limit=limit)
        if not insights:
            return "  (still learning)"
        return "\n".join(f"  — {i['insight'][:100]}" for i in insights)
