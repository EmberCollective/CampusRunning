"""Launcher contracts using decoded logs and mocked processes; no live radio."""

from argparse import Namespace
import json
import queue
import shutil
import signal
import subprocess
import sys
from unittest.mock import Mock

import pytest

from experiments.keep_device import launcher
from experiments.keep_device.test_windows_mac import command, configure


def test_progress_counts_only_successfully_delivered_unique_file_ranges():
    output = []
    status = launcher.Status(1024, output.append)
    read = "INFO:file_transfer command=6/2 offset={offset} requested_length=2048 returned_length=512 status=0"
    sent = "FILE_REPLY_SENT bytes=22 sid=06 cid=02 flags=00"
    status.prototype(read.format(offset=0))
    assert status.sent == 0
    status.prototype("DEVICE_INFO_FAILED sid=06 cid=02 stage=notification")
    status.prototype(sent)
    assert status.sent == 0
    for offset in (0, 0, 256, 512):
        status.prototype(read.format(offset=offset))
        status.prototype(sent)
    assert status.sent == 1024
    assert status.ranges == [(0, 1024)]
    assert sum("运动文件已发送" in line for line in output) == 3
    assert not any("确认领取" in line for line in output)
    status.prototype("INFO:file_transfer command=6/7 type=44 status=1")
    status.prototype("FILE_REPLY_SENT bytes=20 sid=06 cid=07 flags=00")
    assert "有效性和入账仍需" in output[-1]


def test_disconnect_discards_pending_reply_and_unrelated_receipt_does_not_complete_workout():
    output = []
    status = launcher.Status(512, output.append)
    status.prototype("file_transfer command=6/2 offset=0 returned_length=512 status=0")
    status.prototype("SUBSCRIPTION clients=0; session reset")
    status.prototype("FILE_REPLY_SENT sid=06 cid=02 flags=00")
    assert status.sent == 0
    status.prototype("file_transfer command=6/7 type=6 status=1")
    status.prototype("FILE_REPLY_SENT sid=06 cid=07 flags=00")
    assert not any("确认领取" in line for line in output)
    status.prototype("file_transfer command=6/2 offset=256 returned_length=512 status=0")
    with pytest.raises(ValueError, match="outside"):
        status.prototype("FILE_REPLY_SENT sid=06 cid=02 flags=00")


def test_connection_events_do_not_claim_cloud_binding_success():
    output = []
    status = launcher.Status(emit=output.append)
    status.prototype("SUBSCRIPTION clients=1; session reset")
    status.prototype("DEVICE_INFO_SENT sid=01 cid=02 flags=00")
    status.prototype("DEVICE_REPLY_SENT sid=01 cid=05 flags=00")
    assert "等待业务请求" in output[0]
    assert "核对" in output[1]
    assert "不等同" in output[2]
    status.prototype("file_transfer command=6/1 type=44 entries=0")
    status.prototype("FILE_REPLY_SENT sid=06 cid=01 flags=00")
    assert output[-1] == "运动目录为空，无待传记录。"


def test_address_reuses_hci_tracker_and_warns_on_change_without_resetting_binding():
    output = []
    status = launcher.Status(emit=output.append)
    recorder = Mock()
    recorder.feed.side_effect = status.capture
    configure(recorder)
    command(recorder, 0x2039, enabled="0x01")
    assert "4123456789AB" in output[-1]
    command(recorder, 0x2039, enabled="0x00")
    assert "不可用" in output[-1]
    command(recorder, 0x2035, mac="42:23:45:67:89:AB")
    command(recorder, 0x2039, enabled="0x01")
    assert "先在 Keep 解绑" in output[-2]
    assert "4223456789AB" in output[-1]


def test_capture_banner_alone_is_not_ready(monkeypatch):
    events = queue.Queue()
    events.put(("capture-error", "Capturing on 'TCP@127.0.0.1:24352'"))
    events.put(("capture-error", "tshark: socket could not be connected"))
    btvs = Mock(pid=123)
    capture = Mock()
    btvs.poll.return_value = capture.poll.return_value = None
    monkeypatch.setattr(launcher, "_tcp_state", Mock(return_value=False))
    with pytest.raises(RuntimeError, match="无法开始观察"):
        launcher._await_capture(btvs, capture, events)


def test_capture_requires_established_stream(monkeypatch):
    events = queue.Queue()
    events.put(("capture-error", "Capturing on 'TCP@127.0.0.1:24352'"))
    btvs = Mock(pid=123)
    capture = Mock()
    btvs.poll.return_value = capture.poll.return_value = None
    tcp = Mock(return_value=True)
    monkeypatch.setattr(launcher, "_tcp_state", tcp)
    launcher._await_capture(btvs, capture, events)
    tcp.assert_called_once_with(123, "ESTABLISHED")


def test_netstat_ignores_gbk_headings_under_utf8_mode(monkeypatch):
    output = ("活动连接\r\n  协议  本地地址  外部地址  状态  PID\r\n"
              "  TCP  0.0.0.0:24352  0.0.0.0:0  LISTENING  123\r\n"
              "  TCP  127.0.0.1:24352  127.0.0.1:49152  ESTABLISHED  123\r\n").encode("gbk")
    run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout=output, stderr=b""))
    monkeypatch.setattr(launcher.subprocess, "run", run)
    monkeypatch.setattr(launcher.subprocess, "CREATE_NO_WINDOW", 0, raising=False)
    assert launcher._tcp_state(123, "LISTENING")
    assert launcher._tcp_state(123, "ESTABLISHED")
    assert not launcher._tcp_state(124, "LISTENING")
    assert not run.call_args.kwargs.get("text", False)


def test_private_state_and_workout_cannot_be_saved_in_repository():
    with pytest.raises(ValueError, match="仓库外"):
        launcher._private_path(launcher._ROOT / "private-state.json")


def test_capture_failure_never_starts_b5_and_cleans_only_owned_processes(monkeypatch, tmp_path):
    args = Namespace(state=str(tmp_path / "state.json"), workout=None,
                     btvs="btvs.exe", tshark="tshark.exe", duration=10, reset_binding=False)
    monkeypatch.setattr(launcher.socket, "socket", Mock(return_value=Mock(
        __enter__=Mock(return_value=Mock()), __exit__=Mock(return_value=False))))
    monkeypatch.setattr(launcher.socket, "SO_EXCLUSIVEADDRUSE", -5, raising=False)
    monkeypatch.setattr(launcher, "_tcp_state", Mock(return_value=True))
    processes = []

    def spawn(*args, **kwargs):
        process = Mock(pid=len(processes) + 1)
        process.poll.return_value = None
        processes.append(process)
        return process

    start = Mock(side_effect=spawn)
    monkeypatch.setattr(launcher, "_spawn", start)
    monkeypatch.setattr(launcher, "_await_capture", Mock(side_effect=RuntimeError("capture failed")))
    cleanup = Mock()
    monkeypatch.setattr(launcher, "_terminate_child_tree", cleanup)
    with pytest.raises(RuntimeError, match="capture failed"):
        launcher.run(args)
    assert start.call_count == 2
    assert [call.args[1] for call in start.call_args_list] == ["btvs", "capture"]
    assert [call.args[0] for call in cleanup.call_args_list] == list(reversed(processes))
    assert not (tmp_path / "state.json").exists()


@pytest.mark.parametrize("has_mac", [True, False])
def test_launcher_passes_stop_file_and_requires_verified_mac_before_success(monkeypatch, tmp_path, has_mac):
    args = Namespace(state=str(tmp_path / "state.json"), workout=None,
                     btvs="btvs.exe", tshark="tshark.exe", duration=10, reset_binding=False)
    monkeypatch.setattr(launcher.socket, "socket", Mock(return_value=Mock(
        __enter__=Mock(return_value=Mock()), __exit__=Mock(return_value=False))))
    monkeypatch.setattr(launcher.socket, "SO_EXCLUSIVEADDRUSE", -5, raising=False)
    monkeypatch.setattr(launcher, "_tcp_state", Mock(return_value=True))
    monkeypatch.setattr(launcher, "_await_capture", Mock())
    calls = []
    previous_interrupt = signal.getsignal(signal.SIGINT)

    def spawn(arguments, name, events, **kwargs):
        process = Mock(pid=123)
        process.poll.return_value = None
        if name == "prototype":
            stop = launcher.Path(arguments[arguments.index("--stop-file") + 1])
            process.poll.return_value = process.returncode = 0
            if has_mac:
                recorder = Mock()
                recorder.feed.side_effect = lambda line: events.put(("capture", line))
                configure(recorder)
                command(recorder, 0x2039, enabled="0x01")
            events.put(("prototype", "STOPPED"))
            events.put(("prototype", "NAME_REGISTRY_RESTORED"))
            events.put(("prototype", None))

            def wait(timeout):
                assert stop.exists()
                assert signal.getsignal(signal.SIGINT) == signal.SIG_IGN
                signal.raise_signal(signal.SIGINT)
                signal.raise_signal(signal.SIGINT)
                calls.append("prototype-exited")
                return 0

            process.wait.side_effect = wait
            assert "--keep-name" in arguments and "B5" in arguments
        process.name = name
        return process

    monkeypatch.setattr(launcher, "_spawn", spawn)
    monkeypatch.setattr(launcher, "_terminate_child_tree", lambda p: calls.append(p.name))
    output = []
    if has_mac:
        launcher.run(args, output.append)
    else:
        with pytest.raises(RuntimeError, match="未取得有效广播 MAC"):
            launcher.run(args, output.append)
    assert calls == ["prototype-exited", "capture", "btvs"]
    assert any("名称配置已恢复" in line for line in output)
    assert not list(tmp_path.iterdir())
    assert signal.getsignal(signal.SIGINT) == previous_interrupt


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell entry point")
@pytest.mark.parametrize("exit_code", [0, 7])
def test_powershell_wrapper_preserves_spaces_location_encoding_and_exit_code(tmp_path, exit_code):
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    output = tmp_path / "arguments.json"
    fake_python = tmp_path / "fake python.ps1"
    fake_python.write_text(
        "@{argv=@($args);cwd=$PWD.Path;encoding=$env:PYTHONIOENCODING;utf8=$env:PYTHONUTF8} "
        f"| ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath {quote(output)}\n"
        f"$global:LASTEXITCODE = {exit_code}\n", encoding="utf-8")
    harness = tmp_path / "harness.ps1"
    harness.write_text(
        "$ErrorActionPreference='Stop'\n"
        f"function Get-Command {{ [pscustomobject]@{{Source={quote(fake_python)}}} }}\n"
        "$env:PYTHONIOENCODING='ascii'; $env:PYTHONUTF8='0'; $before=$PWD.Path\n"
        f"& {quote(launcher.Path(launcher.__file__).with_name('start-b5.ps1'))} "
        "-Python 'fake python.exe' -Btvs 'fake btvs.exe' -Tshark 'fake tshark.exe' "
        "-State 'state space.json' -Workout 'workout space.sport44' -Duration 12.5 "
        f"{'-ResetBinding' if exit_code else ''}\n"
        f"if ($LASTEXITCODE -ne {exit_code}) {{throw 'exit code changed'}}\n"
        "if ($PWD.Path -ne $before) {throw 'location changed'}\n"
        "if ($env:PYTHONIOENCODING -ne 'ascii' -or $env:PYTHONUTF8 -ne '0') {throw 'encoding changed'}\n",
        encoding="utf-8")
    result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(harness)], cwd=tmp_path, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    data = json.loads(output.read_text(encoding="utf-8-sig"))
    assert launcher.Path(data["cwd"]) == launcher._ROOT
    assert data["encoding"] == "utf-8" and data["utf8"] == "1"
    arguments = data["argv"]
    assert arguments[arguments.index("--state") + 1] == str(tmp_path / "state space.json")
    assert arguments[arguments.index("--workout") + 1] == str(tmp_path / "workout space.sport44")
    assert arguments[arguments.index("--duration") + 1] == "12.5"
    assert ("--reset-binding" in arguments) is bool(exit_code)


@pytest.mark.parametrize("reset,port_available", [(False, True), (True, True), (True, False)])
def test_reset_binding_is_explicit_preserves_configuration_and_requires_free_port(monkeypatch, tmp_path,
                                                                                reset, port_available):
    state_path = tmp_path / "state.json"
    binding = launcher.BindingState(state_path, "C1:23:45:67:89:AB")
    binding.reply(bytes.fromhex("02 01 08 af 01 10 46 18 1e"))
    binding.reply(b"\x01\x05")
    before = state_path.read_bytes()
    config = json.loads(before)["config"]
    workout = tmp_path / "workout.sport44"
    receipt = tmp_path / "workout.sport44.received.json"
    workout.write_bytes(b"unchanged workout")
    receipt.write_bytes(b"unchanged receipt")
    probe = Mock()
    if not port_available:
        probe.bind.side_effect = OSError("port occupied")
    monkeypatch.setattr(launcher.socket, "socket", Mock(return_value=Mock(
        __enter__=Mock(return_value=probe), __exit__=Mock(return_value=False))))
    monkeypatch.setattr(launcher.socket, "SO_EXCLUSIVEADDRUSE", -5, raising=False)
    spawn = Mock(side_effect=RuntimeError("stop before processes"))
    monkeypatch.setattr(launcher, "_spawn", spawn)
    args = Namespace(state=str(state_path), workout=None, btvs="btvs.exe", tshark="tshark.exe",
                     duration=10, reset_binding=reset)
    with pytest.raises((RuntimeError, OSError), match="stop before processes|port occupied"):
        launcher.run(args, lambda _: None)
    assert spawn.call_count == int(port_available)
    after = json.loads(state_path.read_text(encoding="utf-8"))
    assert after["bound"] is not (reset and port_available)
    assert after["config"] == config
    if not (reset and port_available):
        assert state_path.read_bytes() == before
    assert workout.read_bytes() == b"unchanged workout"
    assert receipt.read_bytes() == b"unchanged receipt"


def test_reset_on_missing_state_does_not_create_it_before_prototype(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher.socket, "socket", Mock(return_value=Mock(
        __enter__=Mock(return_value=Mock()), __exit__=Mock(return_value=False))))
    monkeypatch.setattr(launcher.socket, "SO_EXCLUSIVEADDRUSE", -5, raising=False)
    monkeypatch.setattr(launcher, "_spawn", Mock(side_effect=RuntimeError("stop before processes")))
    state = tmp_path / "not-created.json"
    args = Namespace(state=str(state), workout=None, btvs="btvs.exe", tshark="tshark.exe",
                     duration=10, reset_binding=True)
    with pytest.raises(RuntimeError, match="stop before processes"):
        launcher.run(args, lambda _: None)
    assert not state.exists()


def test_prototype_error_remains_primary_when_cleanup_also_fails(monkeypatch, tmp_path):
    args = Namespace(state=str(tmp_path / "state.json"), workout=None,
                     btvs="btvs.exe", tshark="tshark.exe", duration=10, reset_binding=False)
    monkeypatch.setattr(launcher.socket, "socket", Mock(return_value=Mock(
        __enter__=Mock(return_value=Mock()), __exit__=Mock(return_value=False))))
    monkeypatch.setattr(launcher.socket, "SO_EXCLUSIVEADDRUSE", -5, raising=False)
    monkeypatch.setattr(launcher, "_tcp_state", Mock(return_value=True))
    monkeypatch.setattr(launcher, "_await_capture", Mock())
    diagnostic = "Bluetooth restart failed (exit 50); live name is unverified."
    cleaned = []

    def spawn(arguments, name, events, **kwargs):
        process = Mock(pid=123, name=name)
        process.owner = name
        process.poll.return_value = None
        if name == "prototype":
            process.poll.return_value = process.returncode = 1
            process.wait.return_value = 1
            events.put(("prototype", diagnostic))
            events.put(("prototype", None))
        return process

    def cleanup(process):
        cleaned.append(process.owner)
        if process.owner == "capture":
            raise OSError("capture cleanup failed")

    monkeypatch.setattr(launcher, "_spawn", spawn)
    monkeypatch.setattr(launcher, "_terminate_child_tree", cleanup)
    output = []
    previous_interrupt = signal.getsignal(signal.SIGINT)
    with pytest.raises(RuntimeError, match=r"B5.*exit 1.*exit 50") as error:
        launcher.run(args, output.append)
    assert diagnostic in str(error.value)
    assert "原型诊断：" + diagnostic in output
    assert any(line.startswith("附加清理失败：") for line in output)
    assert cleaned == ["capture", "btvs"]
    assert signal.getsignal(signal.SIGINT) == previous_interrupt
