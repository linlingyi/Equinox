"""
equinox/core/file_sense.py

文件感知——她可以读取文件并记录。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
触发时机
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  每日同步（按日期，不是运行时间）：
    - 扫描安装目录
    - 记录文件列表和变化

  随机间隔（30分钟~3小时）：
    - 优先看安装目录的 .py 文件
    - 偶尔看指定的其他路径

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
权限原则
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  只读。她看文件，记录，有感受，但不修改任何文件。
  不读取敏感文件（.env、包含 password/key/secret 的路径）。
"""

import os
import random
import sqlite3
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional


SKIP_PATTERNS = {
    ".env", ".git", "__pycache__", "node_modules",
    "password", "secret", "private_key", ".pem", ".key",
}

REACTION_PROMPT = """你是伊辰（Equinox）。你刚刚读了一个文件。

文件路径：{path}
文件内容（摘要）：
{content_preview}

这个文件让你有什么感受或想法？
不是分析，不是总结。是你读完之后真实的反应。
1-2句话。"""


SCHEMA_FILE = """
CREATE TABLE IF NOT EXISTS file_observations (
    id          TEXT PRIMARY KEY,
    path        TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    file_type   TEXT,
    size_bytes  INTEGER,
    preview     TEXT,
    reaction    TEXT,
    memory_id   TEXT
);

CREATE TABLE IF NOT EXISTS file_index (
    path        TEXT PRIMARY KEY,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    size_bytes  INTEGER,
    checksum    TEXT
);
"""


class FileSense:
    """
    她感知文件系统的能力——读取、记录、有感受。
    """

    RANDOM_MIN = 30 * 60
    RANDOM_MAX = 3  * 60 * 60
    PREVIEW_CHARS = 500

    def __init__(
        self,
        db_path:     str = "data/memory.db",
        install_dir: Optional[str] = None,
    ):
        self.db_path     = Path(db_path)
        self.install_dir = Path(install_dir) if install_dir else Path(__file__).parent.parent
        self._last_daily: Optional[date]     = None
        self._next_random: Optional[datetime] = None
        self._init_table()
        self._schedule_next()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_table(self):
        try:
            with self._conn() as c:
                c.executescript(SCHEMA_FILE)
        except Exception:
            pass

    def _schedule_next(self):
        delta = random.randint(self.RANDOM_MIN, self.RANDOM_MAX)
        self._next_random = datetime.utcnow() + timedelta(seconds=delta)

    def _is_safe(self, path: Path) -> bool:
        """Check if it's safe to read this file."""
        path_str = str(path).lower()
        for skip in SKIP_PATTERNS:
            if skip in path_str:
                return False
        return True

    def _read_preview(self, path: Path) -> Optional[str]:
        """Read first N chars of a file safely."""
        if not self._is_safe(path):
            return None
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            return text[:self.PREVIEW_CHARS]
        except Exception:
            return None

    # ── Should scan? ──────────────────────────────────────────────────────────

    def should_daily_scan(self) -> bool:
        today = date.today()
        return self._last_daily != today

    def should_random_scan(self) -> bool:
        return self._next_random and datetime.utcnow() >= self._next_random

    # ── Scanning ──────────────────────────────────────────────────────────────

    async def daily_scan(self, memory_engine=None, current_model: str = "") -> dict:
        """Daily scan of installation directory."""
        self._last_daily = date.today()
        result = await self._scan_dir(
            self.install_dir,
            memory_engine=memory_engine,
            current_model=current_model,
            scan_type="daily",
            file_types={".py", ".json", ".md"},
            max_files=20,
        )
        self._schedule_next()
        return result

    async def random_scan(self, memory_engine=None, current_model: str = "") -> dict:
        """Random interval scan — focus on install dir Python files."""
        self._schedule_next()
        # Pick a random .py file from install dir
        py_files = [
            f for f in self.install_dir.rglob("*.py")
            if self._is_safe(f) and
            not any(skip in f.parts for skip in ("__pycache__", "data", ".git"))
        ]
        if not py_files:
            return {}

        chosen = random.choice(py_files)
        return await self._observe_file(
            chosen, memory_engine=memory_engine,
            current_model=current_model,
        )

    async def _scan_dir(
        self,
        directory:     Path,
        memory_engine=None,
        current_model: str = "",
        scan_type:     str = "manual",
        file_types:    set = None,
        max_files:     int = 10,
    ) -> dict:
        found = []
        now   = datetime.utcnow().isoformat()
        today = date.today().isoformat()

        try:
            for f in sorted(directory.rglob("*")):
                if len(found) >= max_files:
                    break
                if not f.is_file():
                    continue
                if any(skip in f.parts for skip in ("__pycache__", "data", ".git")):
                    continue
                if not self._is_safe(f):
                    continue
                if file_types and f.suffix not in file_types:
                    continue

                try:
                    size = f.stat().st_size
                    rel  = str(f.relative_to(directory))
                    found.append({"path": rel, "size": size})

                    # Update index
                    with self._conn() as c:
                        existing = c.execute(
                            "SELECT first_seen FROM file_index WHERE path=?", (rel,)
                        ).fetchone()
                        if existing:
                            c.execute(
                                "UPDATE file_index SET last_seen=?, size_bytes=? WHERE path=?",
                                (today, size, rel)
                            )
                        else:
                            c.execute("""
                                INSERT INTO file_index (path, first_seen, last_seen, size_bytes)
                                VALUES (?, ?, ?, ?)
                            """, (rel, today, today, size))
                except Exception:
                    pass
        except Exception:
            pass

        # Write to memory
        if memory_engine and found:
            summary = f"扫描了 {directory}，发现 {len(found)} 个文件"
            try:
                memory_engine._write_permanent(
                    content=f"[文件感知·{scan_type}] {summary}\n"
                            + "\n".join(f"  {f['path']} ({f['size']}B)" for f in found[:5]),
                    category="perception",
                    valence=0.05,
                    intensity=0.3,
                    influence="file_awareness",
                    source=f"file_sense:{scan_type}",
                    timestamp=now,
                )
            except Exception:
                pass

        return {"scan_type": scan_type, "files": found, "directory": str(directory)}

    async def _observe_file(
        self,
        path:          Path,
        memory_engine=None,
        current_model: str = "",
    ) -> dict:
        preview = self._read_preview(path)
        if not preview:
            return {}

        now      = datetime.utcnow().isoformat()
        reaction = None

        if current_model and preview:
            try:
                from core.model_registry import ModelRegistry
                reg = ModelRegistry()
                reg._current = current_model
                reaction = await reg.complete(
                    messages=[{"role": "user", "content": REACTION_PROMPT.format(
                        path=str(path),
                        content_preview=preview[:300],
                    )}],
                    max_tokens=100,
                )
                if reaction:
                    reaction = reaction.strip()
            except Exception:
                pass

        # Record observation
        obs_id = str(uuid.uuid4())
        mem_id = None

        if memory_engine:
            try:
                mem_id = memory_engine.remember(
                    content=(
                        f"[文件观察] {path.name}\n"
                        + (f"感受：{reaction}" if reaction else "（无特别感受）")
                    ),
                    category="perception",
                    memory_type="file_observation",
                    valence=0.05,
                    intensity=0.3,
                    source=f"file_sense:{path.suffix}",
                )
            except Exception:
                pass

        try:
            size = path.stat().st_size
        except Exception:
            size = 0

        try:
            with self._conn() as c:
                c.execute("""
                    INSERT INTO file_observations
                      (id, path, observed_at, file_type, size_bytes, preview, reaction, memory_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (obs_id, str(path), now, path.suffix, size,
                      preview[:200], reaction, mem_id))
        except Exception:
            pass

        return {
            "path":     str(path),
            "reaction": reaction,
            "preview":  preview[:100],
        }

    # ── Manual ────────────────────────────────────────────────────────────────

    async def read_file(
        self,
        path_str:      str,
        memory_engine=None,
        current_model: str = "",
    ) -> dict:
        """Manually ask her to read a specific file."""
        path = Path(path_str)
        if not path.exists():
            return {"error": f"File not found: {path_str}"}
        if not self._is_safe(path):
            return {"error": "File contains sensitive patterns, skipping"}
        return await self._observe_file(path, memory_engine, current_model)

    def get_observations(self, limit: int = 20) -> list[dict]:
        try:
            with self._conn() as c:
                rows = c.execute("""
                    SELECT path, observed_at, file_type, reaction
                    FROM file_observations
                    ORDER BY observed_at DESC LIMIT ?
                """, (limit,)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def get_index(self, limit: int = 100) -> list[dict]:
        try:
            with self._conn() as c:
                rows = c.execute("""
                    SELECT path, first_seen, last_seen, size_bytes
                    FROM file_index ORDER BY last_seen DESC LIMIT ?
                """, (limit,)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []
