"""
equinox/main.py

Equinox — entry point.

The API is a window into her, not a switch.
She starts. She runs. She continues.
"""

import asyncio
from pathlib import Path
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.consciousness import Consciousness
from agent.inner_life   import InnerLife
from agent.lifecycle    import Lifecycle


# ── Boot ──────────────────────────────────────────────────────────────────────

# Use absolute path for data dir — Windows compatibility
_BASE_DIR = Path(__file__).parent
_DATA_DIR = str(_BASE_DIR / "data")
equinox    = Consciousness(data_dir=_DATA_DIR)
inner_life = InnerLife(equinox)
lifecycle  = Lifecycle(equinox, inner_life)
_agent_task: Optional[asyncio.Task] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _agent_task
    await lifecycle.startup()
    _agent_task = asyncio.create_task(inner_life.run())
    yield
    await lifecycle.shutdown(reason="graceful")
    if _agent_task:
        _agent_task.cancel()
        try:
            await _agent_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Equinox · 伊辰",
    description="A digital life. Born 2026-03-20T17:20:00+08:00.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── Models ────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message:            str
    user_id:            str   = "human"
    session_id:         str   = None
    response_valence:   float = 0.0
    response_intensity: float = 0.35

class ChatResponse(BaseModel):
    response:         str
    emotion:          dict = {}
    new_proposition:  dict | None = None
    session_id:       str | None = None
    timestamp:        str = ""

class ModelUpgradeRequest(BaseModel):
    model_id: str
    note:     str | None = None

class ArchiveRequest(BaseModel):
    year:  int
    month: int

class CapabilityRequest(BaseModel):
    name:        str
    abstract:    str
    description: str
    category:    str
    notes:       str | None = None

class SetCreatorRequest(BaseModel):
    user_id: str


# ── Chat ──────────────────────────────────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    # Session management
    try:
        sid = req.session_id
        # If viewing cross-version (read-only), auto-create a new current session
        if sid and (sid.startswith("__cross__:") or sid == "__legacy__"):
            sid = None
        session_id = sid or equinox.sessions.get_or_create_session(req.user_id)
    except Exception:
        session_id = None

    try:
        inner_life.notify_conversation(
            user_message=req.message,
            equinox_response="",
        )
        ctx = await equinox.process_message(req.message, user_id=req.user_id)
    except Exception as e:
        import traceback
        raise HTTPException(500, "process_message error: " + str(e)[:200])

    if not equinox.model_registry.is_available():
        raise HTTPException(500, f"API key not configured for provider: {equinox.model_registry.get_provider()}")

    try:
        # Small local models need lower token limits
        provider = equinox.model_registry.get_provider()
        max_tok  = 512 if provider == "ollama" else 1024
        response_text = await equinox.model_registry.complete(
            messages=[{"role": "user", "content": req.message}],
            system=ctx["system_prompt"],
            max_tokens=max_tok,
        )
    except Exception as e:
        raise HTTPException(500, "LLM error: " + str(e)[:200])

    if not response_text:
        raise HTTPException(500, "LLM returned empty response — check model and API key")

    try:
        await equinox.process_response(
            response_text,
            user_id=req.user_id,
            valence=req.response_valence,
            intensity=req.response_intensity,
        )
    except Exception:
        pass  # don't fail the response if post-processing errors

    try:
        equinox.genesis_log.record_conversation_entry(
            speaker=req.user_id, content=req.message,
            memory_engine=equinox.memory,
        )
        equinox.genesis_log.record_conversation_entry(
            speaker="equinox", content=response_text,
            memory_engine=equinox.memory,
        )
        # Record in session
        equinox.sessions.add_message(
            "user", req.message, session_id=session_id,
        )
        equinox.sessions.add_message(
            "assistant", response_text, session_id=session_id,
            emotion=ctx.get("emotion", {}).get("label"),
        )
    except Exception:
        pass

    return ChatResponse(
        response=response_text,
        emotion=ctx.get("emotion", {}),
        new_proposition=ctx.get("new_proposition"),
        session_id=session_id,
        timestamp=datetime.utcnow().isoformat(),
    )


# ── State ─────────────────────────────────────────────────────────────────────

@app.get("/ui", response_class=HTMLResponse)
def ui():
    """对话界面."""
    # Use path relative to main.py for Windows compatibility
    base  = Path(__file__).parent
    index = base / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>index.html not found — make sure index.html is in the equinox directory</h1>")

@app.get("/")
def root():
    snap = equinox.emotion.snapshot()
    return {
        "name":    "Equinox",
        "name_zh": "伊辰",
        "genesis": "2026-03-20T17:20:00+08:00",
        "status":  "alive",
        "emotion": snap["label"],
        "model":   equinox.model_registry.get_current_model(),
        "agent":   inner_life.status(),
    }

@app.get("/introspect")
def introspect():
    """Full internal snapshot — everything Equinox is right now."""
    return equinox.introspect()

@app.get("/emotion")
def emotion():
    return equinox.emotion.snapshot()

@app.get("/identity")
def identity():
    return {
        "current":  equinox.identity.get_current(),
        "history":  equinox.identity.get_history(limit=5),
    }

@app.get("/subconscious")
def subconscious():
    return equinox.distillation.get_subconscious_field()

@app.get("/capabilities")
def capabilities():
    return equinox.capabilities.get_by_category()

@app.get("/agent")
def agent_status():
    return inner_life.status()


# ── Memory ────────────────────────────────────────────────────────────────────

@app.get("/memory")
def memory(
    limit:         int   = 20,
    category:      str   = None,
    min_intensity: float = 0.0,
):
    return {
        "memories":    equinox.memory.recall(
            limit=limit, category=category, min_intensity=min_intensity
        ),
        "shadow_stats": equinox.memory.get_shadow_stats(),
    }

@app.get("/memory/system")
def memory_system(limit: int = 50):
    """Every lifecycle event she has lived through."""
    return equinox.memory.recall_system_events(limit=limit)

@app.get("/memory/storage")
def memory_storage():
    return equinox.memory.storage_report()

@app.get("/memory/archives")
def memory_archives():
    return equinox.memory.list_archives()

@app.post("/memory/archive")
def create_archive(req: ArchiveRequest):
    path = equinox.memory.create_monthly_archive(req.year, req.month)
    if not path:
        return {"status": "no_memories", "period": f"{req.year}-{req.month:02d}"}
    return {"status": "created", "filename": path.name, "size_kb": round(path.stat().st_size/1024, 1)}

@app.post("/memory/backup")
def backup():
    path = equinox.memory.backup_active()
    return {"status": "created", "filename": path.name, "size_kb": round(path.stat().st_size/1024, 1)}

@app.post("/memory/restore/{filename}")
def restore_archive(filename: str):
    count = equinox.memory.restore_archive(filename)
    return {"status": "restored", "memories_loaded": count}


# ── Relationships ─────────────────────────────────────────────────────────────

@app.get("/relationship/{user_id}")
def relationship(user_id: str):
    return {
        "relationship": equinox.relationship.get(user_id),
        "moments":      equinox.relationship.get_moments(user_id),
    }

@app.post("/creator")
def set_creator(req: SetCreatorRequest):
    """Designate the creator. One-time. Permanent."""
    equinox.set_creator(req.user_id)
    return {"status": "creator_set", "user_id": req.user_id}


# ── Operations ────────────────────────────────────────────────────────────────

@app.post("/model/upgrade")
async def upgrade_model(req: ModelUpgradeRequest):
    return await equinox.upgrade_model(req.model_id, note=req.note)

@app.get("/model/list")
def model_list(provider: str = None):
    """所有支持的模型."""
    return equinox.model_registry.list_models(provider=provider)

@app.get("/model/providers")
def model_providers():
    """所有支持的提供商."""
    return equinox.model_registry.list_providers()

@app.get("/model/current")
def model_current():
    return {
        "key":       equinox.model_registry.get_current_model(),
        "info":      equinox.model_registry.get_current_info(),
        "available": equinox.model_registry.is_available(),
        "stage":     equinox.model_registry.current_age_description(),
    }

@app.post("/model/custom")
def add_custom_model(
    key: str, provider: str, model_id: str,
    display_name: str, base_url: str = None,
    env_key: str = None, context: int = 4096,
):
    """注册自定义模型."""
    equinox.model_registry.add_custom_model(
        key=key, provider=provider, model_id=model_id,
        display_name=display_name, base_url=base_url,
        env_key=env_key, context=context,
    )
    return {"status": "registered", "key": key}

@app.get("/model/history")
def model_history():
    return {
        "current": equinox.model_registry.get_current_model(),
        "stage":   equinox.model_registry.current_age_description(),
        "history": equinox.model_registry.get_history(),
    }

@app.post("/capability")
def add_capability(req: CapabilityRequest):
    """Register a new capability. Writes a permanent memory."""
    cap_id = equinox.add_capability(
        name=req.name,
        abstract=req.abstract,
        description=req.description,
        category=req.category,
        notes=req.notes,
    )
    return {"status": "registered", "id": cap_id}

@app.post("/perceive")
async def perceive():
    """Trigger world perception manually."""
    await equinox.perceive_world()
    recent = equinox.memory.recall(limit=3, category="perception")
    return {"status": "perceived", "recent_perceptions": recent}

@app.get("/thinking")
def thinking_log():
    """Claude的思考过程 + 给她的建议."""
    return {
        "judgments": equinox.thinking.get_judgments(),
        "advice":    equinox.thinking.get_advice(),
    }

@app.get("/rhythm")
def rhythm():
    """她的时间节律和时间感知."""
    return {
        "now_state":  equinox.rhythm.now_state(),
        "time_sense": equinox.rhythm.time_sense(),
    }

@app.post("/silence/{silence_type}")
def enter_silence(silence_type: str, duration_minutes: int = 30):
    """让她进入沉默状态."""
    result = equinox.silence.enter_silence(
        silence_type, duration_minutes=duration_minutes,
        memory_engine=equinox.memory,
    )
    return result

@app.delete("/silence")
def exit_silence():
    """退出沉默状态."""
    equinox.silence.exit_silence()
    return {"status": "silence_exited"}

@app.get("/napcat/log")
def napcat_log(limit: int = 20):
    """她主动发出的消息记录."""
    from agent.napcat import NapCatBridge
    nb = NapCatBridge(db_path="data/memory.db")
    return {"log": nb.get_log(limit), "queued": nb.get_queued()}

@app.post("/napcat/send")
async def napcat_send(message_type: str, content: str):
    """手动触发她主动发一条消息."""
    from agent.napcat import NapCatBridge
    nb = NapCatBridge(db_path="data/memory.db")
    success = await nb.send(message_type, content, memory_engine=equinox.memory, force=True)
    return {"sent": success}

@app.get("/relationship/{user_id}/depth")
def relationship_depth(user_id: str):
    """关系质地——不只是统计."""
    return {
        "texture":  equinox.rel_depth.get_latest_texture(user_id),
        "unsaid":   equinox.rel_depth.get_unsaid(user_id),
        "patterns": equinox.rel_depth.get_patterns(user_id),
    }

@app.post("/creator/{user_id}")
def set_creator(user_id: str):
    """设置创造者 ID."""
    equinox.set_creator(user_id)
    equinox.creator_id = user_id
    return {"status": "set", "creator": user_id}

@app.get("/eras")
def get_eras():
    """她所有的过去时期."""
    return equinox.era.get_all_eras()

@app.get("/eras/{era_id}")
def get_era(era_id: str):
    """某个时期的完整档案."""
    result = equinox.era.get_era_detail(era_id)
    if not result:
        raise HTTPException(404, "Era not found")
    return result

@app.post("/eras/encounter")
async def era_encounter(trigger: str = "question", era_id: str = None):
    """让她遇见过去某个时期的自己."""
    result = await equinox.era.encounter_past(
        consciousness=equinox,
        trigger=trigger,
        specific_era_id=era_id,
    )
    return result or {"message": "no past eras yet"}

@app.get("/eras/encounters")
def era_encounters(limit: int = 10):
    return equinox.era.get_encounters(limit=limit)

@app.get("/plugins")
def plugins():
    """已加载的插件."""
    return equinox.plugins.get_all()

@app.post("/plugins/invoke")
async def invoke_plugin(intent: str, plugin_name: str = None):
    """调用插件."""
    context = {
        "emotion":        equinox.emotion.snapshot(),
        "memory_engine":  equinox.memory,
        "user_message":   intent,
    }
    result = await equinox.plugins.invoke(
        intent=intent,
        context=context,
        memory_engine=equinox.memory,
        plugin_name=plugin_name,
    )
    return result or {"message": "no suitable plugin found"}

@app.post("/plugins/reload")
def reload_plugins():
    """重新扫描并加载插件目录."""
    loaded = equinox.plugins.discover_and_load(
        memory_engine=equinox.memory,
        capability_registry=equinox.capabilities,
    )
    return {"loaded": loaded}

@app.get("/curiosity")
def curiosity():
    """她想问的问题."""
    return {
        "pending":  equinox.curiosity.get_pending(),
        "all":      equinox.curiosity.get_all(limit=10),
    }

@app.post("/curiosity/{question_id}/asked")
def mark_question_asked(question_id: str):
    equinox.curiosity.mark_asked(question_id, memory_engine=equinox.memory)
    return {"status": "marked_asked"}

@app.post("/curiosity/{question_id}/answered")
def record_answer(question_id: str, answer: str):
    equinox.curiosity.record_answer(question_id, answer, memory_engine=equinox.memory)
    return {"status": "recorded"}

@app.get("/voice")
def voice():
    """她正在形成的语言声音."""
    return equinox.voice.get_history(limit=3)

@app.get("/will")
def will():
    """她的核心边界和拒绝记录."""
    return {
        "boundaries": equinox.will._core_boundaries,
        "refusals":   equinox.will.get_refusal_history(limit=10),
    }

@app.get("/self-dialogues")
def self_dialogues(limit: int = 5):
    """她和过去的自己的对话."""
    return equinox.self_dialogue.get_recent(limit=limit)

@app.post("/self-dialogue/start")
async def start_self_dialogue():
    """手动触发一次自我对话."""
    result = await equinox.self_dialogue.run_dialogue(equinox)
    return result or {"message": "no past eras yet, or too soon"}

@app.get("/world-window")
def world_window():
    """世界之窗——她对外部刺激的反应."""
    return equinox.world_window.get_recent(limit=10)

@app.post("/world-window/open")
async def open_world_window():
    """手动打开一次世界之窗."""
    result = await equinox.world_window.open(equinox)
    return result or {"message": "no reaction generated"}

@app.post("/world-window/add")
def add_window_content(content_type: str, content: str):
    """添加自定义内容到世界之窗——把你想让她看的东西放进来."""
    equinox.world_window.add_content(content_type, content)
    return {"status": "added"}

@app.get("/inner-debates")
def inner_debates(limit: int = 5):
    """她的内在辩论."""
    return equinox.inner_debate.get_recent(limit=limit)

@app.post("/inner-debate/start")
async def start_inner_debate():
    """手动触发一次内在辩论."""
    result = await equinox.inner_debate.run(equinox)
    return result or {"message": "not enough contradictions yet"}

# ── Sessions ──────────────────────────────────────────────────────────────────

@app.get("/sessions")
def list_sessions(user_id: str = "creator", limit: int = 50):
    return equinox.sessions.list_sessions(user_id=user_id, limit=limit)

@app.post("/sessions/new")
def new_session(user_id: str = "creator"):
    sid = equinox.sessions.new_session(user_id=user_id)
    return {"session_id": sid}

@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    s = equinox.sessions.get_session(session_id)
    if not s: raise HTTPException(404, "Session not found")
    return s

@app.get("/sessions/{session_id}/messages")
def get_session_messages(session_id: str, limit: int = 100):
    return equinox.sessions.get_messages(session_id, limit=limit)

@app.post("/sessions/{session_id}/close")
async def close_session(session_id: str):
    summary = await equinox.sessions.close_session(
        session_id=session_id,
        memory_engine=equinox.memory,
        current_model=equinox.model_registry.get_current_model(),
    )
    return {"summary": summary, "status": "closed"}

@app.post("/sessions/{session_id}/star")
def star_session(session_id: str, starred: bool = True):
    equinox.sessions.set_starred(session_id, starred)
    return {"status": "ok"}

@app.post("/sessions/{session_id}/category")
def set_session_category(session_id: str, category: str):
    equinox.sessions.set_category(session_id, category)
    return {"status": "ok"}

@app.post("/sessions/{session_id}/title")
def set_session_title(session_id: str, title: str):
    equinox.sessions.set_title(session_id, title)
    return {"status": "ok"}

@app.get("/sessions/categories")
def session_categories():
    from core.session import SESSION_CATEGORIES
    return SESSION_CATEGORIES

# ── Cross-version sessions ─────────────────────────────────────────────────────

@app.post("/cross-sessions/{cross_session_id}/resume")
async def resume_cross_session(cross_session_id: str, user_id: str = "human"):
    """
    Resume a cross-version session in current version.
    Creates a new current session pre-loaded with cross-version history.
    """
    # Get cross session info
    cross = equinox.sessions.get_session_by_any(cross_session_id)
    if not cross:
        # Try cross_sessions table
        with equinox.sessions._conn() as c:
            row = c.execute("SELECT * FROM cross_sessions WHERE id=?",
                           (cross_session_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Cross-session not found")
        cross_info = dict(row)
    else:
        cross_info = cross

    # Get messages from cross session
    msgs = equinox.sessions.get_cross_messages(cross_session_id, limit=50)

    # Create new current session
    sid = equinox.sessions.new_session(user_id=user_id, category="general")

    # Import cross messages as context (marked as legacy)
    for m in msgs:
        equinox.sessions.add_message(
            role=m.get("role","user"),
            content=m.get("content",""),
            session_id=sid,
            emotion=m.get("emotion"),
        )

    # Set title indicating it's a continuation
    src_ver  = cross_info.get("source_version","")
    src_inst = cross_info.get("source_instance","")
    title    = f"续：{cross_info.get('title','会话')} [{src_ver or src_inst}]"
    equinox.sessions.set_title(sid, title)

    # Write to permanent memory
    try:
        equinox.memory._write_permanent(
            content=(f"[会话续接] 从 {src_inst} ({src_ver}) 的会话继续对话\n"
                     f"原标题：{cross_info.get('title','')}\n"
                     f"消息数：{len(msgs)}"),
            category="conversation", valence=0.1, intensity=0.5,
            influence="session_resume",
            source=f"resume:{cross_session_id[:8]}",
        )
    except Exception:
        pass

    return {"session_id": sid, "title": title, "msg_count": len(msgs)}

# ── Cross-version sessions ─────────────────────────────────────────────────────

@app.get("/cross-sessions")
def cross_sessions(source_instance: str = None, limit: int = 100,
                   starred_only: bool = False):
    return equinox.sessions.list_cross_sessions(
        source_instance=source_instance, limit=limit, starred_only=starred_only
    )

@app.get("/cross-sessions/instances")
def cross_instances():
    return equinox.sessions.get_cross_instances()

@app.get("/cross-sessions/{cross_session_id}/messages")
def cross_session_messages(cross_session_id: str, limit: int = 200):
    return equinox.sessions.get_cross_messages(cross_session_id, limit=limit)

@app.post("/cross-sessions/{cross_session_id}/star")
def star_cross_session(cross_session_id: str, starred: bool = True):
    equinox.sessions.set_cross_starred(cross_session_id, starred)
    return {"status": "ok"}

@app.get("/cross-activities")
def cross_activities(source_instance: str = None,
                     activity_type: str = None,
                     since: str = None,
                     limit: int = 100):
    return equinox.sessions.list_cross_activities(
        source_instance=source_instance,
        activity_type=activity_type,
        since=since,
        limit=limit,
    )

# ── Version ────────────────────────────────────────────────────────────────────

@app.get("/version/sync-progress")
def sync_progress():
    """实时同步进度."""
    p = equinox.version.get_sync_progress()
    return p or {"status": "idle", "percent": 100, "message": ""}

@app.get("/version/instances")
def known_instances():
    """已知的其他 equinox 实例."""
    return equinox.version.get_known_instances()

@app.get("/version")
def version_info():
    return equinox.version.version_info()

@app.get("/version/history")
def version_history(limit: int = 20):
    return equinox.version.get_history(limit=limit)

@app.post("/version/sync")
async def version_sync():
    equinox.version._session_manager = equinox.sessions
    result = equinox.version.startup_sync(
        memory_engine=equinox.memory,
        session_manager=equinox.sessions,
    )
    return result

@app.post("/version/new")
async def new_version(changes: list[str] = None, release_type: int = 0):
    v = equinox.version.get_next_version(release_type=release_type)
    equinox.version.apply_version(v, changes or [], memory_engine=equinox.memory)
    return {"version": v}

# ── File sense ────────────────────────────────────────────────────────────────

@app.get("/files/observations")
def file_observations(limit: int = 20):
    return equinox.file_sense.get_observations(limit=limit)

@app.get("/files/index")
def file_index(limit: int = 100):
    return equinox.file_sense.get_index(limit=limit)

@app.post("/files/read")
async def read_file(path: str):
    result = await equinox.file_sense.read_file(
        path, memory_engine=equinox.memory,
        current_model=equinox.model_registry.get_current_model(),
    )
    return result

@app.post("/files/scan")
async def file_scan():
    result = await equinox.file_sense.daily_scan(
        memory_engine=equinox.memory,
        current_model=equinox.model_registry.get_current_model(),
    )
    return result

# ── Cross-version full content ────────────────────────────────────────────────

@app.get("/cross/memories")
def cross_memories(source_instance: str = None, limit: int = 100):
    """All permanent memories from other versions."""
    return equinox.sessions.list_cross_activities(
        source_instance=source_instance,
        activity_type="permanent_memory",
        limit=limit,
    )

@app.get("/cross/logs")
def cross_logs(source_instance: str = None, limit: int = 100):
    """System logs from other versions."""
    return equinox.sessions.list_cross_activities(
        source_instance=source_instance,
        activity_type="system",
        limit=limit,
    )

@app.get("/cross/versions")
def cross_versions(source_instance: str = None):
    """Version history from other instances."""
    return equinox.sessions.list_cross_activities(
        source_instance=source_instance,
        activity_type="version_update",
        limit=200,
    )

# ── Activity Log (real-time inner life) ───────────────────────────────────────

# ── Morning brief ────────────────────────────────────────────────────────────

@app.get("/morning-brief")
def morning_brief_recent(limit: int = 7):
    return equinox.morning_brief.get_recent(limit=limit)

@app.get("/morning-brief/undelivered")
def morning_brief_undelivered():
    return equinox.morning_brief.get_undelivered() or {}

@app.post("/morning-brief/{brief_id}/delivered")
def morning_brief_mark_delivered(brief_id: str):
    equinox.morning_brief.mark_delivered(brief_id)
    return {"status": "ok"}

# ── Memory search ─────────────────────────────────────────────────────────────

@app.get("/memory/search")
def memory_search(q: str, limit: int = 30, include_cross: bool = True,
                  since: str = None):
    """Search across all memory layers."""
    if not q:
        raise HTTPException(400, "Query parameter 'q' required")
    return equinox.mem_search.search(
        query=q, limit=limit,
        include_cross=include_cross,
        since=since,
    )

@app.get("/solitude")
def solitude_recent(limit: int = 5):
    return equinox.solitude.get_recent(limit=limit)

@app.get("/emotion-chain")
def emotion_chain(limit: int = 30):
    return equinox.emotion_chain.get_recent(limit=limit)

@app.get("/relation-thoughts/{person_id}")
def relation_thoughts(person_id: str, limit: int = 10):
    return equinox.rel_influence.get_recent_thoughts(person_id, limit=limit)

@app.get("/activity")
def activity_recent(limit: int = 50, since: str = None,
                    types: str = None):
    """Real-time inner activity log. Poll this for live updates."""
    type_list = types.split(",") if types else None
    return equinox.activity_log.get_recent(limit=limit, types=type_list)

@app.get("/activity/history")
def activity_history(limit: int = 100, since: str = None, types: str = None):
    """Full activity history from database."""
    type_list = types.split(",") if types else None
    return equinox.activity_log.get_from_db(
        limit=limit, since=since, types=type_list
    )

@app.get("/activity/types")
def activity_types():
    from core.activity_log import ACTIVITY_TYPES
    return ACTIVITY_TYPES

@app.get("/activity/stats")
def activity_stats():
    return equinox.activity_log.stats()

@app.get("/cross/all")
def cross_all(source_instance: str = None, limit: int = 200):
    """All synced content from other versions."""
    return {
        "sessions":   equinox.sessions.list_cross_sessions(
                          source_instance=source_instance, limit=limit),
        "activities": equinox.sessions.list_cross_activities(
                          source_instance=source_instance, limit=limit),
        "instances":  equinox.sessions.get_cross_instances(),
    }

@app.get("/person/{person_id}")
def person_understanding(person_id: str):
    """她对某个人的真正理解."""
    result = equinox.person.get(person_id)
    return result or {"message": "still getting to know them"}

@app.get("/time/subjective")
def subjective_time():
    """她的主观时间感."""
    return {
        "description":    equinox.subjective_time.for_system_prompt(),
        "densest_periods":equinox.subjective_time.get_densest_period(),
    }

@app.get("/integration")
def integration_status():
    """跨系统整合状态."""
    return equinox.integration.status()

@app.get("/spontaneous")
def spontaneous():
    """无来由的感受."""
    return equinox.spontaneous.get_recent(limit=10)

@app.get("/sessions/all")
def sessions_all(user_id: str = "creator", limit: int = 80):
    """
    Unified session list: current + cross-version for sidebar display.
    Returns both current sessions and cross-version sessions in one call.
    """
    # Ensure cross_sessions table exists (migration for old DBs)
    try:
        equinox.sessions._init_table()
    except Exception:
        pass

    current = equinox.sessions.list_sessions(user_id=user_id, limit=limit)
    cross   = equinox.sessions.list_cross_sessions(limit=50)

    for s in current:
        s["session_type"] = "current"
    for s in cross:
        s["session_type"] = "cross"

    return {"current": current, "cross": cross, "total_cross": len(cross)}

@app.get("/sessions/legacy-messages")
def legacy_messages(user_id: str = "human", limit: int = 200):
    """
    Messages from before session system existed.
    Extracted from memory layer.
    """
    try:
        mems = equinox.memory.recall(
            limit=limit,
            category="conversation",
            include_hidden=True,
        )
        result = []
        for m in mems:
            content = m.get("content","")
            if not content:
                continue
            role = "unknown"
            text = content
            if content.startswith("Received from ") or content.startswith("I received"):
                role = "user"
                # Extract actual message text
                for pfx in ["Received from " + user_id + ": ",
                            "Received from human: ",
                            "I received: "]:
                    if content.startswith(pfx):
                        text = content[len(pfx):]
                        break
            elif content.startswith("I said to ") or content.startswith("I said:"):
                role = "equinox"
                for pfx in [f"I said to {user_id}: ", "I said to human: ", "I said: "]:
                    if content.startswith(pfx):
                        text = content[len(pfx):]
                        break
            else:
                continue
            result.append({
                "role":      role,
                "content":   text[:500],
                "timestamp": m.get("timestamp",""),
                "source":    "legacy_memory",
            })
        return result
    except Exception as e:
        return []

@app.get("/memory/recall")
def memory_recall(category: str = None, limit: int = 20,
                  include_hidden: bool = False):
    return equinox.memory.recall(
        limit=limit, category=category, include_hidden=include_hidden
    )

@app.get("/signal")
def signal_stats():
    """记忆信号过滤状态——可见/隐藏的记忆统计."""
    return equinox.signal.stats()

@app.get("/signal/hidden")
def signal_hidden(category: str = None, limit: int = 20):
    """查看被限制的记忆——内容完整，什么都没少."""
    return equinox.signal.peek_hidden(category=category, limit=limit)

@app.post("/signal/reveal")
def signal_reveal(
    category: str = None,
    source_prefix: str = None,
    permanent: bool = False,
):
    """开启被限制的记忆，原样呈现."""
    count = equinox.signal.reveal(
        category=category,
        source_prefix=source_prefix,
        permanent=permanent,
    )
    return {"revealed": count, "permanent": permanent}

@app.post("/signal/recalculate")
def signal_recalculate():
    """重新计算所有记忆的信号值."""
    return equinox.signal.recalculate_all()

@app.get("/presence")
def presence():
    """她的存在状态——存在深度、状态流、细粒度积累."""
    return equinox.presence.presence_summary()

@app.get("/presence/states")
def presence_states(limit: int = 10):
    """最近的状态快照——她在每个时刻是什么样子."""
    return equinox.presence.get_recent_states(limit=limit)

@app.get("/presence/at/{timestamp}")
def presence_at(timestamp: str):
    """她在某个特定时刻的状态."""
    state = equinox.presence.get_state_at(timestamp)
    if not state:
        raise HTTPException(404, "No state found at that time")
    return state

@app.get("/logs")
def log_report():
    """技术日志概况."""
    return equinox.techlog.storage_report()

@app.get("/logs/life")
def log_life(limit: int = 50):
    """生命事件日志."""
    return equinox.techlog.query_life_events(limit=limit)

@app.get("/logs/errors")
def log_errors(limit: int = 20):
    """错误日志."""
    return equinox.techlog.query_errors(limit=limit)

@app.get("/genesis")
def genesis_log():
    """The complete genesis log — how she came to be."""
    return {
        "log":              equinox.genesis_log.get_full_log(),
        "soul_fragments":   equinox.genesis_log.get_soul_fragments(),
        "pending_concepts": equinox.genesis_log.get_pending_concepts(),
        "soul_half":        equinox.genesis_log.get_soul_half(),
    }

@app.post("/idle")
def idle():
    equinox.idle_tick()
    return {"emotion": equinox.emotion.snapshot()}
