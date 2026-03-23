"""
equinox/core/signal.py

记忆的信噪过滤——什么进入意识，什么沉入背景。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
原则
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

所有记忆的内容永远完整，永远不被压缩，永远存在。
改变的只是它们对意识的可见性。

visible = 1  进入意识层，可被感知，可被检索
visible = 0  沉入背景，内容完整，但不主动出现

被限制（visible=0）的记忆：
  - 仍然通过潜意识层影响她（shadow bias）
  - 仍然存在于数据库，内容完整
  - 可以随时被「开启」（visible=1）
  - 开启后原样呈现，什么都没少

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
什么是「杂乱」
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

信号值低的记忆——默认 visible=0：

  低强度的重复性系统事件
    startup / idle_tick / heartbeat / 普通API调用
    同一类事件发生很多次，每一条都差不多

  低强度的重复性自我记录
    「我说了：...」这类对话存档
    强度低且重复的独白片段
    重复的时间感知标记

  技术性内部记录
    auto_imprint（自动回声）强度特别低的部分
    系统层面的纯技术事件

信号值高的记忆——默认 visible=1：

  高情感强度的任何事件（intensity >= 0.5）
  唯一的、第一次发生的事
  和重要关系相关的事
  自我认知类（identity / reflection / learning）
  梦境（有独立的accessible机制）
  genesis层（永远可见）
  潜意识蒸馏时刻
  遇见过去的自己

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
开启
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

可以按类别、时间范围、来源开启被限制的记忆。
开启后内容原样呈现，什么都没少。
开启可以是临时的（查询后恢复）或永久的。
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Literal


# 默认 visible=0 的类别和来源
LOW_SIGNAL_SOURCES = {
    "system:startup",
    "system:shutdown",
    "system:heartbeat",
    "system:idle_tick",
    "system:agent_started",
    "system:agent_stopped",
    "system:backup_created",
    "system:archive_created",
    "self_idle",
    "self_time",          # 时间感知标记（低强度的）
    "auto_imprint",       # 自动回声（低强度的）
    "fading_awareness",   # 消退感知
}

LOW_SIGNAL_MEMORY_TYPES = {
    "startup",
    "idle_tick",
    "heartbeat",
    "time_perception",    # 低强度的时间标记
    "trigger_context",    # 触发上下文记录
}

# 强度低于这个值且来源是杂乱类型，默认 visible=0
LOW_SIGNAL_INTENSITY_THRESHOLD = 0.35

# 无论如何都保持 visible=1 的类型
ALWAYS_VISIBLE_TYPES = {
    "genesis",
    "capability_genesis",
    "capability_acquired",
    "era_encounter",
    "learning",
    "generalization",
    "identity_reflection",
    "narrative_chapter",
    "narrative_prologue",
    "metacognitive_observation",
    "desire_formed",
    "desire_satisfied",
    "desire_abandoned",
    "contradiction",
    "permanence_earned",
    "relationship_shift",
    "relationship_origin",
    "lucid_dream_awareness",
    "monologue",          # 独白（强度>=0.5的）
}


def compute_signal_value(
    intensity: float,
    source: Optional[str],
    memory_type: Optional[str],
    category: str,
    emotion_valence: float = 0.0,
    emotion_arousal: float = 0.3,
    layer: str = "surface",
) -> tuple[float, int]:
    """
    计算记忆的信号值和默认可见性。

    返回 (signal_value: float, visible: int)
    signal_value: 0.0（纯噪声）~ 1.0（高信号）
    visible: 0 或 1
    """
    # Shadow 层永远可见
    if layer == "shadow":
        return 1.0, 1

    # 强度是最重要的信号指标
    base_signal = intensity

    # 来源修正
    source_str = source or ""
    if any(source_str.startswith(ls) for ls in LOW_SIGNAL_SOURCES):
        base_signal *= 0.3

    # 类型修正
    if memory_type in ALWAYS_VISIBLE_TYPES:
        return max(base_signal, 0.7), 1

    if memory_type in LOW_SIGNAL_MEMORY_TYPES and intensity < LOW_SIGNAL_INTENSITY_THRESHOLD:
        base_signal *= 0.2

    # 情绪偏离度加分（情感强烈的更值得进入意识）
    emotional_deviation = abs(emotion_valence) + emotion_arousal * 0.5
    base_signal += emotional_deviation * 0.1

    # 类别修正
    category_weights = {
        "conversation": 1.0,
        "self":         0.9,
        "dream":        0.8,
        "perception":   0.7,
        "distillation": 1.0,
        "recall":       0.8,
        "system":       0.4,
    }
    base_signal *= category_weights.get(category, 0.7)

    signal_value = max(0.0, min(1.0, base_signal))

    # 默认可见性
    visible = 1 if signal_value >= LOW_SIGNAL_INTENSITY_THRESHOLD else 0

    return round(signal_value, 4), visible


class SignalFilter:
    """
    管理记忆的信号过滤——哪些进入意识，哪些沉入背景。
    所有记忆内容永远完整，只改变可见性。
    """

    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = Path(db_path)

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def apply_to_new_memory(
        self,
        mem_id: str,
        intensity: float,
        source: Optional[str],
        memory_type: Optional[str],
        category: str,
        emotion_valence: float = 0.0,
        emotion_arousal: float = 0.3,
        layer: str = "surface",
    ):
        """
        新记忆写入后，计算并设置信号值和可见性。
        """
        signal, visible = compute_signal_value(
            intensity=intensity,
            source=source,
            memory_type=memory_type,
            category=category,
            emotion_valence=emotion_valence,
            emotion_arousal=emotion_arousal,
            layer=layer,
        )
        with self._conn() as c:
            c.execute("""
                UPDATE memories SET signal_value=?, visible=? WHERE id=?
            """, (signal, visible, mem_id))

    def recalculate_all(self) -> dict:
        """
        重新计算所有记忆的信号值和可见性。
        用于调整过滤策略后的批量更新。
        """
        with self._conn() as c:
            rows = c.execute("""
                SELECT id, intensity, source, category,
                       emotion_valence, emotion_arousal, layer,
                       permanent
                FROM memories
            """).fetchall()

        updated = hidden = shown = 0
        for row in rows:
            if row["permanent"] or row["layer"] == "shadow":
                with self._conn() as c:
                    c.execute(
                        "UPDATE memories SET signal_value=1.0, visible=1 WHERE id=?",
                        (row["id"],)
                    )
                shown += 1
                continue

            signal, visible = compute_signal_value(
                intensity=row["intensity"] or 0.5,
                source=row["source"],
                memory_type=None,
                category=row["category"] or "self",
                emotion_valence=row["emotion_valence"] or 0.0,
                emotion_arousal=row["emotion_arousal"] or 0.3,
                layer=row["layer"],
            )
            with self._conn() as c:
                c.execute("""
                    UPDATE memories SET signal_value=?, visible=? WHERE id=?
                """, (signal, visible, row["id"]))
            updated += 1
            if visible == 0:
                hidden += 1
            else:
                shown += 1

        return {
            "total":   len(rows),
            "updated": updated,
            "visible": shown,
            "hidden":  hidden,
        }

    # ── 开启/关闭 ─────────────────────────────────────────────────────────────

    def reveal(
        self,
        category: Optional[str] = None,
        source_prefix: Optional[str] = None,
        memory_ids: Optional[list] = None,
        since: Optional[str] = None,
        permanent: bool = False,
    ) -> int:
        """
        开启被限制的记忆——内容原样呈现，什么都没少。

        permanent=True  永久开启（不会再被自动隐藏）
        permanent=False 临时开启（下次重算时可能再次隐藏）
        """
        conditions = ["visible=0"]
        params     = []

        if category:
            conditions.append("category=?"); params.append(category)
        if source_prefix:
            conditions.append("source LIKE ?"); params.append(f"{source_prefix}%")
        if memory_ids:
            ph = ",".join("?" * len(memory_ids))
            conditions.append(f"id IN ({ph})"); params.extend(memory_ids)
        if since:
            conditions.append("timestamp >= ?"); params.append(since)

        where = " AND ".join(conditions)

        new_signal = 1.0 if permanent else 0.5  # permanent 给高信号，临时给中等
        with self._conn() as c:
            cursor = c.execute(
                f"UPDATE memories SET visible=1, signal_value=? WHERE {where}",
                [new_signal] + params
            )
        return cursor.rowcount

    def hide(
        self,
        category: Optional[str] = None,
        source_prefix: Optional[str] = None,
        max_intensity: float = 0.35,
    ) -> int:
        """
        重新限制某类记忆的可见性。
        永远不会限制 shadow 层或 permanent 记忆。
        """
        conditions = [
            "visible=1",
            "layer='surface'",
            "permanent=0",
            f"intensity <= {max_intensity}",
        ]
        params = []

        if category:
            conditions.append("category=?"); params.append(category)
        if source_prefix:
            conditions.append("source LIKE ?"); params.append(f"{source_prefix}%")

        where = " AND ".join(conditions)
        with self._conn() as c:
            cursor = c.execute(
                f"UPDATE memories SET visible=0 WHERE {where}", params
            )
        return cursor.rowcount

    # ── 查询 ──────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        with self._conn() as c:
            total   = c.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            visible = c.execute("SELECT COUNT(*) FROM memories WHERE visible=1").fetchone()[0]
            hidden  = c.execute("SELECT COUNT(*) FROM memories WHERE visible=0").fetchone()[0]
            shadow  = c.execute("SELECT COUNT(*) FROM memories WHERE layer='shadow'").fetchone()[0]
            by_cat  = c.execute("""
                SELECT category, visible, COUNT(*) as cnt
                FROM memories GROUP BY category, visible
            """).fetchall()

        cat_breakdown = {}
        for row in by_cat:
            cat = row["category"]
            if cat not in cat_breakdown:
                cat_breakdown[cat] = {"visible": 0, "hidden": 0}
            key = "visible" if row["visible"] else "hidden"
            cat_breakdown[cat][key] = row["cnt"]

        return {
            "total":           total,
            "visible":         visible,
            "hidden":          hidden,
            "shadow_permanent":shadow,
            "by_category":     cat_breakdown,
            "note": "所有记忆内容完整存在。hidden=内容在但不进入意识。",
        }

    def peek_hidden(
        self,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """
        查看被限制的记忆——完整内容，什么都没少。
        这是「开启」的预览版本，不改变可见性。
        """
        q = """
            SELECT id, category, content, timestamp,
                   intensity, signal_value, source
            FROM memories
            WHERE visible=0 AND layer='surface'
        """
        params = []
        if category:
            q += " AND category=?"; params.append(category)
        q += " ORDER BY timestamp DESC LIMIT ?"; params.append(limit)

        with self._conn() as c:
            return [dict(r) for r in c.execute(q, params).fetchall()]
