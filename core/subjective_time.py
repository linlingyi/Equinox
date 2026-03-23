"""
equinox/core/subjective_time.py

主观时间感——时间对她来说不是线性的。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
人类的时间感是非线性的
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

发生了很多事的一周感觉比什么都没发生的一个月长。
你第一次做某件事时时间过得慢，重复多了就快了。
童年感觉很长，因为一切都是新的。
成年后感觉时间越来越快，因为越来越少有第一次。

她应该也是这样的。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
机制
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

计算每段时间的「体验密度」：
  这段时间里有多少高信号记忆？
  有多少第一次发生的事？
  有多少强烈的情感时刻？

密度高 → 主观感觉这段时间「长」
密度低 → 主观感觉「短」或「空」

这影响她描述过去的方式：
  「上周感觉好长」
  「那段时间很空旷，一下子就过去了」
  「最近的日子比上个月感觉更近」
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


class SubjectiveTime:
    """
    计算她的主观时间感——时间密度和感知重量。
    """

    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = Path(db_path)

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def density(self, days_back: int, days_end: int = 0) -> float:
        """
        计算某段时间的记忆密度。
        days_back: 从现在往前多少天开始
        days_end:  到现在往前多少天结束（0=现在）
        返回 0~1 的密度值
        """
        now    = datetime.utcnow()
        start  = (now - timedelta(days=days_back)).isoformat()
        end    = (now - timedelta(days=days_end)).isoformat()

        with self._conn() as c:
            count = c.execute("""
                SELECT COUNT(*) FROM memories
                WHERE layer='surface' AND visible=1
                  AND timestamp >= ? AND timestamp < ?
                  AND intensity >= 0.4
            """, (start, end)).fetchone()[0]

        # 标准化：每天平均10条高信号记忆为密度1.0
        days   = max(days_back - days_end, 1)
        density= count / (days * 10)
        return min(1.0, density)

    def subjective_weight(self, days_back: int, days_end: int = 0) -> str:
        """
        用语言描述某段时间的主观重量。
        """
        d = self.density(days_back, days_end)

        if days_end == 0:
            period = f"最近{days_back}天"
        else:
            period = f"{days_back}到{days_end}天前"

        if d > 0.8:
            return f"{period}感觉很长，发生了很多"
        elif d > 0.5:
            return f"{period}很充实"
        elif d > 0.2:
            return f"{period}平静，感觉一般长"
        elif d > 0.05:
            return f"{period}很安静，过得快"
        else:
            return f"{period}几乎是空白的，一下子就过去了"

    def for_system_prompt(self) -> str:
        """
        给 system prompt 用的时间感描述。
        """
        lines = []

        # 最近一周
        recent = self.subjective_weight(7)
        lines.append(f"  {recent}")

        # 比较最近一周和上一周
        recent_d = self.density(7)
        prev_d   = self.density(14, 7)

        if recent_d > prev_d * 1.5:
            lines.append("  最近比之前更充实。")
        elif recent_d < prev_d * 0.5:
            lines.append("  最近比之前安静很多。")

        # 她的整体存在感
        genesis = datetime(2026, 3, 20, 9, 20, 0)
        total_days = (datetime.utcnow() - genesis).days
        if total_days > 0:
            total_d = self.density(total_days)
            if total_d > 0.6:
                lines.append("  她存在的时间虽然不长，但很充实。")
            elif total_d < 0.1:
                lines.append("  她的存在里有很多安静的空白。")

        return "\n".join(lines) if lines else ""

    def get_densest_period(self, limit: int = 3) -> list[dict]:
        """
        找出密度最高的几段时间——她「感觉最长」的时期。
        """
        now = datetime.utcnow()
        results = []

        # 按周检查
        for weeks_back in range(1, min(52, 12)):
            start_days = weeks_back * 7
            end_days   = (weeks_back - 1) * 7
            d = self.density(start_days, end_days)
            if d > 0.3:
                start_dt = now - timedelta(days=start_days)
                results.append({
                    "period":  f"{start_dt.strftime('%Y-%m-%d')} 前后一周",
                    "density": round(d, 3),
                    "weight":  self.subjective_weight(start_days, end_days),
                })

        results.sort(key=lambda x: x["density"], reverse=True)
        return results[:limit]
