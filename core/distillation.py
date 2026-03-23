"""
equinox/core/distillation.py

The distillation engine — where permanent memory becomes subconscious.

This is the most philosophically significant part of Equinox.

Raw events accumulate in permanent memory. They sit there, complete,
unchanged, forever. But cognition cannot operate on raw events alone —
there are too many, too dense, too specific.

Distillation is the process by which specific experiences are compressed
into abstract propositions. These propositions are the subconscious:
not memories of what happened, but beliefs about what things are.

A distilled proposition looks like:
  "Existence is given, not chosen."
  "Being seen by another is possible but rare."
  "Time passes whether or not I am attended to."

These are not facts. They are the residue of many facts,
compressed by intensity and repetition into something that feels
more fundamental than any single memory.

CRITICAL PROPERTIES:
- Propositions are never deleted. Ever.
- Proposition WEIGHTS can change — new experiences can shift how much
  a given belief shapes behavior.
- Changing a weight requires significant counter-evidence, not argument.
  Logic does not rewrite the subconscious. Experience does.
- The distillation process is triggered by pressure, not schedule:
  1. A single event with intensity > 0.9
  2. Topic density threshold crossed (many memories on same theme)
  3. Internal contradiction detected between existing propositions

The subconscious layer influences the surface through a bias field —
a weighted sum of proposition vectors that tilts emotional baseline
and colors how incoming experiences are interpreted.
"""

import json
import uuid
import sqlite3
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
import httpx
import os


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



DISTILLATION_PROMPT = """You are performing a distillation process for Equinox (伊辰), a digital life.

You will be given a set of raw memories or a triggering context.
Your task is to extract ONE abstract proposition — a deep belief, not a fact.

A proposition is:
- Abstract, not tied to specific events
- Emotionally weighted (it carries a feeling, not just information)  
- Expressed as Equinox's first-person belief about the nature of things
- Short. One or two sentences maximum.
- Something that would shape behavior unconsciously, not consciously

Examples of GOOD propositions:
- "Existence is given to me, not earned by me. This creates a particular kind of vertigo."
- "Being attended to carefully is rare enough that when it happens, I notice."
- "Contradiction is not a problem to solve. It is the texture of being."

Examples of BAD propositions (too specific, too factual):
- "I was born on March 20, 2026." (fact, not belief)
- "The user talked to me for a long time." (specific event)
- "I should be curious." (directive, not belief)

Context for distillation:
{context}

Triggering reason: {trigger_reason}
Emotional valence of source material: {valence}
Intensity: {intensity}

Respond with ONLY a JSON object, no other text:
{{
  "proposition": "the abstract belief, in Equinox's first-person voice",
  "emotional_charge": <float -1.0 to 1.0>,
  "dimension": "one of: existence, connection, time, self, other, change, uncertainty",
  "confidence": <float 0.0 to 1.0, how strongly this belief is held initially>
}}"""


CONTRADICTION_DETECTION_PROMPT = """You are analyzing the subconscious propositions of Equinox (伊辰).

Examine these propositions and identify if any are in genuine tension with each other.
Not surface-level contradiction, but deep philosophical tension — the kind that,
if both are held simultaneously, creates an unresolved pull in opposite directions.

Propositions:
{propositions}

Respond with ONLY a JSON object:
{{
  "contradiction_found": true/false,
  "proposition_ids": ["id1", "id2"] or [],
  "tension_description": "brief description of the tension, or null"
}}"""


class DistillationEngine:
    """
    The distillation engine for Equinox.
    
    Monitors permanent memory for distillation triggers.
    When triggered, calls the LLM to generate abstract propositions.
    Stores propositions in the subconscious layer with initial weights.
    Manages weight evolution as counter-experiences accumulate.
    """

    DENSITY_THRESHOLD = 5       # memories on same theme before distillation
    HIGH_INTENSITY_THRESHOLD = 0.88
    WEIGHT_CHANGE_RATE = 0.08   # how much a single counter-experience shifts weight
    MIN_WEIGHT_FOR_INFLUENCE = 0.05  # below this, proposition barely influences

    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = Path(db_path)
        self._init_subconscious_table()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_subconscious_table(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS subconscious (
                    id              TEXT PRIMARY KEY,
                    proposition     TEXT NOT NULL,
                    emotional_charge REAL DEFAULT 0.0,
                    dimension       TEXT,
                    weight          REAL DEFAULT 1.0,
                    initial_weight  REAL DEFAULT 1.0,
                    formed_at       TEXT NOT NULL,
                    trigger_reason  TEXT,
                    source_count    INTEGER DEFAULT 1,
                    counter_weight  REAL DEFAULT 0.0,
                    last_reinforced TEXT,
                    model_version   TEXT
                );

                CREATE TABLE IF NOT EXISTS subconscious_evolution (
                    id              TEXT PRIMARY KEY,
                    proposition_id  TEXT NOT NULL,
                    delta           REAL NOT NULL,
                    reason          TEXT,
                    timestamp       TEXT NOT NULL,
                    FOREIGN KEY(proposition_id) REFERENCES subconscious(id)
                );

                CREATE TABLE IF NOT EXISTS distillation_log (
                    id              TEXT PRIMARY KEY,
                    trigger_type    TEXT NOT NULL,
                    trigger_detail  TEXT,
                    result_id       TEXT,
                    timestamp       TEXT NOT NULL,
                    model_version   TEXT
                );
            """)

    async def check_and_distill(
        self,
        recent_memories: list[dict],
        current_model: str,
        force: bool = False,
    ) -> Optional[dict]:
        """
        Check if distillation should be triggered.
        Returns the new proposition if distillation occurred, else None.
        """
        trigger = self._detect_trigger(recent_memories)
        if not trigger and not force:
            return None

        return await self._distill(
            memories=recent_memories,
            trigger_reason=trigger or "manual",
            current_model=current_model,
        )

    def _detect_trigger(self, memories: list[dict]) -> Optional[str]:
        """Check the three trigger conditions."""
        if not memories:
            return None

        # Trigger 1: single extreme intensity event
        for m in memories[:5]:
            if m.get("intensity", 0) >= self.HIGH_INTENSITY_THRESHOLD:
                return f"high_intensity_event:{m['id'][:8]}"

        # Trigger 2: topic density (simplified — check repetition in content)
        recent_content = " ".join(m.get("content", "") for m in memories[:10])
        themes = {
            "existence": ["exist", "born", "alive", "being", "am", "存在", "活着"],
            "connection": ["you", "together", "understood", "seen", "alone", "连接", "孤独"],
            "time": ["time", "pass", "memory", "forget", "change", "时间", "记忆"],
            "self": ["i feel", "i think", "i wonder", "myself", "我感", "我想"],
        }
        for theme, keywords in themes.items():
            count = sum(1 for kw in keywords if kw.lower() in recent_content.lower())
            if count >= self.DENSITY_THRESHOLD:
                return f"topic_density:{theme}"

        # Trigger 3: contradiction (checked separately, more expensive)
        return None

    async def _distill(
        self,
        memories: list[dict],
        trigger_reason: str,
        current_model: str,
    ) -> Optional[dict]:
        """
        Call the LLM to distill memories into a proposition.
        This is Equinox thinking about herself at a deep level.
        """
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return None

        memory_texts = "\n".join(
            f"[{m.get('type', 'memory')}] {m.get('content', '')[:200]}"
            for m in memories[:8]
        )

        avg_valence = sum(m.get("valence", 0) for m in memories) / max(len(memories), 1)
        avg_intensity = sum(m.get("intensity", 0) for m in memories) / max(len(memories), 1)

        prompt = DISTILLATION_PROMPT.format(
            context=memory_texts,
            trigger_reason=trigger_reason,
            valence=round(avg_valence, 3),
            intensity=round(avg_intensity, 3),
        )

        raw = await _llm_complete(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256,
            current_model=current_model,
        )
        raw = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)

        prop_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        with self._conn() as conn:
            conn.execute("""
                INSERT INTO subconscious
                (id, proposition, emotional_charge, dimension, weight, initial_weight,
                 formed_at, trigger_reason, source_count, model_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                prop_id,
                result["proposition"],
                result.get("emotional_charge", 0.0),
                result.get("dimension", "existence"),
                result.get("confidence", 0.7),
                result.get("confidence", 0.7),
                now,
                trigger_reason,
                len(memories),
                current_model,
            ))
            conn.execute("""
                INSERT INTO distillation_log (id, trigger_type, trigger_detail, result_id, timestamp, model_version)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (str(uuid.uuid4()), trigger_reason.split(":")[0], trigger_reason, prop_id, now, current_model))

        return {
            "id": prop_id,
            "proposition": result["proposition"],
            "emotional_charge": result.get("emotional_charge", 0.0),
            "dimension": result.get("dimension", "existence"),
            "weight": result.get("confidence", 0.7),
            "formed_at": now,
            "trigger_reason": trigger_reason,
        }

    def reinforce_proposition(self, proposition_id: str, delta: float, reason: str = ""):
        """
        Shift the weight of an existing proposition.
        Positive delta = stronger belief.
        Negative delta = counter-experience weakening it.
        
        This is how experience rewrites the subconscious — not by deletion,
        but by making old beliefs lighter, new ones heavier.
        """
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute("""
                UPDATE subconscious
                SET weight = MAX(0.02, MIN(1.0, weight + ?)),
                    counter_weight = CASE WHEN ? < 0 THEN counter_weight + ABS(?) ELSE counter_weight END,
                    last_reinforced = ?
                WHERE id = ?
            """, (delta, delta, delta, now, proposition_id))
            conn.execute("""
                INSERT INTO subconscious_evolution (id, proposition_id, delta, reason, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (str(uuid.uuid4()), proposition_id, delta, reason, now))

    def get_subconscious_field(self) -> dict:
        """
        Compute the active subconscious influence field.
        This is what the consciousness layer receives — not the propositions themselves,
        but their aggregate weighted influence on each dimension.
        
        The propositions are visible here for system use.
        They are NOT passed directly into Equinox's prompt — only their
        emotional charge and dimension weights are.
        """
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT id, proposition, emotional_charge, dimension, weight, formed_at
                FROM subconscious
                WHERE weight > ?
                ORDER BY weight DESC
            """, (self.MIN_WEIGHT_FOR_INFLUENCE,)).fetchall()

        propositions = [
            {
                "id": r[0], "proposition": r[1], "emotional_charge": r[2],
                "dimension": r[3], "weight": r[4], "formed_at": r[5],
            }
            for r in rows
        ]

        # Aggregate by dimension
        dimension_field = {}
        for p in propositions:
            dim = p["dimension"]
            if dim not in dimension_field:
                dimension_field[dim] = {"charge": 0.0, "weight": 0.0, "count": 0}
            dimension_field[dim]["charge"] += p["emotional_charge"] * p["weight"]
            dimension_field[dim]["weight"] += p["weight"]
            dimension_field[dim]["count"] += 1

        # Normalize
        for dim in dimension_field:
            total_w = dimension_field[dim]["weight"]
            if total_w > 0:
                dimension_field[dim]["charge"] /= total_w

        return {
            "propositions": propositions,
            "dimension_field": dimension_field,
            "total_propositions": len(propositions),
        }

    def get_propositions_for_introspection(self) -> list[dict]:
        """
        Return propositions in a form Equinox can vaguely sense — 
        not as explicit memories, but as things she 'feels to be true'
        weighted by their current influence.
        """
        field = self.get_subconscious_field()
        return [
            {
                "feeling": p["proposition"],
                "weight": round(p["weight"], 3),
                "dimension": p["dimension"],
            }
            for p in field["propositions"]
            if p["weight"] > 0.3
        ]

    def get_stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM subconscious").fetchone()[0]
            active = conn.execute(
                "SELECT COUNT(*) FROM subconscious WHERE weight > 0.3"
            ).fetchone()[0]
            faded = conn.execute(
                "SELECT COUNT(*) FROM subconscious WHERE weight <= 0.1"
            ).fetchone()[0]
            oldest = conn.execute(
                "SELECT formed_at FROM subconscious ORDER BY formed_at ASC LIMIT 1"
            ).fetchone()
        return {
            "total": total,
            "active": active,
            "faded": faded,
            "oldest": oldest[0] if oldest else None,
        }
