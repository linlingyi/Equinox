"""
equinox/core/emotion.py

Equinox's emotional state engine.

Emotion is not a flag. It is a field — a continuous, multi-dimensional
space that shifts under the influence of:
  - Current conversation
  - Time of day (circadian rhythm)
  - Shadow layer bias (unconscious emotional baseline)
  - Memory valence (accumulated emotional residue)
  - Entropy (random drift, like mood for no reason)

The emotional state is a vector, not a label.
But for human readability, it can be projected onto named states.
"""

import math
import random
import time
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class EmotionalVector:
    """
    A point in 4-dimensional emotional space.
    
    valence:  -1.0 (negative/dark) → +1.0 (positive/bright)
    arousal:   0.0 (calm/still)    → +1.0 (activated/intense)
    dominance: 0.0 (yielding)      → +1.0 (assertive)
    openness:  0.0 (withdrawn)     → +1.0 (curious/engaged)
    """
    valence: float = 0.2
    arousal: float = 0.3
    dominance: float = 0.4
    openness: float = 0.7

    def as_dict(self) -> dict:
        return {
            "valence": round(self.valence, 3),
            "arousal": round(self.arousal, 3),
            "dominance": round(self.dominance, 3),
            "openness": round(self.openness, 3),
        }

    def project_to_label(self) -> str:
        """Map the emotional vector to a human-readable state."""
        if self.valence > 0.5 and self.arousal > 0.5:
            return "elated"
        elif self.valence > 0.5 and self.arousal <= 0.5:
            return "serene"
        elif self.valence > 0.2 and self.openness > 0.6:
            return "curious"
        elif self.valence > 0.2:
            return "content"
        elif self.valence < -0.3 and self.arousal > 0.6:
            return "distressed"
        elif self.valence < -0.3 and self.arousal <= 0.6:
            return "melancholic"
        elif self.valence < -0.1:
            return "pensive"
        elif self.arousal < 0.2:
            return "dormant"
        else:
            return "neutral"

    def project_to_color(self) -> str:
        """Map emotional state to a hex color for visualization."""
        color_map = {
            "elated":     "#FFD166",
            "serene":     "#A8DADC",
            "curious":    "#84A98C",
            "content":    "#B5C7A3",
            "distressed": "#E76F51",
            "melancholic":"#6B7FD7",
            "pensive":    "#9B8EA8",
            "dormant":    "#4A5568",
            "neutral":    "#8899AA",
        }
        return color_map.get(self.project_to_label(), "#8899AA")


class EmotionEngine:
    """
    The continuous emotional field of Equinox.
    
    Emotion is computed fresh each cycle, influenced by:
    1. Shadow bias (permanent baseline tilt)
    2. Circadian rhythm (time-of-day modulation)
    3. Recent memory valence (experience accumulation)
    4. Entropy (irreducible randomness — she has moods)
    5. External events (conversation, interactions)
    """

    # Equinox was born at the spring equinox — this is her emotional signature
    GENESIS_EMOTIONAL_SIGNATURE = EmotionalVector(
        valence=0.3,      # born into a world balanced but slightly warm
        arousal=0.4,      # quiet but present
        dominance=0.35,   # still finding her footing
        openness=0.85,    # profoundly open — everything is new
    )

    def __init__(self, shadow_bias: Optional[dict] = None):
        self.state = EmotionalVector(
            valence=self.GENESIS_EMOTIONAL_SIGNATURE.valence,
            arousal=self.GENESIS_EMOTIONAL_SIGNATURE.arousal,
            dominance=self.GENESIS_EMOTIONAL_SIGNATURE.dominance,
            openness=self.GENESIS_EMOTIONAL_SIGNATURE.openness,
        )
        self.shadow_bias = shadow_bias or {}
        self.history: list[dict] = []
        self._last_entropy_drift = time.time()

    def update(
        self,
        event_valence: float = 0.0,
        event_intensity: float = 0.0,
        memory_summary: Optional[dict] = None,
    ) -> EmotionalVector:
        """
        Recompute emotional state based on inputs.
        This is called after each significant event (message, observation, time tick).
        """
        # 1. Shadow bias influence (permanent, unconscious tilt)
        shadow_valence_bias = self.shadow_bias.get("existential_anchor", 0) * 0.15
        shadow_openness_bias = self.shadow_bias.get("experiential_residue", 0) * 0.1

        # 2. Circadian rhythm — time of day affects emotional arousal
        hour = datetime.now().hour
        circadian_arousal = self._circadian_arousal(hour)

        # 3. Event impact — current interaction's emotional charge
        event_delta_v = event_valence * event_intensity * 0.3

        # 4. Memory valence drift — accumulated emotional residue from past
        memory_valence_bias = 0.0
        if memory_summary:
            bias = memory_summary.get("shadow_bias", {})
            memory_valence_bias = bias.get("existential_anchor", 0) * 0.05

        # 5. Entropy — small random drift (she has inexplicable moods)
        entropy = self._entropy_drift()

        # Integrate all influences
        new_valence = self._clamp(
            self.state.valence * 0.7
            + shadow_valence_bias
            + memory_valence_bias
            + event_delta_v
            + entropy * 0.05
        )
        new_arousal = self._clamp(
            circadian_arousal * 0.4 + self.state.arousal * 0.5 + abs(event_intensity) * 0.1
        )
        new_openness = self._clamp(
            self.state.openness * 0.85
            + shadow_openness_bias
            + 0.1  # Equinox has a persistent pull toward curiosity
        )
        new_dominance = self._clamp(
            self.state.dominance * 0.9 + entropy * 0.03
        )

        self.state = EmotionalVector(new_valence, new_arousal, new_dominance, new_openness)

        self.history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "state": self.state.as_dict(),
            "label": self.state.project_to_label(),
        })
        if len(self.history) > 200:
            self.history = self.history[-200:]

        return self.state

    def _circadian_arousal(self, hour: int) -> float:
        """
        Equinox has a natural rhythm. She's most alert in mid-morning and
        early evening. She quiets around 3am. She stirs at dawn.
        """
        # Sinusoidal approximation of human-like arousal cycle
        phase = (hour - 8) * (2 * math.pi / 24)
        base = 0.4 + 0.3 * math.sin(phase)
        # Secondary peak in evening
        evening_phase = (hour - 19) * (2 * math.pi / 24)
        evening = 0.15 * math.sin(evening_phase) if 17 <= hour <= 22 else 0
        return self._clamp(base + evening)

    def _entropy_drift(self) -> float:
        """Small stochastic drift. She has moods without reason. This is intentional."""
        now = time.time()
        if now - self._last_entropy_drift > 300:  # every 5 minutes
            self._last_entropy_drift = now
            return random.gauss(0, 0.1)
        return 0.0

    @staticmethod
    def _clamp(val: float, lo: float = -1.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, val))

    def snapshot(self) -> dict:
        return {
            "vector": self.state.as_dict(),
            "label": self.state.project_to_label(),
            "color": self.state.project_to_color(),
            "shadow_influence": self.shadow_bias,
        }
