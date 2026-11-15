"""Diagnostic metadata never includes application bodies or exception text."""

import asyncio
from contextlib import suppress

import pytest
from bumble.att import ATT_Error
from bumble.core import UUID
from bumble.device import Peer
from bumble.testing.test_utils import TwoDevices

from experiments.keep_device.btcp import SERVICE_UUID, encode_frame, request_metadata
from experiments.keep_device.protocol import b3_service
from experiments.keep_device.test_simple import request_packet
from experiments.keep_device.test_windows import FakeNotify, WRITE
from experiments.keep_device.windows import DeviceInfoBridge


@pytest.mark.parametrize("model", ["B3", "B5"])
def test_body_and_crc_changes_cannot_change_header_diagnostics(model):
    make_request = (lambda payload: request_packet(7, payload)) if model == "B5" else (lambda payload: encode_frame(payload, 7))
    first = make_request(b"\x02\x01" + b"private-one")
    second = make_request(b"\x02\x01" + b"private-two")
    metadata = request_metadata(first, model)
    assert request_metadata(second, model) == metadata
    assert "sid=02 cid=01" in metadata
    assert "flags=" in metadata
    assert "private" not in metadata


def test_fragmented_simple_reports_only_header_and_size():
    request = bytes.fromhex("34 12 19 03 02 02 01") + b"personal-settings"
    assert request_metadata(request, "B5") == (
        "bytes=24 sid=02 cid=01 flags=19 packet_type=1 ack=1 status=1 last=3 current=2"
    )


@pytest.mark.parametrize("model,packet", [
    ("B3", b"secret"), ("B5", b"secret"), ("B3", encode_frame(b"\x01", 0)),
])
def test_short_headers_do_not_read_body_or_crc_as_command(model, packet):
    assert request_metadata(packet, model) == f"bytes={len(packet)} header=unavailable"


@pytest.mark.parametrize("backend", ["bumble", "windows"])
def test_rejected_commands_and_sensitive_errors_log_metadata_only(backend):
    async def check():
        class PrivateState:
            mac = "C1:23:45:67:89:AB"
            bound = False

            def accepts(self, payload):
                return payload[:2] == b"\x02\x01"

            def reply(self, payload):
                raise ValueError("SECRET-CONFIG-CONTENT")

        state = PrivateState()
        messages = []
        bridge = worker = devices = None
        if backend == "windows":
            notify = FakeNotify()
            bridge = DeviceInfoBridge(notify, state.mac, messages.append, bytes, state, "B5")
            worker = asyncio.create_task(bridge.serve())

            async def send(request):
                bridge.write_request(WRITE, request)
                await asyncio.sleep(0)
                await bridge.queue.join()
                await asyncio.sleep(0)
        else:
            devices = TwoDevices()
            # Use the local controller identity; no physical Bluetooth adapter.
            state.mac = str(devices[1].random_address)
            devices[1].add_service(b3_service(devices[1], 1, messages.append, state, "B5"))
            await devices.setup_connection()
            state.mac = str(devices[1].random_address)
            peer = Peer(devices.connections[0])
            await peer.request_mtu(64)
            service, = await peer.discover_services([UUID(SERVICE_UUID)])
            write, notify = await peer.discover_characteristics(service=service)
            await notify.subscribe(lambda _: None)

            async def send(request):
                with pytest.raises(ATT_Error):
                    await write.write_value(request, with_response=True)

        try:
            await send(request_packet(7, b"\x02\x01SECRET-CONFIG-CONTENT"))
            assert any("sid=02 cid=01" in message and "stage=business error=ValueError" in message for message in messages)
            if bridge is not None:
                assert notify.calls == []
            await send(request_packet(7, b"\x09\x09SECRET-CONFIG-CONTENT"))
            assert any("sid=09 cid=09" in message for message in messages)
            fragmented = bytearray(request_packet(7, b"\x02\x01SECRET-CONFIG-CONTENT"))
            fragmented[3:5] = b"\x02\x01"
            await send(bytes(fragmented))
            assert any("last=2 current=1" in message and "stage=frame error=UnsupportedRequest" in message for message in messages)
            assert all("SECRET" not in message and "534543524554" not in message for message in messages)
        finally:
            if bridge is not None:
                bridge.close()
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker
            if devices is not None:
                await devices.connections[0].disconnect()

    asyncio.run(asyncio.wait_for(check(), 5))
