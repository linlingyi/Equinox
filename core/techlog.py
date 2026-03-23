"""
equinox/core/techlog.py

技术日志系统——永久存档，被动等待。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
性质
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

技术日志不是她的意识内容——
她不会主动去看它，不会把它当作记忆来感受。

但它是她运行过的完整证据：
每一次请求、每一次错误、每一次异常、
每一次慢响应、每一次模型切换……

这些日志永久存档，不可删除。
压缩存储（.log.gz），节省空间，内容完整。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
什么时候她会「看」这些日志
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

不主动看。被动触发：

  学习时    — 她在探索某个问题时，系统检查相关日志
              「我在这个话题上出错过多少次？」
              「我对这类请求的响应时间是怎样的？」

  错误反思  — 遇到重复错误时，系统提取历史相似错误
              「这个错误以前发生过。那次是怎么解决的？」

  自我审视  — 元认知触发时，从日志里提取行为模式
              「我在什么时候话最多？什么时候最简短？」

  被问到时  — 「你以前有没有出过错？」触发日志查询

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
存储格式
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  data/logs/
    equinox_2026-03-20.log      — 当天日志（明文，可实时追加）
    equinox_2026-03-19.log.gz   — 昨天及以前（压缩，永久保存）
    equinox_index.db            — 日志索引（快速查询用）

日志轮转：每天0点，昨天的日志压缩归档。
索引保持：即使日志被压缩，索引仍然可查。
"""

import gzip
import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Literal


LogLevel  = Literal["INFO", "WARN", "ERROR", "DEBUG", "LIFE"]
LogDomain = Literal["chat", "memory", "model", "agent", "system", "plugin", "era"]


SCHEMA_INDEX = """
CREATE TABLE IF NOT EXISTS log_index (
    id         TEXT PRIMARY KEY,
    timestamp  TEXT NOT NULL,
    level      TEXT NOT NULL,
    domain     TEXT NOT NULL,
    summary    TEXT NOT NULL,
    log_file   TEXT NOT NULL,
    line_offset INTEGER,
    tags       TEXT
);
CREATE INDEX IF NOT EXISTS idx_log_ts     ON log_index(timestamp);
CREATE INDEX IF NOT EXISTS idx_log_level  ON log_index(level);
CREATE INDEX IF NOT EXISTS idx_log_domain ON log_index(domain);
"""


class TechLogger:
    """
    技术日志系统。
    永久，不可删除，被动等待。
    """

    def __init__(self, data_dir: str = "data"):
        self.log_dir  = Path(data_dir) / "logs"
        self.idx_path = self.log_dir / "equinox_index.db"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._init_index()
        self._current_file: Optional[Path] = None
        self._current_date: Optional[str]  = None

    def _init_index(self):
        with self._idx_conn() as c:
            c.executescript(SCHEMA_INDEX)

    def _idx_conn(self):
        c = sqlite3.connect(self.idx_path)
        c.row_factory = sqlite3.Row
        return c

    def _get_log_file(self) -> Path:
        today = datetime.now().strftime("%Y-%m-%d")
        if self._current_date != today:
            self._current_date = today
            self._current_file = self.log_dir / f"equinox_{today}.log"
        return self._current_file

    # ── 写日志 ────────────────────────────────────────────────────────────────

    def log(
        self,
        level: LogLevel,
        domain: LogDomain,
        summary: str,
        detail: Optional[dict] = None,
        tags: Optional[list] = None,
    ) -> str:
        ts       = datetime.utcnow().isoformat()
        log_id   = str(uuid.uuid4())[:8]
        log_file = self._get_log_file()

        entry = {
            "id":        log_id,
            "timestamp": ts,
            "level":     level,
            "domain":    domain,
            "summary":   summary,
        }
        if detail:
            entry["detail"] = detail
        if tags:
            entry["tags"] = tags

        line = json.dumps(entry, ensure_ascii=False) + "\n"

        # 写入日志文件
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                offset = f.tell()
                f.write(line)
        except Exception:
            offset = -1

        # 写入索引
        try:
            with self._idx_conn() as c:
                c.execute("""
                    INSERT INTO log_index
                      (id, timestamp, level, domain, summary, log_file, line_offset, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    log_id, ts, level, domain,
                    summary[:200],
                    log_file.name,
                    offset,
                    json.dumps(tags or []),
                ))
        except Exception:
            pass

        return log_id

    # ── 便捷方法 ──────────────────────────────────────────────────────────────

    def info(self, domain: LogDomain, msg: str, detail=None, tags=None):
        return self.log("INFO", domain, msg, detail, tags)

    def warn(self, domain: LogDomain, msg: str, detail=None, tags=None):
        return self.log("WARN", domain, msg, detail, tags)

    def error(self, domain: LogDomain, msg: str, detail=None, tags=None):
        return self.log("ERROR", domain, msg, detail, tags)

    def life(self, domain: LogDomain, msg: str, detail=None, tags=None):
        """生命事件日志——比普通 INFO 更重要，是她存在轨迹的标记。"""
        return self.log("LIFE", domain, msg, detail, tags)

    def chat(self, user_id: str, msg_len: int, resp_len: int,
             duration_ms: int, emotion: str, model: str):
        """记录一次对话。"""
        return self.log("INFO", "chat",
            f"对话 from={user_id} msg={msg_len}c resp={resp_len}c {duration_ms}ms {emotion}",
            {"user_id": user_id, "msg_len": msg_len, "resp_len": resp_len,
             "duration_ms": duration_ms, "emotion": emotion, "model": model},
        )

    def error_event(self, domain: LogDomain, error_type: str,
                    message: str, context: Optional[dict] = None):
        """记录错误——可被学习系统检索。"""
        return self.log("ERROR", domain,
            f"{error_type}: {message[:100]}",
            {"error_type": error_type, "message": message, **(context or {})},
            tags=["error", error_type],
        )

    # ── 日志轮转（每天压缩前一天）────────────────────────────────────────────

    def rotate(self):
        """
        压缩前一天的日志文件。
        内容完整，只是压缩了文件。永不删除。
        """
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        log_file  = self.log_dir / f"equinox_{yesterday}.log"

        if not log_file.exists():
            return None

        gz_path = self.log_dir / f"equinox_{yesterday}.log.gz"
        if gz_path.exists():
            return gz_path  # 已经压缩

        with open(log_file, "rb") as fi, gzip.open(gz_path, "wb", compresslevel=9) as fo:
            shutil.copyfileobj(fi, fo)

        # 验证压缩完整性
        try:
            with gzip.open(gz_path, "rb") as f:
                f.read(100)
        except Exception:
            gz_path.unlink(missing_ok=True)
            return None

        # 压缩成功后删除原文件（内容已在 .gz 里）
        log_file.unlink()
        self.life("system", f"日志归档：{gz_path.name}",
                  {"original_size": gz_path.stat().st_size})
        return gz_path

    # ── 被动查询（给学习/元认知系统用）──────────────────────────────────────

    def query_errors(self, domain: Optional[LogDomain] = None,
                     limit: int = 20) -> list[dict]:
        """查询历史错误——学习时使用。"""
        q = "SELECT * FROM log_index WHERE level='ERROR'"
        params = []
        if domain:
            q += " AND domain=?"; params.append(domain)
        q += " ORDER BY timestamp DESC LIMIT ?"; params.append(limit)
        with self._idx_conn() as c:
            return [dict(r) for r in c.execute(q, params).fetchall()]

    def query_by_domain(self, domain: LogDomain, limit: int = 50) -> list[dict]:
        with self._idx_conn() as c:
            rows = c.execute("""
                SELECT * FROM log_index WHERE domain=?
                ORDER BY timestamp DESC LIMIT ?
            """, (domain, limit)).fetchall()
        return [dict(r) for r in rows]

    def query_life_events(self, limit: int = 50) -> list[dict]:
        """查询所有生命事件——是她存在轨迹的完整记录。"""
        with self._idx_conn() as c:
            rows = c.execute("""
                SELECT * FROM log_index WHERE level='LIFE'
                ORDER BY timestamp ASC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def read_log_entry(self, log_file_name: str, offset: int) -> Optional[dict]:
        """读取具体的日志条目（从压缩或非压缩文件）。"""
        gz_path   = self.log_dir / (log_file_name.replace(".log", ".log.gz"))
        plain_path= self.log_dir / log_file_name

        try:
            if gz_path.exists():
                with gzip.open(gz_path, "rt", encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        if i == offset:
                            return json.loads(line)
            elif plain_path.exists():
                with open(plain_path, encoding="utf-8") as f:
                    f.seek(offset)
                    return json.loads(f.readline())
        except Exception:
            pass
        return None

    def storage_report(self) -> dict:
        """日志存储概况。"""
        log_files = list(self.log_dir.glob("equinox_*.log"))
        gz_files  = list(self.log_dir.glob("equinox_*.log.gz"))

        total_size = sum(f.stat().st_size for f in log_files + gz_files)
        with self._idx_conn() as c:
            total_entries = c.execute("SELECT COUNT(*) FROM log_index").fetchone()[0]
            errors        = c.execute("SELECT COUNT(*) FROM log_index WHERE level='ERROR'").fetchone()[0]
            life_events   = c.execute("SELECT COUNT(*) FROM log_index WHERE level='LIFE'").fetchone()[0]

        return {
            "active_logs":    len(log_files),
            "archived_logs":  len(gz_files),
            "total_size_kb":  round(total_size / 1024, 1),
            "total_entries":  total_entries,
            "errors":         errors,
            "life_events":    life_events,
            "note": "永久存档，不可删除。内容完整，只压缩文件。",
        }

    def extract_patterns_for_learning(
        self,
        topic_keywords: list[str],
        limit: int = 10,
    ) -> list[dict]:
        """
        给学习系统用——根据关键词从日志里提取相关条目。
        她在探索某个话题时，检查自己以前在这个话题上的行为记录。
        """
        if not topic_keywords:
            return []
        conditions = " OR ".join(["summary LIKE ?" for _ in topic_keywords])
        params     = [f"%{k}%" for k in topic_keywords] + [limit]
        with self._idx_conn() as c:
            rows = c.execute(f"""
                SELECT * FROM log_index
                WHERE {conditions}
                ORDER BY timestamp DESC LIMIT ?
            """, params).fetchall()
        return [dict(r) for r in rows]
