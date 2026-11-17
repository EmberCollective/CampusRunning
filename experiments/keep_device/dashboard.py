"""Opt-in watch panel extending the existing Web generator; localhost only."""

import argparse
import atexit
from io import BytesIO
from collections import deque
from datetime import date, datetime
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
from uuid import uuid4

from flask import jsonify, render_template, request
from jinja2 import ChoiceLoader, FileSystemLoader
import segno

from web import routes
from .exporter import B5Exporter
from .files import WorkoutFiles
from .state import BindingState, device_state_lock

ROOT = Path(__file__).resolve().parents[2]


class Watch:
    """Own one transport process and retain selected files and receipts."""

    def __init__(self, lab, state, netsim_ini=None, workout_dir=None, *, transport=None,
                 windows_python=None, btvs=None, tshark=None, windows_state=None):
        self.lab = Path(lab).resolve()
        initial_state = Path(state).resolve()
        initial_windows_state = Path(windows_state).resolve() if windows_state else initial_state.with_stem(initial_state.stem + "-windows")
        if self.lab.is_relative_to(ROOT):
            raise ValueError("手表数据和状态必须保存在仓库外。")
        self.lab.mkdir(parents=True, exist_ok=True)
        self.config_path = self.lab / "connection.json"
        self.config = json.loads(self.config_path.read_text(encoding="utf-8")) if self.config_path.exists() else {}
        if not isinstance(self.config, dict) or set(self.config) - {"transport", "python", "btvs", "tshark", "netsim_ini", "netsim_state", "windows_state"} or any(not isinstance(v, str) for v in self.config.values()):
            raise ValueError("连接配置格式无效，不会自动覆盖。")
        self.config.setdefault("netsim_state", str(initial_state))
        self.config.setdefault("windows_state", str(initial_windows_state))
        self._validate_state_paths(self.config)
        if netsim_ini is not None:
            self.config["netsim_ini"] = str(Path(netsim_ini).resolve())
        self.config.setdefault("netsim_ini", "")
        self.config.setdefault("transport", "netsim" if self.config["netsim_ini"] else "windows")
        for key, value in (("python", windows_python), ("btvs", btvs), ("tshark", tshark)):
            if value is not None:
                self.config[key] = str(value)
            self.config.setdefault(key, shutil.which(key if key != "python" else "python3.11") or "")
        if transport is not None:
            self.config["transport"] = transport
        if self.config["transport"] not in ("netsim", "windows"):
            raise ValueError("不支持的连接路线。")
        self.selection = self.lab / "selection.json"
        self.loaded_job = None
        self.directory = Path(workout_dir).resolve() if workout_dir else None
        if self.directory is None and self.selection.exists():
            self.directory = Path(json.loads(self.selection.read_text(encoding="utf-8"))["directory"]).resolve()
        self.mac = self._identity()
        self.lock = threading.RLock()
        self.events = deque(maxlen=100)
        self.process = None
        self.ready = self.connected = False
        self.error = None
        self.air_mac = None
        self.operation = None
        self.stopping = False
        self.stop_path = None
        self.queue = self._queue()

    @property
    def transport(self):
        return self.config["transport"]

    @property
    def state(self):
        return self.windows_state if self.transport == "windows" else self.netsim_state

    @property
    def netsim_state(self):
        return Path(self.config["netsim_state"])

    @property
    def windows_state(self):
        return Path(self.config["windows_state"])

    @property
    def netsim_ini(self):
        return Path(self.config["netsim_ini"]) if self.config["netsim_ini"] else None

    def _validate_state_paths(self, config):
        for key in ("netsim_state", "windows_state"):
            value = config[key]
            if not isinstance(value, str) or not 0 < len(value) <= 4096:
                raise ValueError("请填写有效的设备状态文件完整路径。")
            path = Path(value).resolve()
            if path.is_relative_to(ROOT) or path in (self.config_path, self.config_path.with_suffix(".tmp"), self.lab / "selection.json"):
                raise ValueError("设备状态必须保存在仓库外，且不能覆盖面板配置或文件清单。")
            if path.exists() and not path.is_file():
                raise ValueError("设备状态路径必须指向 JSON 文件，不能是文件夹。")
            config[key] = str(path)
        if Path(config["netsim_state"]) == Path(config["windows_state"]):
            raise ValueError("Windows 与 Netsim 必须使用独立设备状态。")

    def _identity(self, transport=None, config=None):
        transport = transport or self.transport
        state = Path((config or self.config)[transport + "_state"])
        mac = None
        if state.exists():
            data = json.loads(state.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("mac"), str):
                raise ValueError("设备状态文件无效，不会自动覆盖。")
            mac = data["mac"]
        if transport == "windows":
            if mac is not None:
                BindingState(state, mac)
        else:
            from bumble.hci import Address
            from .emulator import static_address
            mac = str(static_address(mac)) if mac else str(Address.generate_static_address())
            state.parent.mkdir(parents=True, exist_ok=True)
            BindingState(state, mac)
        return mac

    def configuration(self):
        with self.lock:
            return dict(self.config, running=self.running(), operation=self.operation,
                        netsim_configured=self.netsim_ini is not None,
                        config_file=str(self.config_path), data_dir=str(self.lab))

    def _validated_config(self, data):
        if not isinstance(data, dict) or set(data) - {"transport", "python", "btvs", "tshark", "netsim_ini", "netsim_state", "windows_state"} or any(not isinstance(v, str) for v in data.values()):
            raise ValueError("连接配置格式无效。")
        config = dict(self.config, **data)
        self._validate_state_paths(config)
        if config["transport"] == "netsim":
            if not 0 < len(config["netsim_ini"]) <= 4096:
                raise ValueError("请填写模拟器生成的 netsim.ini 完整路径。")
            config["netsim_ini"] = str(Path(config["netsim_ini"]).resolve())
        elif config["transport"] == "windows":
            if sys.platform != "win32":
                raise ValueError("实体蓝牙路线仅支持 Windows。")
            for key in ("python", "btvs", "tshark"):
                value = config.get(key)
                if not isinstance(value, str) or not 0 < len(value) <= 4096 or not shutil.which(value):
                    raise ValueError(f"请填写有效的 {key} 程序位置。")
                config[key] = str(Path(shutil.which(value)).resolve())
        else:
            raise ValueError("该连接路线尚未接入。")
        return config

    def configure(self, data):
        with self.lock:
            if self.running() or self.operation:
                raise ValueError("请先停止广播，等待退出清理完成后再修改连接配置。")
            config = self._validated_config(data)
            mac = self._identity(config["transport"], config)
            temporary = self.config_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(config), encoding="utf-8")
            temporary.replace(self.config_path)
            self.config = config
            self.mac = mac
            self.process = None
            self.air_mac = None
            self.ready = self.connected = False
            self.error = None
            self._note("连接配置已保存，路线=" + self.transport + "；未启动广播")

    def check(self, data=None):
        with self.lock:
            config = self._validated_config(data if data is not None else {})
        if config["transport"] == "netsim":
            exists = Path(config["netsim_ini"]).is_file()
            return dict(ready=exists, checks={"netsim_ini": exists})
        result = subprocess.run([config["python"], "-m", "experiments.keep_device.launcher", "--check",
                                 "--state", str(self.windows_state), "--btvs", config["btvs"], "--tshark", config["tshark"]],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
                                env={**os.environ, "PYTHONUTF8": "1"},
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode:
            raise ValueError("Windows 环境检查未完成；请检查 Python 3.11、Bless 及工具依赖。" + result.stderr[-400:])
        return json.loads(result.stdout)

    def reset_binding(self, data):
        with self.lock:
            if (not isinstance(data, dict) or data.get("keep_unbound") is not True
                    or data.get("transport") != self.transport):
                raise ValueError("请确认 Keep 已解绑，并重新确认当前连接路线。")
            if self.running() or self.operation or self.stopping:
                raise ValueError("请先停止广播，等待退出清理完成后再删除本地绑定记录。")
            if not self.state.is_file():
                raise ValueError("当前路线没有本地绑定记录，无需删除。")
            with device_state_lock(self.state):
                stored = json.loads(self.state.read_text(encoding="utf-8"))
                if not isinstance(stored, dict):
                    raise ValueError("设备状态文件无效，不会自动覆盖。")
                BindingState(self.state, stored.get("mac")).reply(b"\x01\x06")
            self._note("本地绑定标记已清除，路线=" + self.transport + "；保留设备身份、配置与文件接收标记")

    def _note(self, message):
        with self.lock:
            self.events.append(datetime.now().astimezone().isoformat(timespec="seconds") + " " + message)

    def logs(self):
        # Only our diagnostic summaries are shown; Bumble debug traffic may contain user data.
        allowed = ("BATCH_READY", "ADVERTISING", "CONNECTED;", "DISCONNECTED", "STOPPED", "SUBSCRIPTION",
                   "DEVICE_INFO_SENT", "DEVICE_REPLY_SENT", "FILE_REPLY_SENT", "UNSUBSCRIBED_WRITE",
                   "UNSUPPORTED_WRITE", "DEVICE_STATE_FAILED", "WRITE_REJECTED", "DEVICE_INFO_FAILED",
                   "INFO:experiments.keep_device.files:file_transfer", "INFO:experiments.keep_device.files:workout_batch",
                   "Unable to start", "当前广播 MAC", "广播地址已变化", "蓝牙客户端", "设备信息已应答",
                   "已回应绑定请求", "运动文件已发送", "手机已确认领取", "运动目录为空", "手机开始读取",
                   "设备请求未完成", "B5 已启动", "B5 广播已停止", "电脑蓝牙名称配置已恢复", "正在停止",
                   "本地仍为已绑定", "本地绑定标记已重置", "地址观察已就绪", "本轮广播持续")
        with self.lock:
            text = ["当前路线：" + self.transport, "连接配置：" + str(self.config_path),
                    "设备状态：" + str(self.state), "", "面板操作（本次启动）：", *self.events]
        files = sorted((p for p in self.lab.glob("*.log") if p.is_file() and not p.is_symlink()),
                       key=lambda p: p.stat().st_mtime)[-3:]
        for path in files:
            text += ["", "── 广播日志 " + path.name + " ──"]
            try:
                with path.open("rb") as stream:
                    stream.seek(max(0, path.stat().st_size - 65536))
                    lines = stream.read(65536).decode("utf-8", errors="replace").splitlines()[-300:]
                visible = []
                for line in lines:
                    line = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line)
                    message = re.sub(r"^\d{4}-\d{2}-\d{2}T\S+ ", "", line)
                    if message.startswith(allowed):
                        line = re.sub(r"(?i)\b(token|password|authorization|account)=\S+", r"\1=[已隐藏]", line)
                        visible.append(line[:1500])
                text += visible or ["暂无连接事件，等待广播输出"]
            except OSError as exc:
                text.append("日志读取失败：" + type(exc).__name__)
        if not files:
            text += ["", "暂无广播日志；手动启动广播后自动更新"]
        return dict(text="\n".join(text), files=len(files))

    def control(self, action, directory=None, job_id=None):
        if action not in ("start", "stop", "load"):
            raise ValueError("未知操作。")
        with self.lock:
            if self.operation:
                raise ValueError("上一项操作尚未完成，请等待当前状态更新。")
            if self.stopping and self.running() and action != "stop":
                raise ValueError("请等待 Windows 退出清理完成后再启动或载入。")
            self.operation = action
            self.error = None
            self._note("收到操作：" + action + "，路线=" + self.transport)
            background = self.transport == "windows"
        def execute():
            try:
                if action == "load":
                    self.load(directory, job_id)
                else:
                    getattr(self, action)()
            except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as exc:
                with self.lock:
                    self.error = str(exc)
                    self._note("操作失败：" + type(exc).__name__ + "：" + str(exc))
                if not background:
                    raise
            finally:
                with self.lock:
                    self.operation = None
        if background:
            threading.Thread(target=execute, daemon=True).start()
        else:
            execute()

    def _queue(self, directory=None):
        directory = directory or self.directory
        if directory is None:
            return WorkoutFiles(None)
        directory = Path(directory).resolve()
        if directory.is_relative_to(ROOT) or not directory.is_dir():
            raise ValueError("请选择仓库外的有效运动文件目录。")
        return WorkoutFiles(None, paths=sorted(directory.glob("*.sport44")))

    def running(self):
        return self.process is not None and self.process.poll() is None

    def snapshot(self):
        with self.lock:
            records, error = [], self.error
            try:
                self.queue.refresh_receipts()
                records = self.queue.inventory()
            except (OSError, ValueError) as exc:
                error = "运动文件校验失败，请停止广播并检查文件：" + str(exc)
            running = self.running()
            address = self.mac if self.transport == "netsim" else self.air_mac
            return dict(running=running, ready=running and self.ready,
                        connected=running and self.connected, mac=self.mac,
                        keep_mac=address.replace(":", "") if address and running and self.ready and not self.stopping else None,
                        binding_address=dict(value=address if running and self.ready and not self.stopping else None,
                                             medium="physical" if self.transport == "windows" else "virtual"),
                        transport=self.transport, operation=self.operation, stopping=self.stopping,
                        loaded_job=self.loaded_job, records=records, error=error,
                        total_km=round(sum(r["distance_km"] for r in records), 3),
                        pending=sum(not r["received"] for r in records),
                        received=sum(r["received"] for r in records))

    def start(self):
        with self.lock:
            if self.running():
                return
            queue = self._queue()
            queue.inventory()
        if self.transport == "windows":
            if not self.check()["ready"]:
                raise ValueError("本机检查未通过；请确认管理员权限、Python 3.11、蓝牙开启及外设广播能力。")
            self.windows_state.parent.mkdir(parents=True, exist_ok=True)
        else:
            if self.netsim_ini is None:
                raise ValueError("请先配置 Netsim。")
            values = dict(line.split("=", 1) for line in self.netsim_ini.read_text().splitlines() if "=" in line)
            port = int(values["grpc.port"])
            if not 1 <= port <= 65535:
                raise ValueError("模拟器蓝牙端口无效。")
        with self.lock:
            run_id = uuid4().hex
            self.stop_path = self.lab / (run_id + ".stop")
            self.ready = self.connected = False
            self.air_mac = None
            self.stopping = False
            self.error = None
            if self.transport == "windows":
                command = [self.config["python"], "-u", "-m", "experiments.keep_device.launcher", "--events-json",
                           "--btvs", self.config["btvs"], "--tshark", self.config["tshark"],
                           "--state", str(self.state), "--stop-file", str(self.stop_path)]
            else:
                command = [sys.executable, "-u", "-m", "experiments.keep_device.emulator",
                           f"android-netsim:127.0.0.1:{port}", "--model", "B5", "--address", self.mac,
                           "--state", str(self.state), "--stop-file", str(self.stop_path)]
            if self.directory is not None:
                command += ["--workout-dir", str(self.directory)]
            self.process = subprocess.Popen(
                command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(ROOT)},
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            self.queue = queue
            threading.Thread(target=self._read, args=(self.process, self.lab / (run_id + ".log")), daemon=True).start()
            timer = threading.Timer(120 if self.transport == "windows" else 20, self._startup_timeout, args=(self.process, self.stop_path))
            timer.daemon = True
            timer.start()

    def _startup_timeout(self, process, stop_path):
        with self.lock:
            if self.process is not process or process.poll() is not None or self.ready:
                return
            self.error = "广播启动超时，请检查蓝牙环境后重试。"
        self.stop(expected_process=process)

    def _event(self, process, event):
        if self.process is not process:
            return
        kind = event.get("type")
        if kind in ("stopping", "stopped", "error"):
            self.air_mac = None
            self.ready = self.connected = False
            self.stopping = True
            if kind == "error":
                self.error = event.get("message", "Windows 广播运行失败。")
        elif not self.stopping:
            if kind == "advertising":
                self.ready = True
                self.mac = event.get("identity") or self.mac
            elif kind == "address":
                value = event.get("value")
                self.air_mac = value if isinstance(value, str) and re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", value) else None
            elif kind == "link":
                self.connected = event.get("connected") is True
                if event.get("ambiguous"):
                    self.error = "存在多个订阅客户端，请断开多余设备，只连接一台手机。"
                else:
                    self.error = None

    def _read(self, process, log_path):
        try:
            with log_path.open("x", encoding="utf-8") as log:
                for line in process.stdout:
                    log.write(datetime.now().astimezone().isoformat(timespec="seconds") + " " + line)
                    log.flush()
                    if self.process is not process:
                        continue
                    if self.transport == "windows":
                        if line.startswith("WATCH_EVENT "):
                            with self.lock:
                                try:
                                    event = json.loads(line[len("WATCH_EVENT "):])
                                    if not isinstance(event, dict):
                                        raise ValueError("Invalid event")
                                    self._event(process, event)
                                except ValueError:
                                    self.error = "Windows 广播状态无效，正在停止本轮广播，请检查运行日志。"
                                    self.ready = self.connected = False
                                    self.air_mac = None
                                    self.stopping = True
                                    self.stop_path.touch()
                        continue
                    if line.startswith("ADVERTISING"):
                        self.ready = True
                    elif line.startswith("CONNECTED;"):
                        self.connected = True
                    elif line.startswith(("DISCONNECTED", "STOPPED")):
                        self.connected = False
                    elif line.startswith("Unable to start"):
                        self.error = "广播启动失败，请检查模拟器及文件校验结果。"
        finally:
            process.stdout.close()
            code = process.wait()
            with self.lock:
                if self.process is process:
                    self.connected = self.ready = False
                    self.air_mac = None
                    self.stopping = False
                    if code and not self.error:
                        self.error = "广播已异常停止，请检查运行环境及本轮日志后重试。"

    def stop(self, expected_process=None):
        with self.lock:
            if (expected_process is not None and self.process is not expected_process) or not self.running():
                return
            self.stop_path.touch()
            self.stopping = True
            self.ready = self.connected = False
            self.air_mac = None
            process = self.process
        try:
            process.wait(timeout=100 if self.transport == "windows" else 8)
        except subprocess.TimeoutExpired:
            if self.transport == "windows":
                self.error = "Windows 退出清理超时；请检查本轮进程与蓝牙名称恢复后再启动。"
                raise RuntimeError(self.error)
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=True,
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                process.terminate()
            process.wait(timeout=5)
        with self.lock:
            self.connected = self.ready = False
            self.stopping = False

    def load(self, directory, job_id=None):
        with self.lock:
            directory = Path(directory).resolve()
            self._queue(directory).inventory()
            self.queue.refresh_receipts()
            same = directory == self.directory
            if not same and any(not item["received"] for item in self.queue.inventory()):
                raise ValueError("手表还有待同步记录，请先完成当前同步，再载入下一批。")
        if not same:
            self.stop()
            with self.lock:
                temporary = self.selection.with_suffix(".tmp")
                temporary.write_text(json.dumps({"directory": str(directory)}), encoding="utf-8")
                temporary.replace(self.selection)
                self.directory = directory
                self.queue = self._queue()
        self.loaded_job = job_id
        self.start()


def create_app(watch):
    app = routes.create_app(exporters={"b5": B5Exporter()})
    app.config.update(WATCH_ENABLED=True, WATCH_TOKEN=secrets.token_urlsafe(32),
                      TRUSTED_HOSTS=["localhost", "127.0.0.1"], MAX_CONTENT_LENGTH=1024 * 1024)
    app.jinja_loader = ChoiceLoader([app.jinja_loader, FileSystemLoader(Path(__file__).parent / "templates")])

    @app.before_request
    def protect_watch_actions():
        if request.method != "POST":
            return None
        data = request.get_json(silent=True)
        b5_generation = request.path.startswith("/api/generate/") and isinstance(data, dict) and data.get("output_format") == "b5"
        if not (request.path.startswith("/api/watch/") or b5_generation):
            return None
        if not secrets.compare_digest(request.headers.get("X-Watch-Token", ""), app.config["WATCH_TOKEN"]):
            return jsonify(error="页面已过期，请刷新后重试。"), 403
        if b5_generation:
            try:
                if any(data.get(flag, True) is not True for flag in ("include_track", "apply_correction", "enable_cadence")):
                    raise ValueError("B5 数据必须开启轨迹、坐标转换和步频。")
                if "start_date" in data and "end_date" in data:
                    days = (date.fromisoformat(data["end_date"]) - date.fromisoformat(data["start_date"])).days + 1
                    if not 1 <= days <= 64:
                        raise ValueError("B5 每批请选择 1–64 天。")
                if "dates" in data and (not isinstance(data["dates"], list) or not 1 <= len(data["dates"]) <= 64):
                    raise ValueError("B5 每批请选择 1–64 个日期。")
                data["output_dir"] = str(watch.lab / ("generated-" + uuid4().hex))
            except (TypeError, ValueError) as exc:
                return jsonify(error=str(exc)), 400

    @app.get("/watch")
    def watch_page():
        job_id = request.args.get("job", "")
        results = routes._generation_jobs.get(job_id, [])
        candidate = dict(id=job_id, count=len(results), km=round(sum(r.distance_km for r in results), 2)) if results and all(Path(r.filepath).suffix == ".sport44" for r in results) else None
        return render_template("watch.html", token=app.config["WATCH_TOKEN"], candidate=candidate)

    @app.get("/api/watch/status")
    def status():
        response = jsonify(watch.snapshot())
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/watch/config")
    def configuration():
        response = jsonify(watch.configuration())
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/watch/binding-qr")
    def binding_qr():
        current = watch.snapshot()
        address = current["binding_address"]["value"]
        if (not current["running"] or not current["ready"] or current["stopping"]
                or current["operation"] or not isinstance(address, str)
                or not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", address)
                or request.args.get("mac") != address.replace(":", "")):
            response = jsonify(error="本轮地址不可用，请刷新连接状态后重试。")
            response.status_code = 409
        else:
            output = BytesIO()
            segno.make_qr(f"keep://kitbit/bindInfo?mac={address.replace(':', '')}&type=B5",
                          error="m").save(output, kind="png", scale=6, border=4)
            response = app.response_class(output.getvalue(), mimetype="image/png")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/watch/logs")
    def logs():
        if not secrets.compare_digest(request.headers.get("X-Watch-Token", ""), app.config["WATCH_TOKEN"]):
            return jsonify(error="页面已过期，请刷新后重试。"), 403
        response = jsonify(watch.logs())
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/watch/<action>")
    def control(action):
        try:
            if action == "config":
                watch.configure(request.get_json(silent=True))
                return configuration()
            if action == "check":
                response = jsonify(watch.check(request.get_json(silent=True)))
                response.headers["Cache-Control"] = "no-store"
                return response
            if action in ("start", "stop"):
                watch.control(action)
            elif action == "reset-binding":
                watch.reset_binding(request.get_json(silent=True))
            elif action == "load":
                data = request.get_json(silent=True) or {}
                if not isinstance(data, dict) or not isinstance(data.get("job_id"), str):
                    raise ValueError("请选择有效的生成任务。")
                results = routes._generation_jobs.get(data.get("job_id"), [])
                if not results:
                    raise ValueError("生成任务不存在或已过期，请返回生成器。")
                files = [Path(result.filepath).resolve() for result in results]
                directory = files[0].parent
                if any(not p.is_relative_to(watch.lab) or p.parent != directory or p.suffix != ".sport44" for p in files):
                    raise ValueError("只能载入本面板生成的 B5 文件。")
                if set(directory.glob("*.sport44")) != set(files):
                    raise ValueError("生成目录已变化，请重新生成后载入。")
                watch.control("load", directory, data["job_id"])
            else:
                return jsonify(error="未知操作。"), 404
            return jsonify(watch.snapshot())
        except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as exc:
            watch._note(action + " 未完成：" + type(exc).__name__ + "：" + str(exc))
            return jsonify(error=str(exc)), 400

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--netsim-ini")
    parser.add_argument("--transport", choices=("netsim", "windows"))
    parser.add_argument("--windows-python", help="Independent Python 3.11 executable")
    parser.add_argument("--windows-state", help="Separate private Windows binding state")
    parser.add_argument("--btvs")
    parser.add_argument("--tshark")
    parser.add_argument("--no-start", action="store_true", help="Open the panel without starting Bluetooth")
    parser.add_argument("--workout-dir")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    watch = Watch(args.lab, args.state, args.netsim_ini, args.workout_dir, transport=args.transport,
                  windows_python=args.windows_python, windows_state=args.windows_state, btvs=args.btvs, tshark=args.tshark)
    atexit.register(watch.stop)
    if not args.no_start:
        watch.start()
    create_app(watch).run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
