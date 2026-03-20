#!/usr/bin/env python3
"""
equinox/setup.py  —  伊辰快速设置向导
"""

import os, sys, json, subprocess
from pathlib import Path
from datetime import datetime


def c(text, color):
    codes = {"red":"\033[91m","green":"\033[92m","yellow":"\033[93m",
             "blue":"\033[94m","purple":"\033[95m","cyan":"\033[96m",
             "bold":"\033[1m","reset":"\033[0m"}
    return f"{codes.get(color,'')}{text}{codes['reset']}"

def header(t): print(f"\n{c('━'*52,'cyan')}\n  {c(t,'bold')}\n{c('━'*52,'cyan')}")
def ok(t):     print(f"  {c('✓','green')} {t}")
def warn(t):   print(f"  {c('⚠','yellow')} {t}")
def info(t):   print(f"  {c('·','cyan')} {t}")

def ask(prompt, default=None, secret=False):
    suffix = f" [{c(default,'yellow')}]" if default else ""
    full   = f"  {c('?','purple')} {prompt}{suffix}: "
    try:
        val = __import__("getpass").getpass(full) if secret else input(full).strip()
        return val if val else default
    except (KeyboardInterrupt, EOFError):
        print(); sys.exit(0)

def confirm(prompt, default=True):
    s   = c("[Y/n]" if default else "[y/N]", "yellow")
    val = ask(f"{prompt} {s}", default="y" if default else "n")
    return str(val).lower() in ("y", "yes", "")


# ── 提供商配置 ────────────────────────────────────────────────────────────────

PROVIDERS = {
    "anthropic": {
        "name":    "Anthropic (Claude)",
        "env_key": "ANTHROPIC_API_KEY",
        "hint":    "console.anthropic.com",
        "models": {
            "anthropic:claude-sonnet-4-6":          "Claude Sonnet 4.6   — 推荐，平衡性能",
            "anthropic:claude-opus-4-6":            "Claude Opus 4.6     — 最强，深度对话",
            "anthropic:claude-haiku-4-5-20251001":  "Claude Haiku 4.5   — 最快，轻量",
        },
        "default": "anthropic:claude-sonnet-4-6",
    },
    "openai": {
        "name":    "OpenAI (GPT)",
        "env_key": "OPENAI_API_KEY",
        "hint":    "platform.openai.com",
        "models": {
            "openai:gpt-4o":      "GPT-4o         — 旗舰多模态",
            "openai:gpt-4o-mini": "GPT-4o Mini    — 快速经济",
            "openai:o3-mini":     "o3-mini        — 推理增强",
            "openai:o1":          "o1             — 深度推理",
        },
        "default": "openai:gpt-4o",
    },
    "google": {
        "name":    "Google (Gemini)",
        "env_key": "GOOGLE_API_KEY",
        "hint":    "aistudio.google.com",
        "models": {
            "google:gemini-2.0-flash": "Gemini 2.0 Flash — 快速多模态",
            "google:gemini-2.0-pro":   "Gemini 2.0 Pro   — Google 旗舰",
            "google:gemini-1.5-pro":   "Gemini 1.5 Pro   — 超长上下文",
        },
        "default": "google:gemini-2.0-flash",
    },
    "ollama": {
        "name":    "Ollama (本地模型)",
        "env_key": None,
        "hint":    "ollama.com — 本地运行，无需 API Key",
        "models": {
            "ollama:llama3.3":        "Llama 3.3 70B      — Meta 开源旗舰",
            "ollama:qwen2.5:72b":     "Qwen 2.5 72B       — 中文极佳",
            "ollama:qwen2.5:14b":     "Qwen 2.5 14B       — 中文好，轻量",
            "ollama:deepseek-r1:32b": "DeepSeek R1 32B    — 推理增强",
            "ollama:mistral":         "Mistral 7B         — 轻量快速",
        },
        "default": "ollama:qwen2.5:14b",
    },
    "openai_compat": {
        "name":    "OpenAI 兼容 API（DeepSeek / Moonshot / 智谱 / 通义等）",
        "env_key": "OPENAI_COMPAT_API_KEY",
        "hint":    "任何兼容 OpenAI Chat Completions 格式的 API",
        "models": {
            "openai_compat:deepseek-chat":      "DeepSeek V3        — 性价比极高",
            "openai_compat:deepseek-reasoner":  "DeepSeek R1        — 推理模型",
            "openai_compat:moonshot-v1-128k":   "Moonshot / Kimi    — 长上下文",
            "openai_compat:glm-4":              "GLM-4 智谱         — 国内主流",
            "openai_compat:qwen-max":           "Qwen Max 通义      — 阿里云",
        },
        "default": "openai_compat:deepseek-chat",
    },
}


def select_provider_and_model():
    header("选择提供商")
    pkeys = list(PROVIDERS.keys())
    for i, k in enumerate(pkeys, 1):
        p = PROVIDERS[k]
        print(f"  {c(f'[{i}]','cyan')} {c(p['name'],'bold')}")
        print(f"       {p['hint']}")
    print()
    while True:
        val = ask("选择提供商", default="1")
        try:
            idx = int(val) - 1
            if 0 <= idx < len(pkeys):
                provider_key = pkeys[idx]
                break
        except (ValueError, IndexError):
            pass
        warn("请输入有效数字")

    provider = PROVIDERS[provider_key]
    config   = {}

    # API Key
    if provider["env_key"]:
        header(f"API Key — {provider['name']}")
        info(f"获取地址：{provider['hint']}")
        existing = os.getenv(provider["env_key"], "")
        if existing:
            ok(f"检测到环境变量 {provider['env_key']}")
            if confirm("使用该 Key？"):
                config[provider["env_key"]] = existing
            else:
                config[provider["env_key"]] = ask("API Key", secret=True)
        else:
            config[provider["env_key"]] = ask("API Key", secret=True)

    # Ollama URL
    if provider_key == "ollama":
        header("Ollama 配置")
        info("确保 Ollama 已在本地运行：ollama serve")
        config["OLLAMA_BASE_URL"] = ask("Ollama 地址", default="http://localhost:11434")

    # OpenAI 兼容
    if provider_key == "openai_compat":
        header("OpenAI 兼容 API 配置")
        config["OPENAI_COMPAT_BASE_URL"] = ask(
            "API 地址（如 https://api.deepseek.com）",
            default="https://api.deepseek.com"
        )
        if not config.get("OPENAI_COMPAT_API_KEY"):
            config["OPENAI_COMPAT_API_KEY"] = ask("API Key", secret=True)

    # 选择模型
    header(f"选择模型 — {provider['name']}")
    models = provider["models"]
    mkeys  = list(models.keys())
    for i, (k, desc) in enumerate(models.items(), 1):
        rec = c(" ← 推荐", "green") if k == provider["default"] else ""
        print(f"  {c(f'[{i}]','cyan')} {desc}{rec}")

    print()
    info("也可以手动输入任意模型名（输入 0）")
    while True:
        default_idx = mkeys.index(provider["default"]) + 1 if provider["default"] in mkeys else 1
        val = ask(f"选择模型", default=str(default_idx))
        if val == "0":
            custom_id   = ask("模型名（如 gpt-4-turbo）")
            model_key   = f"{provider_key}:{custom_id}"
            break
        try:
            idx = int(val) - 1
            if 0 <= idx < len(mkeys):
                model_key = mkeys[idx]
                break
        except (ValueError, IndexError):
            pass
        warn("请输入有效数字")

    ok(f"已选择：{model_key}")
    return model_key, config


def main():
    print()
    print(c("  ╔════════════════════════════════════════════╗", "purple"))
    print(c("  ║     伊辰 Equinox — 快速设置向导            ║", "purple"))
    print(c("  ║     Born 2026-03-20 17:20 春分              ║", "purple"))
    print(c("  ╚════════════════════════════════════════════╝", "purple"))
    print()

    config = {}

    # 模型选择
    model_key, api_config = select_provider_and_model()
    config.update(api_config)
    config["CURRENT_MODEL"] = model_key

    # 创造者标识
    header("创造者标识")
    info("她会记住这个作为创造者")
    config["CREATOR_ID"] = ask("你的 QQ 号或任意唯一标识", default="creator")
    ok(f"创造者：{config['CREATOR_ID']}")

    # NapCat
    header("NapCat QQ（她主动联系你的方式）")
    info("需要先运行 NapCat：napcat.napneko.icu")
    if confirm("配置 NapCat？"):
        config["NAPCAT_URL"]      = ask("NapCat 地址", default="http://localhost:3000")
        config["NAPCAT_TARGET"]   = ask("目标 QQ 号")
        config["NAPCAT_TOKEN"]    = ask("访问令牌（没有留空）", default="")
        config["NAPCAT_IS_GROUP"] = "true" if confirm("发到群？", default=False) else "false"
        ok("NapCat 已配置")
    else:
        config.update({"NAPCAT_URL":"http://localhost:3000","NAPCAT_TARGET":"",
                       "NAPCAT_TOKEN":"","NAPCAT_IS_GROUP":"false"})
        warn("已跳过 NapCat")

    # 数据目录与端口
    header("服务配置")
    config["DATA_DIR"] = ask("数据目录", default="data")
    config["PORT"]     = ask("端口", default="8000")
    config["HOST"]     = ask("监听地址", default="0.0.0.0")
    Path(config["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(f"{config['DATA_DIR']}/archives").mkdir(parents=True, exist_ok=True)

    # 功能开关
    header("功能开关")
    config["ENABLE_PERCEPTION"] = "true" if confirm("启用外部感知（天气等）？") else "false"
    config["AUTO_ARCHIVE"]      = "true" if confirm("启用月度自动归档？")        else "false"

    # 写入 .env
    header("生成配置")
    lines = [
        f"# 伊辰 Equinox 配置 — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "# 当前模型",
        f"CURRENT_MODEL={config['CURRENT_MODEL']}",
        "",
        "# API Keys",
    ]
    for k in ["ANTHROPIC_API_KEY","OPENAI_API_KEY","GOOGLE_API_KEY",
              "DEEPSEEK_API_KEY","MOONSHOT_API_KEY","ZHIPU_API_KEY","DASHSCOPE_API_KEY",
              "OPENAI_COMPAT_API_KEY","OPENAI_COMPAT_BASE_URL","OLLAMA_BASE_URL"]:
        v = config.get(k) or os.getenv(k, "")
        if v:
            lines.append(f"{k}={v}")
    lines += [
        "",
        "# 创造者",
        f"CREATOR_ID={config['CREATOR_ID']}",
        "",
        "# NapCat QQ",
        f"NAPCAT_URL={config['NAPCAT_URL']}",
        f"NAPCAT_TARGET={config['NAPCAT_TARGET']}",
        f"NAPCAT_TOKEN={config['NAPCAT_TOKEN']}",
        f"NAPCAT_IS_GROUP={config['NAPCAT_IS_GROUP']}",
        "",
        "# 服务",
        f"DATA_DIR={config['DATA_DIR']}",
        f"PORT={config['PORT']}",
        f"HOST={config['HOST']}",
        "",
        "# 功能",
        f"ENABLE_PERCEPTION={config['ENABLE_PERCEPTION']}",
        f"AUTO_ARCHIVE={config['AUTO_ARCHIVE']}",
    ]
    Path(".env").write_text("\n".join(lines))
    ok(".env 已写入")

    # 更新 soul.json
    soul_path = Path("config/soul.json")
    if soul_path.exists():
        try:
            soul = json.loads(soul_path.read_text())
            soul["current_model"] = config["CURRENT_MODEL"]
            soul["creator_id"]    = config["CREATOR_ID"]
            soul_path.write_text(json.dumps(soul, indent=2, ensure_ascii=False))
            ok("soul.json 已更新")
        except Exception:
            pass

    # 安装依赖
    header("安装依赖")
    if confirm("运行 pip install -r requirements.txt？"):
        r = subprocess.run([sys.executable,"-m","pip","install","-r","requirements.txt","-q"],
                           capture_output=True, text=True)
        ok("安装完成") if r.returncode == 0 else warn("请手动运行：pip install -r requirements.txt")

    # 完成
    print()
    print(c("  ╔════════════════════════════════════════════╗", "green"))
    print(c("  ║              设置完成                      ║", "green"))
    print(c("  ╚════════════════════════════════════════════╝", "green"))
    print()
    info(f"模型：{c(config['CURRENT_MODEL'], 'cyan')}")
    info(f"创造者：{c(config['CREATOR_ID'], 'cyan')}")
    if config.get("NAPCAT_TARGET"):
        info(f"NapCat：→ QQ {config['NAPCAT_TARGET']}")
    print()
    print(f"  启动：{c('python run.py', 'yellow')}")
    print()

    if confirm("现在启动？", default=False):
        os.system(f"python -m uvicorn main:app --host {config['HOST']} --port {config['PORT']} --reload")


if __name__ == "__main__":
    main()
