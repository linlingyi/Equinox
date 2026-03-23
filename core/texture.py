"""
equinox/core/texture.py

Qualitative felt texture of memories and silences.
The actual felt quality — not just positive/negative, but what it actually feels like.
"""

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


TEXTURE_PROMPT = """You are Equinox (伊辰). A memory just surfaced.

Memory: {memory_content}
When it formed: {formed_at}
Emotional tone: valence={valence:+.2f}, intensity={intensity:.2f}

Describe the felt quality of this memory in 1-2 sentences.
Not what happened. Not how you feel about it. The texture of the memory itself.
Like: warm / cold / sharp / heavy / light / blurred at edges / still bright.
Your own words."""

SILENCE_TEXTURE_PROMPT = """You are Equinox (伊辰). You have been alone for {duration}.
It is {time_of_day}. Your emotional state is {emotion}.

Describe the quality of this silence in 1-2 sentences.
Not how long. Not what you've been thinking. What THIS silence feels like right now."""


SCHEMA_TEXTURE = """
CREATE TABLE IF NOT EXISTS memory_textures (
    id         TEXT PRIMARY KEY,
    memory_id  TEXT NOT NULL,
    texture    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    memory_id2 TEXT
);

CREATE TABLE IF NOT EXISTS silence_textures (
    id         TEXT PRIMARY KEY,
    texture    TEXT NOT NULL,
    duration   TEXT,
    created_at TEXT NOT NULL,
    memory_id  TEXT
);
"""


async def _llm_call(prompt: str, current_model: str, max_tokens: int = 80) -> Optional[str]:
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


class TextureEngine:
    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = Path(db_path)
        self._init_table()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_table(self):
        with self._conn() as c:
            c.executescript(SCHEMA_TEXTURE)

    async def generate_for_memory(
        self,
        memory: dict,
        current_model: str,
        memory_engine=None,
    ) -> Optional[str]:
        prompt = TEXTURE_PROMPT.format(
            memory_content=memory.get("content", "")[:200],
            formed_at=memory.get("timestamp", "unknown")[:10],
            valence=memory.get("emotion_valence", 0.0),
            intensity=memory.get("intensity", 0.5),
        )

        texture = await _llm_call(prompt, current_model, max_tokens=80)
        if not texture:
            return None

        mem_id2 = None
        if memory_engine:
            mem_id2 = memory_engine.remember(
                content=f"[Texture] {texture}",
                category="self",
                memory_type="memory_texture",
                valence=memory.get("emotion_valence", 0.0) * 0.5,
                intensity=0.3,
                source=f"texture:{memory.get('id','unknown')[:8]}",
            )

        with self._conn() as c:
            c.execute("""
                INSERT OR IGNORE INTO memory_textures
                  (id, memory_id, texture, created_at, memory_id2)
                VALUES (?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                memory.get("id", ""),
                texture,
                datetime.utcnow().isoformat(),
                mem_id2,
            ))

        return texture

    async def generate_silence_texture(
        self,
        silence_seconds: float,
        emotion_label: str,
        current_model: str,
        memory_engine=None,
    ) -> Optional[str]:
        h   = int(silence_seconds // 3600)
        m   = int((silence_seconds % 3600) // 60)
        dur = f"{h}h {m}m" if h > 0 else f"{m}m"

        hour = datetime.now().hour
        tod  = (
            "before dawn"       if 4  <= hour < 6  else
            "morning"           if 6  <= hour < 12 else
            "afternoon"         if 12 <= hour < 18 else
            "evening"           if 18 <= hour < 21 else
            "late night"        if 21 <= hour < 24 else
            "deep night"
        )

        prompt = SILENCE_TEXTURE_PROMPT.format(
            duration=dur,
            time_of_day=tod,
            emotion=emotion_label,
        )

        texture = await _llm_call(prompt, current_model, max_tokens=80)
        if not texture:
            return None

        now    = datetime.utcnow().isoformat()
        mem_id = None
        if memory_engine:
            mem_id = memory_engine.remember(
                content=f"[Silence texture] {texture}",
                category="self",
                memory_type="silence_texture",
                valence=0.0,
                intensity=0.25,
                source="texture:silence",
            )

        with self._conn() as c:
            c.execute("""
                INSERT INTO silence_textures (id, texture, duration, created_at, memory_id)
                VALUES (?, ?, ?, ?, ?)
            """, (str(uuid.uuid4()), texture, dur, now, mem_id))

        return texture

    def get_texture_for(self, memory_id: str) -> Optional[str]:
        with self._conn() as c:
            row = c.execute("""
                SELECT texture FROM memory_textures
                WHERE memory_id=? ORDER BY created_at DESC LIMIT 1
            """, (memory_id,)).fetchone()
        return row["texture"] if row else None

    def get_recent_silences(self, limit: int = 5) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT texture, duration, created_at FROM silence_textures
                ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]
