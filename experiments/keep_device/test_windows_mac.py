"""Synthetic TShark fields; no personal captures or real Bluetooth required."""

from io import StringIO
from unittest.mock import Mock

import pytest

from experiments.keep_device import windows_mac
from experiments.keep_device.windows_mac import AdvertisingAddress


def command(tracker, opcode, handle="0x01", mac="", own="", properties="", enabled="", services="", status="0x00"):
    assert tracker.feed("\t".join((hex(opcode), handle, mac, own, properties, enabled, services, "", ""))) is None
    return tracker.feed("\t".join(("", "", "", "", "", "", "", hex(opcode), status)))


def configure(tracker, handle="0x01", mac="41:23:45:67:89:AB", own="0x01", properties="0x0013", services="0x180a,0x190a"):
    command(tracker, 0x2036, handle, own=own, properties=properties)
    command(tracker, 0x2037, handle, services=services)
    command(tracker, 0x2035, handle, mac=mac)


def test_only_confirmed_connectable_scannable_keep_advertisement_is_reported():
    tracker = AdvertisingAddress()
    configure(tracker, "0x00", "01:23:45:67:89:AB", services="")
    assert command(tracker, 0x2039, "0x00", enabled="0x01") is None
    configure(tracker, "0x02", "42:23:45:67:89:AB", properties="0x0001")
    assert command(tracker, 0x2039, "0x02", enabled="0x01") is None
    configure(tracker)
    assert command(tracker, 0x2039, enabled="0x01") == "AIR_MAC=41:23:45:67:89:AB KEEP_MAC=4123456789AB"
    assert command(tracker, 0x2039, enabled="0x01") is None


def test_failed_commands_never_claim_an_address_and_rotation_invalidates_old_mac():
    tracker = AdvertisingAddress()
    command(tracker, 0x2036, own="0x01", properties="0x0013")
    command(tracker, 0x2037, services="0x190a")
    command(tracker, 0x2035, mac="41:23:45:67:89:AB", status="0x0c")
    assert command(tracker, 0x2039, enabled="0x01") is None
    assert command(tracker, 0x2035, mac="41:23:45:67:89:AB").startswith("AIR_MAC=")
    assert command(tracker, 0x2039, enabled="0x00") == "AIR_MAC_UNAVAILABLE reason=not-advertising"
    assert command(tracker, 0x2035, mac="42:23:45:67:89:AB") is None
    assert command(tracker, 0x2039, enabled="0x01", status="0x0c") is None
    assert command(tracker, 0x2039, enabled="0x01") == "AIR_MAC=42:23:45:67:89:AB KEEP_MAC=4223456789AB"
    assert command(tracker, 0x0C03, handle="") == "AIR_MAC_UNAVAILABLE reason=not-advertising"


@pytest.mark.parametrize("own,mac", [("0x00", "41:23:45:67:89:AB"), ("0x03", "41:23:45:67:89:AB"),
                                    ("0x01", "00:00:00:00:00:00"), ("0x01", "FF:FF:FF:FF:FF:FF")])
def test_unknown_or_unsupported_addresses_are_not_replaced_with_adapter_identity(own, mac):
    tracker = AdvertisingAddress()
    configure(tracker, mac=mac, own=own)
    assert command(tracker, 0x2039, enabled="0x01") is None
    assert tracker.current == ()


def test_ambiguous_sets_are_reported_instead_of_picking_an_address():
    tracker = AdvertisingAddress()
    configure(tracker)
    command(tracker, 0x2039, enabled="0x01")
    configure(tracker, "0x03", "43:23:45:67:89:AB")
    assert command(tracker, 0x2039, "0x03", enabled="0x01") == "AIR_MAC_UNAVAILABLE reason=multiple-matching-advertisements"
    assert command(tracker, 0x203C, "0x03") == "AIR_MAC=41:23:45:67:89:AB KEEP_MAC=4123456789AB"
    assert command(tracker, 0x2039, "0x01,0x02", enabled="0x00") == "AIR_MAC_UNAVAILABLE reason=not-advertising"


def test_starting_mid_capture_does_not_guess_from_random_address_alone():
    tracker = AdvertisingAddress()
    assert command(tracker, 0x2035, mac="41:23:45:67:89:AB") is None
    assert command(tracker, 0x2039, enabled="0x01") is None
    assert tracker.current == ()
    with pytest.raises(ValueError, match="Unexpected TShark"):
        tracker.feed("invalid output")


def test_reset_discards_unconfirmed_commands_from_the_previous_controller_state():
    tracker = AdvertisingAddress()
    for fields in (
        ("0x2036", "0x01", "", "0x01", "0x0013", "", "", "", ""),
        ("0x2037", "0x01", "", "", "", "", "0x190a", "", ""),
        ("0x2035", "0x01", "41:23:45:67:89:AB", "", "", "", "", "", ""),
        ("0x2039", "0x01", "", "", "", "0x01", "", "", ""),
    ):
        assert tracker.feed("\t".join(fields)) is None
    command(tracker, 0x0C03, handle="")
    for opcode in (0x2036, 0x2037, 0x2035, 0x2039):
        assert tracker.feed("\t".join(("", "", "", "", "", "", "", hex(opcode), "0x00"))) is None
    assert tracker.current == ()


@pytest.mark.parametrize("returncode", [0, 1])
def test_cli_rejects_empty_or_failed_capture_without_claiming_a_mac(monkeypatch, capsys, returncode):
    process = Mock(stdout=StringIO(""))
    process.wait.return_value = returncode
    process.poll.return_value = returncode
    start = Mock(return_value=process)
    monkeypatch.setattr(windows_mac.subprocess, "Popen", start)
    monkeypatch.setattr("sys.argv", ["windows_mac", "--tshark", "C:/tools/tshark.exe", "--duration", "5"])
    with pytest.raises(SystemExit) as error:
        windows_mac.main()
    assert error.value.code == 1
    assert "AIR_MAC=" not in capsys.readouterr().out
    arguments = start.call_args.args[0]
    assert "TCP@127.0.0.1:24352" in arguments and "duration:5" in arguments
    assert "-w" not in arguments


def test_cli_prints_live_address_and_invalidation_without_changing_bluetooth(monkeypatch, capsys):
    lines = []
    tracker = AdvertisingAddress()
    original_feed = tracker.feed

    def record(line):
        lines.append(line + "\n")
        return original_feed(line)

    tracker.feed = record
    configure(tracker)
    command(tracker, 0x2039, enabled="0x01")
    command(tracker, 0x2039, enabled="0x00")
    process = Mock(stdout=StringIO("".join(lines)))
    process.wait.return_value = 0
    process.poll.return_value = 0
    monkeypatch.setattr(windows_mac.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr("sys.argv", ["windows_mac"])
    with pytest.raises(SystemExit) as error:
        windows_mac.main()
    assert error.value.code == 1  # The last observed state is no longer advertising.
    output = capsys.readouterr().out
    assert "AIR_MAC=41:23:45:67:89:AB KEEP_MAC=4123456789AB" in output
    assert "AIR_MAC_UNAVAILABLE reason=not-advertising" in output
