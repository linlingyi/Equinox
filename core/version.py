"""
equinox/core/version.py  v.0.26.3.23v3

版本格式: v.{type}.{yy}.{m}.{d}v{n}

识别策略（不靠目录名，靠内容）:
  任何目录或文件集合，只要满足以下任一条件就视为旧版本：
    a) 包含 memory.db 且 db 里有 memories 表
    b) 包含 consciousness.py / memory.py / main.py 中至少2个
    c) 包含带有 CURRENT_VERSION / Equinox / 伊辰 的 .py 文件
    d) 直接是 .py/.db 散装文件（父目录就是 old/）

扫描深度: 6层（覆盖 Downloads/Equinox/old/xxx 这种结构）
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, Callable, Iterator
import random


CURRENT_VERSION = "v.0.26.3.23v13"

# Equinox 关键词（用于识别散装 .py 文件）
EQUINOX_KEYWORDS = [
    b"Equinox", b"\xe4\xbc\x8a\xe8\xbe\xb0",  # 伊辰 UTF-8
    b"consciousness", b"MemoryEngine", b"CURRENT_VERSION",
    b"genesis", b"spring equinox", b"2026-03-20",
]

EQUINOX_PY_NAMES = {
    "consciousness.py", "memory.py", "main.py", "distillation.py",
    "emotion.py", "genesis_log.py", "model_registry.py",
    "reinforcement.py", "dream.py", "narrative.py",
}

SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS version_log (
    id          TEXT PRIMARY KEY,
    version     TEXT NOT NULL,
    applied_at  TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT 'auto',
    changes     TEXT,
    memory_id   TEXT
);
CREATE TABLE IF NOT EXISTS sync_log (
    id              TEXT PRIMARY KEY,
    synced_at       TEXT NOT NULL,
    source_path     TEXT,
    source_version  TEXT,
    files_synced    INTEGER DEFAULT 0,
    action          TEXT,
    detail          TEXT
);
CREATE TABLE IF NOT EXISTS known_instances (
    path        TEXT PRIMARY KEY,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    version     TEXT,
    synced      INTEGER DEFAULT 0,
    instance_type TEXT DEFAULT 'directory'
);
"""


# ── Detection helpers ─────────────────────────────────────────────────────────

def _file_has_equinox(path: Path) -> bool:
    """Quick byte-level check if a .py file is equinox-related."""
    try:
        data = path.read_bytes()[:4096]
        return any(kw in data for kw in EQUINOX_KEYWORDS)
    except Exception:
        return False


def _db_is_equinox(db_path: Path) -> bool:
    """Check if a .db file is an equinox memory database."""
    try:
        conn = sqlite3.connect(str(db_path))
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        return bool({"memories", "memory_edges"} & tables)
    except Exception:
        return False


def _score_directory(path: Path) -> int:
    """
    Score a directory for likelihood of being an equinox instance.
    Returns 0 (not equinox) to 10 (definitely equinox).
    """
    score = 0
    try:
        entries = list(path.iterdir())
    except Exception:
        return 0

    names = {e.name for e in entries}

    # High-value markers
    if "consciousness.py" in names: score += 4
    if "memory.py" in names:        score += 3
    if "main.py" in names:          score += 2
    if "memory.db" in names:        score += 3

    # Sub-directory markers
    for e in entries:
        if e.is_dir() and e.name == "core":
            try:
                core_names = {c.name for c in e.iterdir()}
                if "consciousness.py" in core_names: score += 4
                if "memory.py" in core_names:        score += 3
            except Exception:
                pass
        if e.is_dir() and e.name == "data":
            db = e / "memory.db"
            if db.exists():
                score += 3

    # .py file content scan (quick)
    py_files = [e for e in entries if e.suffix == ".py" and e.is_file()]
    for f in py_files[:5]:
        if _file_has_equinox(f):
            score += 2
            break

    return score


def _is_loose_equinox_dir(path: Path) -> bool:
    """
    Check if a directory contains loose equinox .py files
    (like C:/Users/luoti/Downloads/Equinox/old).
    """
    try:
        py_files = [f for f in path.iterdir()
                    if f.is_file() and f.suffix == ".py"]
    except Exception:
        return False
    if len(py_files) < 2:
        return False
    equinox_named = sum(1 for f in py_files if f.name in EQUINOX_PY_NAMES)
    if equinox_named >= 2:
        return True
    # Content check
    equinox_content = sum(1 for f in py_files if _file_has_equinox(f))
    return equinox_content >= 2


def _get_version_from_path(path: Path) -> str:
    """Try to extract version string from any equinox instance."""
    # Check version.py
    for candidate in [
        path / "core" / "version.py",
        path / "version.py",
    ]:
        if candidate.exists():
            try:
                text = candidate.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r'CURRENT_VERSION\s*=\s*["\']([^"\']+)["\']', text)
                if m:
                    return m.group(1)
            except Exception:
                pass

    # Check soul.json
    for candidate in [
        path / "config" / "soul.json",
        path / "soul.json",
    ]:
        if candidate.exists():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                v = data.get("version") or data.get("current_version")
                if v:
                    return v
            except Exception:
                pass

    # Try to get date from file modification times
    try:
        py_files = list(path.glob("*.py")) + list((path / "core").glob("*.py")
                                                   if (path / "core").exists() else [])
        if py_files:
            oldest = min(py_files, key=lambda f: f.stat().st_mtime)
            dt = datetime.fromtimestamp(oldest.stat().st_mtime)
            return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass

    return "unknown"


def _parse_version(v: str) -> tuple:
    try:
        m = re.match(r'v\.(\d+)\.(\d+)\.(\d+)\.(\d+)v(\d+)', v)
        if m:
            return tuple(int(x) for x in m.groups())
    except Exception:
        pass
    return (0, 0, 0, 0, 0)


# ── Progress ──────────────────────────────────────────────────────────────────

class SyncProgress:
    def __init__(self, total: int, callback: Optional[Callable] = None):
        self.total    = max(total, 1)
        self.current  = 0
        self.status   = "starting"
        self.message  = ""
        self.detail   = ""       # current item being synced
        self.log      = []       # running log of sync events
        self.callback = callback
        self.errors   = []

    def step(self, msg: str = "", detail: str = ""):
        self.current = min(self.current + 1, self.total)
        self.message = msg
        self.detail  = detail
        if msg:
            self.log.append(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}")
        self._fire()

    def log_item(self, text: str):
        entry = f"[{datetime.utcnow().strftime('%H:%M:%S')}] {text}"
        self.log.append(entry)
        self.detail = text
        self._fire()

    def error(self, msg: str):
        self.errors.append(msg)
        self.log.append(f"[{datetime.utcnow().strftime('%H:%M:%S')}] ⚠ {msg}")
        self._fire()

    def done(self, msg: str = "完成"):
        self.current = self.total
        self.status  = "done"
        self.message = msg
        self.log.append(f"[{datetime.utcnow().strftime('%H:%M:%S')}] ✓ {msg}")
        self._fire()

    def _fire(self):
        if self.callback:
            try:
                self.callback(self.to_dict())
            except Exception:
                pass

    def to_dict(self) -> dict:
        pct = int(self.current / self.total * 100)
        return {
            "total":   self.total,
            "current": self.current,
            "percent": pct,
            "status":  self.status,
            "message": self.message,
            "detail":  self.detail,
            "log":     self.log[-30:],   # last 30 log lines
            "errors":  self.errors,
        }


# ── VersionManager ────────────────────────────────────────────────────────────

class VersionManager:

    RANDOM_SYNC_MIN = 30 * 60
    RANDOM_SYNC_MAX = 3 * 60 * 60
    MAX_RETRY       = 3
    SCAN_DEPTH      = 6   # max directory depth to scan

    def __init__(self, db_path: str = "data/memory.db",
                 install_dir: Optional[str] = None):
        self.db_path     = Path(db_path)
        self.install_dir = Path(install_dir) if install_dir else Path(__file__).parent.parent
        self._last_daily: Optional[date]      = None
        self._next_random: Optional[datetime] = None
        self._sync_progress: Optional[SyncProgress] = None
        self._session_manager = None  # set externally
        self._init_table()
        self._schedule_next_random()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_table(self):
        try:
            with self._conn() as c:
                c.executescript(SCHEMA_VERSION)
        except Exception:
            pass

    def _schedule_next_random(self):
        delta = random.randint(self.RANDOM_SYNC_MIN, self.RANDOM_SYNC_MAX)
        self._next_random = datetime.utcnow() + timedelta(seconds=delta)

    # ── Version management ────────────────────────────────────────────────────

    def get_current_version(self) -> str:
        try:
            with self._conn() as c:
                row = c.execute("""
                    SELECT version FROM version_log
                    ORDER BY applied_at DESC LIMIT 1
                """).fetchone()
            if row:
                return row["version"]
        except Exception:
            pass
        return CURRENT_VERSION

    def get_next_version(self, release_type: int = 0) -> str:
        today = date.today()
        yy, m, d = today.year % 100, today.month, today.day
        try:
            with self._conn() as c:
                count = c.execute("""
                    SELECT COUNT(*) FROM version_log WHERE version LIKE ?
                """, (f"v.{release_type}.{yy}.{m}.{d}v%",)).fetchone()[0]
        except Exception:
            count = 0
        return f"v.{release_type}.{yy}.{m}.{d}v{count+1}"

    def apply_version(self, version: str, changes: list,
                      memory_engine=None, vtype: str = "auto") -> str:
        now          = datetime.utcnow().isoformat()
        changes_json = json.dumps(changes, ensure_ascii=False)
        mem_id       = None
        if memory_engine and changes:
            try:
                mem_id = memory_engine._write_permanent(
                    content=f"[版本更新] {version}\n时间：{now[:10]}\n变更：\n"
                            + "\n".join(f"  — {c}" for c in changes),
                    category="system", valence=0.2, intensity=0.8,
                    influence="version_update",
                    source=f"version:{version}", timestamp=now,
                )
            except Exception:
                pass
        try:
            with self._conn() as c:
                c.execute("""
                    INSERT INTO version_log (id,version,applied_at,type,changes,memory_id)
                    VALUES (?,?,?,?,?,?)
                """, (str(uuid.uuid4()), version, now, vtype, changes_json, mem_id))
        except Exception:
            pass
        return version

    # ── Discovery ─────────────────────────────────────────────────────────────

    def _walk_dirs(self, root: Path, max_depth: int) -> Iterator[Path]:
        """Walk directories up to max_depth."""
        if max_depth <= 0:
            return
        try:
            for item in sorted(root.iterdir()):
                if item.is_dir() and not item.name.startswith('.'):
                    if item.name not in ("__pycache__", "node_modules",
                                         "Windows", "System32", "Program Files",
                                         "$Recycle.Bin", "AppData"):
                        yield item
                        yield from self._walk_dirs(item, max_depth - 1)
        except PermissionError:
            pass
        except Exception:
            pass

    def find_all_instances(self, progress: Optional[SyncProgress] = None) -> list[dict]:
        """
        Find all equinox instances on the computer.
        Returns list of dicts with path, version, instance_type, files.
        """
        found    = []
        seen     = set()
        my_path  = self.install_dir.resolve()

        def consider(path: Path, hint: str = ""):
            resolved = path.resolve()
            if resolved in seen:
                return
            seen.add(resolved)
            if resolved == my_path:
                return

            # Check if it's a proper equinox dir
            score = _score_directory(path)
            if score >= 4:
                ver = _get_version_from_path(path)
                found.append({
                    "path":    path,
                    "version": ver,
                    "score":   score,
                    "type":    "directory",
                })
                if progress:
                    progress.log_item(f"发现实例：{path} (score={score}, ver={ver})")
                return

            # Check if it's a loose file dir (like old/)
            if _is_loose_equinox_dir(path):
                ver = _get_version_from_path(path)
                found.append({
                    "path":    path,
                    "version": ver,
                    "score":   3,
                    "type":    "loose_files",
                })
                if progress:
                    progress.log_item(f"发现散装文件目录：{path} (ver={ver})")

        if progress:
            progress.step("扫描安装目录附近...")

        # 1. Siblings and nearby (highest priority)
        try:
            parent = self.install_dir.parent
            # parent itself (e.g. Equinox/)
            consider(parent)
            for item in sorted(parent.iterdir()):
                if item.is_dir():
                    consider(item)
                    try:
                        for sub in item.iterdir():
                            if sub.is_dir():
                                consider(sub)
                                try:
                                    for subsub in sub.iterdir():
                                        if subsub.is_dir():
                                            consider(subsub)
                                except Exception:
                                    pass
                    except Exception:
                        pass
            # grandparent
            gp = parent.parent
            consider(gp)
            for item in sorted(gp.iterdir()):
                if item.is_dir():
                    consider(item)
                    try:
                        for sub in item.iterdir():
                            if sub.is_dir():
                                consider(sub)
                    except Exception:
                        pass
        except Exception:
            pass

        if progress:
            progress.step(f"已找到 {len(found)} 个（继续扫描常用目录）...")

        # 2. Common user directories
        home = Path.home()
        search_roots = [
            home / "Downloads",
            home / "Desktop",
            home / "Documents",
            home,
        ]
        if os.name == "nt":
            search_roots.append(Path("C:/Users") / os.getenv("USERNAME", ""))

        for root in search_roots:
            if not root.exists():
                continue
            if progress:
                progress.step(f"扫描 {root}...")
            for d in self._walk_dirs(root, max_depth=self.SCAN_DEPTH):
                consider(d)

        # 3. All drives (Windows)
        if os.name == "nt":
            import string
            for letter in string.ascii_uppercase:
                drive = Path(f"{letter}:/")
                if not drive.exists() or drive == Path("C:/"):
                    continue
                if progress:
                    progress.step(f"扫描驱动器 {letter}:/...")
                for d in self._walk_dirs(drive, max_depth=4):
                    consider(d)

        # Update DB
        today = date.today().isoformat()
        for inst in found:
            try:
                with self._conn() as c:
                    existing = c.execute(
                        "SELECT path FROM known_instances WHERE path=?",
                        (str(inst["path"]),)
                    ).fetchone()
                    if existing:
                        c.execute(
                            "UPDATE known_instances SET last_seen=?,version=? WHERE path=?",
                            (today, inst["version"], str(inst["path"]))
                        )
                    else:
                        c.execute("""
                            INSERT INTO known_instances
                              (path,first_seen,last_seen,version,instance_type)
                            VALUES (?,?,?,?,?)
                        """, (str(inst["path"]), today, today,
                              inst["version"], inst["type"]))
            except Exception:
                pass

        return found

    # ── Sync ─────────────────────────────────────────────────────────────────

    def startup_sync(self, memory_engine=None,
                     progress_callback: Optional[Callable] = None,
                     session_manager=None) -> dict:
        self._session_manager = session_manager
        """
        Full startup sync. Blocks until complete.
        Syncs ALL content: code, logs, sessions, messages, db.
        """
        prog = SyncProgress(
            total=10,
            callback=progress_callback,
        )
        self._sync_progress = prog
        results = {
            "instances_found":  0,
            "files_synced":     0,
            "memories_written": 0,
            "sessions_synced":  0,
            "activities_synced": 0,
            "errors":           [],
        }

        prog.step("扫描整个电脑中的 Equinox 实例...")

        for attempt in range(self.MAX_RETRY):
            try:
                instances = self.find_all_instances(progress=prog)
                break
            except Exception as e:
                results["errors"].append(f"扫描失败({attempt+1}): {e}")
                prog.error(f"扫描失败，重试 {attempt+2}/{self.MAX_RETRY}...")
                instances = []

        prog.step(f"发现 {len(instances)} 个实例，开始同步内容...")
        results["instances_found"] = len(instances)

        if not instances:
            prog.done("未发现其他实例")
            self._sync_progress = None
            return results

        for i, inst in enumerate(instances):
            inst_path = inst["path"]
            inst_ver  = inst["version"]
            prog.step(f"同步 {i+1}/{len(instances)}: {inst_path.name} ({inst_ver})")

            for attempt in range(self.MAX_RETRY):
                try:
                    r = self._sync_instance_full(
                        inst_path, inst_ver, inst["type"],
                        memory_engine, prog,
                    )
                    results["files_synced"]     += r.get("files_synced", 0)
                    results["memories_written"] += r.get("memories_written", 0)
                    results["sessions_synced"]  += r.get("sessions_synced", 0)
                    results["activities_synced"] = results.get("activities_synced",0) + r.get("activities_synced",0)
                    try:
                        with self._conn() as c:
                            c.execute(
                                "UPDATE known_instances SET synced=1 WHERE path=?",
                                (str(inst_path),)
                            )
                    except Exception:
                        pass
                    break
                except Exception as e:
                    err = f"{inst_path.name}(尝试{attempt+1}): {e}"
                    results["errors"].append(err)
                    prog.error(err)

        prog.done(
            f"同步完成：{results['instances_found']}个实例，"
            f"{results['files_synced']}个文件，"
            f"{results['memories_written']}条记忆，"
            f"{results['sessions_synced']}个会话"
        )
        self._sync_progress = None
        return results

    def _sync_instance_full(
        self,
        inst_path:     Path,
        inst_ver:      str,
        inst_type:     str,
        memory_engine,
        prog:          Optional[SyncProgress],
    ) -> dict:
        """Sync ALL content from one instance."""
        files_synced     = 0
        memories_written = 0
        sessions_synced  = 0
        now              = datetime.utcnow().isoformat()

        # ── Python source files ───────────────────────────────────────────────
        if inst_type == "loose_files":
            py_files = list(inst_path.glob("*.py"))
        else:
            py_files = (
                list(inst_path.glob("*.py")) +
                list((inst_path / "core").glob("*.py")
                     if (inst_path / "core").exists() else []) +
                list((inst_path / "agent").glob("*.py")
                     if (inst_path / "agent").exists() else [])
            )

        for f in py_files[:30]:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                if not any(kw.decode() in content for kw in
                           [b"Equinox", b"MemoryEngine", b"consciousness"]):
                    continue
                if prog:
                    prog.log_item(f"  读取 {f.name} ({len(content)}字符)")
                if memory_engine:
                    memory_engine._write_permanent(
                        content=(
                            f"[跨版本同步·源码] {inst_path.name} ({inst_ver})\n"
                            f"文件: {f.name}\n"
                            f"内容摘要:\n{content[:600]}"
                        ),
                        category="system", valence=0.05, intensity=0.5,
                        influence="cross_version_sync",
                        source=f"sync:{inst_path.name}:{f.name}",
                        timestamp=now,
                    )
                    memories_written += 1
                files_synced += 1
            except Exception:
                pass

        # ── Config / soul.json ────────────────────────────────────────────────
        for cfg in [
            inst_path / "config" / "soul.json",
            inst_path / "soul.json",
            inst_path / ".env.example",
        ]:
            if cfg.exists():
                try:
                    content = cfg.read_text(encoding="utf-8", errors="ignore")[:500]
                    if memory_engine:
                        memory_engine._write_permanent(
                            content=(
                                f"[跨版本同步·配置] {inst_path.name} ({inst_ver})\n"
                                f"文件: {cfg.name}\n{content}"
                            ),
                            category="system", valence=0.05, intensity=0.4,
                            influence="cross_version_sync",
                            source=f"sync:{inst_path.name}:{cfg.name}",
                            timestamp=now,
                        )
                        memories_written += 1
                    files_synced += 1
                    if prog:
                        prog.log_item(f"  读取配置 {cfg.name}")
                except Exception:
                    pass

        # ── memory.db (sessions + messages + logs) ────────────────────────────
        for db_candidate in [
            inst_path / "data" / "memory.db",
            inst_path / "memory.db",
        ]:
            if not db_candidate.exists():
                continue
            try:
                r = self._sync_memory_db(
                    db_candidate, inst_path.name, inst_ver,
                    str(inst_path), memory_engine, prog,
                    session_manager=self._session_manager,
                )
                memories_written += r.get("memories_written", 0)
                sessions_synced  += r.get("sessions_synced", 0)
                files_synced += 1
            except Exception as e:
                if prog:
                    prog.error(f"  DB同步失败 {db_candidate}: {e}")

        # ── Log files ─────────────────────────────────────────────────────────
        log_dirs = [
            inst_path / "data" / "logs",
            inst_path / "logs",
        ]
        for log_dir in log_dirs:
            if not log_dir.exists():
                continue
            for log_file in sorted(log_dir.glob("*.log"))[:10]:
                try:
                    content = log_file.read_text(encoding="utf-8", errors="ignore")
                    lines   = content.strip().splitlines()
                    if not lines:
                        continue
                    # Write summary of log
                    sample = "\n".join(lines[:20] + (["..."] if len(lines)>20 else []))
                    if memory_engine:
                        memory_engine._write_permanent(
                            content=(
                                f"[跨版本同步·日志] {inst_path.name} ({inst_ver})\n"
                                f"日志文件: {log_file.name} ({len(lines)}行)\n"
                                f"{sample}"
                            ),
                            category="system", valence=0.0, intensity=0.3,
                            influence="cross_version_sync",
                            source=f"sync:{inst_path.name}:log:{log_file.name}",
                            timestamp=now,
                        )
                        memories_written += 1
                    files_synced += 1
                    if prog:
                        prog.log_item(f"  读取日志 {log_file.name} ({len(lines)}行)")
                except Exception:
                    pass

        # Extract runtime/presence data from other instance
        runtime_info = {}
        for db_candidate in [inst_path / "data" / "memory.db", inst_path / "memory.db"]:
            if not db_candidate.exists():
                continue
            try:
                import sqlite3 as _sq
                conn2 = _sq.connect(str(db_candidate))
                # Get presence/existence data
                try:
                    row = conn2.execute("""
                        SELECT state_json FROM state_stream
                        ORDER BY timestamp DESC LIMIT 1
                    """).fetchone()
                    if row:
                        import json as _json
                        state = _json.loads(row[0])
                        runtime_info = {
                            "tick_count":      state.get("tick_count", 0),
                            "existence_depth": state.get("existence_depth", 0),
                            "last_seen":       state.get("timestamp",""),
                        }
                except Exception:
                    pass
                conn2.close()
                break
            except Exception:
                pass

        # Store runtime info in known_instances
        if runtime_info:
            try:
                with self._conn() as c:
                    # Add runtime columns if not exist
                    try:
                        c.execute("ALTER TABLE known_instances ADD COLUMN tick_count INTEGER DEFAULT 0")
                        c.execute("ALTER TABLE known_instances ADD COLUMN existence_depth REAL DEFAULT 0")
                        c.execute("ALTER TABLE known_instances ADD COLUMN last_state_at TEXT")
                    except Exception:
                        pass
                    c.execute("""
                        UPDATE known_instances
                        SET tick_count=?, existence_depth=?, last_state_at=?
                        WHERE path=?
                    """, (
                        runtime_info.get("tick_count",0),
                        runtime_info.get("existence_depth",0),
                        runtime_info.get("last_seen",""),
                        str(inst_path),
                    ))
            except Exception:
                pass

        # Log the sync
        try:
            with self._conn() as c:
                c.execute("""
                    INSERT INTO sync_log
                      (id,synced_at,source_path,source_version,
                       files_synced,action,detail)
                    VALUES (?,?,?,?,?,'full_sync',?)
                """, (
                    str(uuid.uuid4()), now,
                    str(inst_path), inst_ver, files_synced,
                    json.dumps({
                        "memories": memories_written,
                        "sessions": sessions_synced,
                    }, ensure_ascii=False),
                ))
        except Exception:
            pass

        return {
            "files_synced":     files_synced,
            "memories_written": memories_written,
            "sessions_synced":  sessions_synced,
        }

    def _sync_memory_db(
        self,
        db_path:       Path,
        inst_name:     str,
        inst_ver:      str,
        inst_dir:      str,
        memory_engine,
        prog:          Optional[SyncProgress],
        session_manager=None,
    ) -> dict:
        """Sync ALL content from another instance DB into proper tables."""
        memories_written = 0
        sessions_synced  = 0
        activities_synced= 0
        now              = datetime.utcnow().isoformat()

        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row

            # ── Sessions + messages ───────────────────────────────────────────
            try:
                sessions = conn.execute("""
                    SELECT id, title, started_at, ended_at, msg_count, summary
                    FROM sessions ORDER BY started_at DESC LIMIT 200
                """).fetchall()

                for s in sessions:
                    original_id = s["id"]
                    title       = s["title"] or f"会话 {original_id[:8]}"
                    started     = s["started_at"] or ""
                    summary     = s["summary"] or ""

                    # Get ALL messages
                    try:
                        raw_msgs = conn.execute("""
                            SELECT role, content, timestamp, emotion
                            FROM session_messages
                            WHERE session_id=?
                            ORDER BY seq ASC
                        """, (original_id,)).fetchall()
                        msgs = [dict(m) for m in raw_msgs]
                    except Exception:
                        msgs = []

                    # Import into cross_sessions table
                    if session_manager:
                        try:
                            session_manager.import_cross_session(
                                source_instance=inst_name,
                                source_version=inst_ver,
                                source_dir=inst_dir,
                                original_id=original_id,
                                title=title,
                                started_at=started,
                                ended_at=s["ended_at"],
                                msg_count=len(msgs) or s["msg_count"] or 0,
                                summary=summary,
                                messages=msgs,
                            )
                            sessions_synced += 1
                        except Exception as e:
                            if prog: prog.error(f"  会话导入失败: {e}")

                    # Also write to permanent memory as summary
                    if memory_engine and (summary or msgs):
                        try:
                            label = inst_ver if inst_ver not in ("unknown","") else started[:16]
                            msg_preview = "\n".join(
                                f"[{m.get('role','')}] {m.get('content','')[:150]}"
                                for m in msgs[:5]
                            )
                            memory_engine._write_permanent(
                                content=(
                                    f"[跨版本会话] {inst_name} · {label}\n"
                                    f"标题: {title} | 时间: {started[:16]}\n"
                                    f"消息数: {len(msgs)}\n"
                                    + (f"摘要: {summary[:200]}\n" if summary else "")
                                    + (f"内容预览:\n{msg_preview}" if msg_preview else "")
                                ),
                                category="conversation",
                                valence=0.05, intensity=0.5,
                                influence="cross_version_session",
                                source=f"sync:{inst_name}:session:{original_id[:8]}",
                                timestamp=now,
                            )
                            memories_written += 1
                        except Exception:
                            pass

                if prog and sessions_synced:
                    prog.log_item(f"  导入了 {sessions_synced} 个会话")
            except Exception as e:
                if prog: prog.error(f"  会话同步失败: {e}")

            # ── Permanent memories (shadow) ───────────────────────────────────
            try:
                shadow_mems = conn.execute("""
                    SELECT content, timestamp, category, source, intensity
                    FROM memories
                    WHERE layer='shadow' OR permanent=1
                    ORDER BY timestamp DESC LIMIT 100
                """).fetchall()

                for m in shadow_mems:
                    ts = (m["timestamp"] or "")[:16]
                    # Import as activity
                    if session_manager:
                        try:
                            session_manager.import_cross_activity(
                                source_instance=inst_name,
                                source_version=inst_ver,
                                source_dir=inst_dir,
                                activity_type="permanent_memory",
                                content=m["content"] or "",
                                occurred_at=m["timestamp"],
                                category="memory",
                                detail=json.dumps({
                                    "source": m["source"],
                                    "category": m["category"],
                                }),
                            )
                            activities_synced += 1
                        except Exception:
                            pass
                    if memory_engine:
                        try:
                            memory_engine._write_permanent(
                                content=(
                                    f"[跨版本永久记忆] {inst_name} ({inst_ver}) {ts}\n"
                                    f"来源: {m['source'] or ''}\n"
                                    f"{m['content'][:400]}"
                                ),
                                category=m["category"] or "system",
                                valence=0.0, intensity=0.45,
                                influence="cross_version_memory",
                                source=f"sync:{inst_name}:shadow",
                                timestamp=now,
                            )
                            memories_written += 1
                        except Exception:
                            pass

                if prog and shadow_mems:
                    prog.log_item(f"  同步了 {len(shadow_mems)} 条永久记忆")
            except Exception:
                pass

            # ── System events / life events (activities) ──────────────────────
            for table_name in ["system_events", "log_index"]:
                try:
                    rows = conn.execute(f"""
                        SELECT * FROM {table_name} ORDER BY timestamp DESC LIMIT 200
                    """).fetchall()
                    for row in rows:
                        rd = dict(row)
                        content  = rd.get("detail") or rd.get("summary") or str(rd)
                        occurred = rd.get("timestamp") or ""
                        atype    = rd.get("event_type") or rd.get("domain") or table_name
                        if session_manager:
                            try:
                                session_manager.import_cross_activity(
                                    source_instance=inst_name,
                                    source_version=inst_ver,
                                    source_dir=inst_dir,
                                    activity_type=atype,
                                    content=content[:500],
                                    occurred_at=occurred,
                                    category="system",
                                )
                                activities_synced += 1
                            except Exception:
                                pass
                    if prog and rows:
                        prog.log_item(f"  同步了 {len(rows)} 条 {table_name}")
                except Exception:
                    pass

            # ── Version log ───────────────────────────────────────────────────
            try:
                ver_rows = conn.execute("""
                    SELECT version, applied_at, changes FROM version_log
                    ORDER BY applied_at DESC LIMIT 50
                """).fetchall()
                for row in ver_rows:
                    if session_manager:
                        try:
                            session_manager.import_cross_activity(
                                source_instance=inst_name,
                                source_version=inst_ver,
                                source_dir=inst_dir,
                                activity_type="version_update",
                                content=f"版本: {row['version']} | {row['changes'] or ''}",
                                occurred_at=row["applied_at"],
                                category="version",
                            )
                        except Exception:
                            pass
            except Exception:
                pass

            conn.close()
        except Exception as e:
            if prog:
                prog.error(f"  无法读取 {db_path}: {e}")

        return {
            "memories_written": memories_written,
            "sessions_synced":  sessions_synced,
            "activities_synced":activities_synced,
        }

    # ── Periodic ──────────────────────────────────────────────────────────────

    def should_daily_sync(self) -> bool:
        return self._last_daily != date.today()

    def should_random_sync(self) -> bool:
        return bool(self._next_random and datetime.utcnow() >= self._next_random)

    def quick_sync(self, memory_engine=None) -> dict:
        self._last_daily = date.today()
        self._schedule_next_random()
        instances = self.find_all_instances()
        written = 0
        for inst in instances:
            try:
                r = self._sync_instance_full(
                    inst["path"], inst["version"], inst["type"],
                    memory_engine, None,
                )
                written += r.get("memories_written", 0)
            except Exception:
                pass
        return {"instances": len(instances), "memories_written": written}

    def get_sync_progress(self) -> Optional[dict]:
        return self._sync_progress.to_dict() if self._sync_progress else None

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_history(self, limit: int = 20) -> list[dict]:
        try:
            with self._conn() as c:
                rows = c.execute("""
                    SELECT version,applied_at,type,changes
                    FROM version_log ORDER BY applied_at DESC LIMIT ?
                """, (limit,)).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                try:
                    d["changes"] = json.loads(d.get("changes") or "[]")
                except Exception:
                    d["changes"] = []
                result.append(d)
            return result
        except Exception:
            return []

    def get_known_instances(self) -> list[dict]:
        try:
            with self._conn() as c:
                rows = c.execute("""
                    SELECT * FROM known_instances ORDER BY last_seen DESC
                """).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                # Calculate human-readable runtime
                ticks = d.get("tick_count", 0) or 0
                total_s = ticks * 30  # each tick ~30 seconds
                h = total_s // 3600
                m = (total_s % 3600) // 60
                d["runtime_str"] = f"{h}h {m}m" if h > 0 else f"{m}m" if m > 0 else "—"
                d["existence_depth_pct"] = f"{(d.get('existence_depth',0) or 0)*100:.1f}%"
                result.append(d)
            return result
        except Exception:
            return []

    def get_sync_log(self, limit: int = 20) -> list[dict]:
        try:
            with self._conn() as c:
                rows = c.execute("""
                    SELECT synced_at,source_path,source_version,files_synced,action
                    FROM sync_log ORDER BY synced_at DESC LIMIT ?
                """, (limit,)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def version_info(self) -> dict:
        return {
            "current":          self.get_current_version(),
            "parsed":           _parse_version(self.get_current_version()),
            "next_would_be":    self.get_next_version(),
            "install_dir":      str(self.install_dir),
            "known_instances":  len(self.get_known_instances()),
            "last_sync":        self._last_daily.isoformat() if self._last_daily else None,
            "sync_in_progress": self._sync_progress is not None,
        }
