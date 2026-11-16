"""Fake notification transport tests; these do not start a Windows BLE service."""

import argparse
import asyncio
from contextlib import suppress
import subprocess
import sys
from tempfile import TemporaryDirectory
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from experiments.keep_device.btcp import CHARACTERISTIC_UUIDS, decode_frame, encode_frame
from experiments.keep_device.state import BindingState
from experiments.keep_device.windows import (
    DeviceInfoBridge, NameRefreshError, _duration, _refresh_radio, _restart_adapter, _run_with_keep_name,
    _temporary_keep_name, main,
)


REQUEST = bytes.fromhex("a5a5a000040001020303678d")
WRITE = SimpleNamespace(uuid=CHARACTERISTIC_UUIDS[0])


def client(name="one", size=20):
    return SimpleNamespace(
        session=SimpleNamespace(device_id=SimpleNamespace(id=name)),
        max_notification_size=size,
    )


class FakeNotify:
    def __init__(self):
        self.subscribed_clients = [client()]
        self.calls = []
        self.status = 0
        self.short = False
        self.on_send = None

    async def notify_value_async(self, data, subscriber):
        self.calls.append((bytes(data), subscriber.session.device_id.id))
        if self.on_send is not None:
            self.on_send()
        await asyncio.sleep(0)
        return SimpleNamespace(status=self.status, bytes_sent=len(data) - int(self.short))


class WindowsDeviceInfoTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.notify = FakeNotify()
        self.messages = []
        self.bridge = DeviceInfoBridge(self.notify, "C1:23:45:67:89:AB", self.messages.append, bytes)
        self.worker = asyncio.create_task(self.bridge.serve())

    async def asyncTearDown(self):
        self.bridge.close()
        self.worker.cancel()
        with suppress(asyncio.CancelledError):
            await self.worker

    async def settle(self):
        await asyncio.sleep(0)
        await self.bridge.queue.join()
        await asyncio.sleep(0)

    async def request(self, data=REQUEST):
        await asyncio.to_thread(self.bridge.write_request, WRITE, data)
        await self.settle()

    def sent(self):
        return sum(message.startswith("DEVICE_INFO_SENT") for message in self.messages)

    async def test_cross_thread_write_splits_and_awaits_all_notifications(self):
        await self.request()
        self.assertGreater(len(self.notify.calls), 1)
        self.assertTrue(all(len(data) <= 20 and key == "one" for data, key in self.notify.calls))
        self.assertEqual(decode_frame(b"".join(data for data, _ in self.notify.calls)).fsn, 0)
        self.assertEqual(self.sent(), 1)
        self.notify.calls.clear()
        await self.request()
        self.assertEqual(decode_frame(b"".join(data for data, _ in self.notify.calls)).fsn, 1)

    async def test_unknown_and_sensitive_payloads_are_not_queued_or_logged(self):
        secret = b"token=private-binding-data"
        for data in (secret, encode_frame(b"\x01\x05", 0), REQUEST[:-1]):
            await self.request(data)
        self.assertEqual(self.notify.calls, [])
        self.assertEqual(self.sent(), 0)
        self.assertNotIn("token", " ".join(self.messages))
        await self.request()
        self.assertEqual(decode_frame(b"".join(data for data, _ in self.notify.calls)).fsn, 0)

    async def test_binding_write_persists_even_when_notification_fails(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "device.json"
            self.bridge.state = BindingState(path, self.bridge.mac)
            self.notify.status = 1
            await self.request(encode_frame(b"\x01\x05", 0))
            self.assertTrue(BindingState(path, self.bridge.mac).bound)
            self.assertFalse(any(message.startswith("DEVICE_REPLY_SENT") for message in self.messages))
            self.notify.status = 0
            self.notify.calls.clear()
            self.bridge.subscription_changed(self.notify, None)
            await self.settle()
            await self.request()
            reply = decode_frame(b"".join(data for data, _ in self.notify.calls))
            self.assertEqual(reply.fsn, 0)
            self.assertTrue(reply.payload.endswith(b"\x30\x01"))

    async def test_b5_notification_fragments_keep_their_own_headers(self):
        self.bridge.model = "B5"
        await self.request(bytes.fromhex("34 12 00 00 00 01 02 03 03 5b 2c"))
        packets = [data for data, _ in self.notify.calls]
        self.assertGreater(len(packets), 1)
        for index, packet in enumerate(packets):
            self.assertLessEqual(len(packet), 20)
            self.assertEqual(packet[:7], b"\x34\x12\x01" + bytes((len(packets) - 1, index, 1, 2)))
        self.assertIn(b"KeepB5 Lab", b"".join(packet[7:] for packet in packets))
        self.assertEqual(self.sent(), 1)
        self.assertTrue(any(message.startswith("DEVICE_INFO_SENT bytes=11 sid=01 cid=02 flags=00")
                            for message in self.messages))

    async def test_b5_device_info_query_without_body_reaches_the_subscriber(self):
        from experiments.keep_device.test_simple import request_packet

        self.bridge.model = "B5"
        await self.request(request_packet(0x1234, b"\x01\x02"))
        self.assertEqual(self.sent(), 1)
        packets = [data for data, _ in self.notify.calls]
        self.assertTrue(all(packet[:3] == b"\x34\x12\x01" for packet in packets))
        self.assertIn(b"KeepB5 Lab", b"".join(packet[7:] for packet in packets))

    async def test_subscription_change_discards_queued_binding_before_state_mutation(self):
        with TemporaryDirectory() as directory:
            self.bridge.state = BindingState(Path(directory) / "device.json", self.bridge.mac)
            self.bridge.write_request(WRITE, encode_frame(b"\x01\x05", 0))
            self.bridge.subscription_changed(self.notify, None)
            await self.settle()
            self.assertFalse(self.bridge.state.bound)
            self.assertEqual(self.notify.calls, [])

    async def test_unsubscribed_and_multiple_clients_get_no_reply(self):
        for clients in ([], [client("one"), client("two")]):
            self.notify.subscribed_clients = clients
            await self.request()
        self.assertEqual(self.notify.calls, [])
        self.assertEqual(self.sent(), 0)

    async def test_status_failure_never_reports_sent(self):
        self.notify.status = 1
        await self.request()
        self.assertEqual(len(self.notify.calls), 1)
        self.assertEqual(self.sent(), 0)
        self.assertTrue(any(message.startswith("DEVICE_INFO_FAILED") for message in self.messages))

    async def test_short_send_never_reports_sent(self):
        self.notify.short = True
        await self.request()
        self.assertEqual(len(self.notify.calls), 1)
        self.assertEqual(self.sent(), 0)

    async def test_invalid_notification_size_cannot_loop_or_claim_success(self):
        self.notify.subscribed_clients = [client(size=0)]
        await self.request()
        self.assertEqual(self.notify.calls, [])
        self.assertEqual(self.sent(), 0)

    async def test_subscription_change_during_send_stops_remaining_chunks_and_resets(self):
        def replace_client():
            self.notify.subscribed_clients = [client("two")]
            self.bridge.subscription_changed(self.notify, None)
            self.notify.on_send = None

        self.notify.on_send = replace_client
        await self.request()
        self.assertEqual(len(self.notify.calls), 1)
        self.assertEqual(self.sent(), 0)
        self.notify.calls.clear()
        await self.request()
        self.assertTrue(all(key == "two" for _, key in self.notify.calls))
        self.assertEqual(decode_frame(b"".join(data for data, _ in self.notify.calls)).fsn, 0)

    async def test_queued_old_request_cannot_cross_reconnect_even_to_same_device(self):
        self.bridge.write_request(WRITE, REQUEST)
        self.bridge.subscription_changed(self.notify, None)
        await self.settle()
        self.assertEqual(self.notify.calls, [])
        await self.request()
        self.assertEqual(decode_frame(b"".join(data for data, _ in self.notify.calls)).fsn, 0)

    async def test_new_client_without_event_does_not_receive_old_request(self):
        self.bridge.write_request(WRITE, REQUEST)
        self.notify.subscribed_clients = [client("two")]
        await self.settle()
        self.assertEqual(self.notify.calls, [])

    async def test_callback_backlog_is_bounded(self):
        for _ in range(9):
            self.bridge.write_request(WRITE, REQUEST)
        await self.settle()
        self.assertEqual(self.sent(), 8)
        self.assertTrue(any("queue-full" in message for message in self.messages))

    async def test_shutdown_discards_pending_callbacks(self):
        self.bridge.write_request(WRITE, REQUEST)
        self.bridge.close()
        await self.settle()
        self.assertEqual(self.notify.calls, [])

    def test_duration_rejects_unbounded_or_invalid_values(self):
        for value in (0, -1, "nan", "inf"):
            with self.assertRaises(argparse.ArgumentTypeError):
                _duration(value)


class TemporaryNameTests(unittest.TestCase):
    def setUp(self):
        self.registry = MagicMock()
        self.registry.KEY_QUERY_VALUE = 1
        self.registry.KEY_SET_VALUE = 2
        self.key = self.registry.OpenKeyEx.return_value.__enter__.return_value
        self.adapter = SimpleNamespace(
            _adapter_name=r"USB\LAB\ADAPTER",
            _set_registry_name=Mock(),
            _dev=SimpleNamespace(Close=Mock()),
        )
        self.patch = patch.dict("sys.modules", {
            "winreg": self.registry,
            "bless.backends.winrt.ble": SimpleNamespace(BLEAdapter=Mock(return_value=self.adapter)),
        })
        self.patch.start()
        self.addCleanup(self.patch.stop)
        restart_patch = patch("experiments.keep_device.windows._restart_adapter")
        self.restart = restart_patch.start()
        self.addCleanup(restart_patch.stop)
        process_patch = patch("experiments.keep_device.windows.subprocess.Popen")
        self.process = process_patch.start()
        self.addCleanup(process_patch.stop)
        self.child = self.process.return_value
        self.child.pid = 4242
        self.child.wait.return_value = 0
        self.child.poll.return_value = 0
        taskkill_patch = patch("experiments.keep_device.windows.subprocess.run")
        self.taskkill = taskkill_patch.start()
        self.taskkill.return_value.returncode = 0
        self.addCleanup(taskkill_patch.stop)
        radio_patch = patch("experiments.keep_device.windows._refresh_radio")
        self.radio_refresh = radio_patch.start()
        self.addCleanup(radio_patch.stop)
        environment_patch = patch.dict("os.environ", {"SystemRoot": "C:/Windows", "COMPUTERNAME": "LABPC"})
        environment_patch.start()
        self.addCleanup(environment_patch.stop)
        print_patch = patch("builtins.print")
        self.print = print_patch.start()
        self.addCleanup(print_patch.stop)

    def test_absent_value_is_removed_after_temporary_name(self):
        self.registry.QueryValueEx.side_effect = FileNotFoundError
        with _temporary_keep_name(self.adapter):
            self.adapter._set_registry_name.assert_called_once_with("Keep B3 Lab")
            self.registry.DeleteValue.assert_not_called()
        self.registry.OpenKeyEx.assert_called_once_with(
            self.registry.HKEY_LOCAL_MACHINE,
            r"SYSTEM\ControlSet001\Enum\USB\LAB\ADAPTER\Device Parameters", 0, 3,
        )
        self.registry.DeleteValue.assert_called_once_with(self.key, "Local Name")
        self.registry.SetValueEx.assert_not_called()
        self.assertEqual(
            [call.args for call in self.adapter._set_registry_name.call_args_list],
            [("Keep B3 Lab",), ("LABPC",)],
        )
        self.assertEqual(self.restart.call_count, 2)

    def test_original_binary_value_and_type_are_restored_exactly(self):
        original = b"Original\x00\xff"
        self.registry.QueryValueEx.return_value = (original, 3)
        with patch.dict("os.environ", {}, clear=True):
            with _temporary_keep_name(self.adapter):
                pass
        self.registry.SetValueEx.assert_called_once_with(self.key, "Local Name", 0, 3, original)
        self.registry.DeleteValue.assert_not_called()
        self.assertEqual(self.restart.call_count, 2)

    def test_body_exception_restores_original_value(self):
        self.registry.QueryValueEx.return_value = ("Original", 1)
        with self.assertRaisesRegex(RuntimeError, "advertising failed"):
            with _temporary_keep_name(self.adapter):
                raise RuntimeError("advertising failed")
        self.registry.SetValueEx.assert_called_once_with(self.key, "Local Name", 0, 1, "Original")
        self.assertEqual(self.restart.call_count, 2)

    def test_partial_rename_failure_still_restores_missing_value(self):
        self.registry.QueryValueEx.side_effect = FileNotFoundError
        self.adapter._set_registry_name.side_effect = [OSError("failed after registry write"), None]
        with self.assertRaises(OSError):
            with _temporary_keep_name(self.adapter):
                self.fail("rename failed before body")
        self.registry.DeleteValue.assert_called_once_with(self.key, "Local Name")
        self.restart.assert_called_once_with(self.adapter._adapter_name)

    def test_handle_closed_before_rename_and_restart_and_restore_after_body(self):
        self.registry.QueryValueEx.side_effect = FileNotFoundError
        events = []
        self.adapter._dev.Close.side_effect = lambda: events.append("close")
        self.adapter._set_registry_name.side_effect = lambda name: events.append("name:" + name)
        self.restart.side_effect = lambda name: events.append("restart")
        self.registry.DeleteValue.side_effect = lambda *args: events.append("restore")
        with _temporary_keep_name(self.adapter):
            events.append("body")
        self.assertEqual(events, [
            "close", "name:Keep B3 Lab", "restart", "body", "name:LABPC", "restart", "restore",
        ])
        self.assertTrue(all(call.args == (self.adapter._adapter_name,) for call in self.restart.call_args_list))

    def test_initial_restart_failure_restores_and_never_runs_body(self):
        self.registry.QueryValueEx.side_effect = FileNotFoundError
        self.restart.side_effect = [NameRefreshError("restart required"), None]
        with self.assertRaisesRegex(NameRefreshError, "restart required"):
            with _temporary_keep_name(self.adapter):
                self.fail("must not advertise after failed refresh")
        self.registry.DeleteValue.assert_called_once_with(self.key, "Local Name")
        self.assertEqual(self.restart.call_count, 2)

    def test_restoration_restart_failure_is_not_claimed_as_success(self):
        self.registry.QueryValueEx.side_effect = FileNotFoundError
        self.restart.side_effect = [None, NameRefreshError("restore restart required")]
        self.registry.DeleteValue.side_effect = lambda *args: self.assertEqual(self.restart.call_count, 2)
        with self.assertRaisesRegex(NameRefreshError, "restore restart required"):
            with _temporary_keep_name(self.adapter):
                pass
        self.registry.DeleteValue.assert_called_once_with(self.key, "Local Name")

    def test_absent_override_without_computername_refuses_before_name_change(self):
        self.registry.QueryValueEx.side_effect = FileNotFoundError
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(NameRefreshError, "COMPUTERNAME.*no name change attempted"):
                _run_with_keep_name(3)
        self.adapter._set_registry_name.assert_not_called()
        self.restart.assert_not_called()
        self.process.assert_not_called()
        self.registry.SetValueEx.assert_not_called()
        self.registry.DeleteValue.assert_not_called()

    def test_default_name_write_failure_still_removes_originally_absent_override(self):
        self.registry.QueryValueEx.side_effect = FileNotFoundError
        self.adapter._set_registry_name.side_effect = [None, OSError("default name write failed")]
        with self.assertRaisesRegex(OSError, "default name write failed"):
            _run_with_keep_name(3)
        self.registry.DeleteValue.assert_called_once_with(self.key, "Local Name")
        self.restart.assert_called_once_with(self.adapter._adapter_name)
        self.assertFalse(any("NAME_REGISTRY_RESTORED" in call.args[0] for call in self.print.call_args_list))

    def test_close_failure_leaves_registry_untouched(self):
        self.adapter._dev.Close.side_effect = OSError("handle close failed")
        with self.assertRaises(OSError):
            with _temporary_keep_name(self.adapter):
                self.fail("must not rename without closing handle")
        self.adapter._set_registry_name.assert_not_called()
        self.registry.SetValueEx.assert_not_called()
        self.registry.DeleteValue.assert_not_called()
        self.restart.assert_not_called()

    def test_child_starts_after_restart_without_recursive_name_flag_and_exits_before_restore(self):
        self.registry.QueryValueEx.side_effect = FileNotFoundError
        events = []
        self.adapter._dev.Close.side_effect = lambda: events.append("close")
        self.adapter._set_registry_name.side_effect = lambda name: events.append("name:" + name)
        self.restart.side_effect = lambda name: events.append("restart")
        self.process.side_effect = lambda command: events.append("child-start") or self.process.return_value
        self.child.wait.side_effect = lambda: events.append("child-exit") or 0
        self.registry.DeleteValue.side_effect = lambda *args: events.append("restore")
        self.radio_refresh.side_effect = lambda: events.append("radio-refresh")
        _run_with_keep_name(3)
        self.process.assert_called_once_with([
            sys.executable, "-m", "experiments.keep_device.windows", "--duration", "3.0",
        ])
        self.assertEqual(events, [
            "close", "name:Keep B3 Lab", "restart", "child-start", "child-exit",
            "name:LABPC", "restart", "restore", "radio-refresh",
        ])
        self.child.terminate.assert_not_called()
        self.taskkill.assert_not_called()

    @patch("experiments.keep_device.windows.WorkoutFiles")
    def test_b5_name_state_and_workout_are_forwarded_to_fresh_child(self, workout):
        self.registry.QueryValueEx.side_effect = FileNotFoundError
        _run_with_keep_name(3, "C:/private/device-b5.json", "B5", "C:/private/run.sport44")
        workout.assert_called_once_with("C:/private/run.sport44")
        self.adapter._set_registry_name.assert_any_call("KeepB5 Lab")
        self.process.assert_called_once_with([
            sys.executable, "-m", "experiments.keep_device.windows", "--duration", "3.0",
            "--state", "C:/private/device-b5.json", "--model", "B5",
            "--workout", "C:/private/run.sport44",
        ])

    @patch("experiments.keep_device.windows.WorkoutFiles", side_effect=ValueError("invalid file"))
    def test_invalid_workout_does_not_rename_or_start_child(self, workout):
        with self.assertRaisesRegex(ValueError, "invalid file"):
            _run_with_keep_name(3, model="B5", workout_path="invalid.sport44")
        self.adapter._set_registry_name.assert_not_called()
        self.restart.assert_not_called()
        self.process.assert_not_called()

    def test_child_failure_is_reported_after_original_name_is_restored(self):
        self.registry.QueryValueEx.return_value = (b"Original", 3)
        self.child.wait.return_value = self.child.poll.return_value = 7
        with self.assertRaises(subprocess.CalledProcessError) as raised:
            _run_with_keep_name(3)
        self.assertEqual(raised.exception.returncode, 7)
        self.registry.SetValueEx.assert_called_once_with(self.key, "Local Name", 0, 3, b"Original")
        self.assertEqual(self.restart.call_count, 2)

    def test_child_start_failure_restores_original_missing_value(self):
        self.registry.QueryValueEx.side_effect = FileNotFoundError
        self.process.side_effect = OSError("cannot create process")
        with self.assertRaises(OSError):
            _run_with_keep_name(3)
        self.registry.DeleteValue.assert_called_once_with(self.key, "Local Name")
        self.assertEqual(self.restart.call_count, 2)

    def test_wait_failure_reaps_running_child_before_restoring(self):
        self.registry.QueryValueEx.side_effect = FileNotFoundError
        self.child.wait.side_effect = [RuntimeError("wait failed"), 0]
        self.child.poll.return_value = None
        self.registry.DeleteValue.side_effect = lambda *args: self.assertEqual(self.child.wait.call_count, 2)
        with self.assertRaisesRegex(RuntimeError, "wait failed"):
            _run_with_keep_name(3)
        self.taskkill.assert_called_once()
        self.child.terminate.assert_not_called()
        self.registry.DeleteValue.assert_called_once_with(self.key, "Local Name")

    def test_interrupt_allows_child_cleanup_then_restores(self):
        self.registry.QueryValueEx.side_effect = FileNotFoundError
        self.child.wait.side_effect = [KeyboardInterrupt, 0]
        with self.assertRaises(KeyboardInterrupt):
            _run_with_keep_name(3)
        self.assertEqual(self.child.wait.call_args_list[-1].kwargs, {"timeout": 10})
        self.child.terminate.assert_not_called()
        self.taskkill.assert_not_called()
        self.registry.DeleteValue.assert_called_once_with(self.key, "Local Name")
        self.radio_refresh.assert_awaited_once()

    def test_interrupt_terminates_and_reaps_child_if_cleanup_times_out(self):
        self.registry.QueryValueEx.side_effect = FileNotFoundError
        self.child.wait.side_effect = [KeyboardInterrupt, subprocess.TimeoutExpired("child", 10), 0]
        self.child.poll.return_value = None
        self.registry.DeleteValue.side_effect = lambda *args: self.assertEqual(self.child.wait.call_count, 3)
        with self.assertRaises(KeyboardInterrupt):
            _run_with_keep_name(3)
        self.taskkill.assert_called_once()
        args, kwargs = self.taskkill.call_args
        self.assertTrue(args[0][0].replace("\\", "/").endswith("/System32/taskkill.exe"))
        self.assertEqual(args[0][1:], ["/PID", "4242", "/T", "/F"])
        self.assertEqual(kwargs, {"capture_output": True, "timeout": 30, "check": False})
        self.assertEqual(self.child.wait.call_args_list[-1].kwargs, {"timeout": 30})
        self.child.terminate.assert_not_called()
        self.registry.DeleteValue.assert_called_once_with(self.key, "Local Name")
        self.assertEqual(self.restart.call_count, 2)

    def test_process_tree_cleanup_failure_is_reported_without_claiming_restoration(self):
        self.registry.QueryValueEx.side_effect = FileNotFoundError
        self.child.wait.side_effect = [KeyboardInterrupt, subprocess.TimeoutExpired("child", 10)]
        self.child.poll.return_value = None
        self.taskkill.return_value.returncode = 5
        with self.assertRaisesRegex(NameRefreshError, "process-tree cleanup failed.*exit 5"):
            _run_with_keep_name(3)
        self.registry.DeleteValue.assert_called_once_with(self.key, "Local Name")
        self.radio_refresh.assert_not_awaited()
        self.assertFalse(any("NAME_REGISTRY_RESTORED" in call.args[0] for call in self.print.call_args_list))

    def test_failed_initial_restart_does_not_spawn_child(self):
        self.registry.QueryValueEx.side_effect = FileNotFoundError
        self.restart.side_effect = [NameRefreshError("initial restart failed"), None]
        with self.assertRaisesRegex(NameRefreshError, "initial restart failed"):
            _run_with_keep_name(3)
        self.process.assert_not_called()
        self.registry.DeleteValue.assert_called_once_with(self.key, "Local Name")

    def test_restore_failure_after_child_exit_is_not_reported_as_success(self):
        self.registry.QueryValueEx.side_effect = FileNotFoundError
        self.restart.side_effect = [None, NameRefreshError("restore restart failed")]
        with self.assertRaisesRegex(NameRefreshError, "restore restart failed"):
            _run_with_keep_name(3)
        self.child.wait.assert_called_once()
        self.radio_refresh.assert_not_awaited()
        self.assertFalse(any("NAME_REGISTRY_RESTORED" in call.args[0] for call in self.print.call_args_list))

    def test_radio_refresh_failure_after_name_restore_is_not_reported_as_success(self):
        self.registry.QueryValueEx.side_effect = FileNotFoundError
        self.radio_refresh.side_effect = NameRefreshError("radio access denied")
        with self.assertRaisesRegex(NameRefreshError, "radio access denied"):
            _run_with_keep_name(3)
        self.registry.DeleteValue.assert_called_once_with(self.key, "Local Name")
        self.assertEqual(self.restart.call_count, 2)
        self.assertFalse(any("NAME_REGISTRY_RESTORED" in call.args[0] for call in self.print.call_args_list))


class RadioRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.radio = SimpleNamespace(state=1)
        self.radio.set_state_async = AsyncMock(side_effect=self.set_state)
        adapter = SimpleNamespace(get_radio_async=AsyncMock(return_value=self.radio))
        self.bluetooth_adapter = SimpleNamespace(get_default_async=AsyncMock(return_value=adapter))
        modules = patch.dict("sys.modules", {
            "winrt.windows.devices.bluetooth": SimpleNamespace(BluetoothAdapter=self.bluetooth_adapter),
            "winrt.windows.devices.radios": SimpleNamespace(
                RadioAccessStatus=SimpleNamespace(ALLOWED=1),
                RadioState=SimpleNamespace(ON=1, OFF=2),
            ),
        })
        modules.start()
        self.addCleanup(modules.stop)
        timeout = patch("experiments.keep_device.windows._RADIO_TIMEOUT_SECONDS", 0.02)
        timeout.start()
        self.addCleanup(timeout.stop)

    async def set_state(self, state):
        self.radio.state = state
        return 1

    async def test_on_radio_cycles_off_then_on_and_confirms_restoration(self):
        await _refresh_radio()
        self.assertEqual([call.args for call in self.radio.set_state_async.await_args_list], [(2,), (1,)])
        self.assertEqual(self.radio.state, 1)

    async def test_adapter_reenumeration_after_pnp_is_awaited(self):
        adapter = self.bluetooth_adapter.get_default_async.return_value
        self.bluetooth_adapter.get_default_async.side_effect = [None, adapter]
        with patch("experiments.keep_device.windows._RADIO_TIMEOUT_SECONDS", 0.5):
            await _refresh_radio()
        self.assertEqual(self.bluetooth_adapter.get_default_async.await_count, 2)
        self.assertEqual(self.radio.state, 1)

    async def test_missing_adapter_times_out_without_changing_radio(self):
        self.bluetooth_adapter.get_default_async.return_value = None
        with self.assertRaisesRegex(NameRefreshError, "TimeoutError"):
            await _refresh_radio()
        self.radio.set_state_async.assert_not_awaited()

    async def test_non_on_radio_is_never_forced_on(self):
        for state in (0, 2, 3):
            with self.subTest(state=state):
                self.radio.state = state
                await _refresh_radio()
                self.assertEqual(self.radio.state, state)
        self.radio.set_state_async.assert_not_awaited()

    async def test_denied_off_is_reported_even_when_original_state_is_preserved(self):
        async def deny_off(state):
            return 2 if state == 2 else await self.set_state(state)

        self.radio.set_state_async.side_effect = deny_off
        with self.assertRaisesRegex(NameRefreshError, "did not allow"):
            await _refresh_radio()
        self.assertEqual(self.radio.state, 1)
        self.assertEqual([call.args for call in self.radio.set_state_async.await_args_list], [(2,), (1,)])

    async def test_partial_off_failure_still_restores_original_state(self):
        async def partial_failure(state):
            self.radio.state = state
            if state == 2:
                raise OSError("failed after turning off")
            return 1

        self.radio.set_state_async.side_effect = partial_failure
        with self.assertRaisesRegex(NameRefreshError, "radio refresh failed"):
            await _refresh_radio()
        self.assertEqual(self.radio.state, 1)

    async def test_cancellation_during_off_still_restores_original_state(self):
        entered = asyncio.Event()

        async def pending_off(state):
            self.radio.state = state
            if state == 2:
                entered.set()
                await asyncio.Future()
            return 1

        self.radio.set_state_async.side_effect = pending_off
        task = asyncio.create_task(_refresh_radio())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.radio.state, 1)

    async def test_denied_restore_is_reported(self):
        async def deny_on(state):
            return 2 if state == 1 else await self.set_state(state)

        self.radio.set_state_async.side_effect = deny_on
        with self.assertRaisesRegex(NameRefreshError, "did not allow"):
            await _refresh_radio()
        self.assertEqual(self.radio.state, 2)

    async def test_allowed_restore_without_state_change_times_out(self):
        async def leave_off(state):
            return 1 if state == 1 else await self.set_state(state)

        self.radio.set_state_async.side_effect = leave_off
        with self.assertRaisesRegex(NameRefreshError, "TimeoutError"):
            await _refresh_radio()
        self.assertEqual(self.radio.state, 2)

    async def test_off_state_timeout_still_attempts_and_confirms_original_state(self):
        async def leave_on(state):
            return 1 if state == 2 else await self.set_state(state)

        self.radio.set_state_async.side_effect = leave_on
        with self.assertRaisesRegex(NameRefreshError, "TimeoutError"):
            await _refresh_radio()
        self.assertEqual(self.radio.state, 1)
        self.assertEqual([call.args for call in self.radio.set_state_async.await_args_list], [(2,), (1,)])


class EntryPointTests(unittest.TestCase):
    @patch("experiments.keep_device.windows.sys.platform", "win32")
    @patch("experiments.keep_device.windows.sys.argv", ["windows", "--keep-name", "--duration", "3"])
    @patch("experiments.keep_device.windows.asyncio.run")
    @patch("experiments.keep_device.windows._run_with_keep_name")
    def test_named_parent_never_runs_advertising_in_process(self, named_run, async_run):
        main()
        named_run.assert_called_once_with(3.0, None, "B3", None)
        async_run.assert_not_called()

    @patch("experiments.keep_device.windows.sys.platform", "win32")
    @patch("experiments.keep_device.windows.sys.argv", ["windows", "--duration", "3"])
    @patch("experiments.keep_device.windows._run_with_keep_name")
    @patch("experiments.keep_device.windows.asyncio.run")
    @patch("experiments.keep_device.windows.run", new_callable=Mock)
    def test_default_entry_stays_in_process_without_name_changes(self, run, async_run, named_run):
        main()
        run.assert_called_once_with(3.0, None, "B3", None)
        async_run.assert_called_once_with(run.return_value)
        named_run.assert_not_called()


class PnpRestartTests(unittest.TestCase):
    @patch.dict("os.environ", {"SystemRoot": "C:/Windows"})
    @patch("experiments.keep_device.windows.subprocess.run")
    def test_restart_targets_only_exact_instance_and_never_reboots(self, run):
        run.return_value.returncode = 0
        _restart_adapter(r"USB\LAB\ADAPTER")
        args, kwargs = run.call_args
        self.assertTrue(args[0][0].replace("\\", "/").endswith("/System32/pnputil.exe"))
        self.assertEqual(args[0][1:], ["/restart-device", r"USB\LAB\ADAPTER"])
        self.assertEqual(kwargs, {"capture_output": True, "timeout": 30, "check": False})

    @patch.dict("os.environ", {"SystemRoot": "C:/Windows"})
    @patch("experiments.keep_device.windows.subprocess.run")
    def test_reboot_required_and_failure_are_errors(self, run):
        for code in (3010, 5):
            with self.subTest(code=code):
                run.return_value.returncode = code
                with self.assertRaisesRegex(NameRefreshError, str(code)):
                    _restart_adapter(r"USB\LAB\ADAPTER")


if __name__ == "__main__":
    unittest.main()
