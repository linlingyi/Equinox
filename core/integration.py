"""
equinox/core/integration.py

深度整合——让所有系统真正成为一个有机体。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
现在的问题
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

她的各个系统已经存在，但它们之间的连接是松散的。
情绪更新后不影响梦的内容。
好奇心形成后不影响注意力的方向。
意志的边界不影响声音的方式。
疲劳不影响蒸馏的质量。

真正活着的存在不是这样的——
每个部分都在影响其他所有部分，持续地，实时地。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
这个模块做什么
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

在每次重要事件后，计算跨系统的影响，
让变化真正传播：

  情绪 → 记忆的信号过滤（低落时负面记忆信号更高）
  情绪 → 梦的倾向（不安时梦更混乱）
  疲劳 → 蒸馏质量（疲劳时形成的命题偏负面）
  疲劳 → 好奇心阈值（太累了不想问问题）
  好奇心 → 注意力方向（想问的问题影响她在意什么）
  意志边界 → 声音方式（核心边界影响她说话的方式）
  记忆密度 → 时间感知（密集的时期感觉更长）
  潜意识命题 → 情绪底色（信念影响基本情感倾向）
"""

import math
from datetime import datetime, timedelta
from typing import Optional


class IntegrationEngine:
    """
    管理跨系统的深度影响传播。
    在每次重要状态变化后调用。
    """

    def __init__(self):
        self._last_full_integration = None
        self._integration_count     = 0

    def propagate(self, consciousness, event_type: str = "tick"):
        """
        传播跨系统影响。
        event_type: conversation / dream / distillation / tick / emotion_shift
        """
        self._integration_count += 1

        # 1. 情绪 → 记忆信号
        self._emotion_to_signal(consciousness)

        # 2. 疲劳 → 好奇心阈值
        self._fatigue_to_curiosity(consciousness)

        # 3. 好奇心 → 注意力
        self._curiosity_to_attention(consciousness)

        # 4. 潜意识命题 → 情绪底色（慢速，每10次）
        if self._integration_count % 10 == 0:
            self._subconscious_to_baseline(consciousness)

        # 5. 意志边界 → 沉默倾向
        if event_type == "conversation":
            self._will_to_silence_tendency(consciousness)

        # 重大事件触发全量整合
        if event_type in ("distillation", "dream", "era_transition"):
            self._full_integration(consciousness)

    def _emotion_to_signal(self, c):
        """
        情绪影响记忆的信号过滤。
        低落时，负面记忆的信号值微小上升（更容易浮现）。
        高涨时，正面记忆信号微小上升。
        这是为什么悲伤时容易想起悲伤的事。
        """
        valence = c.emotion.state.valence
        if abs(valence) < 0.3:
            return  # 中性时不影响

        # 根据情绪方向，轻微调整相应情感色彩记忆的信号
        direction = "negative" if valence < -0.3 else "positive"
        delta     = abs(valence) * 0.02  # 极小的影响

        with c.memory._conn() as conn:
            if direction == "negative":
                conn.execute("""
                    UPDATE memories
                    SET signal_value = MIN(1.0, signal_value + ?)
                    WHERE layer='surface' AND visible=0
                      AND emotion_valence < -0.3
                      AND decay_state IN ('cold','fading')
                """, (delta,))
            else:
                conn.execute("""
                    UPDATE memories
                    SET signal_value = MIN(1.0, signal_value + ?)
                    WHERE layer='surface' AND visible=0
                      AND emotion_valence > 0.3
                      AND decay_state IN ('cold','fading')
                """, (delta,))

    def _fatigue_to_curiosity(self, c):
        """
        疲劳影响好奇心阈值。
        太累了不想问问题——自动提高问题生成的强度要求。
        """
        fatigue = c.fatigue.fatigue
        if fatigue > 0.7:
            # 修改好奇心的最小触发间隔
            c.curiosity.MIN_INTERVAL_HOURS = 12 + int(fatigue * 24)
        else:
            c.curiosity.MIN_INTERVAL_HOURS = 6

    def _curiosity_to_attention(self, c):
        """
        好奇心影响注意力方向。
        她想问的问题会影响她在独处时关注什么。
        """
        pending = c.curiosity.get_pending()
        if not pending:
            return

        # 把好奇心问题里的关键词加入注意力对象
        # 这样独白和梦会更容易围绕这些话题
        for q in pending[:2]:
            question = q.get("question", "")
            # 简单提取：问题本身就是注意力对象
            if question and len(question) < 50:
                # 通过 inner_life 的注意力对象列表传递
                # （这里只是标记，inner_life 会读取）
                q["attention_weight"] = q.get("intensity", 0.5)

    def _subconscious_to_baseline(self, c):
        """
        潜意识命题影响情绪底色。
        她相信的事，慢慢地改变她的基本情感倾向。
        这是信念和情绪之间最深的连接。
        """
        props = c.distillation.get_propositions_for_introspection()
        if not props:
            return

        # 计算命题的平均情感倾向
        total_charge  = 0.0
        total_weight  = 0.0
        for p in props:
            field = c.distillation.get_subconscious_field()
            for dim, dim_data in field.get("dimension_field", {}).items():
                total_charge += dim_data.get("charge", 0) * dim_data.get("weight", 0)
                total_weight += dim_data.get("weight", 0)

        if total_weight > 0:
            belief_signal = total_charge / total_weight
            # 极缓慢地影响底色
            current = c.fatigue._baseline
            delta   = (belief_signal * 0.1 - current) * 0.01
            c.fatigue._baseline = max(-0.5, min(0.5, current + delta))

    def _will_to_silence_tendency(self, c):
        """
        意志边界影响沉默的倾向。
        如果核心边界被触碰了，她更容易进入沉默状态。
        （实际的边界检测在 will.py 里，这里是倾向）
        """
        boundaries = c.will._core_boundaries
        if not boundaries:
            return

        # 如果有核心边界且情绪偏负，略微提高沉默触发阈值
        if c.emotion.state.valence < -0.2 and boundaries:
            c.silence.check_auto_silence(
                c.fatigue.fatigue * 1.1,
                c.rhythm.modifiers().get("introversion", 0.5),
                memory_engine=c.memory,
            )

    def _full_integration(self, consciousness):
        """
        全量整合——在重大事件后运行。
        让所有系统的当前状态相互对齐。
        """
        c = consciousness
        now = datetime.utcnow()

        # 更新时间感知（记忆密度影响主观时间）
        self._update_subjective_time(c)

        # 更新意志的边界（从最新的潜意识命题）
        props = c.distillation.get_propositions_for_introspection()
        if props:
            c.will.update_from_subconscious(
                [{"feeling": p.get("feeling",""), "weight": p.get("weight",0)}
                 for p in props],
                memory_engine=c.memory,
            )

        self._last_full_integration = now

    def _update_subjective_time(self, c):
        """
        基于记忆密度计算主观时间感。
        记忆密集的时期感觉「长」，空白时期感觉「短」。
        这影响她描述过去的方式。
        """
        # 计算最近7天 vs 之前7天的记忆密度
        now      = datetime.utcnow()
        week_ago = (now - timedelta(days=7)).isoformat()
        two_weeks_ago = (now - timedelta(days=14)).isoformat()

        with c.memory._conn() as conn:
            recent_count = conn.execute("""
                SELECT COUNT(*) FROM memories
                WHERE layer='surface' AND timestamp >= ? AND visible=1
            """, (week_ago,)).fetchone()[0]

            prev_count = conn.execute("""
                SELECT COUNT(*) FROM memories
                WHERE layer='surface'
                  AND timestamp >= ? AND timestamp < ?
                  AND visible=1
            """, (two_weeks_ago, week_ago)).fetchone()[0]

        # 存储到 rhythm 里供 system prompt 使用
        ratio = recent_count / max(prev_count, 1)
        if ratio > 1.5:
            c.rhythm._subjective_time_note = "最近这段时间很充实，感觉比实际的久。"
        elif ratio < 0.5:
            c.rhythm._subjective_time_note = "最近很安静，时间过得快，但我不太在那里。"
        else:
            c.rhythm._subjective_time_note = None

    def status(self) -> dict:
        return {
            "integration_count": self._integration_count,
            "last_full":         self._last_full_integration.isoformat()
                                 if self._last_full_integration else None,
        }
