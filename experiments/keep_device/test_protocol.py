"""Offline checks; these do not establish compatibility with the Keep app."""

import asyncio

import pytest
from bumble.att import ATT_REQUEST_NOT_SUPPORTED_ERROR, ATT_Error
from bumble.core import AdvertisingData, UUID
from bumble.device import Peer
from bumble.gatt import Characteristic
from bumble.testing.test_utils import TwoDevices

from experiments.keep_device.emulator import static_address
from experiments.keep_device.btcp import decode_frame, encode_frame
from experiments.keep_device.state import BindingState
from experiments.keep_device.test_simple import reference_crc, request_packet
from experiments.keep_device.protocol import (
    CHARACTERISTIC_UUIDS,
    SERVICE_UUID,
    advertisement,
    b3_service,
)


def test_reuse_probe_address_preserves_manual_mac():
    assert str(static_address("C1:23:45:67:89:AB")) == "C1:23:45:67:89:AB"


@pytest.mark.parametrize("value", [
    "invalid", "C1:23", "00:11:22:33:44:55", "C1:23:45:67:89:AB/P",
    "C0:00:00:00:00:00", "FF:FF:FF:FF:FF:FF",
])
def test_reused_address_rejects_invalid_or_non_static_address(value):
    with pytest.raises(ValueError):
        static_address(value)


def test_advertisement_is_standard_ble_with_observed_identifiers():
    data = advertisement("Keep B3 Lab")
    decoded = AdvertisingData.from_bytes(data)
    assert len(data) <= 31
    assert decoded.get(AdvertisingData.COMPLETE_LOCAL_NAME) == "Keep B3 Lab"
    assert UUID("190A") in decoded.get(AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS)


@pytest.mark.parametrize("name", ["Other device", "Keep B3 " + "界" * 8])
def test_invalid_advertisement_is_rejected(name):
    with pytest.raises(ValueError):
        advertisement(name)


@pytest.mark.parametrize("direction", [1, 2])
def test_unknown_write_is_rejected_without_logging_credentials(direction):
    async def check():
        messages = []
        devices = TwoDevices()
        service = b3_service(devices[1], direction, messages.append)
        devices[1].add_service(service)
        await devices.setup_connection()
        write, notify = service.characteristics
        assert service.uuid == UUID(SERVICE_UUID)
        assert write.uuid == UUID(CHARACTERISTIC_UUIDS[direction - 1])
        assert notify.uuid == UUID(CHARACTERISTIC_UUIDS[2 - direction])
        assert notify.properties == Characteristic.Properties.NOTIFY
        peer = Peer(devices.connections[0])
        remote_service, = await peer.discover_services([UUID(SERVICE_UUID)])
        _, remote_notify = await peer.discover_characteristics(service=remote_service)
        await remote_notify.subscribe(lambda _: pytest.fail("Unknown writes must not get a response"))
        secret = b"password=do-not-print;token=private"
        with pytest.raises(ATT_Error) as raised:
            await write.write_value(devices.connections[1], secret)
        assert raised.value.error_code == ATT_REQUEST_NOT_SUPPORTED_ERROR
        assert messages[-1] == (f"UNSUPPORTED_WRITE characteristic={direction} bytes={len(secret)} "
                                "header=unavailable stage=frame error=ValueError")
        assert all("private" not in message for message in messages)
        await devices.connections[0].disconnect()

    asyncio.run(check())


def test_invalid_direction_is_rejected():
    async def check():
        with pytest.raises(ValueError):
            b3_service(TwoDevices()[1], 3, lambda _: None)

    asyncio.run(check())


def test_bumble_peer_can_discover_subscribe_and_observe_unsupported_request():
    async def exchange():
        messages = []
        devices = TwoDevices()
        devices[1].add_service(b3_service(devices[1], 1, messages.append))
        await devices.setup_connection()
        peer = Peer(devices.connections[0])
        services = await peer.discover_services([UUID(SERVICE_UUID)])
        assert len(services) == 1
        write, notify = await peer.discover_characteristics(service=services[0])
        await notify.subscribe(lambda _: pytest.fail("Unknown writes must not get a response"))
        with pytest.raises(ATT_Error) as raised:
            await write.write_value(b"private-binding-payload", with_response=True)
        assert raised.value.error_code == ATT_REQUEST_NOT_SUPPORTED_ERROR
        assert messages == [
            "SUBSCRIPTION notify=True indicate=False; device-info response available",
            "UNSUPPORTED_WRITE characteristic=1 bytes=23 header=unavailable stage=frame error=ValueError",
        ]
        await devices.connections[0].disconnect()

    async def bounded_exchange():
        await asyncio.wait_for(exchange(), timeout=5)

    asyncio.run(bounded_exchange())


@pytest.mark.parametrize("model", ["B3", "B5"])
def test_binding_survives_transport_restart_and_unbind_updates_identity(tmp_path, model):
    async def check():
        state_path = tmp_path / "device.json"
        address = static_address("C1:23:45:67:89:AB")
        # Each stage uses fresh controllers, services, sessions, and state loaded from disk.
        stages = (
            ((b"\x01\x02\x03\x03", 2), (b"\x01\x05", b"\x01\x05\x08\x02")),
            ((b"\x01\x02\x03\x03", 1), (b"\x01\x05", b"\x01\x05\x08\x01"),
             (b"\x01\x06", b"\x01\x06\x08\x02"), (b"\x01\x02\x03\x03", 2)),
            ((b"\x01\x02\x03\x03", 2),),
        )
        for stage_number, stage in enumerate(stages):
            devices = TwoDevices()
            devices[1].static_address = address
            devices[1].random_address = address
            state = BindingState(state_path, str(address))
            devices[1].add_service(b3_service(devices[1], 1, lambda _: None, state, model))
            await devices.setup_connection()
            peer = Peer(devices.connections[0])
            service, = await peer.discover_services([UUID(SERVICE_UUID)])
            write, notify = await peer.discover_characteristics(service=service)
            chunks = bytearray()
            simple_packets = []
            received = asyncio.Event()

            def collect(data):
                if model == "B5":
                    simple_packets.append(bytes(data))
                    if data[3] == data[4]:
                        received.set()
                else:
                    chunks.extend(data)
                if model == "B3" and len(chunks) >= 6 and len(chunks) == int.from_bytes(chunks[4:6], "little") + 8:
                    received.set()

            # Subscription is mandatory even when the requested operation changes state.
            with pytest.raises(ATT_Error):
                request = request_packet(91, b"\x01\x05") if model == "B5" else encode_frame(b"\x01\x05", 0)
                await write.write_value(request, with_response=True)
            assert state.bound == (stage_number == 1)
            await notify.subscribe(collect)
            for sequence, (payload, expected) in enumerate(stage):
                chunks.clear()
                simple_packets.clear()
                received.clear()
                request_id = 91 + sequence
                request = request_packet(request_id, payload) if model == "B5" else encode_frame(payload, request_id)
                await write.write_value(request, with_response=True)
                await asyncio.wait_for(received.wait(), 2)
                if model == "B5":
                    for index, packet in enumerate(simple_packets):
                        assert len(packet) <= 20
                        assert packet[:7] == (request_id.to_bytes(2, "little")
                                              + bytes((1, len(simple_packets) - 1, index)) + payload[:2])
                    body_crc = b"".join(packet[7:] for packet in simple_packets)
                    checksum_input = (request_id.to_bytes(2, "little") + b"\x01"
                                      + (len(body_crc) - 2).to_bytes(2, "little") + payload[:2] + body_crc[:-2])
                    assert body_crc[-2:] == reference_crc(checksum_input)
                    response_payload = payload[:2] + body_crc[:-2]
                else:
                    response = decode_frame(bytes(chunks))
                    assert response.fsn == sequence
                    response_payload = response.payload
                if isinstance(expected, int):
                    assert response_payload.startswith(b"\x01\x02")
                    assert response_payload.endswith(bytes((0x30, expected)))
                else:
                    assert response_payload == expected
            await devices.connections[0].disconnect()

    asyncio.run(asyncio.wait_for(check(), 10))


def test_device_info_crosses_default_mtu_and_sequence_resets_on_reconnect():
    async def exchange():
        devices = TwoDevices()
        messages = []
        devices[1].add_service(b3_service(devices[1], 1, messages.append))
        await devices.setup_connection()
        request = bytes.fromhex("a5 a5 a0 00 04 00 01 02 03 03 67 8d")
        for connection_number in range(2):
            if connection_number:
                await devices[1].start_advertising(advertising_interval_min=1.0)
                await devices[0].connect(devices[1].random_address)
            peer = Peer(devices.connections[0])
            service, = await peer.discover_services([UUID(SERVICE_UUID)])
            write, notify = await peer.discover_characteristics(service=service)
            assert devices.connections[0].att_mtu == 23
            sent_before = sum(message.startswith("DEVICE_INFO_SENT") for message in messages)
            with pytest.raises(ATT_Error) as raised:
                await write.write_value(request, with_response=True)
            assert raised.value.error_code == ATT_REQUEST_NOT_SUPPORTED_ERROR
            assert sum(message.startswith("DEVICE_INFO_SENT") for message in messages) == sent_before
            chunks = []
            received = asyncio.Event()

            def on_notification(data):
                chunks.append(data)
                assembled = b"".join(chunks)
                if len(assembled) >= 6 and len(assembled) == 8 + int.from_bytes(assembled[4:6], "little"):
                    received.set()

            await notify.subscribe(on_notification)
            for expected_sequence in (0, 1):
                chunks.clear()
                received.clear()
                await write.write_value(request, with_response=False)
                await asyncio.wait_for(received.wait(), timeout=2)
                assert len(chunks) > 1
                assert all(0 < len(chunk) <= 20 for chunk in chunks)
                frame = decode_frame(b"".join(chunks))
                assert frame.fsn == expected_sequence
                assert frame.payload.startswith(b"\x01\x02")
                assert b"LAB" + str(devices[1].random_address).replace(":", "").encode() in frame.payload
            await devices.connections[0].disconnect()
        assert sum(message.startswith("DEVICE_INFO_SENT") for message in messages) == 4
        assert all("sid=01 cid=02 flags=a0" in message for message in messages
                   if message.startswith("DEVICE_INFO_SENT"))

    async def bounded_exchange():
        await asyncio.wait_for(exchange(), timeout=10)

    asyncio.run(bounded_exchange())
