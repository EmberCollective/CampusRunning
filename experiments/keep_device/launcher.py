"""Start the Windows B5 experiment and show address, connection and transfer state.

Run in the independent Windows experiment environment, from an administrator
console. Uses BTVS/TShark and the existing Bless entry point, not a new BLE stack.
"""

import argparse
import asyncio
import ctypes
import json
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

from .files import WorkoutFiles
from .state import BindingState
from .windows import _duration, _terminate_child_tree, _workouts
from .windows_mac import AdvertisingAddress, _FIELDS, _FILTER


_ROOT = Path(__file__).resolve().parents[2]
_PORT = 24352


class Status:
    """Present confirmed transport events; neither receipt nor BLE proves upload."""

    def __init__(self, size=0, emit=print, event=lambda data: None):
        self.emit = emit
        self.event = event
        self.size = size
        self.address = AdvertisingAddress()
        self.last_mac = None
        self.pending = None
        self.ranges = []
        self.sent = 0
        self.last_diagnostic = None

    def capture(self, line):
        message = self.address.feed(line)
        if message is None:
            return
        if message.startswith("AIR_MAC="):
            mac = self.address.current[0]
            if self.last_mac is not None and self.last_mac != mac:
                self.emit("广播地址已变化；重新添加请使用新 MAC。若 Keep 保留旧绑定，请先在 Keep 解绑。")
            self.last_mac = mac
            self.event(dict(type="address", value=mac))
            self.emit(f"当前广播 MAC：{mac}；Keep 输入：{mac.replace(':', '')}")
        else:
            self.event(dict(type="address", value=None))
            self.emit("当前广播 MAC 不可用，请等待新的地址提示。" + message)

    def prototype(self, line):
        if "file_transfer command=" in line:
            self.pending = dict(re.findall(r"(\w+)=([\w/]+)", line))
        elif line.startswith("SUBSCRIPTION"):
            self.pending = None
            clients = int(re.search(r"clients=(\d+);", line)[1])
            self.event(dict(type="link", connected=clients == 1, ambiguous=clients > 1))
            self.emit("蓝牙客户端已订阅，等待业务请求。" if "clients=1;" in line
                      else "蓝牙订阅已断开或存在多个客户端，请只连接一台手机。")
        elif line.startswith("DEVICE_INFO_SENT"):
            self.emit("设备信息已应答；请在 Keep 核对绑定或连接结果。")
        elif line.startswith("DEVICE_REPLY_SENT") and "sid=01 cid=05 " in line:
            self.emit("已回应绑定请求；这不等同于 Keep 云端绑定成功。")
        elif line.startswith("FILE_REPLY_SENT"):
            pending, self.pending = self.pending, None
            if pending is None:
                return
            command = pending.get("command")
            if command == "6/2" and "sid=06 cid=02 " in line and pending.get("status") == "0" and self.size:
                start = int(pending["offset"])
                end = start + int(pending["returned_length"])
                if not 0 <= start < end <= self.size:
                    raise ValueError("File progress falls outside the selected workout")
                merged = []
                for left, right in sorted(self.ranges + [(start, end)]):
                    if merged and left <= merged[-1][1]:
                        merged[-1] = (merged[-1][0], max(merged[-1][1], right))
                    else:
                        merged.append((left, right))
                self.ranges = merged
                sent = sum(right - left for left, right in merged)
                if sent != self.sent:
                    self.sent = sent
                    self.emit(f"运动文件已发送：{sent}/{self.size} 字节（{sent / self.size:.0%}）；等待手机收讫。")
            elif ((command == "6/7" and "sid=06 cid=07 " in line and pending.get("status") == "1")
                  or (command == "6/3" and "sid=06 cid=03 " in line and int(pending.get("entries", 0)) > 0)):
                if pending.get("type") == "44":
                    self.emit("手机已确认领取运动文件；活动来源、有效性和入账仍需在 Keep 核对。")
            elif command == "6/1" and "sid=06 cid=01 " in line and pending.get("type") == "44":
                self.emit("运动目录为空，无待传记录。" if pending.get("entries") == "0" else "手机开始读取运动目录。")
        elif line.startswith(("WRITE_REJECTED", "DEVICE_INFO_FAILED")):
            self.pending = None
            self.emit("设备请求未完成：" + line)
        elif line.startswith("ADVERTISING"):
            identity = re.search(r"adapter_address=([0-9A-F:]{17})", line)
            self.event(dict(type="advertising", identity=identity[1] if identity else None))
            self.emit("B5 已启动，等待本轮广播 MAC。")
        elif line.startswith("STOPPED"):
            self.pending = None
            self.event(dict(type="stopped"))
            self.emit("B5 广播已停止，正在恢复电脑蓝牙名称。")
        elif line.startswith("NAME_REGISTRY_RESTORED"):
            self.emit("电脑蓝牙名称配置已恢复；实际广播名称仍以扫描结果为准。")
        elif line and not line.startswith(("NAME_REQUESTED", "REPLY_PACKETS", "DEVICE_REPLY_SENT",
                                           "INFO:experiments.keep_device.files:workout_receipt")):
            self.last_diagnostic = line
            self.emit("原型诊断：" + line)


def _tool(value):
    result = shutil.which(value)
    if result is None:
        raise argparse.ArgumentTypeError(f"找不到工具：{value}")
    return str(Path(result).resolve())


def _tcp_state(pid, state):
    # Query the listener without connecting and consuming BTVS's capture stream.
    result = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True,
                            timeout=5, check=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    # Localized headings use the Windows code page, even under PYTHONUTF8=1.
    output = result.stdout.decode("ascii", errors="replace")
    return any(len(parts := line.split()) == 5 and parts[0] == "TCP"
               and parts[1].endswith(f":{_PORT}") and parts[3] == state
               and parts[4] == str(pid) for line in output.splitlines())


def _read_stream(stream, name, events):
    try:
        for line in stream:
            events.put((name, line.rstrip("\r\n")))
    finally:
        events.put((name, None))
        stream.close()


def _spawn(command, name, events, separate_stderr=False):
    process = subprocess.Popen(command, cwd=_ROOT, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE if separate_stderr else subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace",
                               env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
                               creationflags=subprocess.CREATE_NO_WINDOW)
    threading.Thread(target=_read_stream, args=(process.stdout, name, events), daemon=True).start()
    if separate_stderr:
        threading.Thread(target=_read_stream, args=(process.stderr, "capture-error", events), daemon=True).start()
    return process


def _await_capture(btvs, capture, events):
    deadline = time.monotonic() + 15
    started = False
    while time.monotonic() < deadline:
        if btvs.poll() is not None or capture.poll() is not None:
            raise RuntimeError("地址观察启动失败；B5 未启动。检查 BTVS 与 TShark。")
        try:
            source, line = events.get(timeout=0.1)
        except queue.Empty:
            line = None
        else:
            if source == "capture-error" and line:
                if "Capturing on" in line:
                    started = True
                elif "could not" in line.lower() or "error" in line.lower():
                    raise RuntimeError("TShark 无法开始观察；B5 未启动。" + line)
        if started and _tcp_state(btvs.pid, "ESTABLISHED"):
            # Capturing on is printed even when opening the socket subsequently fails.
            if capture.poll() is None:
                return
    raise RuntimeError("等待 TShark 接入 BTVS 超时；B5 未启动。")


def _private_path(value):
    path = Path(value).expanduser().resolve()
    if path.is_relative_to(_ROOT):
        raise ValueError("状态和运动文件必须放在仓库外的私人目录。")
    return path


def run(args, emit=print, event=lambda data: None):
    state = _private_path(args.state)
    binding = None
    if not state.parent.is_dir():
        raise ValueError("状态文件的父目录不存在，请先创建私人实验目录。")
    if state.exists():
        data = json.loads(state.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("状态文件格式无效；不会自动覆盖。")
        binding = BindingState(state, data.get("mac"))
    size = 0
    if args.workout:
        workout = _private_path(args.workout)
        WorkoutFiles(workout)
        size = workout.stat().st_size
    workout_dir = getattr(args, "workout_dir", None)
    if workout_dir:
        workout_dir = _private_path(workout_dir)
        _workouts(args.workout, workout_dir)
    requested_stop = Path(args.stop_file) if getattr(args, "stop_file", None) else None

    def check_stop():
        if requested_stop is not None and requested_stop.exists():
            raise KeyboardInterrupt
    # Fail before starting anything if another capture already owns this endpoint.
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind(("0.0.0.0", _PORT))
        if binding is not None and binding.bound:
            if args.reset_binding:
                binding.reply(b"\x01\x06")  # Same local unbind operation as the state CLI.
                emit("本地绑定标记已重置，配置与运动接收记录保留；没有修改 Keep 云端绑定。")
            else:
                emit("本地仍为已绑定；若要重新添加，请先在 Keep 解绑，再使用 -ResetBinding / --reset-binding 启动。")
    events = queue.Queue()
    processes = {}
    status = Status(size, emit, event)
    with tempfile.TemporaryDirectory(prefix="keep-b5-", dir=state.parent) as private:
        stop_file = Path(private) / "stop"
        original_error = None
        try:
            check_stop()
            processes["btvs"] = _spawn([args.btvs, "-Mode", "Wireshark", "-Remote", "on",
                                         "-Port", str(_PORT)], "btvs", events)
            deadline = time.monotonic() + 15
            while not _tcp_state(processes["btvs"].pid, "LISTENING"):
                check_stop()
                if processes["btvs"].poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("BTVS 未能开始监听；B5 未启动。")
                time.sleep(0.1)
            command = [args.tshark, "-l", "-n", "-i", f"TCP@127.0.0.1:{_PORT}",
                       "-Y", _FILTER, "-T", "fields"]
            for field in _FIELDS:
                command.extend(["-e", field])
            processes["capture"] = _spawn(command, "capture", events, separate_stderr=True)
            _await_capture(processes["btvs"], processes["capture"], events)
            check_stop()
            command = [sys.executable, "-u", "-m", "experiments.keep_device.windows", "--model", "B5",
                       "--keep-name", "--duration", str(args.duration), "--state", str(state),
                       "--stop-file", str(stop_file)]
            if args.workout:
                command.extend(["--workout", str(workout)])
            if workout_dir:
                command.extend(["--workout-dir", str(workout_dir)])
            processes["prototype"] = _spawn(command, "prototype", events)
            emit("地址观察已就绪，正在启动 B5。按 Ctrl+C 停止并等待名称恢复。")
            emit(f"本轮广播持续 {args.duration:g} 秒，到期自动停止。")
            emit("广播地址由 Windows 管理，可能变化；此入口不保证跨重启自动重连。")
            emit("本轮结束建议先在 Keep 解绑，再停止脚本；若已先停止，可在 Keep 解绑后用 -ResetBinding 恢复本地标记。")
            if size:
                emit(f"已加载运动文件：{size} 字节；已有接收标记会保留，不重复发送。")
            deadline = time.monotonic() + 90
            prototype_eof = False
            while True:
                check_stop()
                try:
                    source, line = events.get(timeout=0.2)
                except queue.Empty:
                    source, line = None, None
                if line is not None:
                    if source == "capture":
                        status.capture(line)
                    elif source == "prototype":
                        status.prototype(line)
                elif source == "prototype":
                    prototype_eof = True
                if processes["prototype"].poll() is not None and prototype_eof:
                    if processes["prototype"].returncode:
                        detail = status.last_diagnostic or "请检查依赖、管理员权限或名称恢复。"
                        raise RuntimeError(f"B5 退出失败（exit {processes['prototype'].returncode}）：{detail}")
                    if status.last_mac is None:
                        raise RuntimeError("B5 已退出，但本轮未取得有效广播 MAC；启动未通过验证。")
                    break
                if any(processes[name].poll() is not None for name in ("btvs", "capture")):
                    raise RuntimeError("地址观察已中断，正在停止 B5；此前 MAC 不再保证有效。")
                if status.last_mac is None and time.monotonic() >= deadline:
                    raise RuntimeError("未观察到有效 B5 广播 MAC，正在停止；不会用适配器地址代替。")
        except KeyboardInterrupt:
            emit("正在停止，请等待电脑蓝牙名称恢复。")
        except Exception as error:
            original_error = error
            raise
        finally:
            event(dict(type="stopping"))
            previous_interrupt = signal.signal(signal.SIGINT, signal.SIG_IGN)
            try:
                stop_file.touch()
                prototype = processes.get("prototype")
                cleanup_failed = False
                if prototype is not None:
                    try:
                        prototype.wait(timeout=90)
                        if prototype.returncode:
                            cleanup_failed = True
                    except subprocess.TimeoutExpired:
                        cleanup_failed = True
                        try:
                            _terminate_child_tree(prototype)
                        except (OSError, RuntimeError, subprocess.SubprocessError):
                            cleanup_failed = True
                    while not events.empty():
                        source, line = events.get_nowait()
                        if source == "prototype" and line is not None:
                            status.prototype(line)
                for name in ("capture", "btvs"):
                    process = processes.get(name)
                    if process is not None and process.poll() is None:
                        try:
                            _terminate_child_tree(process)
                        except (OSError, RuntimeError, subprocess.SubprocessError):
                            cleanup_failed = True
                if cleanup_failed:
                    raise RuntimeError("退出清理未全部完成：请检查本次进程和电脑蓝牙实际名称。")
            except Exception as cleanup_error:
                if original_error is None:
                    raise
                emit(f"附加清理失败：{cleanup_error}")
            finally:
                signal.signal(signal.SIGINT, previous_interrupt)


async def check_environment():
    """Read capabilities only; do not rename, restart or start advertising."""
    from importlib.metadata import version
    from winrt.windows.devices.bluetooth import BluetoothAdapter
    from winrt.windows.devices.radios import RadioState
    import bless  # Verify the configured interpreter can load the runtime.

    adapter = await asyncio.wait_for(BluetoothAdapter.get_default_async(), 10)
    radio = await asyncio.wait_for(adapter.get_radio_async(), 10) if adapter else None
    checks = dict(python=sys.version_info[:2] == (3, 11), bless=version("bless") == "0.3.0",
                  administrator=bool(ctypes.windll.shell32.IsUserAnAdmin()),
                  peripheral=bool(adapter and adapter.is_peripheral_role_supported),
                  radio_on=bool(radio and radio.state == RadioState.ON))
    return dict(checks=checks, ready=all(checks.values()), python_version=sys.version.split()[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--btvs", required=True, type=_tool, help="Microsoft BTVS executable")
    parser.add_argument("--tshark", required=True, type=_tool, help="Wireshark TShark executable")
    parser.add_argument("--state", required=True, help="Private persistent state JSON outside the repository")
    workouts = parser.add_mutually_exclusive_group()
    workouts.add_argument("--workout", help="Optional private SPORT44 file")
    workouts.add_argument("--workout-dir", help="Optional fixed directory of SPORT44 files")
    parser.add_argument("--stop-file", help="Private panel signal for graceful shutdown")
    parser.add_argument("--events-json", action="store_true", help="Emit structured lifecycle events for the local panel")
    parser.add_argument("--check", action="store_true", help="Read environment capabilities without changing Bluetooth")
    parser.add_argument("--reset-binding", action="store_true",
                        help="Reset only local binding before startup; first unbind this device in Keep")
    parser.add_argument("--duration", type=_duration, default=3600, help="advertising seconds (default: 3600)")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.exit(1, "此入口仅支持 Windows。\n")
    if args.check:
        try:
            print(json.dumps(asyncio.run(check_environment())), flush=True)
        except Exception as error:
            parser.exit(1, f"环境检查失败（{type(error).__name__}），请核对独立 Python 与 Windows 蓝牙驱动。\n")
        return
    if not ctypes.windll.shell32.IsUserAnAdmin():
        parser.exit(1, "请在管理员终端运行；更名和启动电脑蓝牙需要管理员权限。\n")
    try:
        event = lambda data: print("WATCH_EVENT " + json.dumps(data), flush=True) if args.events_json else None
        run(args, lambda message: print(message, flush=True), event)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        if args.events_json:
            event(dict(type="error", message=str(error)))
        parser.exit(1, f"启动或运行失败：{error}\n")


if __name__ == "__main__":
    main()
