"""Offline file sync through Bumble LocalLink and a fake Windows notifier."""

import asyncio
from contextlib import suppress
from unittest.mock import Mock

import pytest
from bumble.att import ATT_Error, ATT_UNLIKELY_ERROR_ERROR
from bumble.core import UUID
from bumble.device import Peer
from bumble.testing.test_utils import TwoDevices

from experiments.keep_device import emulator, windows
from experiments.keep_device.btcp import DeviceInfoSession, SERVICE_UUID, UnsupportedRequest
from experiments.keep_device.files import WorkoutFiles
from experiments.keep_device.protocol import b3_service
from experiments.keep_device.state import BindingState
from experiments.keep_device.test_files import source, wire
from experiments.keep_device.test_simple import reference_crc, request_packet
from experiments.keep_device.test_windows import FakeNotify, WRITE


def response_payload(packets, request_id, command):
    assert packets
    for index, packet in enumerate(packets):
        assert packet[:7] == request_id.to_bytes(2, "little") + bytes((1, len(packets) - 1, index)) + command
    body_crc = b"".join(packet[7:] for packet in packets)
    crc_input = request_id.to_bytes(2, "little") + b"\x01" + (len(body_crc) - 2).to_bytes(2, "little") + command + body_crc[:-2]
    assert body_crc[-2:] == reference_crc(crc_input)
    return body_crc[:-2]


@pytest.mark.parametrize("backend", ["bumble", "windows"])
@pytest.mark.parametrize("receipt_fails", [False, True])
def test_file_sync_routes_alongside_binding_and_preserves_source(source, wire, backend, receipt_fails, monkeypatch):
    async def check():
        original = source.read_bytes()
        workout = WorkoutFiles(source)
        messages = []
        state = BindingState(source.parent / "state.json", "C1:23:45:67:89:AB")
        packets = []
        ready = asyncio.Event()
        bridge = worker = devices = None
        if backend == "windows":
            notify = FakeNotify()
            bridge = windows.DeviceInfoBridge(notify, state.mac, messages.append, bytes, state, "B5", workout)
            worker = asyncio.create_task(bridge.serve())
        else:
            devices = TwoDevices()
            devices[1].random_address = emulator.static_address(state.mac)
            devices[1].static_address = devices[1].random_address
            devices[1].add_service(b3_service(devices[1], 1, messages.append, state, "B5", workout))
            await devices.setup_connection()
            peer = Peer(devices.connections[0])
            # Long uint64 file IDs need a request larger than the default ATT payload.
            await peer.request_mtu(64)
            service, = await peer.discover_services([UUID(SERVICE_UUID)])
            write, notify = await peer.discover_characteristics(service=service)

            def collect(packet):
                packets.append(bytes(packet))
                if packet[3] == packet[4]:
                    ready.set()

            await notify.subscribe(collect)

        async def exchange(payload, request_id=32768, fails=False):
            packets.clear()
            ready.clear()
            request = request_packet(request_id, payload)
            if bridge is not None:
                notify.calls.clear()
                bridge.write_request(WRITE, request)
                await asyncio.sleep(0)
                await bridge.queue.join()
                packets.extend(data for data, _ in notify.calls)
                assert all(len(packet) <= 20 for packet in packets)
            elif fails:
                with pytest.raises(ATT_Error) as error:
                    await write.write_value(request, with_response=True)
                assert error.value.error_code == ATT_UNLIKELY_ERROR_ERROR
            else:
                await write.write_value(request, with_response=True)
                await asyncio.wait_for(ready.wait(), 2)
                assert all(len(packet) <= 61 for packet in packets)
            if fails:
                assert packets == []
                return
            return response_payload(packets, request_id, payload[:2])

        try:
            assert await exchange(b"\x01\x05") == b"\x08\x02"
            assert state.bound
            listing = await exchange(b"\x06\x01\x08\x2c")
            entry, = wire["Directory"].FromString(listing).entries
            received = bytearray()
            while len(received) < entry.size:
                request = wire["Read"](id=entry.id, count=2048, offset=len(received))
                chunk = wire["Chunk"].FromString(await exchange(b"\x06\x02" + request.SerializeToString()))
                assert chunk.state == 0 and chunk.data
                received.extend(chunk.data)
            assert received == original
            if receipt_fails:
                def fail_replace(*args):
                    raise PermissionError("simulated receipt failure")
                monkeypatch.setattr("experiments.keep_device.files.os.replace", fail_replace)
            sent_before = sum(message.startswith("FILE_REPLY_SENT ") for message in messages)
            result = await exchange(b"\x06\x03\x08\x2c", fails=receipt_fails)
            if receipt_fails:
                assert sum(message.startswith("FILE_REPLY_SENT ") for message in messages) == sent_before
            else:
                entry, = wire["Directory"].FromString(result).entries
                assert entry.state == 1
                assert await exchange(b"\x06\x01\x08\x2c") == b""
            restarted = DeviceInfoSession(state.mac, state, "B5", WorkoutFiles(source))
            entries = wire["Directory"].FromString(restarted.reply_payload(b"\x06\x01\x08\x2c")[2:]).entries
            assert bool(entries) == receipt_fails
            assert source.read_bytes() == original
            assert state.bound
        finally:
            if bridge is not None:
                bridge.close()
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker
            if devices is not None:
                await devices.connections[0].disconnect()

    asyncio.run(asyncio.wait_for(check(), 10))


def test_workout_is_explicit_and_b5_only(source):
    workout = WorkoutFiles(source)
    with pytest.raises(ValueError, match="B5"):
        DeviceInfoSession("C1:23:45:67:89:AB", workout=workout)
    with pytest.raises(ValueError, match="B5"):
        b3_service(None, 1, print, workout=workout)
    with pytest.raises(ValueError, match="B5"):
        windows.DeviceInfoBridge(None, "C1:23:45:67:89:AB", print, workout=workout)
    for model in ("B3", "B5"):
        with pytest.raises(UnsupportedRequest):
            DeviceInfoSession("C1:23:45:67:89:AB", model=model).reply_payload(b"\x06\x01\x08\x2c")


def test_b5_empty_queue_replies_through_windows_notifications():
    async def check():
        notify = FakeNotify()
        bridge = windows.DeviceInfoBridge(
            notify, "C1:23:45:67:89:AB", lambda _: None, bytes,
            model="B5", workout=WorkoutFiles(None),
        )
        worker = asyncio.create_task(bridge.serve())
        try:
            for kind in (6, 44):
                notify.calls.clear()
                bridge.write_request(WRITE, request_packet(12, b"\x06\x01\x08" + bytes([kind])))
                await asyncio.sleep(0)
                await bridge.queue.join()
                packets = [packet for packet, _ in notify.calls]
                assert response_payload(packets, 12, b"\x06\x01") == b""
        finally:
            bridge.close()
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker

    asyncio.run(asyncio.wait_for(check(), 2))


@pytest.mark.parametrize("entrypoint", [emulator, windows])
def test_b5_without_workout_enables_empty_file_service_before_transport(entrypoint, monkeypatch):
    class StopBeforeTransport(Exception):
        pass

    def check_empty(path):
        assert path is None
        assert WorkoutFiles(path).reply(bytes.fromhex("06 01 08 2c")) == b"\x06\x01"
        raise StopBeforeTransport

    monkeypatch.setattr(entrypoint, "WorkoutFiles", check_empty)
    arguments = {"model": "B5"}
    if entrypoint is emulator:
        arguments.update(transport_spec="must-not-open", name="KeepB5 Lab", write_characteristic=1)
    with pytest.raises(StopBeforeTransport):
        asyncio.run(entrypoint.run(**arguments))


@pytest.mark.parametrize("entrypoint", [emulator, windows])
def test_cli_rejects_workout_for_b3_before_run(entrypoint, monkeypatch):
    arguments = ["program", "--workout", "private.sport44"]
    if entrypoint is emulator:
        arguments.append("android-netsim:")
    run = Mock()
    monkeypatch.setattr("sys.argv", arguments)
    monkeypatch.setattr(entrypoint, "run", run)
    with pytest.raises(SystemExit) as error:
        entrypoint.main()
    assert error.value.code == 2
    run.assert_not_called()


@pytest.mark.parametrize("entrypoint", [emulator, windows])
def test_cli_passes_explicit_b5_workout(entrypoint, monkeypatch):
    arguments = ["program", "--model", "B5", "--workout", "private run.sport44"]
    if entrypoint is emulator:
        arguments.append("android-netsim:")
    run = Mock()
    monkeypatch.setattr("sys.argv", arguments)
    monkeypatch.setattr(windows.sys, "platform", "win32")
    monkeypatch.setattr(entrypoint, "run", run)
    monkeypatch.setattr(entrypoint.asyncio, "run", Mock())
    entrypoint.main()
    assert run.call_args.args[-2:] == ("B5", "private run.sport44")


@pytest.mark.parametrize("model", ["B3", "B5"])
@pytest.mark.parametrize("entrypoint", [emulator, windows])
def test_invalid_workout_is_rejected_before_transport_access(entrypoint, model, tmp_path):
    arguments = {"model": model, "workout_path": str(tmp_path / "missing.sport44")}
    if entrypoint is emulator:
        arguments.update(transport_spec="must-not-open", name="KeepB5 Lab" if model == "B5" else "Keep B3 Lab", write_characteristic=1)
    with pytest.raises(FileNotFoundError if model == "B5" else ValueError):
        asyncio.run(entrypoint.run(**arguments))
