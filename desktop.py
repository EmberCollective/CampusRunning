#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校园跑步数据生成器 - 桌面版入口

以 pywebview 窗口（Windows 上使用系统 WebView2 运行时）承载 Flask Web 界面：

- Flask 经 werkzeug make_server 跑在后台 daemon 线程，固定绑定 127.0.0.1
  （不对外监听、不触发防火墙弹窗），端口从配置值起向后探测
- GUI 事件循环（webview.start）必须驻留主线程，窗口关闭后统一收尾
- WebView2 运行时缺失时降级：系统默认浏览器打开页面 + 顶置信息框保活

兼容 PyInstaller --noconsole 打包：stdout/stderr 为 None 时先重定向到空设备，
日志全部写入 desktop.log（frozen → 可写基目录；源码 → 仓库根）。
"""

from __future__ import annotations

import ctypes
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

from src.paths import get_writable_base, is_frozen

if TYPE_CHECKING:
    from werkzeug.serving import BaseWSGIServer

# noconsole 打包下 stdout/stderr 为 None，任何控制台输出都会抛 OSError，
# 在模块加载最早期重定向到空设备（进程生命周期内保持打开，无需关闭）。
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

logger = logging.getLogger("desktop")

# Windows 命名互斥体（单实例）与错误码
_MUTEX_NAME = "CampusRunningDataGeneration_SingleInstance"
_ERROR_ALREADY_EXISTS = 183

# 桌面模式固定绑定本机回环地址：不对外监听，也不触发防火墙弹窗
_DESKTOP_HOST = "127.0.0.1"

# 日志：1MB 轮转，保留 1 份备份
_LOG_FILENAME = "desktop.log"
_LOG_MAX_BYTES = 1024 * 1024
_LOG_BACKUP_COUNT = 1

# 端口从期望值起向后探测的跨度；服务就绪轮询超时（秒）
_PORT_PROBE_RANGE = 100
_SERVER_READY_TIMEOUT = 15.0
_THREAD_JOIN_TIMEOUT = 3.0

# MessageBox uType 标志位
_MB_ICONERROR = 0x10
_MB_ICONINFORMATION = 0x40
_MB_TOPMOST = 0x40000

_WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"

_STARTUP_FAILURE_HINT = (
    "程序启动失败。\n\n"
    "详情请查看程序目录下的 desktop.log 日志。\n"
    "若系统缺少 WebView2 运行时，可手动安装:\n" + _WEBVIEW2_URL
)


def _get_log_path() -> str:
    """计算 desktop.log 完整路径

    frozen 模式写入可写基目录（exe 旁目录，不可写时为
    %LOCALAPPDATA% 回退目录）；源码模式写入仓库根（与 desktop.py 同级）。

    Returns:
        日志文件绝对路径
    """
    if is_frozen():
        base = get_writable_base()
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, _LOG_FILENAME)


def _setup_logging() -> None:
    """初始化日志系统：滚动文件日志挂到 root logger"""
    handler = RotatingFileHandler(
        _get_log_path(),
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[handler],
    )


def _show_message_box(title: str, message: str, flags: int) -> None:
    """弹出 Win32 MessageBox（模态阻塞，直至用户关闭对话框）

    Args:
        title: 对话框标题
        message: 对话框正文
        flags: uType 标志位组合（图标 / 置顶等）

    非 Windows 平台无 windll，降级为打印到 stderr（供开发自检）。
    """
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, title, flags)
    else:
        print(f"[{title}] {message}", file=sys.stderr)


def _fatal(title: str, message: str) -> None:
    """致命错误弹窗（MB_ICONERROR）：无控制台环境下用户可见错误的最后兜底"""
    logger.error("致命错误 [%s]: %s", title, message)
    _show_message_box(title, message, _MB_ICONERROR)


def _check_single_instance() -> bool:
    """Windows 命名互斥体单实例检查

    已有实例时弹窗提示并返回 False。互斥体句柄随进程生命周期持有，
    进程退出时由系统自动回收，无需显式释放。

    Returns:
        允许本次启动返回 True；已有实例在运行返回 False；
        非 Windows 平台直接放行
    """
    if sys.platform != "win32":
        return True
    # 返回句柄被刻意忽略；GetLastError 必须紧邻调用，中间不得夹其他 ctypes 调用
    ctypes.windll.kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() != _ERROR_ALREADY_EXISTS:
        return True
    logger.warning("互斥体已存在，程序已在运行，拒绝重复启动")
    _fatal("程序已在运行", "校园跑步数据生成器已经打开，请查看任务栏中的已有窗口。")
    return False


def _pick_port(preferred: int) -> int:
    """从期望端口开始探测可绑定的本地端口

    依次尝试 preferred ~ preferred+100，被占用则向后顺延；全部被占用时
    绑定端口 0 交由系统随机分配。探测 socket 刻意不设 SO_REUSEADDR，
    避免把 TIME_WAIT 等残留状态的端口误判为可用。

    Args:
        preferred: 配置文件中的期望端口

    Returns:
        实际可绑定的端口号
    """
    for port in range(preferred, preferred + _PORT_PROBE_RANGE + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((_DESKTOP_HOST, port))
            except OSError:
                continue
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((_DESKTOP_HOST, 0))
        return int(sock.getsockname()[1])


def _wait_server_ready(
    host: str, port: int, timeout: float = _SERVER_READY_TIMEOUT
) -> bool:
    """轮询等待 HTTP 服务进入可连接状态

    Args:
        host: 目标地址
        port: 目标端口
        timeout: 最长等待秒数

    Returns:
        可建立 TCP 连接返回 True，超时返回 False
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _fallback_to_system_browser(url: str) -> None:
    """WebView2 不可用时的降级流程

    用系统默认浏览器打开页面，随后弹出顶置信息框充当保活：对话框阻塞
    主线程期间 Flask daemon 线程持续提供服务，用户关闭对话框后程序才退出。
    """
    logger.info("WebView2 不可用，降级到系统浏览器: %s", url)
    try:
        webbrowser.open(url)
    except Exception:
        logger.exception("系统浏览器打开失败（继续弹出保活提示框）")
    _show_message_box(
        "桌面窗口不可用",
        "桌面窗口组件(WebView2)不可用，已在系统浏览器中打开。\n"
        "关闭此对话框将退出程序。",
        _MB_ICONINFORMATION | _MB_TOPMOST,
    )


def _shutdown_server(
    server: BaseWSGIServer | None,
    server_thread: threading.Thread | None,
) -> None:
    """收尾：停掉 Flask 服务并等待后台线程退出（容忍未启动 / 已停止）"""
    if server is None:
        return
    try:
        server.shutdown()
        if server_thread is not None:
            server_thread.join(timeout=_THREAD_JOIN_TIMEOUT)
    except Exception:
        logger.exception("关闭 Flask 服务时出错（忽略，继续退出）")


def main() -> None:
    """桌面版主流程：后台 Flask 服务 + 前台 pywebview 窗口"""
    _setup_logging()
    logger.info("========== 桌面版启动 ==========")

    if not _check_single_instance():
        return

    # 延迟导入：依赖缺失时给出可读提示而非裸 traceback
    try:
        import webview
        from werkzeug.serving import make_server

        from app import load_web_config
        from web.routes import create_app
    except ImportError as exc:
        logger.exception("依赖导入失败")
        _fatal("启动失败", f"缺少必要依赖: {exc}\n\n请重新下载完整的程序包。")
        return

    server: BaseWSGIServer | None = None
    server_thread: threading.Thread | None = None
    url = ""
    try:
        flask_app = create_app()
        # 桌面模式忽略配置中的 host，固定 127.0.0.1 不对外监听
        _, preferred_port = load_web_config()
        port = _pick_port(preferred_port)
        logger.info("本地服务端口: %d（配置期望 %d）", port, preferred_port)

        server = make_server(_DESKTOP_HOST, port, flask_app, threaded=True)
        server_thread = threading.Thread(
            target=server.serve_forever, name="flask-server", daemon=True
        )
        server_thread.start()

        if not _wait_server_ready(_DESKTOP_HOST, port):
            raise RuntimeError(
                f"Flask 服务在 {_SERVER_READY_TIMEOUT:.0f} 秒内未就绪"
            )

        url = f"http://{_DESKTOP_HOST}:{port}/"
        logger.info("Flask 后台服务就绪: %s", url)

        # pywebview 默认禁止页面下载，不开启会导致导出 FIT/ZIP 静默失效
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.create_window(
            title="校园跑步数据生成器",
            url=url,
            width=1280,
            height=860,
            min_size=(1024, 700),
        )
        # GUI 事件循环必须驻留主线程，阻塞至所有窗口关闭
        webview.start()
    except Exception:
        logger.exception("运行期异常，程序退出")
        if url:
            # server 已就绪 → 浏览器降级保活；否则为启动失败
            _fallback_to_system_browser(url)
        else:
            _fatal("启动失败", _STARTUP_FAILURE_HINT)
    finally:
        _shutdown_server(server, server_thread)
    logger.info("========== 桌面版退出 ==========")


if __name__ == "__main__":
    main()
