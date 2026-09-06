#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校园跑步数据生成器 - Web应用入口

作者: 猫娘幽浮喵
"""

import json
import logging
import os
import sys

try:
    from flask import Flask
except ImportError:
    print("错误: Flask 未安装。请运行: pip install flask")
    sys.exit(1)

from web.routes import create_app


def load_web_config() -> tuple[str, int]:
    """从配置文件加载Web服务配置

    Returns:
        (host, port) 元组
    """
    config_path = os.path.join(os.path.dirname(__file__), "config", "default_settings.json")
    if os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        host = config.get("web_host", "0.0.0.0")
        port = config.get("web_port", 5000)
        logging.info("Web配置已加载: host=%s, port=%d", host, port)
        return host, port
    return "0.0.0.0", 5000


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    app = create_app()
    host, port = load_web_config()

    print("=" * 50)
    print("校园跑步数据生成器 - Web界面")
    print(f"局域网访问 http://<本机IP>:{port}")
    print(f"本机访问 http://127.0.0.1:{port}")
    print("按 Ctrl+C 停止服务器")
    print("=" * 50)

    # use_reloader=False 防止多次生成后因文件句柄/内存累积导致进程崩溃
    app.run(debug=True, host=host, port=port, use_reloader=False)


if __name__ == "__main__":
    main()
