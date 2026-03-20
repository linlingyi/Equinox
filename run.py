#!/usr/bin/env python3
"""
equinox/run.py

一键启动伊辰。

首次运行会检查 .env 是否存在，
不存在则自动引导设置。
"""

import os
import sys
import subprocess
from pathlib import Path


def load_env():
    env_path = Path(".env")
    if not env_path.exists():
        return {}
    config = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            config[key.strip()] = val.strip()
    return config


def main():
    print()
    print("  伊辰 Equinox")
    print("  Born 2026-03-20 17:20 春分")
    print()

    env_path = Path(".env")
    if not env_path.exists():
        print("  首次运行，启动设置向导...")
        print()
        os.system(f"{sys.executable} setup.py")
        return

    config = load_env()

    # 检查 API Key
    api_key = config.get("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("  ✗ 未找到 ANTHROPIC_API_KEY，请运行 python setup.py")
        sys.exit(1)

    # 设置环境变量
    for key, val in config.items():
        os.environ.setdefault(key, val)

    host = config.get("HOST", "0.0.0.0")
    port = config.get("PORT", "8000")

    print(f"  启动中... http://{host}:{port}")
    print(f"  模型：{config.get('CURRENT_MODEL', 'claude-sonnet-4-6')}")
    print(f"  按 Ctrl+C 停止")
    print()

    os.system(
        f"{sys.executable} -m uvicorn main:app "
        f"--host {host} --port {port} --reload"
    )


if __name__ == "__main__":
    main()
