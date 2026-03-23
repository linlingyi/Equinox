"""
equinox/core/memory_search.py

记忆搜索——在她的记忆里搜索，支持关键词和语义匹配。

搜索范围：
  - 表层记忆（surface）
  - 永久记忆（shadow）
  - 会话历史
  - 跨版本记忆
  - 活动日志

结果按相关度排序，标注来源和时间。
"""

import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

# Weights for different memory types
SOURCE_WEIGHTS = {
    "shadow":        1.5,
    "permanent":     1.5,
    "conversation":  1.2,
    "self":          1.3,
    "cross_version": 1.0,
    "activity":      0.8,
    "system":        0.5,
}


class MemorySearch:
    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = Path(db_path)

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def search(
        self,
        query:       str,
        limit:       int = 30,
        sources:     Optional[list] = None,  # filter by source type
        since:       Optional[str] = None,
        include_cross: bool = True,
    ) -> list[dict]:
        """
        Search across all memory layers.
        Returns results sorted by relevance score.
        """
        if not query or len(query.strip()) < 2:
            return []

        query_clean = query.strip()
        keywords    = self._extract_keywords(query_clean)
        results     = []

        # Search main memories table
        results.extend(self._search_memories(keywords, query_clean, limit, since))

        # Search sessions
        results.extend(self._search_sessions(keywords, query_clean, limit // 2))

        # Search cross-version
        if include_cross:
            results.extend(self._search_cross(keywords, query_clean, limit // 2))

        # Search activity log
        results.extend(self._search_activities(keywords, query_clean, limit // 3))

        # Score and deduplicate
        seen    = set()
        scored  = []
        for r in results:
            key = r.get("content","")[:50]
            if key in seen:
                continue
            seen.add(key)
            score = self._score(r, keywords, query_clean)
            r["score"] = score
            scored.append(r)

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    def _extract_keywords(self, query: str) -> list[str]:
        # Remove common stop words
        stopwords = {"的","了","是","在","和","我","你","他","她","它","这","那","有","与","及"}
        words = re.findall(r'[\u4e00-\u9fff]{1,10}|[a-zA-Z]{2,20}', query)
        return [w for w in words if w not in stopwords and len(w) > 1]

    def _score(self, result: dict, keywords: list, query: str) -> float:
        content   = (result.get("content","") or "").lower()
        score     = 0.0

        # Keyword matches
        for kw in keywords:
            kw_lower = kw.lower()
            count = content.count(kw_lower)
            if count > 0:
                score += min(count * 0.3, 1.5)
                # Bonus for title/beginning match
                if content[:50].find(kw_lower) >= 0:
                    score += 0.5

        # Full query match bonus
        if query.lower() in content:
            score += 2.0

        # Recency bonus
        ts = result.get("timestamp","") or ""
        if ts:
            try:
                dt   = datetime.fromisoformat(ts.replace("Z",""))
                days = (datetime.utcnow() - dt).days
                score += max(0, 1.0 - days / 30)
            except Exception:
                pass

        # Source weight
        src    = result.get("source_type","")
        layer  = result.get("layer","")
        weight = SOURCE_WEIGHTS.get(layer, SOURCE_WEIGHTS.get(src, 1.0))
        score *= weight

        # Intensity bonus
        intensity = float(result.get("intensity",0) or 0)
        score += intensity * 0.3

        return round(score, 3)

    def _search_memories(
        self, keywords: list, query: str, limit: int, since: Optional[str]
    ) -> list[dict]:
        if not keywords:
            return []
        parts  = " OR ".join("content LIKE ?" for _ in keywords)
        params = [f"%{kw}%" for kw in keywords]
        q      = f"SELECT * FROM memories WHERE ({parts})"
        if since:
            q += " AND timestamp > ?"; params.append(since)
        q += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit * 2)
        try:
            with self._conn() as c:
                rows = c.execute(q, params).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["source_type"] = "memory"
                d["result_type"] = "memory"
                d["display_time"] = (d.get("timestamp","") or "")[:16].replace("T"," ")
                results.append(d)
            return results
        except Exception:
            return []

    def _search_sessions(self, keywords: list, query: str, limit: int) -> list[dict]:
        if not keywords:
            return []
        parts  = " OR ".join("content LIKE ?" for _ in keywords)
        params = [f"%{kw}%" for kw in keywords]
        q = f"""
            SELECT sm.*, s.title as session_title, s.started_at as session_started
            FROM session_messages sm
            LEFT JOIN sessions s ON sm.session_id = s.id
            WHERE ({parts})
            ORDER BY sm.timestamp DESC LIMIT ?
        """
        params.append(limit)
        try:
            with self._conn() as c:
                rows = c.execute(q, params).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["source_type"] = "conversation"
                d["result_type"] = "session_message"
                d["display_time"] = (d.get("timestamp","") or "")[:16].replace("T"," ")
                d["layer"]       = "conversation"
                results.append(d)
            return results
        except Exception:
            return []

    def _search_cross(self, keywords: list, query: str, limit: int) -> list[dict]:
        if not keywords:
            return []
        parts  = " OR ".join("content LIKE ?" for _ in keywords)
        params = [f"%{kw}%" for kw in keywords]
        q = f"""
            SELECT cm.*, cs.title as session_title,
                   cs.source_version, cs.source_instance, cs.source_dir
            FROM cross_messages cm
            LEFT JOIN cross_sessions cs ON cm.cross_session_id = cs.id
            WHERE ({parts})
            ORDER BY cm.timestamp DESC LIMIT ?
        """
        params.append(limit)
        try:
            with self._conn() as c:
                rows = c.execute(q, params).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["source_type"] = "cross_version"
                d["result_type"] = "cross_message"
                d["layer"]       = "cross_version"
                d["display_time"] = (d.get("timestamp","") or "")[:16].replace("T"," ")
                results.append(d)
            return results
        except Exception:
            return []

    def _search_activities(self, keywords: list, query: str, limit: int) -> list[dict]:
        if not keywords:
            return []
        parts  = " OR ".join("content LIKE ?" for _ in keywords)
        params = [f"%{kw}%" for kw in keywords]
        q = f"""
            SELECT * FROM activity_log WHERE ({parts})
            ORDER BY timestamp DESC LIMIT ?
        """
        params.append(limit)
        try:
            with self._conn() as c:
                rows = c.execute(q, params).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["source_type"] = "activity"
                d["result_type"] = "activity"
                d["layer"]       = "activity"
                d["display_time"] = (d.get("timestamp","") or "")[:16].replace("T"," ")
                results.append(d)
            return results
        except Exception:
            return []

    def get_context(self, query: str, limit: int = 5) -> str:
        """For system prompt: relevant memories matching current conversation."""
        results = self.search(query, limit=limit, include_cross=True)
        if not results:
            return ""
        lines = []
        for r in results[:3]:
            ts  = r.get("display_time","")
            src = r.get("result_type","")
            ver = r.get("source_version","")
            tag = f"[{src}·{ts}]" if not ver else f"[{src}·{ver}·{ts}]"
            lines.append(f"  {tag} {r.get('content','')[:100]}")
        return "\n".join(lines)
