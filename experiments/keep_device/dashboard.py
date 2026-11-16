"""Opt-in watch panel extending the existing Web generator; localhost only."""

import argparse
import atexit
from datetime import date
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
from uuid import uuid4

from bumble.hci import Address
from flask import jsonify, render_template, request
from jinja2 import ChoiceLoader, FileSystemLoader

from web import routes
from .emulator import static_address
from .exporter import B5Exporter
from .files import WorkoutFiles
from .state import BindingState

ROOT = Path(__file__).resolve().parents[2]


class Watch:
    """Own one Netsim process and retain its selected files and receipts."""

    def __init__(self, lab, state, netsim_ini, workout_dir=None):
        self.lab, self.state = Path(lab).resolve(), Path(state).resolve()
        if self.lab.is_relative_to(ROOT) or self.state.is_relative_to(ROOT):
            raise ValueError("手表数据和状态必须保存在仓库外。")
        self.lab.mkdir(parents=True, exist_ok=True)
        self.netsim_ini = Path(netsim_ini)
        self.selection = self.lab / "selection.json"
        self.directory = Path(workout_dir).resolve() if workout_dir else None
        if self.directory is None and self.selection.exists():
            self.directory = Path(json.loads(self.selection.read_text(encoding="utf-8"))["directory"]).resolve()
        self.mac = str(static_address(json.loads(self.state.read_text(encoding="utf-8"))["mac"])) if self.state.exists() else str(Address.generate_static_address())
        BindingState(self.state, self.mac)
        self.lock = threading.RLock()
        self.process = None
        self.ready = self.connected = False
        self.error = None
        self.stop_path = None
        self.queue = self._queue()

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
            return dict(running=running, ready=running and self.ready,
                        connected=running and self.connected, mac=self.mac,
                        keep_mac=self.mac.replace(":", ""),
                        binding_address=dict(value=self.mac if running and self.ready else None, medium="virtual"),
                        transport="netsim", records=records, error=error,
                        total_km=round(sum(r["distance_km"] for r in records), 3),
                        pending=sum(not r["received"] for r in records),
                        received=sum(r["received"] for r in records))

    def start(self):
        with self.lock:
            if self.running():
                return
            queue = self._queue()
            queue.inventory()
            values = dict(line.split("=", 1) for line in self.netsim_ini.read_text().splitlines() if "=" in line)
            port = int(values["grpc.port"])
            if not 1 <= port <= 65535:
                raise ValueError("模拟器蓝牙端口无效。")
            run_id = uuid4().hex
            self.stop_path = self.lab / (run_id + ".stop")
            self.ready = self.connected = False
            self.error = None
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
            timer = threading.Timer(20, self._startup_timeout, args=(self.process, self.stop_path))
            timer.daemon = True
            timer.start()

    def _startup_timeout(self, process, stop_path):
        with self.lock:
            if self.process is process and process.poll() is None and not self.ready:
                self.error = "广播启动超时，请检查模拟器蓝牙后重试。"
                self.stop()

    def _read(self, process, log_path):
        try:
            with log_path.open("x", encoding="utf-8") as log:
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    if self.process is not process:
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
            if self.process is process:
                self.connected = self.ready = False
                if code and not self.error:
                    self.error = "广播已异常停止，请检查模拟器后重试。"

    def stop(self):
        with self.lock:
            if not self.running():
                return
            self.stop_path.touch()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"], check=True,
                                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    self.process.terminate()
                self.process.wait(timeout=5)
            self.connected = self.ready = False

    def load(self, directory):
        with self.lock:
            directory = Path(directory).resolve()
            self._queue(directory).inventory()
            if directory == self.directory:
                self.start()
                return
            self.queue.refresh_receipts()
            if any(not item["received"] for item in self.queue.inventory()):
                raise ValueError("手表还有待同步记录，请先完成当前同步，再载入下一批。")
            self.stop()
            temporary = self.selection.with_suffix(".tmp")
            temporary.write_text(json.dumps({"directory": str(directory)}), encoding="utf-8")
            temporary.replace(self.selection)
            self.directory = directory
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

    @app.post("/api/watch/<action>")
    def control(action):
        try:
            if action == "start":
                watch.start()
            elif action == "stop":
                watch.stop()
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
                watch.load(directory)
            else:
                return jsonify(error="未知操作。"), 404
            return jsonify(watch.snapshot())
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            return jsonify(error=str(exc)), 400

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--netsim-ini", required=True)
    parser.add_argument("--workout-dir")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    watch = Watch(args.lab, args.state, args.netsim_ini, args.workout_dir)
    atexit.register(watch.stop)
    watch.start()
    create_app(watch).run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
