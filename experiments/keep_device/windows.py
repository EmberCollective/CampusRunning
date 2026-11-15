"""Bounded Windows device-info experiment using Bless and WinRT notifications.

Only one subscribed client is supported. Bless does not identify the writer, so
this cannot authenticate a writer or safely multiplex clients. Rejected writes
get no business reply; Bless may still acknowledge the ATT write itself.
Device binding requires --state; B5 workout transfer requires --workout. No packet capture. --keep-name requests
a temporary name, broadcasts in a fresh process, and restores it on exit; verify on-air.
Without that option, the adapter name is left unchanged.
"""

import argparse
import asyncio
from contextlib import contextmanager, suppress
import logging
import math
import os
import subprocess
import sys
import threading

from .btcp import (
    CHARACTERISTIC_UUIDS,
    DEVICE_INFO_REQUEST,
    DEVICE_NAMES,
    SERVICE_UUID,
    DeviceInfoSession,
    request_metadata,
    request_payload,
)
from .state import BindingState
from .files import WorkoutFiles


_RADIO_TIMEOUT_SECONDS = 10


def _buffer(value: bytes):
    from bleak_winrt.windows.storage.streams import DataWriter

    writer = DataWriter()
    writer.write_bytes(value)
    return writer.detach_buffer()


class DeviceInfoBridge:
    """Serialize replies and invalidate queued work at subscription changes."""

    def __init__(self, notify, mac: str, report, to_buffer=_buffer, state=None, model="B3", workout=None):
        if workout is not None and model != "B5":
            raise ValueError("Workout transfer requires B5")
        self.notify = notify
        self.mac = mac
        self.report = report
        self.to_buffer = to_buffer
        self.state = state
        self.model = model
        self.workout = workout
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue(maxsize=8)
        # Bound callbacks waiting for the loop as well as queued requests.
        self._slots = threading.BoundedSemaphore(8)
        self._lock = threading.Lock()
        self._epoch = 0
        self._closed = False
        self._session_key = None
        self._session = None

    def _log(self, message):
        with self._lock:
            if not self._closed:
                self.loop.call_soon_threadsafe(self.report, message)

    def _client(self):
        clients = list(self.notify.subscribed_clients or [])
        if len(clients) != 1 or clients[0].session is None:
            raise ValueError("exactly-one-subscriber-required")
        return clients[0], clients[0].session.device_id.id

    def subscription_changed(self, _sender, _args):
        with self._lock:
            if self._closed:
                return
            self._epoch += 1
            self.loop.call_soon_threadsafe(self._reset, self._epoch)

    def _reset(self, epoch):
        if not self._closed and epoch == self._epoch:
            self._session = None
            self._session_key = None
            self.report(f"SUBSCRIPTION clients={len(self.notify.subscribed_clients or [])}; session reset")

    def write_request(self, characteristic, value):
        """Bless callback; queue only supported requests and never log their contents."""
        metadata = f"bytes={len(value)}"
        stage = "characteristic"
        try:
            if str(characteristic.uuid).lower() != CHARACTERISTIC_UUIDS[0]:
                raise ValueError("wrong-characteristic")
            request = bytes(value)
            metadata = request_metadata(request, self.model)
            stage = "frame"
            payload = request_payload(request, self.model)
            stage = "command"
            if (payload != DEVICE_INFO_REQUEST
                    and not (self.state is not None and self.state.accepts(payload))
                    and not (self.workout is not None and self.workout.accepts(payload))):
                raise ValueError("unsupported-request")
            with self._lock:
                epoch = self._epoch
            stage = "subscriber"
            _, client_id = self._client()
        except (ValueError, AttributeError, OSError) as error:
            self._log(f"WRITE_REJECTED {metadata} stage={stage} error={type(error).__name__}; no business reply")
            return
        if not self._slots.acquire(blocking=False):
            self._log(f"WRITE_REJECTED {metadata} reason=queue-full; no business reply")
            return
        with self._lock:
            if self._closed:
                self._slots.release()
                return
            self.loop.call_soon_threadsafe(self._enqueue, epoch, client_id, request)

    def _enqueue(self, epoch, client_id, request):
        if self._closed or epoch != self._epoch:
            self._slots.release()
            return
        self.queue.put_nowait((epoch, client_id, request))

    def _current_client(self, epoch, client_id):
        with self._lock:
            if self._closed or epoch != self._epoch:
                raise ValueError("subscription-changed")
        client, current_id = self._client()
        if current_id != client_id:
            raise ValueError("subscriber-changed")
        return client

    async def serve(self):
        while True:
            epoch, client_id, request = await self.queue.get()
            self._slots.release()
            metadata = request_metadata(request, self.model)
            stage = "subscriber"
            try:
                client = self._current_client(epoch, client_id)
                stage = "session"
                if self._session_key != (epoch, client_id):
                    self._session = DeviceInfoSession(self.mac, self.state, self.model, self.workout)
                    self._session_key = (epoch, client_id)
                payload = request_payload(request, self.model)
                stage = "business"
                packets = self._session.reply_packets(request, client.max_notification_size)
                self.report(
                    f"REPLY_PACKETS {metadata}; peer_limit={client.max_notification_size} "
                    f"sizes={','.join(str(len(packet)) for packet in packets)}"
                )
                stage = "notification"
                for chunk in packets:
                    client = self._current_client(epoch, client_id)
                    if len(chunk) > client.max_notification_size:
                        raise ValueError("invalid-notification-size")
                    result = await asyncio.wait_for(
                        self.notify.notify_value_async(self.to_buffer(chunk), client),
                        timeout=10,
                    )
                    # GattCommunicationStatus.SUCCESS is 0; success alone may be partial.
                    if result.status != 0 or result.bytes_sent != len(chunk):
                        raise ValueError("notification-not-delivered-in-full")
                self._current_client(epoch, client_id)
                if payload[:2] == b"\x01\x02":
                    self.report(f"DEVICE_INFO_SENT {metadata}; server binding and history synchronization unverified")
                elif payload[0] == 6:
                    self.report(f"FILE_REPLY_SENT {metadata}; cloud upload unverified")
                else:
                    self.report(f"DEVICE_REPLY_SENT {metadata}; device state saved, server binding unverified")
            except Exception as error:
                # Exception strings from transports can contain remote identifiers.
                self.report(f"DEVICE_INFO_FAILED {metadata} stage={stage} error={type(error).__name__}; no success claimed")
            finally:
                self.queue.task_done()

    def close(self):
        with self._lock:
            self._closed = True
            self._epoch += 1


def _duration(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("duration must be a positive finite number of seconds")
    return seconds


class NameRefreshError(RuntimeError):
    """Cleanup or PnP restart failed; the live radio name is unverified."""


def _restart_adapter(instance_id):
    result = subprocess.run(
        [os.path.join(os.environ["SystemRoot"], "System32", "pnputil.exe"),
         "/restart-device", instance_id],
        capture_output=True, timeout=30, check=False,
    )
    if result.returncode == 3010:
        raise NameRefreshError("Bluetooth restart requires a Windows reboot (3010); live name is unverified.")
    if result.returncode:
        raise NameRefreshError(f"Bluetooth restart failed (exit {result.returncode}); live name is unverified.")


def _terminate_child_tree(child):
    # A venv python.exe may launch another interpreter that also owns radio handles.
    try:
        result = subprocess.run(
            [os.path.join(os.environ["SystemRoot"], "System32", "taskkill.exe"),
             "/PID", str(child.pid), "/T", "/F"],
            capture_output=True, timeout=30, check=False,
        )
        if result.returncode:
            raise NameRefreshError(
                f"Advertising process-tree cleanup failed (exit {result.returncode}); "
                "child exit and live name restoration are unverified."
            )
        child.wait(timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise NameRefreshError(
            "Advertising process-tree cleanup could not complete; "
            "child exit and live name restoration are unverified."
        ) from error


async def _refresh_radio() -> None:
    """Refresh Windows' BLE name cache without turning an originally off radio on."""
    try:
        from winrt.windows.devices.bluetooth import BluetoothAdapter
        from winrt.windows.devices.radios import RadioAccessStatus, RadioState

        async def wait_for_adapter():
            # PnP can return before WinRT has enumerated the restarted adapter.
            while (adapter := await BluetoothAdapter.get_default_async()) is None:
                await asyncio.sleep(0.1)
            return adapter

        adapter = await asyncio.wait_for(wait_for_adapter(), _RADIO_TIMEOUT_SECONDS)
        radio = await asyncio.wait_for(adapter.get_radio_async(), _RADIO_TIMEOUT_SECONDS)
        if radio is None:
            raise NameRefreshError("No Bluetooth radio is available for refresh; live name is unverified.")
        original_state = radio.state
        if original_state != RadioState.ON:
            return

        async def change_state(state):
            status = await radio.set_state_async(state)
            if status != RadioAccessStatus.ALLOWED:
                raise NameRefreshError(
                    "Windows did not allow the Bluetooth radio change; "
                    "original radio state and live name are unverified."
                )
            while radio.state != state:
                await asyncio.sleep(0.1)

        try:
            await asyncio.wait_for(change_state(RadioState.OFF), _RADIO_TIMEOUT_SECONDS)
        finally:
            await asyncio.wait_for(change_state(original_state), _RADIO_TIMEOUT_SECONDS)
    except NameRefreshError:
        raise
    except Exception as error:
        raise NameRefreshError(
            f"Bluetooth radio refresh failed ({type(error).__name__}); "
            "original radio state and live name are unverified."
        ) from error


@contextmanager
def _temporary_keep_name(adapter, after_restore=None, name="Keep B3 Lab"):
    """Restore the saved override, or the Windows default name if it was absent."""
    import winreg

    path = rf"SYSTEM\ControlSet001\Enum\{adapter._adapter_name}\Device Parameters"
    with winreg.OpenKeyEx(
        winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE
    ) as key:
        try:
            original = winreg.QueryValueEx(key, "Local Name")
        except FileNotFoundError:
            original = None
        default_name = os.environ.get("COMPUTERNAME")
        if original is None and not default_name:
            raise NameRefreshError("COMPUTERNAME is required to restore the default Bluetooth name; no name change attempted.")
        # Bless's exclusive handle must not survive into PnP restart or child startup.
        adapter._dev.Close()
        try:
            adapter._set_registry_name(name)
            _restart_adapter(adapter._adapter_name)
            yield
        finally:
            if original is None:
                # Deleting an override alone leaves the controller's current name cached.
                try:
                    adapter._set_registry_name(default_name)
                    _restart_adapter(adapter._adapter_name)
                finally:
                    with suppress(FileNotFoundError):
                        winreg.DeleteValue(key, "Local Name")
            else:
                value, value_type = original
                winreg.SetValueEx(key, "Local Name", 0, value_type, value)
                _restart_adapter(adapter._adapter_name)
            if after_restore is not None:
                after_restore()


def _run_with_keep_name(duration: float, state_path: str | None = None, model: str = "B3", workout_path: str | None = None) -> None:
    if workout_path is not None:
        if model != "B5":
            raise ValueError("--workout requires --model B5")
        WorkoutFiles(workout_path)  # Reject invalid input before renaming/restarting the adapter.
    from bless.backends.winrt.ble import BLEAdapter

    duration = _duration(duration)
    command = [sys.executable, "-m", "experiments.keep_device.windows", "--duration", str(duration)]
    if state_path is not None:
        command.extend(["--state", state_path])
    if model != "B3":
        command.extend(["--model", model])
    if workout_path is not None:
        command.extend(["--workout", workout_path])
    child = None
    child_exited = False

    def refresh_after_exit():
        if child is None or child_exited:
            asyncio.run(_refresh_radio())

    # A fresh process avoids reusing WinRT objects from before the adapter restart.
    name = DEVICE_NAMES[model]
    with _temporary_keep_name(BLEAdapter(), refresh_after_exit, name):
        print(f"NAME_REQUESTED {name}; starting a fresh advertising process", flush=True)
        # No Popen context: its implicit unbounded wait can hide a tree-cleanup failure.
        child = subprocess.Popen(command)
        try:
            returncode = child.wait()
        except KeyboardInterrupt:
            # Console Ctrl+C also reaches the child; give its cleanup time to finish.
            with suppress(subprocess.TimeoutExpired):
                child.wait(timeout=10)
            raise
        finally:
            if child.poll() is None:
                _terminate_child_tree(child)
            child_exited = True
    print("NAME_REGISTRY_RESTORED; PnP restart succeeded; verify the runtime name separately", flush=True)
    if returncode:
        raise subprocess.CalledProcessError(returncode, command)


async def run(duration: float = 300, state_path: str | None = None, model: str = "B3", workout_path: str | None = None) -> None:
    """Run for duration seconds after advertising starts; always stop on exit."""
    if workout_path is not None and model != "B5":
        raise ValueError("--workout requires --model B5")
    workout = WorkoutFiles(workout_path) if workout_path is not None else None
    from bless import BlessServer, GATTAttributePermissions, GATTCharacteristicProperties
    from bleak_winrt.windows.devices.bluetooth import BluetoothAdapter

    duration = _duration(duration)
    adapter = await BluetoothAdapter.get_default_async()
    if adapter is None or not adapter.is_peripheral_role_supported:
        raise RuntimeError("The default Bluetooth adapter cannot act as a BLE peripheral")
    address = adapter.bluetooth_address
    if not 0 < address < 2**48:
        raise RuntimeError("The adapter did not provide a valid Bluetooth address")
    mac = ":".join(f"{address:012X}"[index:index + 2] for index in range(0, 12, 2))
    state = BindingState(state_path, mac) if state_path is not None else None
    report = lambda message: print(message, flush=True)
    server = BlessServer(name=DEVICE_NAMES[model], loop=asyncio.get_running_loop(), name_overwrite=False)
    bridge = worker = notify = token = None
    try:
        await server.add_new_service(SERVICE_UUID)
        await server.add_new_characteristic(
            SERVICE_UUID, CHARACTERISTIC_UUIDS[0],
            GATTCharacteristicProperties.write | GATTCharacteristicProperties.write_without_response,
            bytearray(), GATTAttributePermissions.writeable,
        )
        await server.add_new_characteristic(
            SERVICE_UUID, CHARACTERISTIC_UUIDS[1], GATTCharacteristicProperties.notify,
            bytearray(), GATTAttributePermissions(0),
        )
        notify = server.get_characteristic(CHARACTERISTIC_UUIDS[1]).obj
        bridge = DeviceInfoBridge(notify, mac, report, state=state, model=model, workout=workout)
        token = notify.add_subscribed_clients_changed(bridge.subscription_changed)
        server.write_request_func = bridge.write_request
        worker = asyncio.create_task(bridge.serve())
        # Bless 0.3.0 itself waits for Windows' advertising event without a timeout.
        await server.start()
        if not await server.is_advertising():
            raise RuntimeError("Windows did not start advertising")
        report(
            f"ADVERTISING adapter_address={mac} service=190a duration={duration:g}s; "
            "name=Windows-current (unchanged by this process); "
            f"air address managed by Windows; single subscriber, persistent_binding={state is not None}; "
            f"workout_transfer={workout is not None}; cloud upload unverified"
        )
        await asyncio.sleep(duration)
    finally:
        if bridge is not None:
            bridge.close()
        try:
            if worker is not None:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker
            if token is not None:
                notify.remove_subscribed_clients_changed(token)
        finally:
            await server.stop()
            report("STOPPED")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=_duration, default=300, help="seconds after advertising starts (default: 300)")
    parser.add_argument("--keep-name", action="store_true", help="temporarily use the selected model's name with PnP restarts (administrator); restore original name on exit")
    parser.add_argument("--state", help="Private JSON state file enabling device binding")
    parser.add_argument("--model", choices=tuple(DEVICE_NAMES), default="B3", help="B3 legacy BTCP or B5 SIMPLE framing")
    parser.add_argument("--workout", help="Explicit SPORT44 file to serve; requires --model B5")
    args = parser.parse_args()
    if args.workout is not None and args.model != "B5":
        parser.error("--workout requires --model B5")
    if sys.platform != "win32":
        parser.exit(1, "This entry point requires Windows and requirements-windows.txt.\n")
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("experiments.keep_device.files").setLevel(logging.INFO)
    try:
        if args.keep_name:
            _run_with_keep_name(args.duration, args.state, args.model, args.workout)
        else:
            asyncio.run(run(args.duration, args.state, args.model, args.workout))
    except KeyboardInterrupt:
        pass
    except NameRefreshError as error:
        parser.exit(1, f"{error}\n")
    except Exception as error:
        parser.exit(1, f"Windows device-info experiment failed ({type(error).__name__}).\n")


if __name__ == "__main__":
    main()
