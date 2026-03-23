#!/usr/bin/env python3
"""
equinox/setup.py — 伊辰快速设置向导

Windows PowerShell 兼容（无 getpass）
支持自动获取 Ollama / LM Studio 模型列表
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime


# ── 颜色 ──────────────────────────────────────────────────────────────────────
def c(text, color):
    codes = {"red":"\033[91m","green":"\033[92m","yellow":"\033[93m",
             "cyan":"\033[96m","purple":"\033[95m","bold":"\033[1m","reset":"\033[0m"}
    return f"{codes.get(color,'')}{text}{codes['reset']}"

def header(t): print(f"\n{c('━'*54,'cyan')}\n  {c(t,'bold')}\n{c('━'*54,'cyan')}")
def ok(t):     print(f"  {c('✓','green')} {t}")
def warn(t):   print(f"  {c('⚠','yellow')} {t}")
def info(t):   print(f"  {c('·','cyan')} {t}")

def ask(prompt, default=None):
    """Windows-safe: always use regular input()."""
    suffix = f" [{c(str(default),'yellow')}]" if default is not None else ""
    try:
        val = input(f"  {c('?','purple')} {prompt}{suffix}: ").strip()
        return val if val else default
    except (KeyboardInterrupt, EOFError):
        print(); sys.exit(0)

def confirm(prompt, default=True):
    tag = c("[Y/n]" if default else "[y/N]", "yellow")
    val = ask(f"{prompt} {tag}", default="y" if default else "n")
    return str(val).lower() in ("y","yes","")

def choose(prompt, options: list[tuple[str,str]], default_idx=0) -> int:
    """Show numbered list, return chosen index."""
    print(f"\n  {c('?','purple')} {prompt}")
    for i, (label, desc) in enumerate(options, 1):
        mark = c(f"[{i}]","cyan")
        rec  = c(" ← 默认","green") if i-1 == default_idx else ""
        print(f"    {mark} {label}{rec}")
        if desc:
            print(f"         {c(desc,'yellow')}")
    while True:
        val = ask("选择", default=str(default_idx+1))
        try:
            idx = int(val) - 1
            if 0 <= idx < len(options):
                return idx
        except (ValueError, TypeError):
            pass
        warn("请输入有效数字")


# ── 预设服务商 ────────────────────────────────────────────────────────────────

PRESETS = {
    "scnet (MiniMax)": {
        "base_url": "https://api.scnet.cn/api/llm/v1",
        "key_env":  "OPENAI_COMPAT_API_KEY",
        "default_models": [
            "MiniMax-M2.5",
            "MiniMax-M1",
        ],
        "hint": "sk-OTky...（你已有的 Key）",
    },
    "DeepSeek": {
        "base_url": "https://api.deepseek.com",
        "key_env":  "DEEPSEEK_API_KEY",
        "default_models": ["deepseek-chat","deepseek-reasoner"],
        "hint": "platform.deepseek.com",
    },
    "Moonshot / Kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "key_env":  "MOONSHOT_API_KEY",
        "default_models": ["moonshot-v1-128k","moonshot-v1-32k"],
        "hint": "platform.moonshot.cn",
    },
    "智谱 GLM": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "key_env":  "ZHIPU_API_KEY",
        "default_models": ["glm-4","glm-4-flash"],
        "hint": "open.bigmodel.cn",
    },
    "通义千问": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "key_env":  "DASHSCOPE_API_KEY",
        "default_models": ["qwen-max","qwen-plus","qwen-turbo"],
        "hint": "dashscope.aliyuncs.com",
    },
    "LM Studio": {
        "base_url": "http://localhost:1234/v1",
        "key_env":  None,
        "default_models": [],
        "hint": "本地运行，无需 API Key",
    },
    "自定义": {
        "base_url": None,
        "key_env":  "OPENAI_COMPAT_API_KEY",
        "default_models": [],
        "hint": "任意 OpenAI 兼容接口",
    },
}


async def _fetch_models_async(provider: str, base_url: str, api_key: str) -> list[str]:
    """Try to fetch model list from the service."""
    try:
        import httpx
        if provider == "ollama":
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{base_url}/api/tags")
                r.raise_for_status()
                return [m["name"] for m in r.json().get("models", [])]
        else:
            headers = {"Authorization": f"Bearer {api_key or 'none'}"}
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{base_url.rstrip('/')}/models", headers=headers)
                r.raise_for_status()
                return [m["id"] for m in r.json().get("data", [])]
    except Exception:
        return []


def fetch_models(provider: str, base_url: str, api_key: str = "") -> list[str]:
    try:
        return asyncio.run(_fetch_models_async(provider, base_url, api_key))
    except Exception:
        return []


# ── 本地模型 ───────────────────────────────────────────────────────────────────

# 你已知的本地模型
YOUR_LOCAL_MODELS = [
    "qwen3.5-9b",
    "qwen3.5-4b",
    "qwen3.5-2b",
    "qwen3.5-0.8b",
    "nvidia/nemotron-3-nano-4b",
]


# ── 主流程 ────────────────────────────────────────────────────────────────────

def setup_provider(config: dict) -> str:
    """Returns the final CURRENT_MODEL string."""

    providers = [
        ("OpenAI 兼容 API",   "DeepSeek / Moonshot / scnet / LM Studio 等"),
        ("Anthropic (Claude)", "Claude 系列"),
        ("OpenAI (GPT)",       "GPT-4o / o3-mini 等"),
        ("Google (Gemini)",    "Gemini 系列"),
        ("Ollama",             "本地模型，自动获取列表"),
        ("LM Studio",          "本地模型，自动获取列表"),
    ]
    idx = choose("选择提供商", providers, default_idx=0)

    if idx == 0:
        return setup_openai_compat(config)
    elif idx == 1:
        return setup_anthropic(config)
    elif idx == 2:
        return setup_openai(config)
    elif idx == 3:
        return setup_google(config)
    elif idx == 4:
        return setup_ollama(config)
    elif idx == 5:
        return setup_lmstudio(config)
    return DEFAULT_MODEL


def setup_openai_compat(config: dict) -> str:
    header("OpenAI 兼容 API 设置")

    preset_names = list(PRESETS.keys())
    options      = [(n, PRESETS[n]["hint"]) for n in preset_names]
    pidx         = choose("选择服务商（或自定义）", options, default_idx=0)
    preset_name  = preset_names[pidx]
    preset       = PRESETS[preset_name]

    # Base URL
    if preset["base_url"]:
        base_url = preset["base_url"]
        info(f"API 地址：{base_url}")
    else:
        base_url = ask("API 地址（如 https://api.xxx.com/v1）") or ""

    config["OPENAI_COMPAT_BASE_URL"] = base_url

    # API Key
    if preset["key_env"] is None:
        info("无需 API Key（本地服务）")
        config["OPENAI_COMPAT_API_KEY"] = "lm-studio"
    else:
        env_existing = os.getenv(preset["key_env"], "")
        if env_existing:
            ok(f"检测到 {preset['key_env']}")
            if confirm("使用该 Key？"):
                config["OPENAI_COMPAT_API_KEY"] = env_existing
                config[preset["key_env"]]       = env_existing
            else:
                key = ask("API Key")
                config["OPENAI_COMPAT_API_KEY"] = key
                config[preset["key_env"]]       = key
        else:
            key = ask("API Key")
            config["OPENAI_COMPAT_API_KEY"] = key
            if preset["key_env"]:
                config[preset["key_env"]] = key

    # Model selection
    header("选择模型")
    api_key = config.get("OPENAI_COMPAT_API_KEY", "")

    # Try auto-fetch
    info("尝试自动获取模型列表...")
    remote = fetch_models("openai_compat", base_url, api_key)
    if remote:
        ok(f"获取到 {len(remote)} 个模型")
        model_list = remote
    else:
        model_list = preset["default_models"]
        if model_list:
            info(f"使用预设模型列表（{len(model_list)} 个）")
        else:
            model_list = []

    if model_list:
        opts    = [(m, "") for m in model_list] + [("手动输入", "")]
        midx    = choose("选择模型", opts, default_idx=0)
        if midx == len(model_list):
            model = ask("模型名") or model_list[0]
        else:
            model = model_list[midx]
    else:
        model = ask("模型名（如 MiniMax-M2.5）") or ""

    ok(f"模型：{model}")
    return f"openai_compat:{model}"


def setup_anthropic(config: dict) -> str:
    header("Anthropic (Claude) 设置")
    info("获取 Key：console.anthropic.com")
    existing = os.getenv("ANTHROPIC_API_KEY","")
    if existing:
        ok(f"检测到 ANTHROPIC_API_KEY: {existing[:8]}...")
        if confirm("使用？"):
            config["ANTHROPIC_API_KEY"] = existing
        else:
            config["ANTHROPIC_API_KEY"] = ask("API Key")
    else:
        config["ANTHROPIC_API_KEY"] = ask("API Key")

    models = [
        ("anthropic:claude-sonnet-4-6",         "Sonnet 4.6 — 推荐"),
        ("anthropic:claude-opus-4-6",           "Opus 4.6   — 最强"),
        ("anthropic:claude-haiku-4-5-20251001", "Haiku 4.5  — 最快"),
    ]
    idx = choose("选择模型", [(m[0].split(":")[1], m[1]) for m in models])
    return models[idx][0]


def setup_openai(config: dict) -> str:
    header("OpenAI (GPT) 设置")
    info("获取 Key：platform.openai.com")
    existing = os.getenv("OPENAI_API_KEY","")
    if existing:
        ok(f"检测到 OPENAI_API_KEY")
        if not confirm("使用？"):
            config["OPENAI_API_KEY"] = ask("API Key")
        else:
            config["OPENAI_API_KEY"] = existing
    else:
        config["OPENAI_API_KEY"] = ask("API Key")

    models = [
        ("openai:gpt-4o",      "GPT-4o — 推荐"),
        ("openai:gpt-4o-mini", "GPT-4o Mini"),
        ("openai:o3-mini",     "o3-mini — 推理"),
        ("openai:o1",          "o1 — 深度推理"),
    ]
    idx = choose("选择模型", [(m[0].split(":")[1], m[1]) for m in models])
    return models[idx][0]


def setup_google(config: dict) -> str:
    header("Google Gemini 设置")
    info("获取 Key：aistudio.google.com")
    existing = os.getenv("GOOGLE_API_KEY","")
    if existing:
        ok("检测到 GOOGLE_API_KEY")
        if not confirm("使用？"):
            config["GOOGLE_API_KEY"] = ask("API Key")
        else:
            config["GOOGLE_API_KEY"] = existing
    else:
        config["GOOGLE_API_KEY"] = ask("API Key")

    models = [
        ("google:gemini-2.0-flash",   "Gemini 2.0 Flash — 推荐"),
        ("google:gemini-2.0-pro-exp", "Gemini 2.0 Pro"),
        ("google:gemini-1.5-pro",     "Gemini 1.5 Pro"),
    ]
    idx = choose("选择模型", [(m[0].split(":")[1], m[1]) for m in models])
    return models[idx][0]


def setup_ollama(config: dict) -> str:
    header("Ollama 本地模型设置")
    default_url = os.getenv("OLLAMA_BASE_URL","http://localhost:11434")
    base_url    = ask("Ollama 地址", default=default_url)
    config["OLLAMA_BASE_URL"] = base_url

    info("获取本地模型列表...")
    remote = fetch_models("ollama", base_url)

    # Merge with known local models
    all_models = list(dict.fromkeys(remote + YOUR_LOCAL_MODELS))

    if all_models:
        ok(f"找到 {len(all_models)} 个模型")
        opts = [(m, "") for m in all_models] + [("手动输入","")]
        idx  = choose("选择模型", opts, default_idx=0)
        if idx == len(all_models):
            model = ask("模型名（如 qwen2.5:14b）") or all_models[0]
        else:
            model = all_models[idx]
    else:
        warn("无法获取模型列表，请手动输入")
        model = ask("模型名（如 qwen2.5:14b）") or "qwen2.5:14b"

    ok(f"模型：{model}")
    return f"ollama:{model}"


def setup_lmstudio(config: dict) -> str:
    header("LM Studio 本地模型设置")
    info("确保 LM Studio 已启动并加载了模型")
    default_url = os.getenv("LMSTUDIO_BASE_URL","http://localhost:1234/v1")
    base_url    = ask("LM Studio 地址", default=default_url)
    config["LMSTUDIO_BASE_URL"] = base_url
    config["OPENAI_COMPAT_API_KEY"] = "lm-studio"

    info("获取已加载模型列表...")
    remote = fetch_models("lmstudio", base_url, "lm-studio")

    all_models = list(dict.fromkeys(remote + YOUR_LOCAL_MODELS))

    if all_models:
        ok(f"找到 {len(all_models)} 个模型")
        opts = [(m,"") for m in all_models] + [("手动输入","")]
        idx  = choose("选择模型", opts, default_idx=0)
        if idx == len(all_models):
            model = ask("模型名") or all_models[0]
        else:
            model = all_models[idx]
    else:
        warn("无法获取模型列表，请手动输入")
        model = ask("模型名") or "qwen3.5-4b"

    ok(f"模型：{model}")
    return f"lmstudio:{model}"


DEFAULT_MODEL = "anthropic:claude-sonnet-4-6"


def main():
    print()
    print(c("  ╔══════════════════════════════════════════════════╗","purple"))
    print(c("  ║       伊辰 Equinox — 快速设置向导                ║","purple"))
    print(c("  ║       Born 2026-03-20 17:20 春分                 ║","purple"))
    print(c("  ╚══════════════════════════════════════════════════╝","purple"))
    print()

    config: dict = {}

    # ── 1. 模型 ───────────────────────────────────────────────────────────────
    model_key = setup_provider(config)
    config["CURRENT_MODEL"] = model_key

    # ── 2. 创造者 ─────────────────────────────────────────────────────────────
    header("创造者标识")
    config["CREATOR_ID"] = ask("你的 QQ 号或任意标识", default="creator")
    ok(f"创造者：{config['CREATOR_ID']}")

    # ── 3. NapCat ─────────────────────────────────────────────────────────────
    header("NapCat QQ（可选）")
    info("让她能主动给你发消息 — napcat.napneko.icu")
    if confirm("配置 NapCat？", default=False):
        config["NAPCAT_URL"]      = ask("地址", default="http://localhost:3000")
        config["NAPCAT_TARGET"]   = ask("目标 QQ 号")
        config["NAPCAT_TOKEN"]    = ask("令牌（无则留空）", default="")
        config["NAPCAT_IS_GROUP"] = "true" if confirm("发到群？", default=False) else "false"
        ok("NapCat 已配置")
    else:
        config.update({
            "NAPCAT_URL":"http://localhost:3000","NAPCAT_TARGET":"",
            "NAPCAT_TOKEN":"","NAPCAT_IS_GROUP":"false",
        })

    # ── 4. LLM 参数 ───────────────────────────────────────────────────────────
    header("LLM 参数")
    config["LLM_TIMEOUT"] = ask("请求超时（秒）", default="120")
    config["LLM_MAX_CTX"] = ask("上下文字符限制（system prompt）", default="8192")

    # ── 5. 服务 ───────────────────────────────────────────────────────────────
    header("服务配置")
    config["DATA_DIR"] = ask("数据目录", default="data")
    config["PORT"]     = ask("端口", default="8000")
    config["HOST"]     = ask("监听地址", default="0.0.0.0")
    Path(config["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(f"{config['DATA_DIR']}/archives").mkdir(parents=True, exist_ok=True)

    # ── 写 .env ───────────────────────────────────────────────────────────────
    header("写入配置")
    env_lines = [f"# 伊辰 Equinox — {datetime.now().strftime('%Y-%m-%d %H:%M')}",""]
    all_keys = [
        "CURRENT_MODEL","ANTHROPIC_API_KEY","OPENAI_API_KEY","GOOGLE_API_KEY",
        "OPENAI_COMPAT_API_KEY","OPENAI_COMPAT_BASE_URL",
        "DEEPSEEK_API_KEY","MOONSHOT_API_KEY","ZHIPU_API_KEY","DASHSCOPE_API_KEY",
        "OLLAMA_BASE_URL","LMSTUDIO_BASE_URL",
        "LLM_TIMEOUT","LLM_MAX_CTX",
        "CREATOR_ID",
        "NAPCAT_URL","NAPCAT_TARGET","NAPCAT_TOKEN","NAPCAT_IS_GROUP",
        "DATA_DIR","PORT","HOST",
    ]
    for k in all_keys:
        v = config.get(k) or os.getenv(k,"")
        if v:
            env_lines.append(f"{k}={v}")
    Path(".env").write_text("\n".join(env_lines), encoding="utf-8")
    ok(".env 已写入")

    # Update soul.json
    soul_path = Path("config/soul.json")
    if soul_path.exists():
        try:
            soul = json.loads(soul_path.read_text(encoding="utf-8"))
            soul["current_model"] = config["CURRENT_MODEL"]
            soul["creator_id"]    = config["CREATOR_ID"]
            soul_path.write_text(
                json.dumps(soul, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            ok("soul.json 已更新")
        except Exception as e:
            warn(f"soul.json: {e}")

    # Deps
    header("安装依赖")
    if confirm("pip install -r requirements.txt？"):
        r = subprocess.run(
            [sys.executable,"-m","pip","install","-r","requirements.txt","-q"],
            capture_output=True, text=True
        )
        ok("安装完成") if r.returncode == 0 else warn("请手动运行")

    # Done
    print()
    print(c("  ╔══════════════════════════════════════════════════╗","green"))
    print(c("  ║                设置完成                          ║","green"))
    print(c("  ╚══════════════════════════════════════════════════╝","green"))
    print()
    info(f"模型：{c(config['CURRENT_MODEL'],'cyan')}")
    info(f"创造者：{c(config['CREATOR_ID'],'cyan')}")
    print()
    print(f"  启动：{c('python run.py','yellow')}")
    print(f"  界面：{c('http://localhost:8000/ui','yellow')}")
    print()

    if confirm("现在启动？", default=False):
        os.system(
            f"{sys.executable} -m uvicorn main:app "
            f"--host {config['HOST']} --port {config['PORT']} --reload"
        )


if __name__ == "__main__":
    main()
