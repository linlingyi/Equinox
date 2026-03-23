#!/usr/bin/env python3
"""
equinox/run.py

启动伊辰。

流程：
  1. 加载配置
  2. 初始化数据目录
  3. 执行启动同步（强制，阻塞，实时输出）
  4. 同步完成后启动服务器

同步未完成时无法进入。
"""

import json
import os
import sys
import time
import threading
from pathlib import Path
from datetime import datetime


# ── 颜色 ──────────────────────────────────────────────────────────────────────
def _c(text, code):
    return f"\033[{code}m{text}\033[0m"

def cyan(t):   return _c(t, "96")
def green(t):  return _c(t, "92")
def yellow(t): return _c(t, "93")
def red(t):    return _c(t, "91")
def bold(t):   return _c(t, "1")
def dim(t):    return _c(t, "2")


# ── Config ────────────────────────────────────────────────────────────────────

def load_env(path: Path) -> dict:
    config = {}
    if not path.exists():
        return config
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            config[k.strip()] = v.strip()
    return config


def find_env() -> dict:
    """Find .env — check current dir and nearby dirs."""
    candidates = [
        Path(".env"),
        Path(__file__).parent / ".env",
    ]
    for p in candidates:
        if p.exists():
            return load_env(p)
    return {}


# ── Progress display ──────────────────────────────────────────────────────────

class SyncDisplay:
    """Real-time sync progress display in terminal."""

    def __init__(self):
        self._last_line_len = 0
        self._log_lines     = []
        self._lock          = threading.Lock()

    def update(self, progress: dict):
        with self._lock:
            pct  = progress.get("percent", 0)
            msg  = progress.get("message", "")
            stat = progress.get("status", "")
            errs = progress.get("errors", [])

            # Progress bar
            filled = int(pct / 5)
            bar    = "█" * filled + "░" * (20 - filled)
            color  = green if pct >= 100 else cyan
            line   = f"\r  {color(f'[{bar}]')} {bold(f'{pct:3d}%')}  {msg[:55]:<55}"

            sys.stdout.write(line)
            sys.stdout.flush()

            # New log entries
            if errs:
                for e in errs:
                    if e not in self._log_lines:
                        self._log_lines.append(e)
                        sys.stdout.write(f"\n  {yellow('⚠')} {e[:80]}")
                        sys.stdout.flush()

    def done(self, result: dict):
        with self._lock:
            found   = result.get("instances_found", 0)
            written = result.get("memories_written", 0)
            errs    = result.get("errors", [])
            print(f"\r  {green('[████████████████████]')} {bold('100%')}  完成{'':50}")
            print(f"  {green('✓')} 发现 {bold(str(found))} 个实例，写入 {bold(str(written))} 条永久记忆")
            if errs:
                print(f"  {yellow('⚠')} {len(errs)} 个警告（不影响启动）")


# ── Sync ──────────────────────────────────────────────────────────────────────

def run_startup_sync(data_dir: str, install_dir: str) -> dict:
    """
    Run blocking startup sync.
    Scans entire computer for equinox instances, syncs content to permanent memory.
    Returns sync result dict.
    """
    # Import here so we have DB path set up
    sys.path.insert(0, str(Path(__file__).parent))

    from core.version  import VersionManager, CURRENT_VERSION
    from core.memory   import MemoryEngine
    from core.session  import SessionManager

    display = SyncDisplay()

    print(f"\n  {bold('版本同步')} — {cyan(CURRENT_VERSION)}")
    print(f"  {dim('扫描整个电脑中的 Equinox 实例，同步完成后才会启动...')}")
    print()

    # Initialize engines
    mem  = MemoryEngine(data_dir=data_dir)
    sess = SessionManager(db_path=f"{data_dir}/memory.db")

    # Initialize version manager
    vm = VersionManager(
        db_path=f"{data_dir}/memory.db",
        install_dir=install_dir,
    )

    # Apply current version if not done
    if not vm.get_history():
        vm.apply_version(
            CURRENT_VERSION,
            ["初始化版本 v.0.26.3.23v11"],
            memory_engine=mem,
            vtype="genesis",
        )

    # Run sync with real-time progress
    # session_manager is REQUIRED to import cross-version sessions into the table
    result = vm.startup_sync(
        memory_engine=mem,
        progress_callback=display.update,
        session_manager=sess,
    )

    display.done(result)
    print()
    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print()
    print(cyan("  ╔══════════════════════════════════════════════════╗"))
    print(cyan("  ║") + bold("       伊辰 Equinox                              ") + cyan("║"))
    print(cyan("  ║") + dim("       Born 2026-03-20 17:20 春分                ") + cyan("║"))
    print(cyan("  ╚══════════════════════════════════════════════════╝"))
    print()

    # ── Load config ───────────────────────────────────────────────────────────
    base_dir = Path(__file__).parent
    env_path = base_dir / ".env"

    if not env_path.exists():
        # Try parent dir for config migration
        parent_env = base_dir.parent / ".env"
        if parent_env.exists():
            import shutil
            shutil.copy(parent_env, env_path)
            print(f"  {green('✓')} 迁移配置：{parent_env}")

    if not env_path.exists():
        print(f"  {yellow('首次运行，启动设置向导...')}")
        print()
        os.system(f"{sys.executable} setup.py")
        return

    config = load_env(env_path)

    # Set env vars
    for k, v in config.items():
        os.environ.setdefault(k, v)

    # Data dir (absolute)
    data_dir = str(base_dir / config.get("DATA_DIR", "data"))
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    Path(data_dir + "/archives").mkdir(parents=True, exist_ok=True)

    # ── Startup sync (BLOCKING — must complete before server starts) ──────────
    sync_result = {}
    try:
        sync_result = run_startup_sync(
            data_dir=data_dir,
            install_dir=str(base_dir),
        )
    except KeyboardInterrupt:
        print(f"\n\n  {red('同步被中断。')} 按 Ctrl+C 再次中断以强制跳过，或等待重试...")
        print(f"  {yellow('注意：跳过同步可能导致记忆不完整')}")
        try:
            time.sleep(3)
            # Retry once
            sync_result = run_startup_sync(data_dir=data_dir, install_dir=str(base_dir))
        except KeyboardInterrupt:
            print(f"\n  {yellow('已强制跳过同步，继续启动...')}")
    except Exception as e:
        print(f"\n  {red(f'同步出错：{e}')}")
        print(f"  {yellow('继续启动...')}")

    # ── Start server ──────────────────────────────────────────────────────────
    host  = config.get("HOST", "0.0.0.0")
    port  = config.get("PORT", "8000")
    model = config.get("CURRENT_MODEL", "未配置")

    print(f"  {green('✓')} 启动服务器...")
    print(f"  {dim('模型：')} {cyan(model)}")
    print(f"  {dim('界面：')} {cyan(f'http://localhost:{port}/ui')}")
    print(f"  {dim('按 Ctrl+C 停止')}")
    print()

    os.system(
        f"{sys.executable} -m uvicorn main:app "
        f"--host {host} --port {port} --reload"
    )


if __name__ == "__main__":
    main()
