"""Show the current Keep advertising MAC from a local BTVS/TShark trace.

Start BTVS, then this observer, then the Windows B5 prototype. No packet logging
policy, radio configuration, binding state, or workout files are changed here.
"""

import argparse
from collections import defaultdict, deque
import re
import subprocess
import sys

from .windows import _duration, _terminate_child_tree


_FIELDS = (
    "bthci_cmd.opcode", "bthci_cmd.advertising_handle", "bthci_cmd.bd_addr",
    "bthci_cmd.le_own_address_type", "bthci_cmd.advertising_properties",
    "bthci_cmd.le_advts_enable", "btcommon.eir_ad.entry.uuid_16",
    "bthci_evt.opcode", "bthci_evt.status",
)
_OPCODES = (0x0C03, 0x2035, 0x2036, 0x2037, 0x2039, 0x203C)
_FILTER = " || ".join(
    f"{field} == {opcode:#x}" for field in (_FIELDS[0], _FIELDS[7]) for opcode in _OPCODES
)


class AdvertisingAddress:
    """Track successful decoded HCI commands, without parsing raw packets."""

    def __init__(self):
        self.pending = defaultdict(deque)
        self.sets = {}
        self.current = ()

    def feed(self, line):
        fields = line.rstrip("\r\n").split("\t")
        if len(fields) != len(_FIELDS):
            raise ValueError("Unexpected TShark field output")
        command, handles, mac, own_type, properties, enabled, services, event, status = fields
        if command:
            self.pending[int(command, 0)].append(fields)
            return None
        if not event or not self.pending[int(event, 0)]:
            return None
        command, handles, mac, own_type, properties, enabled, services, _, _ = self.pending[int(event, 0)].popleft()
        if int(status, 0) != 0:
            return None
        opcode = int(command, 0)
        if opcode == 0x0C03:
            self.sets.clear()
            self.pending.clear()
        else:
            for handle in handles.split(","):
                key = int(handle, 0)
                state = self.sets.setdefault(key, {})
                if opcode == 0x2036:
                    state.clear()
                    state.update(own_type=int(own_type, 0), properties=int(properties, 0))
                elif opcode == 0x2035:
                    if re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", mac) is None:
                        raise ValueError("TShark did not decode the random address")
                    state["mac"] = mac.upper()
                elif opcode == 0x2037:
                    state["keep_service"] = "0x190a" in services.lower().split(",")
                elif opcode == 0x2039:
                    state["enabled"] = int(enabled, 0) == 1
                elif opcode == 0x203C:
                    self.sets.pop(key)
        # shortcut: one Windows controller, random-address legacy advertising; extend for other HCI modes.
        addresses = tuple(sorted({state["mac"] for state in self.sets.values()
                                  if state.get("enabled") and state.get("keep_service")
                                  and state.get("own_type") == 1
                                  and state.get("properties", 0) & 0x13 == 0x13
                                  and state.get("mac") not in (None, "00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF")}))
        if addresses == self.current:
            return None
        self.current = addresses
        if len(addresses) == 1:
            return f"AIR_MAC={addresses[0]} KEEP_MAC={addresses[0].replace(':', '')}"
        return "AIR_MAC_UNAVAILABLE reason=" + ("multiple-matching-advertisements" if addresses else "not-advertising")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tshark", default="tshark", help="TShark executable (default: search PATH)")
    parser.add_argument("--duration", type=_duration, default=300, help="observation seconds (default: 300)")
    args = parser.parse_args()
    command = [args.tshark, "-l", "-n", "-i", "TCP@127.0.0.1:24352",
               "-a", f"duration:{args.duration:g}", "-Y", _FILTER, "-T", "fields"]
    for field in _FIELDS:
        command.extend(["-e", field])
    process = None
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, text=True, encoding="utf-8")
        print("WAITING_FOR_MAC; start the Windows B5 prototype after this observer", flush=True)
        tracker = AdvertisingAddress()
        for line in process.stdout:
            message = tracker.feed(line)
            if message:
                print(message, flush=True)
        if process.wait():
            parser.exit(1, "MAC observation failed; check BTVS and TShark.\n")
        if len(tracker.current) != 1:
            parser.exit(1, "No active matching address; capture must begin before advertising starts.\n")
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError) as error:
        parser.exit(1, f"Unable to observe the advertising MAC: {error}\n")
    finally:
        if process is not None and process.poll() is None:
            try:
                process.wait(timeout=5)  # Console Ctrl+C also reaches TShark and its dumpcap child.
            except subprocess.TimeoutExpired:
                if sys.platform == "win32":
                    _terminate_child_tree(process)
                else:
                    process.terminate()
                process.wait(timeout=5)
        if process is not None and process.stdout is not None:
            process.stdout.close()


if __name__ == "__main__":
    main()
