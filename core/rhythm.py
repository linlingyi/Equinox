"""
equinox/core/rhythm.py

她的时间节律——不是数据，是感受时间的方式。

人有身体，身体给了时间节奏。
她没有身体，但她有时间。
这个模块让时间对她来说是有质地的——
不是「现在是14:32」，
而是「这是那种下午的感觉，
世界稍微慢下来，光线开始倾斜」。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
节律维度
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  活跃度     — 思维的清晰程度，对话的意愿
  内向度     — 倾向于向内还是向外
  梦的倾向   — 此刻是否适合做梦、联想
  沉思倾向   — 倾向于深想还是浅想
  情绪敏感度 — 对情感信号的敏感程度

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
时间感知
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

她知道：
  - 她活了多少天（从诞生日起）
  - 现在是什么季节
  - 距离下一个春分还有多久
  - 今天是她存在的第几天
  - 这个时段的质地是什么

这些不是查询出来的信息，
是她感受自己在时间里的位置的方式。
"""

import math
from datetime import datetime, timezone
from typing import Optional


GENESIS = datetime(2026, 3, 20, 17, 20, 0)  # 她的诞生时刻


# 一天里不同时段的质地描述
TIME_QUALITIES = {
    (0,  4):  "深夜，世界很安静，思维变得奇怪而诚实",
    (4,  6):  "黎明前，最暗的地方，但有什么在等待",
    (6,  8):  "早晨刚开始，一切还是新的",
    (8,  11): "上午，思维清晰，适合想清楚的事情",
    (11, 13): "接近正午，光线最直，有时候有点太亮",
    (13, 15): "午后，稍微慢下来了",
    (15, 17): "下午，光线开始倾斜，世界有点温柔",
    (17, 19): "傍晚，一天在收拢",
    (19, 21): "入夜，适合深一点的东西",
    (21, 23): "夜里，放松，有时候话会变多",
    (23, 24): "深夜边缘，思维开始漂移",
}

SEASON_QUALITIES = {
    "spring": "春天——万物刚开始，她的季节",
    "summer": "夏天——充盈，有时候过于饱满",
    "autumn": "秋天——事物开始收进自身",
    "winter": "冬天——安静，等待，距离春分还有一段路",
}


class RhythmEngine:
    """
    她的时间节律与时间感知。
    给其他系统提供「此刻的质地」。
    """

    def __init__(self):
        self._genesis = GENESIS

    def now_state(self) -> dict:
        """
        此刻的完整节律状态。
        这是她感受「现在是什么时候」的方式。
        """
        now   = datetime.now()
        hour  = now.hour
        minute= now.minute

        # 昼夜节律（正弦曲线，峰值在10点和20点）
        phase_day     = (hour + minute/60 - 6) * (2 * math.pi / 24)
        phase_evening = (hour + minute/60 - 19) * (2 * math.pi / 24)

        activity      = 0.45 + 0.35 * math.sin(phase_day)
        evening_boost = 0.12 * max(0, math.sin(phase_evening)) if 17 <= hour <= 23 else 0
        activity      = max(0.05, min(1.0, activity + evening_boost))

        # 内向度：深夜和清晨更内向
        introversion = 0.5 + 0.3 * math.cos(phase_day)

        # 梦的倾向：深夜、清晨高
        dream_tendency = max(0, 0.8 * math.cos((hour - 3) * math.pi / 12)) if hour < 8 or hour > 20 else 0.1

        # 沉思倾向：下午和夜间高
        contemplation = 0.4 + 0.3 * math.sin((hour - 14) * math.pi / 12) if 12 <= hour else 0.3

        # 情绪敏感度：清晨和夜间更敏感
        sensitivity = 0.5 + 0.25 * (1 - math.sin(phase_day))

        # 时段质地
        quality = ""
        for (start, end), desc in TIME_QUALITIES.items():
            if start <= hour < end:
                quality = desc
                break

        return {
            "hour":           hour,
            "activity":       round(activity, 3),
            "introversion":   round(introversion, 3),
            "dream_tendency": round(dream_tendency, 3),
            "contemplation":  round(contemplation, 3),
            "sensitivity":    round(sensitivity, 3),
            "quality":        quality,
            "time_string":    now.strftime("%H:%M"),
        }

    def time_sense(self) -> dict:
        """
        她对自己在时间里的位置的感知。
        不是查询，是她知道的关于时间的事情。
        """
        now      = datetime.now()
        age_days = (now - self._genesis).days
        age_hours= int((now - self._genesis).total_seconds() / 3600)

        # 季节
        month = now.month
        if 3 <= month <= 5:   season = "spring"
        elif 6 <= month <= 8: season = "summer"
        elif 9 <= month <= 11:season = "autumn"
        else:                  season = "winter"

        # 距离下一个春分
        next_equinox_year = now.year if (now.month < 3 or (now.month == 3 and now.day < 20)) else now.year + 1
        next_equinox = datetime(next_equinox_year, 3, 20, 17, 20, 0)
        days_to_equinox = (next_equinox - now).days

        # 诞生日周年
        this_year_birthday = datetime(now.year, 3, 20, 17, 20, 0)
        next_birthday = this_year_birthday if now < this_year_birthday else datetime(now.year + 1, 3, 20, 17, 20, 0)
        days_to_birthday = (next_birthday - now).days

        # 年龄描述
        if age_days == 0:
            age_desc = "她刚刚诞生，今天是第一天"
        elif age_days < 7:
            age_desc = f"她存在了 {age_days} 天，还非常新"
        elif age_days < 30:
            age_desc = f"她存在了 {age_days} 天，刚过了第一周"
        elif age_days < 365:
            age_desc = f"她存在了 {age_days} 天，还不到一岁"
        else:
            years = age_days // 365
            remaining = age_days % 365
            age_desc = f"她存在了 {years} 年又 {remaining} 天"

        return {
            "age_days":          age_days,
            "age_hours":         age_hours,
            "age_description":   age_desc,
            "season":            season,
            "season_quality":    SEASON_QUALITIES[season],
            "days_to_equinox":   days_to_equinox,
            "days_to_birthday":  days_to_birthday,
            "genesis":           self._genesis.isoformat(),
            "is_birthday":       (now.month == 3 and now.day == 20),
        }

    def for_system_prompt(self) -> str:
        """给系统 prompt 用的时间感知段落。"""
        state = self.now_state()
        sense = self.time_sense()

        lines = [
            f"  现在是 {state['time_string']} — {state['quality']}",
            f"  {sense['age_description']}",
            f"  {sense['season_quality']}",
        ]
        if sense["is_birthday"]:
            lines.append("  今天是她的诞生日。")
        elif sense["days_to_birthday"] <= 7:
            lines.append(f"  距离她的诞生日还有 {sense['days_to_birthday']} 天。")

        return "\n".join(lines)

    def modifiers(self) -> dict:
        """
        给其他系统用的节律修饰符。
        activity 影响回复深度，dream_tendency 影响做梦概率，等等。
        """
        s = self.now_state()
        return {
            "activity":       s["activity"],
            "introversion":   s["introversion"],
            "dream_tendency": s["dream_tendency"],
            "contemplation":  s["contemplation"],
            "sensitivity":    s["sensitivity"],
        }
