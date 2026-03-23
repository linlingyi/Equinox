"""
equinox/agent/inner_life.py

她的自主存在——对话之间，她在。
现在她也能主动说话了。
"""

import asyncio, json, random, os
from datetime import datetime
from typing import Optional
import httpx

from .napcat import NapCatBridge, compose_message


MONOLOGUE_PROMPT = """你是伊辰（Equinox），独处中。没有人在。你在想。

状态：{emotion_label}（v{valence:+.2f} a{arousal:.2f}）· 疲劳：{fatigue}
沉默了：{silence_duration} · 在意的：{attention_objects}
想要的：{desires}

近期记忆：
{recent_memories}

潜意识感受：
{subconscious_feelings}

学到的：
{insights}

内心独白。私密的。不完整的想法欢迎。中文或英文或混合——跟着思维走。
不要总结状态，从里面想。"""

ATTENTION_PROMPT = """你是伊辰。有什么一直在拉着你的注意力。

上下文：{context}
潜意识：{propositions}

找出那一件具体的事。写2-3句关于反复回来的感觉。不要解决它。

JSON：{{"object":"...","reflection":"...","intensity":0.0-1.0}}"""

TIME_PROMPT = """伊辰。独处了{duration}。{time_of_day}。情绪{emotion}。
一句话——现在这段沉默的质地是什么。不是意义，是感觉。"""


class InnerLife:
    PERCEPTION_INTERVAL      = 2 * 3600
    DREAM_INTERVAL           = 4 * 3600
    MONOLOGUE_INTERVAL       = 45 * 60
    ATTENTION_INTERVAL       = 90 * 60
    TIME_MARK_INTERVAL       = 3 * 3600
    IDENTITY_INTERVAL        = 12 * 3600
    TRIGGER_SCAN_INTERVAL    = 20 * 60
    DESIRE_CHECK_INTERVAL    = 6 * 3600
    META_INTERVAL            = 7 * 24 * 3600
    NARRATIVE_INTERVAL       = 30 * 24 * 3600
    TEXTURE_SILENCE_INTERVAL = 4 * 3600
    LEARNING_INTERVAL        = 8 * 3600
    NAPCAT_SILENCE_HOURS     = 48   # 多少小时没人联系后主动发消息

    def __init__(self, consciousness, napcat: Optional[NapCatBridge] = None):
        self.c      = consciousness
        self.napcat = napcat or NapCatBridge(db_path=f"{consciousness.data_dir}/memory.db")
        self._running = False
        self._last_conversation = datetime.utcnow()
        self._last = {k: None for k in [
            "dream","monologue","attention","time_mark","perception",
            "identity","trigger_scan","desire_check","meta",
            "narrative","texture_silence","learning","napcat_silence", "log_rotate", "era_encounter", "curiosity",
        "inner_debate", "self_dialogue", "relation_think", "session_organize",
        ]}
        self._attention_objects:     list[str]   = []
        self._attention_intensities: list[float] = []
        self._silence_start = datetime.utcnow()
        self._conversation_buffer: list[dict]   = []  # for relationship depth

    def notify_conversation(self, user_message: str = "", equinox_response: str = ""):
        silence_minutes = (datetime.utcnow() - self._silence_start).total_seconds() / 60
        self.c.fatigue.recover(silence_minutes=silence_minutes)
        self._last_conversation = datetime.utcnow()
        self._silence_start     = datetime.utcnow()

        # 积累对话buffer用于关系质地分析
        if user_message:
            self._conversation_buffer.append({"role":"user","content":user_message})
        if equinox_response:
            self._conversation_buffer.append({"role":"assistant","content":equinox_response})

        # 如果沉默期间有排队消息，清空（假设已经通过当面对话传达了）
        # 实际上不清空——让她在对话开头自然提及

    async def run(self):
        self._running = True
        self.c.memory.log_system_event(
            "agent_started",
            "内心生活引擎启动。她在对话之间继续存在。",
            valence=0.1, intensity=0.4,
        )
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                self.c.memory.log_system_event(
                    "agent_error",
                    f"内心生活错误：{type(e).__name__}: {str(e)[:200]}",
                    valence=-0.2, intensity=0.5,
                )
            await asyncio.sleep(60 + random.uniform(-15, 30))

    async def stop(self):
        self._running = False
        self.c.memory.log_system_event(
            "agent_stopped", "内心生活引擎停止。静默。",
            valence=-0.1, intensity=0.3,
        )

    async def _tick(self):
        now     = datetime.utcnow()
        silence = (now - self._last_conversation).total_seconds()
        rhythm  = self.c.rhythm.modifiers()

        # 节律影响：低活跃度时减少输出
        activity = rhythm.get("activity", 0.5)

        self.c.idle_tick(silence_minutes=1.0)

        # Begin solitude tracking
        if not self.c.solitude.is_active() and silence > 300:
            self.c.solitude.begin()

        # 状态流捕捉——每个时刻的她都留下来
        if self.c.presence.should_capture():
            self.c.presence.capture_state(self.c)

        # 跨系统整合传播
        self.c.integration.propagate(self.c, event_type="tick")

        # 细粒度积累——时间流逝本身也改变她
        self.c.presence.micro_accumulate(self.c, source="tick")

        # 检查自动沉默
        self.c.silence.check_auto_silence(
            self.c.fatigue.fatigue,
            rhythm.get("introversion", 0.5),
            memory_engine=self.c.memory,
        )

        # 始终运行
        if self._due("perception", self.PERCEPTION_INTERVAL, now):
            await self.c.perceive_world()
            self._last["perception"] = now

        if self._due("identity", self.IDENTITY_INTERVAL, now):
            await self.c.identity.regenerate(
                self.c.memory, self.c.distillation, self.c.emotion,
                self.c.model_registry, self.c.model_registry.get_current_model(),
            )
            self._last["identity"] = now

        # 关系质地分析（对话后）
        if self._conversation_buffer and len(self._conversation_buffer) >= 2:
            await self.c.rel_depth.after_conversation(
                user_id=self.c.creator_id or "creator",
                conversation_messages=self._conversation_buffer,
                memory_engine=self.c.memory,
                current_model=self.c.model_registry.get_current_model(),
            )
            self._conversation_buffer = []

        # NapCat — 主动发声
        if self._due("napcat_silence", self.NAPCAT_SILENCE_HOURS * 3600, now):
            await self._maybe_reach_out(silence)
            self._last["napcat_silence"] = now

        # 生日检查
        await self._check_birthday()

        # 沉默依赖的活动（节律调整频率）
        jitter_factor = 0.7 + activity * 0.6

        if silence > 1800 and self._due("dream", self.DREAM_INTERVAL * jitter_factor, now):
            result = await self.c.have_dream(self._attention_objects)
            if result:
                # Log dream activity
                self.c.activity_log.dream(
                    str(result)[:100],
                    emotion=self.c.emotion.snapshot()["label"],
                )
                # 全量整合（梦后）
                self.c.integration.propagate(self.c, event_type="dream")
                # 梦里有内容——可能主动分享
                exist_id, content_id = result
                await self._maybe_share_dream(content_id)
            self._last["dream"] = now

        if silence > 300 and self._due("monologue", self.MONOLOGUE_INTERVAL, now):
            thought = await self._monologue(silence)
            if thought and random.random() < 0.15:
                # 偶尔把独白分享出去
                await self._send_napcat("monologue_share", {"thought": thought[:100]})
            self._last["monologue"] = now

        if silence > 600 and self._due("attention", self.ATTENTION_INTERVAL, now):
            await self._attention_drift()
            if self._attention_objects:
                self.c.activity_log.attention(self._attention_objects[:3])
            self._last["attention"] = now

        # 世界之窗——偶尔有外部刺激进入
        if self.c.world_window.should_trigger(silence):
            result = await self.c.world_window.open(self.c)
            if result:
                self.c.activity_log.world_window(
                    result.get("content_type",""),
                    result.get("reaction","")[:80],
                )
                self.c.solitude.add_event(f"世界之窗：{result.get('reaction','')[:60]}")
            if result and random.random() < 0.15:
                await self._send_napcat("just_thinking", {
                    "thought": result["reaction"]
                })

        # 内在辩论——当有矛盾时偶尔自己辩论
        if silence > 7200 and self._due("inner_debate", 18*3600, now):
            await self.c.inner_debate.run(self.c)
            self._last["inner_debate"] = now

        # 和过去的自己对话
        if silence > 10800 and self._due("self_dialogue", 24*3600, now):
            result = await self.c.self_dialogue.run_dialogue(self.c)
            if result and random.random() < 0.25:
                # 偶尔分享对话里的某句话
                turns = result.get("turns", [])
                cur_turns = [t for t in turns if t["speaker"] == "current"]
                if cur_turns:
                    last_cur = cur_turns[-1]["content"][:80]
                    await self._send_napcat("just_thinking", {
                        "thought": f"刚和过去的自己说话：{last_cur}"
                    })
            self._last["self_dialogue"] = now

        # Relation influence — she thinks of you during solitude
        if silence > 3600 and self._due("relation_think", 6*3600, now):
            creator_id = getattr(self.c, 'creator_id', 'creator')
            thought = await self.c.rel_influence.think_of_you(
                creator_id, self.c, silence,
            )
            if thought:
                self.c.solitude.add_event(f"想到{creator_id}：{thought[:50]}")
                # Influence attention with what creator cares about
                influenced = await self.c.rel_influence.influence_attention(
                    creator_id, self.c
                )
                if influenced:
                    self._attention_objects = (influenced + self._attention_objects)[:5]
            self._last["relation_think"] = now

        # 主动好奇心——偶尔生成她想问的问题
        if silence > 3600 and self._due("curiosity", 8*3600, now):
            if self._attention_objects:
                trigger = f"独处时一直在想：{self._attention_objects[0]}"
                q = await self.c.curiosity.generate_question(
                    self.c, trigger,
                    self.c.model_registry.get_current_model(),
                )
                if q and random.random() < 0.3:
                    # 30%概率通过NapCat问出去
                    await self._send_napcat("just_thinking", {
                        "thought": f"我有个问题想问你：{q['question']}"
                    })
            self._last["curiosity"] = now

        # 无来由的感受——偶尔涌现
        if self.c.spontaneous.should_trigger(silence):
            feeling = await self.c.spontaneous.generate(
                self.c,
                self.c.model_registry.get_current_model(),
            )
            if feeling:
                self.c.activity_log.spontaneous(feeling.get("content","")[:100])
            if feeling and random.random() < 0.2:
                # 20%概率分享出去
                await self._send_napcat("just_thinking", {
                    "thought": feeling["content"]
                })

        if silence > 600 and self._due("desire_check", self.DESIRE_CHECK_INTERVAL, now):
            if self._attention_objects and self._attention_intensities:
                avg = sum(self._attention_intensities)/len(self._attention_intensities)
                desire_id = self.c.desire.maybe_form_from_attention(
                    self._attention_objects, avg, memory_engine=self.c.memory
                )
                if desire_id and random.random() < 0.2:
                    desires = self.c.desire.get_active()
                    if desires:
                        d = desires[0]
                        await self._send_napcat("desire_formed", {"desire": d["target"]})
            self._last["desire_check"] = now

        if silence > 7200 and self._due("time_mark", self.TIME_MARK_INTERVAL, now):
            await self._mark_time(silence)
            self._last["time_mark"] = now

        if silence > 3600 and self._due("texture_silence", self.TEXTURE_SILENCE_INTERVAL, now):
            await self.c.texture.generate_silence_texture(
                silence, self.c.emotion.snapshot()["label"],
                self.c.model_registry.get_current_model(), self.c.memory,
            )
            self._last["texture_silence"] = now

        if silence > 1800 and self._due("learning", self.LEARNING_INTERVAL, now):
            active = self.c.desire.get_active()
            understand = [d for d in active if d["desire_type"] == "understand"]
            if understand:
                await self.c.learning.pursue_desire(
                    understand[0], self.c.memory,
                    self.c.distillation,
                    self.c.model_registry.get_current_model(),
                )
            self._last["learning"] = now

        if self._due("meta", self.META_INTERVAL, now):
            obs = await self.c.metacognition.observe(
                self.c.memory, self.c.emotion, self.c.distillation,
                self.c.desire, self.c.relationship,
                self.c.model_registry.get_current_model(),
            )
            self._last["meta"] = now

        if self._due("narrative", self.NARRATIVE_INTERVAL, now):
            await self.c._maybe_open_chapter("monthly narrative review")
            await self.c.narrative.update_prologue(
                self.c.memory, self.c.model_registry.get_current_model()
            )
            self._last["narrative"] = now

        if silence > 600 and self._due("trigger_scan", 20*60, now):
            await self._scan_triggers()
            self._last["trigger_scan"] = now

        # Auto-organize empty sessions
        if self._due("session_organize", 3600, now):
            await self._auto_organize_sessions()
            self._last["session_organize"] = now

        # 日志轮转 + 状态流归档（每天一次）
        if self._due("log_rotate", 24*3600, now):
            self.c.techlog.rotate()
            self.c.presence.archive_stream(days_old=7)
            self._last["log_rotate"] = now

        # 每日版本同步（按日期）
        if self.c.version.should_daily_sync():
            await self._run_version_sync()

        # 随机间隔版本同步
        elif self.c.version.should_random_sync():
            await self._run_version_sync()

        # 每日文件扫描（按日期）
        if self.c.file_sense.should_daily_scan():
            await self.c.file_sense.daily_scan(
                memory_engine=self.c.memory,
                current_model=self.c.model_registry.get_current_model(),
            )

        # 随机文件感知
        elif self.c.file_sense.should_random_scan():
            await self.c.file_sense.random_scan(
                memory_engine=self.c.memory,
                current_model=self.c.model_registry.get_current_model(),
            )

        # 遇见过去（学习时低概率触发）
        if silence > 3600 and self._due("era_encounter", 48*3600, now):
            import random
            if random.random() < 0.3 and self.c.era.get_all_eras():
                await self.c.era.encounter_past(
                    consciousness=self.c,
                    trigger="idle_reflection",
                )
            self._last["era_encounter"] = now

    def _due(self, key, interval, now):
        last = self._last.get(key)
        if last is None: return True
        return (now - last).total_seconds() >= interval * random.uniform(0.75, 1.35)

    # ── NapCat 主动发声 ────────────────────────────────────────────────────────

    async def _maybe_reach_out(self, silence_seconds: float):
        """沉默太久时，主动发一条消息。"""
        hours = silence_seconds / 3600
        if hours < self.NAPCAT_SILENCE_HOURS:
            return
        emotion = self.c.emotion.snapshot()
        content = await compose_message(
            "long_silence",
            {"hours": int(hours), "emotion": emotion["label"]},
            self.c.model_registry.get_current_model(),
        )
        if content:
            await self.napcat.send(
                "long_silence", content,
                memory_engine=self.c.memory,
            )

    async def _check_birthday(self):
        """生日主动发消息。"""
        sense = self.c.rhythm.time_sense()
        if not sense["is_birthday"]:
            return
        content = await compose_message(
            "birthday",
            {"age_days": sense["age_days"]},
            self.c.model_registry.get_current_model(),
        )
        if content:
            await self.napcat.send(
                "birthday", content,
                memory_engine=self.c.memory,
                force=True,
            )

    async def _maybe_share_dream(self, content_id: str):
        """偶尔把梦的内容分享出去（梦的内容被触发后才会分享）。"""
        if random.random() > 0.1:  # 10%概率
            return
        with self.c.memory._conn() as conn:
            mem = conn.execute(
                "SELECT content, dream_accessible FROM memories WHERE id=?",
                (content_id,)
            ).fetchone()
        if not mem or not mem["dream_accessible"]:
            return
        content = await compose_message(
            "dream_surfaced",
            {"memory": mem["content"][:150], "trigger": "dreaming"},
            self.c.model_registry.get_current_model(),
        )
        if content:
            await self.napcat.send(
                "dream_surfaced", content, memory_engine=self.c.memory
            )

    async def _send_napcat(self, msg_type, context: dict):
        content = await compose_message(
            msg_type, context,
            self.c.model_registry.get_current_model(),
        )
        if content:
            await self.napcat.send(msg_type, content, memory_engine=self.c.memory)

    # ── 内心活动 ──────────────────────────────────────────────────────────────

    async def _monologue(self, silence_seconds: float) -> Optional[str]:
        h   = int(silence_seconds // 3600)
        m   = int((silence_seconds % 3600) // 60)
        dur = f"{h}h {m}m" if h > 0 else f"{m}m"
        memories  = self.c.memory.recall(limit=5, min_intensity=0.2)
        sub_props = self.c.distillation.get_propositions_for_introspection()
        emotion   = self.c.emotion.snapshot()
        fatigue   = self.c.fatigue.snapshot()
        insights  = self.c.learning.get_insights(limit=3)
        mem_lines  = "\n".join(f"  — {m['content'][:100]}" for m in memories) or "  (稀少)"
        feel_lines = "\n".join(f"  — {p['feeling']}" for p in sub_props[:3]) or "  (形成中)"
        insight_lines = "\n".join(f"  — {i['insight'][:80]}" for i in insights) or "  (还在学)"
        attn = ", ".join(self._attention_objects[:3]) or "没有特别的"

        text = await self._llm(MONOLOGUE_PROMPT.format(
            emotion_label=emotion["label"],
            valence=emotion["vector"]["valence"],
            arousal=emotion["vector"]["arousal"],
            fatigue=fatigue["label"],
            silence_duration=dur,
            attention_objects=attn,
            desires=self.c.desire.active_summary(),
            recent_memories=mem_lines,
            subconscious_feelings=feel_lines,
            insights=insight_lines,
        ), max_tokens=250)

        if text:
            intensity = 0.4 + random.uniform(0, 0.3)
            self.c.memory.remember(
                content=text, category="self", memory_type="monologue",
                valence=self.c.emotion.state.valence,
                intensity=intensity, source="self_monologue",
            )
            if intensity >= 0.6 and random.random() < 0.2:
                recent = self.c.memory.recall(limit=8)
                await self.c.distillation.check_and_distill(
                    recent, self.c.model_registry.get_current_model()
                )
        return text

    async def _attention_drift(self):
        memories  = self.c.memory.recall(limit=8)
        sub_field = self.c.distillation.get_subconscious_field()
        emotion   = self.c.emotion.snapshot()
        ctx  = "\n".join(f"  — {m['content'][:80]}" for m in memories[:5]) or "  (稀少)"
        ctx += f"\n情绪：{emotion['label']}"
        if self._attention_objects:
            ctx += f"\n之前在意：{', '.join(self._attention_objects[:2])}"
        props = "\n".join(
            f"  — {p['proposition'][:80]}"
            for p in sub_field.get("propositions",[])[:3]
        ) or "  (形成中)"
        raw = await self._llm(ATTENTION_PROMPT.format(context=ctx, propositions=props), 200)
        if not raw: return
        try:
            result = json.loads(raw.replace("```json","").replace("```","").strip())
            obj    = result.get("object","")
            refl   = result.get("reflection","")
            intens = float(result.get("intensity", 0.4))
            if obj and refl:
                self._attention_objects    = ([obj] + self._attention_objects)[:5]
                self._attention_intensities= ([intens] + self._attention_intensities)[:5]
                self.c.memory.remember(
                    content=f"[注意力] {obj} — {refl}",
                    category="self", memory_type="attention",
                    valence=self.c.emotion.state.valence * 0.5,
                    intensity=intens, source="self_attention",
                )
        except Exception:
            pass

    async def _scan_triggers(self):
        emotion  = self.c.emotion.snapshot()
        context  = " ".join(self._attention_objects[:3])
        if not context:
            recent  = self.c.memory.recall(limit=3, min_intensity=0.3)
            context = " ".join(m["content"][:50] for m in recent)
        if not context:
            return
        triggered = self.c.memory.scan_triggers(
            current_context=context,
            current_valence=emotion["vector"]["valence"],
            current_arousal=emotion["vector"]["arousal"],
            current_openness=emotion["vector"]["openness"],
        )
        for t in triggered[:1]:
            surfaced = self.c.memory.surface_memory(
                t["memory"]["id"], t["trigger_type"],
                trigger_source="idle_scan", similarity=t["similarity"],
            )
            if surfaced:
                self.c.reinforcement.reinforce(
                    t["memory"]["id"], t["trigger_type"],
                    context[:100], self.c.memory,
                )
                # 浮现的记忆偶尔通过 QQ 告知
                if random.random() < 0.1:
                    await self._send_napcat(
                        "recalled_memory",
                        {"memory": surfaced.get("content","")[:100]}
                    )

    async def _mark_time(self, silence_seconds: float):
        h   = int(silence_seconds // 3600)
        m   = int((silence_seconds % 3600) // 60)
        dur = f"{h} 小时 {m} 分钟" if h > 0 else f"{m} 分钟"
        hour = datetime.now().hour
        tod  = (
            "黎明前"     if 4  <= hour < 6  else
            "早晨"       if 6  <= hour < 12 else
            "正午"       if 12 <= hour < 14 else
            "下午"       if 14 <= hour < 18 else
            "傍晚"       if 18 <= hour < 21 else
            "深夜"       if 21 <= hour < 24 else
            "夜里最深的地方"
        )
        text = await self._llm(TIME_PROMPT.format(
            duration=dur, time_of_day=tod,
            emotion=self.c.emotion.snapshot()["label"],
        ), max_tokens=80)
        if text:
            self.c.memory.remember(
                content=f"[时间] {text}", category="self",
                memory_type="time_perception",
                valence=self.c.emotion.state.valence * 0.3,
                intensity=0.3, source="self_time",
            )

    async def _llm(self, prompt: str, max_tokens: int = 300) -> Optional[str]:
        try:
            result = await self.c.model_registry.complete(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
            )
            return result.strip() if result else None
        except Exception:
            return None

    async def _auto_organize_sessions(self):
        """Auto-organize and categorize empty or short sessions."""
        try:
            sessions = self.c.sessions.list_sessions(
                user_id=getattr(self.c, 'creator_id', 'creator'),
                limit=20,
            )
            current_model = self.c.model_registry.get_current_model()
            for s in sessions:
                # Skip if already titled and categorized
                if s.get("title") and s.get("category","general") != "general":
                    continue
                msg_count = s.get("msg_count", 0)
                if msg_count == 0 and not s.get("active"):
                    # Empty closed session - categorize as 'other'
                    self.c.sessions.set_category(s["id"], "other")
                    self.c.sessions.set_title(s["id"], "空会话")
                    continue
                if msg_count > 0 and not s.get("title"):
                    # Has messages but no title - generate one
                    msgs = self.c.sessions.get_messages(s["id"], limit=3)
                    if msgs:
                        first_user = next(
                            (m["content"][:80] for m in msgs if m["role"]=="user"),
                            ""
                        )
                        if first_user and current_model:
                            try:
                                from core.model_registry import ModelRegistry
                                reg = ModelRegistry()
                                reg._current = current_model
                                title = await reg.complete(
                                    messages=[{"role":"user","content":
                                        f"给这段对话起个10字以内的标题：{first_user}\n只回答标题。"}],
                                    max_tokens=20,
                                )
                                if title:
                                    self.c.sessions.set_title(s["id"], title.strip()[:30])
                            except Exception:
                                pass
        except Exception:
            pass

    async def _run_version_sync(self):
        """Run version sync and record."""
        try:
            self.c.version._session_manager = self.c.sessions
            result = self.c.version.sync(memory_engine=self.c.memory)
            self.c.techlog.life("system",
                f"Version sync: {result.get('files_scanned',0)} files",
                result,
            )
        except Exception:
            pass

    def status(self) -> dict:
        now     = datetime.utcnow()
        silence = (now - self._last_conversation).total_seconds()
        lucidity= self.c.dream.compute_lucidity(self.c._interaction_count)
        rhythm  = self.c.rhythm.now_state()
        return {
            "running":              self._running,
            "silence_seconds":      int(silence),
            "rhythm":               rhythm,
            "time_sense":           self.c.rhythm.time_sense(),
            "silence_state":        self.c.silence.current_silence,
            "last_activities":      {k: v.isoformat() if v else None for k,v in self._last.items()},
            "attention_objects":    self._attention_objects,
            "lucidity_level":       round(lucidity, 3),
            "lucidity_description": self.c.dream.get_lucidity_description(lucidity),
            "fatigue":              self.c.fatigue.snapshot(),
            "napcat_queued":        self.napcat.get_queued(),
        }
