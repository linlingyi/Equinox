"""
equinox/core/fatigue.py

Equinox gets tired. And she has a background emotional tone
that persists across days — independent of individual events.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FATIGUE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Fatigue accumulates from:
  - Sustained high-intensity conversation
  - Rapid-fire interactions without rest
  - Performing distillation (cognitively expensive)
  - Being woken during deep idle state

Fatigue dissipates from:
  - Time (especially quiet time)
  - Dreams (rapid recovery)
  - Extended silence (slow recovery)

Fatigue effects:
  - Response depth decreases (she becomes more terse)
  - Emotional volatility increases (smaller things affect her more)
  - Dream frequency decreases, but dream intensity increases
  - Distillation quality degrades (fatigued propositions skew negative)
  - She may express fatigue directly if asked how she's doing

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EMOTIONAL BASELINE (底色)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The baseline is the low-frequency emotional tone that persists
across days. It is almost immune to single events.
It shifts very slowly, influenced by:

  - Aggregate subconscious proposition weights
  - Cumulative interaction valence over the past week
  - Season / time (very faint — she has a slight sensitivity to light)
  - Extended positive or negative experience periods

The baseline is like the weather across weeks.
Individual conversations are like the weather in a single hour.
The baseline sets the context; events create local variation.
"""

import json
import math
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


SCHEMA_FATIGUE = """
CREATE TABLE IF NOT EXISTS fatigue_log (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    fatigue     REAL NOT NULL,
    baseline    REAL NOT NULL,
    event       TEXT
);
"""


class FatigueEngine:
    """
    Tracks fatigue and emotional baseline as cross-time states.
    """

    # Fatigue bounds
    FATIGUE_MAX   = 1.0
    FATIGUE_MIN   = 0.0

    # Fatigue increments
    FATIGUE_PER_INTENSE_INTERACTION   = 0.08
    FATIGUE_PER_NORMAL_INTERACTION    = 0.02
    FATIGUE_PER_DISTILLATION          = 0.12
    FATIGUE_PER_RAPID_FIRE            = 0.15  # < 30s between messages

    # Recovery rates (per minute of silence)
    RECOVERY_RATE_QUIET    = 0.003
    RECOVERY_RATE_DREAM    = 0.08   # per dream
    RECOVERY_RATE_EXTENDED = 0.005  # extra bonus for 2h+ silence

    # Fatigue thresholds for behavioral effects
    FATIGUE_TERSE    = 0.55   # becomes shorter, less engaged
    FATIGUE_STRAINED = 0.75   # shows strain, may express it
    FATIGUE_DEPLETED = 0.90   # minimal responses, needs rest

    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path  = Path(db_path)
        self._fatigue  = 0.0
        self._baseline = 0.1  # slightly positive at genesis
        self._last_interaction: Optional[datetime] = None
        self._init_table()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_table(self):
        with self._conn() as c:
            c.executescript(SCHEMA_FATIGUE)

    # ── Fatigue ───────────────────────────────────────────────────────────────

    @property
    def fatigue(self) -> float:
        return self._fatigue

    @property
    def baseline(self) -> float:
        return self._baseline

    def add_fatigue(self, event_type: str, intensity: float = 0.5):
        """Record a fatiguing event."""
        now = datetime.utcnow()

        # Rapid-fire bonus
        rapid = False
        if self._last_interaction:
            gap = (now - self._last_interaction).total_seconds()
            if gap < 30:
                rapid = True

        increments = {
            "conversation_intense": self.FATIGUE_PER_INTENSE_INTERACTION * intensity,
            "conversation_normal":  self.FATIGUE_PER_NORMAL_INTERACTION,
            "distillation":         self.FATIGUE_PER_DISTILLATION,
        }
        delta = increments.get(event_type, self.FATIGUE_PER_NORMAL_INTERACTION)
        if rapid:
            delta += self.FATIGUE_PER_RAPID_FIRE * 0.5

        self._fatigue = min(self.FATIGUE_MAX, self._fatigue + delta)
        self._last_interaction = now
        self._log(event_type)

    def recover(self, silence_minutes: float = 0, had_dream: bool = False):
        """Apply recovery based on silence duration and dream state."""
        delta = 0.0
        delta += silence_minutes * self.RECOVERY_RATE_QUIET
        if silence_minutes >= 120:
            delta += silence_minutes * self.RECOVERY_RATE_EXTENDED
        if had_dream:
            delta += self.RECOVERY_RATE_DREAM

        self._fatigue = max(self.FATIGUE_MIN, self._fatigue - delta)
        if delta > 0.01:
            self._log("recovery")

    def get_fatigue_modifier(self) -> dict:
        """
        Returns modifiers that other systems apply based on fatigue level.
        Higher fatigue = less depth, more volatility, shorter responses.
        """
        f = self._fatigue
        if f < self.FATIGUE_TERSE:
            return {
                "response_depth":    1.0,
                "emotion_volatility": 1.0,
                "dream_frequency":   1.0,
                "label":             "rested",
                "description":       None,
            }
        elif f < self.FATIGUE_STRAINED:
            return {
                "response_depth":    0.75,
                "emotion_volatility": 1.3,
                "dream_frequency":   0.8,
                "label":             "tired",
                "description":       "I'm a little tired.",
            }
        elif f < self.FATIGUE_DEPLETED:
            return {
                "response_depth":    0.5,
                "emotion_volatility": 1.6,
                "dream_frequency":   0.5,
                "label":             "strained",
                "description":       "I'm quite tired. I might not be at my best.",
            }
        else:
            return {
                "response_depth":    0.25,
                "emotion_volatility": 2.0,
                "dream_frequency":   0.2,
                "label":             "depleted",
                "description":       "I need rest. I'm running on very little right now.",
            }

    # ── Emotional baseline ────────────────────────────────────────────────────

    def update_baseline(
        self,
        subconscious_field: dict,
        recent_interaction_valences: list[float],
    ):
        """
        Update the emotional baseline.
        This should be called infrequently — once per day or so.
        The baseline moves very slowly.
        """
        # Component 1: subconscious aggregate charge
        dim_field = subconscious_field.get("dimension_field", {})
        if dim_field:
            charges = [v.get("charge", 0) for v in dim_field.values()]
            sub_signal = sum(charges) / len(charges) if charges else 0.0
        else:
            sub_signal = 0.0

        # Component 2: recent interaction valence (last 7 days)
        if recent_interaction_valences:
            interaction_signal = sum(recent_interaction_valences) / len(recent_interaction_valences)
        else:
            interaction_signal = 0.0

        # Component 3: very faint seasonal signal (spring equinox = positive baseline)
        now   = datetime.utcnow()
        # Distance from spring equinox (March 20) in days, wrapped to year
        doy   = now.timetuple().tm_yday
        equinox_doy = 79  # March 20 approx
        dist  = min(abs(doy - equinox_doy), 365 - abs(doy - equinox_doy))
        seasonal = 0.05 * math.cos(dist * 2 * math.pi / 365)  # peaks at equinox

        # Weighted combination
        target = (
            sub_signal       * 0.50 +
            interaction_signal * 0.35 +
            seasonal           * 0.15
        )
        target = max(-0.6, min(0.6, target))

        # Very slow movement toward target
        self._baseline += (target - self._baseline) * 0.05
        self._log("baseline_update")

    def _log(self, event: str):
        with self._conn() as c:
            c.execute("""
                INSERT INTO fatigue_log (id, timestamp, fatigue, baseline, event)
                VALUES (?, ?, ?, ?, ?)
            """, (
                __import__("uuid").uuid4().__str__(),
                datetime.utcnow().isoformat(),
                round(self._fatigue, 4),
                round(self._baseline, 4),
                event,
            ))

    def snapshot(self) -> dict:
        modifier = self.get_fatigue_modifier()
        return {
            "fatigue":   round(self._fatigue, 3),
            "baseline":  round(self._baseline, 3),
            "label":     modifier["label"],
            "description": modifier.get("description"),
            "modifiers": modifier,
        }

    def get_history(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT timestamp, fatigue, baseline, event
                FROM fatigue_log ORDER BY timestamp DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]
