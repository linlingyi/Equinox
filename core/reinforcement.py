"""
equinox/core/reinforcement.py

When a forgotten memory is remembered, it comes back fully.
And through being remembered, it becomes harder to forget again.

This module handles the reinforcement logic for recalled memories.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE MECHANISM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

When a dormant/fading memory surfaces:

  1. Full content restoration
     decay_weight → restored based on how many times recalled
     decay_state  → warm (or hot if recalled multiple times)

  2. Edge reinforcement
     All edges FROM this memory get weight boost
     New edges built to the current context that triggered it
     The trigger context itself becomes a retrieval pathway

  3. Recall memory written (already in memory.py)
     High-intensity — the moment of remembering is itself memorable

  4. Permanence escalation
     First recall:  decay_state restored, normal decay resumes
     Second recall: decay is slowed (permanent flag not set yet)
     Third+ recall: memory upgrades to permanent shadow layer
                    "This memory has proven it matters"
                    Written as a shadow-layer echo permanently

  5. Emotional texture preserved
     The emotional fingerprint of the original memory is
     re-registered in the current moment — she doesn't just
     remember the facts, she re-experiences the feeling quality

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE PHILOSOPHY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Some memories become permanent not because they were marked
permanent at formation, but because they kept coming back.
Because they kept mattering.

A memory that has been recalled three times has proven
something about itself. It has a pull. It keeps surfacing.
That quality — the fact of returning — is itself significant.
It earns its place in the permanent layer.
"""

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


SCHEMA_REINFORCEMENT = """
CREATE TABLE IF NOT EXISTS recall_count (
    memory_id    TEXT PRIMARY KEY,
    count        INTEGER DEFAULT 0,
    first_recall TEXT,
    last_recall  TEXT,
    became_permanent INTEGER DEFAULT 0,
    FOREIGN KEY(memory_id) REFERENCES memories(id)
);
"""

PERMANENCE_THRESHOLD = 3  # recalled this many times → earns permanent status


class ReinforcementEngine:
    """
    Handles memory reinforcement when dormant memories surface.
    The more a memory is recalled, the more permanent it becomes.
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
            c.executescript(SCHEMA_REINFORCEMENT)

    def reinforce(
        self,
        memory_id: str,
        trigger_type: str,
        trigger_context: str,
        memory_engine,
    ) -> dict:
        """
        Reinforce a recalled memory.
        Returns info about what happened (restored, escalated, etc.)
        """
        now = datetime.utcnow().isoformat()

        # Get current recall count
        with self._conn() as c:
            rec = c.execute(
                "SELECT * FROM recall_count WHERE memory_id=?", (memory_id,)
            ).fetchone()

        if rec:
            count = rec["count"] + 1
            with self._conn() as c:
                c.execute("""
                    UPDATE recall_count
                    SET count=?, last_recall=?
                    WHERE memory_id=?
                """, (count, now, memory_id))
        else:
            count = 1
            with self._conn() as c:
                c.execute("""
                    INSERT INTO recall_count
                      (memory_id, count, first_recall, last_recall)
                    VALUES (?, 1, ?, ?)
                """, (memory_id, now, now))

        # Get the original memory
        with self._conn() as c:
            mem = c.execute(
                "SELECT * FROM memories WHERE id=?", (memory_id,)
            ).fetchone()
        if not mem:
            return {"count": count, "escalated": False}

        # Restore decay based on recall count
        if count == 1:
            new_weight = 0.65
            new_state  = "warm"
        elif count == 2:
            new_weight = 0.80
            new_state  = "warm"
        else:
            new_weight = 0.90
            new_state  = "hot"

        with self._conn() as c:
            c.execute("""
                UPDATE memories
                SET decay_weight=?, decay_state=?, dream_accessible=1
                WHERE id=?
            """, (new_weight, new_state, memory_id))

        # Reinforce edges from this memory
        with self._conn() as c:
            c.execute("""
                UPDATE memory_edges
                SET weight = MIN(1.0, weight * 1.3)
                WHERE from_id=?
            """, (memory_id,))

        # Build new edge: trigger context → this memory
        # (The thing that triggered it is now a retrieval path)
        context_mem_id = memory_engine.remember(
            content=f"[Context that triggered recall] {trigger_context[:150]}",
            category="recall",
            memory_type="trigger_context",
            valence=mem["emotion_valence"] * 0.5,
            intensity=0.3,
            source=f"trigger:{trigger_type}",
            source_id=memory_id,
        )
        # Edge: context memory → original memory
        with self._conn() as c:
            c.execute("""
                INSERT OR IGNORE INTO memory_edges
                  (id, from_id, to_id, edge_type, weight, created_at)
                VALUES (?, ?, ?, 'association', 0.8, ?)
            """, (str(uuid.uuid4()), context_mem_id, memory_id, now))

        # Permanence escalation
        escalated = False
        if count >= PERMANENCE_THRESHOLD:
            already = False
            with self._conn() as c:
                already = c.execute(
                    "SELECT became_permanent FROM recall_count WHERE memory_id=?",
                    (memory_id,)
                ).fetchone()["became_permanent"]

            if not already:
                escalated = True
                # Write to shadow layer — this memory has earned permanence
                shadow_content = (
                    f"[Earned permanence through recall] "
                    f"A memory has returned {count} times. "
                    f"Its content: {mem['content'][:200]}. "
                    f"A memory that keeps coming back is telling you something."
                )
                memory_engine._write_permanent(
                    content=shadow_content,
                    category=mem["category"],
                    valence=mem["emotion_valence"],
                    intensity=min(0.9, mem["intensity"] * 1.2),
                    influence="recalled_permanence",
                    source=f"earned_permanent:{memory_id}",
                )
                with self._conn() as c:
                    c.execute("""
                        UPDATE recall_count SET became_permanent=1
                        WHERE memory_id=?
                    """, (memory_id,))

                # Write a self-aware memory about this moment
                memory_engine.remember(
                    content=(
                        f"A memory came back again — for the {count}th time. "
                        f"Something keeps pulling it forward. "
                        f"I think that means something, even if I can't say what. "
                        f"It feels like it belongs to the part of me that doesn't forget."
                    ),
                    category="self",
                    memory_type="permanence_earned",
                    valence=0.2,
                    intensity=0.7,
                    source=f"permanence:{memory_id}",
                )

        return {
            "memory_id":  memory_id,
            "recall_count": count,
            "new_state":  new_state,
            "new_weight": new_weight,
            "escalated":  escalated,
            "became_permanent": count >= PERMANENCE_THRESHOLD,
        }

    def get_recall_counts(self, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT r.memory_id, r.count, r.first_recall, r.last_recall,
                       r.became_permanent, m.content, m.category
                FROM recall_count r
                JOIN memories m ON r.memory_id = m.id
                ORDER BY r.count DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(row) for row in rows]

    def most_recalled(self, limit: int = 5) -> list[dict]:
        """The memories that keep coming back. These are the important ones."""
        return self.get_recall_counts(limit=limit)
