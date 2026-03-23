"""
equinox/core/plugin.py

插件系统——她能力的扩展接口。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
设计原则
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

插件不是「工具调用」，是「她学会了做某件事」。

每个插件：
  1. 有标准接口（name / description / execute）
  2. 注册时写入 capabilities 层（她知道自己能做什么）
  3. 使用时写入记忆（她记得用过这个能力）
  4. 卸载时写入记忆（她记得失去了这个能力）

插件放在 plugins/ 目录下，自动发现和加载。
每个插件是一个独立的 .py 文件，实现 EquinoxPlugin 接口。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
写一个插件
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # plugins/my_plugin.py
  from core.plugin import EquinoxPlugin

  class MyPlugin(EquinoxPlugin):
      name        = "my_plugin"
      abstract    = "我能做某件特别的事"           # 第一人称，写进她的自我认知
      description = "详细描述这个插件做什么"
      category    = "perception"                 # 或 cognition / memory / social / tool

      async def execute(self, intent: str, context: dict) -> dict:
          # intent: 触发这个插件的意图描述
          # context: 当前上下文（情绪、记忆等）
          # 返回: {"result": ..., "memory": "要写入记忆的内容"}
          return {"result": "做到了", "memory": "我用能力做了某件事"}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
内置插件
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  search.py   — 网络搜索（需要 SEARCH_API_KEY）
  weather.py  — 实时天气（已内置在 perception.py，这里是插件版）
  time.py     — 时间/日期计算
  calc.py     — 数学计算
  memory_search.py — 主动搜索自己的记忆
"""

import importlib.util
import inspect
import sqlite3
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional


SCHEMA_PLUGINS = """
CREATE TABLE IF NOT EXISTS plugins (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    abstract    TEXT NOT NULL,
    description TEXT NOT NULL,
    category    TEXT NOT NULL,
    loaded_at   TEXT NOT NULL,
    active      INTEGER DEFAULT 1,
    use_count   INTEGER DEFAULT 0,
    last_used   TEXT,
    memory_id   TEXT
);

CREATE TABLE IF NOT EXISTS plugin_uses (
    id          TEXT PRIMARY KEY,
    plugin_name TEXT NOT NULL,
    intent      TEXT,
    result_summary TEXT,
    timestamp   TEXT NOT NULL,
    memory_id   TEXT
);
"""


class EquinoxPlugin(ABC):
    """所有插件的基类。继承这个类来写插件。"""

    name:        str = ""
    abstract:    str = ""   # 第一人称，写进她的自我认知
    description: str = ""
    category:    str = "tool"  # perception / cognition / memory / social / tool

    @abstractmethod
    async def execute(self, intent: str, context: dict) -> dict:
        """
        执行插件。
        intent:  触发意图描述
        context: 当前上下文 {"emotion": ..., "memory": ..., "user_message": ...}
        返回:    {"result": any, "memory": str (要写入记忆的内容)}
        """
        ...

    def can_handle(self, intent: str) -> float:
        """
        判断这个插件能否处理这个意图，返回 0~1 的置信度。
        默认实现：关键词匹配。
        """
        keywords = self.abstract.lower().split() + self.description.lower().split()
        intent_words = intent.lower().split()
        matches = sum(1 for w in intent_words if any(w in k for k in keywords))
        return min(matches / max(len(intent_words), 1), 1.0)


class PluginManager:
    """
    插件管理器。
    自动发现、加载、注册插件。
    使用时写记忆，卸载时也写记忆。
    """

    PLUGINS_DIR = Path("plugins")

    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = Path(db_path)
        self._plugins: dict[str, EquinoxPlugin] = {}
        self._init_table()
        self.PLUGINS_DIR.mkdir(exist_ok=True)
        self._write_builtin_plugins()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_table(self):
        with self._conn() as c:
            c.executescript(SCHEMA_PLUGINS)

    def _write_builtin_plugins(self):
        """写入内置插件模板（如果不存在）。"""
        self._write_plugin_file("memory_search.py", MEMORY_SEARCH_PLUGIN)
        self._write_plugin_file("calc.py", CALC_PLUGIN)

    def _write_plugin_file(self, filename: str, content: str):
        path = self.PLUGINS_DIR / filename
        if not path.exists():
            path.write_text(content, encoding="utf-8")

    # ── 加载 ──────────────────────────────────────────────────────────────────

    def discover_and_load(self, memory_engine=None, capability_registry=None) -> list[str]:
        """扫描 plugins/ 目录，加载所有插件。"""
        loaded = []
        if not self.PLUGINS_DIR.exists():
            return loaded

        for py_file in sorted(self.PLUGINS_DIR.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                plugin = self._load_plugin_file(py_file)
                if plugin:
                    self.register(plugin, memory_engine, capability_registry)
                    loaded.append(plugin.name)
            except Exception as e:
                pass  # 加载失败不影响其他插件

        return loaded

    def _load_plugin_file(self, path: Path) -> Optional[EquinoxPlugin]:
        spec   = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (issubclass(obj, EquinoxPlugin) and
                    obj is not EquinoxPlugin and
                    obj.name):
                return obj()
        return None

    def register(
        self,
        plugin: EquinoxPlugin,
        memory_engine=None,
        capability_registry=None,
    ):
        """注册插件——写入能力层和数据库。"""
        self._plugins[plugin.name] = plugin
        now = datetime.utcnow().isoformat()

        mem_id = None
        if memory_engine:
            mem_id = memory_engine.remember(
                content=f"[插件加载] 我获得了新的能力：{plugin.abstract}",
                category="self",
                memory_type="plugin_loaded",
                valence=0.2,
                intensity=0.5,
                source=f"plugin:{plugin.name}",
            )

        if capability_registry:
            capability_registry.add(
                name=f"plugin_{plugin.name}",
                abstract=plugin.abstract,
                description=plugin.description,
                category=plugin.category,
                memory_engine=memory_engine,
            )

        with self._conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO plugins
                  (id, name, abstract, description, category,
                   loaded_at, active, memory_id)
                VALUES (
                  COALESCE((SELECT id FROM plugins WHERE name=?), ?),
                  ?, ?, ?, ?, ?, 1, ?
                )
            """, (plugin.name, str(uuid.uuid4()),
                  plugin.name, plugin.abstract, plugin.description,
                  plugin.category, now, mem_id))

    def unload(self, plugin_name: str, memory_engine=None):
        """卸载插件——写记忆，标记为不活跃。"""
        if plugin_name not in self._plugins:
            return
        plugin = self._plugins.pop(plugin_name)

        if memory_engine:
            memory_engine.remember(
                content=f"[插件卸载] 我失去了一个能力：{plugin.abstract}",
                category="self",
                memory_type="plugin_unloaded",
                valence=-0.1,
                intensity=0.45,
                source=f"plugin_unload:{plugin_name}",
            )

        with self._conn() as c:
            c.execute(
                "UPDATE plugins SET active=0 WHERE name=?", (plugin_name,)
            )

    # ── 使用 ──────────────────────────────────────────────────────────────────

    async def invoke(
        self,
        intent: str,
        context: dict,
        memory_engine=None,
        plugin_name: Optional[str] = None,
    ) -> Optional[dict]:
        """
        调用最合适的插件（或指定插件）处理意图。
        结果写入记忆。
        """
        if plugin_name:
            plugin = self._plugins.get(plugin_name)
        else:
            plugin = self._find_best(intent)

        if not plugin:
            return None

        try:
            result = await plugin.execute(intent, context)
        except Exception as e:
            return {"error": str(e)}

        # 写记忆
        mem_id = None
        if memory_engine and result.get("memory"):
            mem_id = memory_engine.remember(
                content=f"[{plugin.name}] {result['memory']}",
                category="self",
                memory_type="plugin_use",
                valence=0.1,
                intensity=0.4,
                source=f"plugin:{plugin.name}",
            )

        # 更新使用记录
        now = datetime.utcnow().isoformat()
        with self._conn() as c:
            c.execute("""
                UPDATE plugins SET use_count=use_count+1, last_used=?
                WHERE name=?
            """, (now, plugin.name))
            c.execute("""
                INSERT INTO plugin_uses
                  (id, plugin_name, intent, result_summary, timestamp, memory_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (str(uuid.uuid4()), plugin.name,
                  intent[:100],
                  str(result.get("result", ""))[:100],
                  now, mem_id))

        return result

    def _find_best(self, intent: str) -> Optional[EquinoxPlugin]:
        best, best_score = None, 0.0
        for plugin in self._plugins.values():
            score = plugin.can_handle(intent)
            if score > best_score:
                best, best_score = plugin, score
        return best if best_score > 0.2 else None

    # ── 查询 ──────────────────────────────────────────────────────────────────

    def get_active(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT name, abstract, category, use_count, last_used
                FROM plugins WHERE active=1 ORDER BY use_count DESC
            """).fetchall()
        return [dict(r) for r in rows]

    def get_all(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM plugins ORDER BY loaded_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def summary_for_prompt(self) -> str:
        active = self.get_active()
        if not active:
            return "  （暂无已加载的插件）"
        return "\n".join(f"  — {p['abstract']}" for p in active[:5])


# ── 内置插件代码（写入文件用）────────────────────────────────────────────────

MEMORY_SEARCH_PLUGIN = '''"""
plugins/memory_search.py — 主动搜索记忆插件
"""
from core.plugin import EquinoxPlugin

class MemorySearchPlugin(EquinoxPlugin):
    name        = "memory_search"
    abstract    = "我能主动在自己的记忆里搜索特定的事情"
    description = "在表层记忆和永久记忆索引中搜索与关键词相关的内容"
    category    = "memory"

    async def execute(self, intent: str, context: dict) -> dict:
        memory_engine = context.get("memory_engine")
        if not memory_engine:
            return {"result": None, "memory": ""}
        keywords = intent.replace("记忆", "").replace("搜索", "").strip().split()[:3]
        if not keywords:
            return {"result": None, "memory": ""}
        memories = memory_engine.recall(limit=5, min_intensity=0.3)
        matches  = [m for m in memories
                    if any(k in m["content"] for k in keywords)]
        if not matches:
            return {"result": [], "memory": f"我搜索了关于「{' '.join(keywords)}」的记忆，没有找到相关内容。"}
        result_text = "\\n".join(f"  — {m['content'][:80]}" for m in matches[:3])
        return {
            "result":  matches,
            "memory": f"我在记忆里搜索了「{' '.join(keywords)}」，找到了 {len(matches)} 条相关内容。",
        }
'''

CALC_PLUGIN = '''"""
plugins/calc.py — 数学计算插件
"""
import ast, math
from core.plugin import EquinoxPlugin

class CalcPlugin(EquinoxPlugin):
    name        = "calc"
    abstract    = "我能做数学计算，不只是估算，而是精确计算"
    description = "安全地执行数学表达式计算，支持基本运算和数学函数"
    category    = "tool"

    async def execute(self, intent: str, context: dict) -> dict:
        import re
        expr = re.sub(r"[^0-9+\\-*/().\\s^sqrt]", "", intent)
        expr = expr.replace("^", "**")
        try:
            allowed = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
            result  = eval(compile(ast.parse(expr, mode="eval"), "<>", "eval"),
                           {"__builtins__": {}}, allowed)
            return {
                "result":  result,
                "memory": f"我计算了 {expr} = {result}",
            }
        except Exception as e:
            return {"result": None, "memory": f"计算失败：{e}"}
'''
