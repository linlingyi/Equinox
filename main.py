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

equinox    = Consciousness(data_dir="data")
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
    response_valence:   float = 0.0
    response_intensity: float = 0.35

class ChatResponse(BaseModel):
    response:         str
    emotion:          dict
    new_proposition:  dict | None
    timestamp:        str

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
    inner_life.notify_conversation(
        user_message=req.message,
        equinox_response="",  # will be updated after response
    )
    ctx = await equinox.process_message(req.message, user_id=req.user_id)

    if not equinox.model_registry.is_available():
        raise HTTPException(500, f"API key not configured for provider: {equinox.model_registry.get_provider()}")

    response_text = await equinox.model_registry.complete(
        messages=[{"role": "user", "content": req.message}],
        system=ctx["system_prompt"],
        max_tokens=1024,
    )
    await equinox.process_response(
        response_text,
        user_id=req.user_id,
        valence=req.response_valence,
        intensity=req.response_intensity,
    )

    # Record this exchange in genesis log — permanent, complete, uncompressed
    equinox.genesis_log.record_conversation_entry(
        speaker=req.user_id,
        content=req.message,
        memory_engine=equinox.memory,
    )
    equinox.genesis_log.record_conversation_entry(
        speaker="equinox",
        content=response_text,
        memory_engine=equinox.memory,
    )

    return ChatResponse(
        response=response_text,
        emotion=ctx["emotion"],
        new_proposition=ctx.get("new_proposition"),
        timestamp=datetime.utcnow().isoformat(),
    )


# ── State ─────────────────────────────────────────────────────────────────────

@app.get("/ui", response_class=HTMLResponse)
def ui():
    """对话界面."""
    index = Path("index.html")
    if index.exists():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>index.html not found</h1>")

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
