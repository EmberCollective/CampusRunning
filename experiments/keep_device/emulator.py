"""Run the B3/B5 prototype over Bumble; official Keep acceptance is unverified."""

import argparse
import asyncio
import logging
from pathlib import Path

from bumble.device import Device
from bumble.hci import Address
from bumble.transport import open_transport
from bumble.transport.common import TransportInitError

from .protocol import advertisement, b3_service
from .state import BindingState
from .btcp import DEVICE_NAMES
from .files import WorkoutFiles


def report(message: str) -> None:
    print(message, flush=True)


def static_address(value: str) -> Address:
    address = Address(value)
    if not address.is_static or bytes(address) in (b"\x00" * 5 + b"\xc0", b"\xff" * 6):
        raise ValueError("Use a valid static random address generated for this experiment.")
    return address


async def run(
    transport_spec: str, name: str, write_characteristic: int, address: Address | None = None,
    state_path: str | None = None,
    model: str = "B3",
    workout_path: str | None = None,
    workout_dir: str | None = None,
    stop_file: str | None = None,
) -> None:
    stop_path = Path(stop_file) if stop_file else None
    if stop_path is not None and (stop_path.exists() or not stop_path.parent.is_dir()):
        raise ValueError("Stop file must be a new file in an existing directory")
    prefixes = ("KeepB5",) if model == "B5" else ("Keep B3", "Keep-B3")
    if model not in DEVICE_NAMES or not name.startswith(prefixes):
        raise ValueError("Advertising name must match the selected model")
    if (workout_path is not None or workout_dir is not None) and model != "B5":
        raise ValueError("--workout requires --model B5")
    paths = None
    if workout_dir is not None:
        directory = Path(workout_dir)
        if not directory.is_dir():
            raise ValueError("Workout directory does not exist")
        paths = sorted(directory.glob("*.sport44"))
    workout = WorkoutFiles(workout_path, paths=paths) if model == "B5" else None
    if paths is not None:
        report(f"BATCH_READY files={len(paths)}; receipt is not proof of valid activity")
    advertising_data = advertisement(name)
    if state_path is not None and address is None:
        raise ValueError("--state requires --address to preserve device identity across restarts")
    # Reuse our own generated address across retries without borrowing a device identity.
    address = address or Address.generate_static_address()
    state = BindingState(state_path, str(address)) if state_path is not None else None

    async with await open_transport(transport_spec) as transport:
        device = Device.with_hci(name, address, transport.source, transport.sink)
        device.add_service(b3_service(device, write_characteristic, report, state, model, workout))

        def on_connection(connection) -> None:
            report(f"CONNECTED; persistent_binding={state is not None}; workout_transfer={workout is not None}")
            connection.on("disconnection", lambda reason: report(f"DISCONNECTED reason={reason}"))

        device.on("connection", on_connection)
        await device.power_on()
        await device.start_advertising(advertising_data=advertising_data, auto_restart=True)
        report(
            f"ADVERTISING name={name!r} address={address} service=190a "
            f"write={write_characteristic}; persistent_binding={state is not None}; "
            f"workout_transfer={workout is not None}; cloud upload unverified"
        )
        if stop_path is None:
            await transport.source.terminated
        else:
            while not stop_path.exists():
                done, _ = await asyncio.wait([transport.source.terminated], timeout=1)
                if done:
                    break
            await device.stop_advertising()
            report("STOPPED")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transport", help="Bumble transport, e.g. android-netsim:127.0.0.1:PORT")
    parser.add_argument("--name", help="Optional advertising name matching the selected model")
    parser.add_argument("--model", choices=tuple(DEVICE_NAMES), default="B3")
    parser.add_argument("--state", help="Private JSON state file enabling device binding; requires --address")
    workouts = parser.add_mutually_exclusive_group()
    workouts.add_argument("--workout", help="Explicit SPORT44 file to serve; requires --model B5")
    workouts.add_argument("--workout-dir", help="Fixed batch of 1-64 SPORT44 files; requires --model B5")
    parser.add_argument("--stop-file", help="Stop when this initially absent file appears")
    parser.add_argument(
        "--address", type=static_address,
        help="Reuse this experiment's previously generated static random address",
    )
    parser.add_argument(
        "--write-characteristic",
        type=int,
        choices=(1, 2),
        default=1,
        help="Experimental direction, not a recovered protocol fact (default: 1)",
    )
    args = parser.parse_args()
    if (args.workout is not None or args.workout_dir is not None) and args.model != "B5":
        parser.error("--workout requires --model B5")
    # Bumble debug output can contain raw application traffic.
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("experiments.keep_device.files").setLevel(logging.INFO)
    try:
        asyncio.run(run(args.transport, args.name or DEVICE_NAMES[args.model], args.write_characteristic,
                        args.address, args.state, args.model, args.workout,
                        workout_dir=args.workout_dir, stop_file=args.stop_file))
    except KeyboardInterrupt:
        report("STOPPED")
    except (ValueError, OSError, TransportInitError) as error:
        parser.exit(1, f"Unable to start the virtual device: {error}\n")


if __name__ == "__main__":
    main()
