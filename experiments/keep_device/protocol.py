"""B3/B5 GATT profile with optional binding and B5 workout transfer."""

from collections.abc import Callable

from bumble.att import ATT_REQUEST_NOT_SUPPORTED_ERROR, ATT_UNLIKELY_ERROR_ERROR, ATT_Error
from bumble.core import AdvertisingData
from bumble.device import Device
from bumble.gatt import Characteristic, CharacteristicValue, Service

from .btcp import CHARACTERISTIC_UUIDS, SERVICE_UUID, DeviceInfoSession, request_metadata, request_payload


def advertisement(name: str) -> bytes:
    """Build standard BLE advertising data using Bumble's encoder."""
    if not name.startswith(("Keep B3", "Keep-B3", "KeepB5")):
        raise ValueError("The observed scan prefixes are 'Keep B3', 'Keep-B3', and 'KeepB5'.")
    data = bytes(
        AdvertisingData(
            [
                (AdvertisingData.FLAGS, b"\x06"),
                (AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS, b"\x0a\x19"),
                (AdvertisingData.COMPLETE_LOCAL_NAME, name.encode("utf-8")),
            ]
        )
    )
    if len(data) > 31:
        raise ValueError("The name exceeds the 31-byte legacy advertising limit.")
    return data


def b3_service(device: Device, write_characteristic: int, report: Callable[[str], None], state=None, model="B3", workout=None) -> Service:
    """Share device state across connections while keeping transport sequences separate."""
    if write_characteristic not in (1, 2):
        raise ValueError("write_characteristic must be 1 or 2")
    if workout is not None and model != "B5":
        raise ValueError("Workout transfer requires B5")

    sessions = {}

    async def on_write(connection, value: bytes) -> None:
        metadata = request_metadata(value, model)
        if not device.gatt_server.read_cccd(connection, notify)[0] & 1:
            report(f"UNSUBSCRIBED_WRITE characteristic={write_characteristic} {metadata} reason=unsubscribed")
            raise ATT_Error(ATT_REQUEST_NOT_SUPPORTED_ERROR)
        stage = "session"
        try:
            session = sessions.get(connection) or DeviceInfoSession(str(device.random_address), state, model, workout)
            stage = "frame"
            payload = request_payload(value, model)
            stage = "business"
            packets = session.reply_packets(value, connection.att_mtu - 3)
        except ValueError as error:
            report(f"UNSUPPORTED_WRITE characteristic={write_characteristic} {metadata} stage={stage} error={type(error).__name__}")
            raise ATT_Error(ATT_REQUEST_NOT_SUPPORTED_ERROR) from None
        except OSError as error:
            report(f"DEVICE_STATE_FAILED {metadata} stage={stage} error={type(error).__name__}; no success reply")
            raise ATT_Error(ATT_UNLIKELY_ERROR_ERROR) from None
        if connection not in sessions:
            sessions[connection] = session
            connection.on("disconnection", lambda _: sessions.pop(connection, None))
        for packet in packets:
            await device.notify_subscriber(connection, notify, packet)
        if payload[:2] == b"\x01\x02":
            report(f"DEVICE_INFO_SENT {metadata}; server binding and history synchronization unverified")
        elif payload[0] == 6:
            report(f"FILE_REPLY_SENT {metadata}; cloud upload unverified")
        else:
            report(f"DEVICE_REPLY_SENT {metadata}; device state saved, server binding unverified")

    def on_subscription(_bearer, notify: bool, indicate: bool) -> None:
        report(f"SUBSCRIPTION notify={notify} indicate={indicate}; device-info response available")

    write = Characteristic(
        CHARACTERISTIC_UUIDS[write_characteristic - 1],
        Characteristic.Properties.WRITE | Characteristic.Properties.WRITE_WITHOUT_RESPONSE,
        Characteristic.WRITEABLE,
        CharacteristicValue(write=on_write),
    )
    notify = Characteristic(
        CHARACTERISTIC_UUIDS[2 - write_characteristic],
        Characteristic.Properties.NOTIFY,
        0,
        b"",
    )
    notify.on(Characteristic.EVENT_SUBSCRIPTION, on_subscription)
    return Service(SERVICE_UUID, [write, notify])
