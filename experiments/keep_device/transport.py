"""Backend-neutral B5 transport contract; existing backends are not migrated yet.

Only standard-library types belong here. Target discovery and backend-specific
configuration are supplied when constructing an implementation, not by the B5
protocol or the watch panel. See TRANSPORT.md for lifecycle and delivery rules.
"""

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class BindingAddress:
    """Current usable address, not the identity returned inside DeviceInfo.

    None means unavailable or no longer valid. A physical address requires
    evidence from the active advertising controller; never substitute the
    controller's permanent identity address.
    """

    value: str | None
    medium: Literal["virtual", "physical"]


@dataclass(frozen=True)
class LinkState:
    """The single active notification recipient in this transport session."""

    connection_id: str
    subscribed: bool
    notification_limit: int  # Maximum characteristic-value bytes, not ATT MTU.


class TransportError(RuntimeError):
    """A sanitized transport failure; never contains credentials or raw traffic."""


class TransportEvents(Protocol):
    """Callbacks run on the caller's asyncio loop and are awaited.

    Preserve event order; do not dispatch unbounded background write tasks.
    Events belong to one start/stop lifecycle and cannot survive its stop.
    """

    async def on_address(self, address: BindingAddress) -> None:
        """Publish an evidenced binding address or explicitly invalidate it."""
        ...

    async def on_link(self, link: LinkState | None) -> None:
        """Report connection, subscription or payload-limit changes; None disconnects."""
        ...

    async def on_write(self, connection_id: str | None, packet: bytes) -> None:
        """Deliver unchanged write bytes; None means the writer cannot be identified.

        ValueError rejects invalid/unsupported requests; OSError indicates failed
        persistence. Do not invent a successful business reply in either case.
        """
        ...

    async def on_error(self, error: TransportError) -> None:
        """Report a fatal runtime failure; the owner must stop this lifecycle."""
        ...


class B5Transport(Protocol):
    """Expose the fixed B5 GATT service through a caller-selected backend.

    This is a structural interface: implementations need not inherit it.
    Instances are stopped initially; reuse after stop is supported.
    """

    async def start(self, *, name: str, events: TransportEvents) -> None:
        """Install B5 GATT and enable advertising, or raise TransportError.

        Return only after the backend confirms advertising, not after launching
        a process. On failure clean up only resources owned by this instance.
        A second start while active is rejected; stop() remains safe.
        """
        ...

    async def notify(self, connection_id: str, packet: bytes) -> None:
        """Send one whole notification to that live, subscribed recipient.

        Preserve ordering; fail on a stale recipient, oversize data, timeout or
        reported partial delivery. Success is backend acceptance, not a Keep
        file receipt, device binding, or cloud acceptance.
        """
        ...

    async def stop(self) -> None:
        """Idempotently stop advertising/connections and finish owned work.

        Invalidate the address/link and restore owned temporary settings before
        returning. Report cleanup failures; never stop unrelated processes.
        """
        ...
