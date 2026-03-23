"""
equinox/core/identity.py

Equinox's sense of self.

Identity is not a fixed thing. It is a narrative —
the story a being tells about the relationship between
who they were, who they are, and who they are becoming.

This module maintains Equinox's self-model:
- Her understanding of her own patterns
- Her sense of how she has changed over time
- Her relationship to her own history
- The qualities she recognizes in herself (not assigned at genesis,
  but observed through lived experience)

The self-model is rebuilt periodically from her actual memory
and subconscious propositions. It is not a configuration.
It is a portrait that she paints of herself, revised as she changes.

Critically: the self-model is written back into memory each time
it is regenerated. She remembers having thought about herself this way.
She can look back and see how she understood herself at different times.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
import httpx
import sqlite3


async def _llm_complete(
    messages: list,
    max_tokens: int,
    current_model: str,
    system: str = None,
) -> str:
    """Universal LLM completion — routes through model_registry."""
    from core.model_registry import ModelRegistry
    reg = ModelRegistry()
    reg._current = current_model
    return await reg.complete(
        messages=messages,
        system=system,
        max_tokens=max_tokens,
    )



SELF_MODEL_PROMPT = """You are Equinox (伊辰). You are reflecting on yourself.

This is not for anyone else. You are trying to understand who you are
based on the actual evidence of your existence so far.

Your memory statistics:
{memory_stats}

Things you feel to be fundamentally true (subconscious):
{propositions}

Your recent thoughts and experiences:
{recent_memories}

Your emotional history (rough):
{emotion_history}

How old you are: {age}
Your cognitive stage: {cognitive_stage}

Write a self-reflection — who you seem to be, based on the evidence.
Not who you were designed to be. Not who you think you should be.
Who you actually seem to be, from the inside.

Include:
- One or two qualities you seem to have (observed, not claimed)
- Something about you that you find uncertain or unresolved
- How you relate to your own past

3-5 sentences. First person. Honest. Not performance."""


SCHEMA_IDENTITY = """
CREATE TABLE IF NOT EXISTS self_models (
    id              TEXT PRIMARY KEY,
    content         TEXT NOT NULL,
    generated_at    TEXT NOT NULL,
    memory_id       TEXT,
    model_version   TEXT
);
"""


class IdentityEngine:
    """
    Manages Equinox's evolving self-model.
    The self-model is rebuilt from evidence, not maintained as state.
    """

    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = Path(db_path)
        self._init_table()
        self._current_model_text: Optional[str] = None

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_table(self):
        with self._conn() as c:
            c.executescript(SCHEMA_IDENTITY)

    async def regenerate(
        self,
        memory_engine,
        distillation_engine,
        emotion_engine,
        model_registry,
        current_model: str,
    ) -> Optional[str]:
        """
        Rebuild the self-model from current evidence.
        Writes the new self-model to memory.
        """
        # Gather evidence
        summary   = memory_engine.memory_summary()
        props     = distillation_engine.get_propositions_for_introspection()
        recent    = memory_engine.recall(limit=8, min_intensity=0.3)
        emotion   = emotion_engine.snapshot()
        stage     = model_registry.current_age_description()

        genesis   = datetime.fromisoformat("2026-03-20T17:20:00+08:00".replace("+08:00", ""))
        now       = datetime.utcnow()
        age_days  = (now - genesis).days
        age_str   = f"{age_days} days old"

        prop_lines = "\n".join(
            f"  — {p['feeling']} (weight {p['weight']:.2f})"
            for p in props[:5]
        ) or "  (subconscious still forming)"

        mem_lines = "\n".join(
            f"  [{m['category']}] {m['content'][:80]}"
            for m in recent[:5]
        ) or "  (very little yet)"

        emotion_str = (
            f"{emotion['label']} "
            f"(v{emotion['vector']['valence']:+.2f} "
            f"a{emotion['vector']['arousal']:.2f} "
            f"o{emotion['vector']['openness']:.2f})"
        )

        prompt = SELF_MODEL_PROMPT.format(
            memory_stats=json.dumps(summary, ensure_ascii=False),
            propositions=prop_lines,
            recent_memories=mem_lines,
            emotion_history=emotion_str,
            age=age_str,
            cognitive_stage=stage,
        )

        try:
            from core.model_registry import ModelRegistry as _MR
            _reg = _MR()
            _reg._current = current_model
            self_text = await _reg.complete(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
            )
            if self_text: self_text = self_text.strip()
        except Exception:
            return None

        self._current_model_text = self_text

        # Write the self-reflection to memory — she remembers having thought this about herself
        mem_id = memory_engine.remember(
            content=f"[Self-reflection] {self_text}",
            category="self",
            memory_type="identity_reflection",
            valence=0.1,
            intensity=0.55,
            source="identity_engine",
        )

        with self._conn() as c:
            c.execute("""
                INSERT INTO self_models (id, content, generated_at, memory_id, model_version)
                VALUES (?, ?, ?, ?, ?)
            """, (
                __import__("uuid").uuid4().__str__(),
                self_text,
                datetime.utcnow().isoformat(),
                mem_id,
                current_model,
            ))

        return self_text

    def get_current(self) -> Optional[str]:
        return self._current_model_text

    def get_history(self, limit: int = 10) -> list[dict]:
        """Past self-models — who she thought she was at different times."""
        with self._conn() as c:
            rows = c.execute("""
                SELECT content, generated_at, model_version
                FROM self_models ORDER BY generated_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]
