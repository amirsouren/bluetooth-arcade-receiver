"""BlueZ 5 System D-Bus backend engine (specs/09_implementation_checklist.txt -> STEP 2).

Implements the contracts of specs/05_backend_contracts.txt §3 and the notes of
specs/06_dbus_bluez_notes.txt:

* The worker iterates a *dedicated* GLib main context inside a daemon
  background thread (pushed as thread-default before subscribing), so
  D-Bus signals are dispatched without ever touching Qt's event machinery
  (spec 06 §5 option "a", hardening per spec 08 §3).
* ``org.freedesktop.DBus.ObjectManager`` ``InterfacesAdded`` /
  ``InterfacesRemoved`` on ``/`` detect when ``org.bluez.MediaPlayer1``
  appears (phone connected) or disappears (phone disconnected).
* ``org.freedesktop.DBus.Properties.PropertiesChanged`` is filtered for
  interface ``org.bluez.MediaPlayer1`` to capture ``Track`` and ``Status``
  (plus ``Position``).
* AVRCP controls: :meth:`play`, :meth:`pause`, :meth:`next`,
  :meth:`previous` (``Stop()`` is out of MVP scope: spec 01 [F-03]).

Consumer-facing events use the exact names of spec 05 §3::

    sig_device_connected(device_name: str, device_path: str)
    sig_device_disconnected()
    sig_metadata_changed(metadata: TrackMetadata)
    sig_status_changed(status: str)

Threading model
---------------
Callbacks are emitted on the GLib worker thread.  This module deliberately has
**no Qt dependency** (strict layering, spec 00 §2); the Qt controller
(checklist STEP 3) subscribes here and re-emits through ``Qt.Signal`` so the
UI thread absorbs updates via queued connections (spec 08 §3).  The control
methods may be called from any thread: pydbus uses
``GDBusConnection.call_sync``, which is safe from outside the GLib thread.
"""

import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

import pydbus
from gi.repository import GLib

from ..core.config import (
    BLUEZ_BUS_NAME,
    BLUEZ_ROOT_PATH,
    DBUS_START_TIMEOUT_S,
    FALLBACK_DEVICE_NAME,
    IFACE_DEVICE,
    IFACE_MEDIA_PLAYER,
    IFACE_OBJECT_MANAGER,
    IFACE_PROPERTIES,
    STATUS_DISCONNECTED,
    STATUS_STOPPED,
    VALID_STATUSES,
)
from ..core.event_bus import Signal
from ..core.models import PlayerState, TrackMetadata

logger = logging.getLogger(__name__)

__all__ = ["BluezService"]


def _as_ms(value: object) -> int:
    """Best-effort conversion of a D-Bus numeric property to milliseconds."""
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


class BluezService:
    """Background D-Bus listener/remote-control for ``org.bluez`` (BlueZ 5).

    Lifecycle::

        service = BluezService()
        service.sig_device_connected.connect(...)
        service.start()   # spawns the daemon GLib thread + initial scan
        ...
        service.stop()    # quits the loop, unsubscribes everything
    """

    def __init__(self, bus: Any = None) -> None:
        # ``bus`` is injectable for tests (duck-typed pydbus Bus replacement);
        # when None a real pydbus.SystemBus() is created on the worker thread.
        self._bus = bus
        self._context = GLib.MainContext.new()  # dedicated worker context
        self._thread: Optional[threading.Thread] = None
        self._subscriptions: List[Any] = []
        self._ready = threading.Event()
        self._start_error: Optional[BaseException] = None
        self._lock = threading.RLock()
        self._control_lock = threading.Lock()
        self._started = False
        self._stopping = False

        self._player_path: Optional[str] = None
        self._device_path: Optional[str] = None
        self._devices: Dict[str, Dict[str, str]] = {}  # device path -> {name, address}

        # Live state (dataclasses per spec 05 §1) — treat as read-only snapshots.
        self.state = PlayerState()
        self.metadata = TrackMetadata()

        # Signal contract (spec 05 §3).
        self.sig_device_connected = Signal("sig_device_connected")
        self.sig_device_disconnected = Signal("sig_device_disconnected")
        self.sig_metadata_changed = Signal("sig_metadata_changed")
        self.sig_status_changed = Signal("sig_status_changed")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self, timeout: float = DBUS_START_TIMEOUT_S) -> None:
        """Start the background GLib loop and run the initial BlueZ scan.

        Raises ``TimeoutError`` if the worker thread does not come up within
        ``timeout`` seconds, or ``RuntimeError`` if its setup failed (e.g. no
        system D-Bus).  A *missing* ``org.bluez`` service (Bluetooth switched
        off) is **not** an error: the listener keeps waiting for
        ``InterfacesAdded`` (edge case, spec 08).
        """
        if self._started:
            return
        self._ready.clear()
        self._start_error = None
        self._stopping = False
        self._thread = threading.Thread(
            target=self._run, name="BluezGLibLoop", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout):
            raise TimeoutError(
                f"BlueZ D-Bus worker did not start within {timeout:.1f}s"
            )
        if self._start_error is not None:
            error, self._start_error = self._start_error, None
            raise RuntimeError("BlueZ D-Bus worker failed to start") from error
        self._started = True

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the worker loop and release all D-Bus signal subscriptions."""
        thread = self._thread
        self._stopping = True
        # Wake a possibly blocked may-block iteration so the worker observes
        # _stopping immediately (cross-thread teardown, spec 08 §3).  No
        # g_main_loop.quit() is used: its check-then-run race can lose wakeups.
        self._context.wakeup()
        if thread is not None and thread.is_alive():
            thread.join(timeout)
            if thread.is_alive():
                logger.warning("BlueZ worker thread did not stop within %.1fs", timeout)
        self._started = False
        self._thread = None

    @property
    def is_running(self) -> bool:
        """True while the background GLib worker thread is alive."""
        thread = self._thread
        return self._started and thread is not None and thread.is_alive()

    @property
    def player_path(self) -> Optional[str]:
        """Object path of the active ``MediaPlayer1``, if any."""
        with self._lock:
            return self._player_path

    def _run(self) -> None:
        """Worker-thread entry point: set up bus/signals, then iterate."""
        # Own context + thread-default: GDBus dispatches our signal callbacks
        # here, fully decoupled from Qt's event machinery (spec 08 §3).
        self._context.push_thread_default()
        try:
            if self._bus is None:
                self._bus = pydbus.SystemBus()
            self._subscribe()
            self._initial_scan()
        except Exception as error:  # noqa: BLE001 - surfaced via start()
            logger.error("BlueZ worker setup failed: %s", error, exc_info=True)
            self._start_error = error
            self._cleanup_subscriptions()
            self._ready.set()
            self._context.pop_thread_default()
            return
        self._ready.set()
        # Manual may-block iteration instead of GLib.MainLoop.run(): the
        # _stopping flag + context wakeup has no check-then-run race, so
        # stop() is deterministic even racing loop start (spec 08 §3).
        try:
            while not self._stopping:
                self._context.iteration(may_block=True)
        finally:
            self._cleanup_subscriptions()
            self._context.pop_thread_default()

    # ------------------------------------------------------------------
    # Signal wiring (checklist STEP 2: ObjectManager + PropertiesChanged)
    # ------------------------------------------------------------------
    def _subscribe(self) -> None:
        bus = self._bus
        assert bus is not None
        self._subscriptions = [
            # Detect MediaPlayer1 (and Device1) appearing/disappearing.
            bus.subscribe(
                sender=BLUEZ_BUS_NAME,
                object=BLUEZ_ROOT_PATH,
                iface=IFACE_OBJECT_MANAGER,
                signal="InterfacesAdded",
                signal_fired=self._on_interfaces_added,
            ),
            bus.subscribe(
                sender=BLUEZ_BUS_NAME,
                object=BLUEZ_ROOT_PATH,
                iface=IFACE_OBJECT_MANAGER,
                signal="InterfacesRemoved",
                signal_fired=self._on_interfaces_removed,
            ),
            # Track & Status arrive as PropertiesChanged; the player object
            # path is unknown up front, so match every path and filter by
            # interface inside the callback (spec 06 §4).
            bus.subscribe(
                sender=BLUEZ_BUS_NAME,
                iface=IFACE_PROPERTIES,
                signal="PropertiesChanged",
                signal_fired=self._on_properties_changed,
            ),
        ]
        logger.debug("Subscribed to BlueZ ObjectManager + PropertiesChanged signals")

    def _cleanup_subscriptions(self) -> None:
        for subscription in self._subscriptions:
            try:
                subscription.unsubscribe()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                logger.debug("Failed to unsubscribe %r", subscription, exc_info=True)
        self._subscriptions = []

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def _initial_scan(self) -> None:
        """Adopt already-present objects (spec 06 §2: ``GetManagedObjects``)."""
        assert self._bus is not None
        try:
            manager = self._bus.get(BLUEZ_BUS_NAME, BLUEZ_ROOT_PATH)
            objects = manager.GetManagedObjects()
        except Exception as error:  # noqa: BLE001
            # org.bluez absent (Bluetooth off / bluez down): stay up and wait
            # for InterfacesAdded instead of failing (edge case, spec 08).
            logger.info("org.bluez not available yet (%s); waiting for it", error)
            return
        if not isinstance(objects, dict):
            return
        # Pass 1: cache every device so player activation can resolve its name.
        for path, interfaces in objects.items():
            if isinstance(interfaces, dict) and IFACE_DEVICE in interfaces:
                self._cache_device(path, interfaces[IFACE_DEVICE])
        # Pass 2: adopt an already-connected media player.
        for path, interfaces in objects.items():
            if isinstance(interfaces, dict) and IFACE_MEDIA_PLAYER in interfaces:
                self._activate_player(path, interfaces[IFACE_MEDIA_PLAYER])

    def _cache_device(self, path: str, properties: object) -> None:
        props = properties if isinstance(properties, dict) else {}
        name = str(props.get("Alias") or props.get("Name") or "").strip()
        address = str(props.get("Address") or "").strip()
        self._devices[path] = {"name": name, "address": address}

    def _resolve_device(self, player_path: str) -> Tuple[str, str, str]:
        """Return ``(device_path, display_name, address)`` for a player path.

        Player paths look like ``/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF/player0``
        (spec 06 §2), so the owning device is the parent path.  If the device
        was never announced, the MAC is parsed from the path as a last resort.
        """
        device_path = player_path.rsplit("/", 1)[0]
        entry = self._devices.get(device_path)
        if entry is None:
            address = ""
            if "/dev_" in device_path:
                address = device_path.rsplit("/dev_", 1)[1].replace("_", ":")
            entry = {"name": "", "address": address}
            self._devices[device_path] = entry
        display_name = entry["name"] or entry["address"] or FALLBACK_DEVICE_NAME
        return device_path, display_name, entry["address"]

    # ------------------------------------------------------------------
    # Player activation / deactivation
    # ------------------------------------------------------------------
    def _activate_player(self, path: str, props: object = None) -> None:
        """Adopt ``path`` as the active ``MediaPlayer1`` and publish state.

        Runs on the GLib thread (initial scan, ``InterfacesAdded`` or a
        lazily-adopted ``PropertiesChanged``).  Emits a full snapshot
        (connected + metadata + status) so the UI never keeps stale data
        from a previous device.
        """
        properties = props if isinstance(props, dict) else {}
        emit_connect = False
        device_name, device_path = "", ""
        with self._lock:
            if self._player_path == path and self.state.connected:
                emit_connect = False  # duplicate announcement -> refresh only
            else:
                emit_connect = True
                self._player_path = path
                device_path, device_name, device_address = self._resolve_device(path)
                self._device_path = device_path
                self.state = PlayerState(
                    device_name=device_name,
                    device_address=device_address,
                    status=STATUS_STOPPED,
                    position_ms=0,
                    connected=True,
                )
                self.metadata = TrackMetadata()
                # Seed the properties BlueZ usually announces together with
                # the interface (spec 06 §2/§3).
                if "Track" in properties:
                    self.metadata = TrackMetadata.from_bluez_track(
                        properties.get("Track")
                    )
                if "Status" in properties:
                    status = self._normalize_status(properties.get("Status"))
                    if status is not None:
                        self.state.status = status
                if "Position" in properties:
                    self.state.position_ms = _as_ms(properties.get("Position"))
            metadata = self.metadata
            status = self.state.status

        if not emit_connect:
            self._apply_properties_update(path, properties)
            return
        logger.info("Media player appeared: %s (device %r)", path, device_name)
        self.sig_device_connected.emit(device_name, device_path)
        self.sig_metadata_changed.emit(metadata)
        self.sig_status_changed.emit(status)

    def _deactivate_player(self, reason: str) -> None:
        """Forget the active player and publish the disconnection (idempotent)."""
        with self._lock:
            if self._player_path is None and not self.state.connected:
                return  # nothing published yet — stay quiet
            self._player_path = None
            self._device_path = None
            self.state = PlayerState(status=STATUS_DISCONNECTED)
            self.metadata = TrackMetadata()
        logger.info("Media player removed (%s)", reason)
        self.sig_device_disconnected.emit()
        # Keeps the UI status pill in sync; the controller resets the metadata
        # text on sig_device_disconnected (spec 05 §3, spec 08 §1).
        self.sig_status_changed.emit(STATUS_DISCONNECTED)

    # ------------------------------------------------------------------
    # D-Bus callbacks (executed on the GLib worker thread)
    # ------------------------------------------------------------------
    def _on_interfaces_added(
        self, sender: str, object_path: str, iface: str, signal: str, params: Any
    ) -> None:
        try:
            path, interfaces = params  # (ObjectPath, a{sa{sv}}) — pydbus unpacks
        except (TypeError, ValueError):
            return
        if not isinstance(interfaces, dict):
            return
        if IFACE_DEVICE in interfaces:
            self._cache_device(path, interfaces[IFACE_DEVICE])
        if IFACE_MEDIA_PLAYER in interfaces:
            self._activate_player(path, interfaces[IFACE_MEDIA_PLAYER])

    def _on_interfaces_removed(
        self, sender: str, object_path: str, iface: str, signal: str, params: Any
    ) -> None:
        try:
            path, removed_interfaces = params  # (ObjectPath, Array[String])
        except (TypeError, ValueError):
            return
        if isinstance(removed_interfaces, (list, tuple, set, frozenset)):
            if IFACE_MEDIA_PLAYER in removed_interfaces and path == self._player_path:
                self._deactivate_player(f"player removed: {path}")
            elif IFACE_DEVICE in removed_interfaces and path == self._device_path:
                self._deactivate_player(f"device removed: {path}")
        self._devices.pop(path, None)

    def _on_properties_changed(
        self, sender: str, object_path: str, iface: str, signal: str, params: Any
    ) -> None:
        try:
            interface_name, changed, _invalidated = params  # spec 06 §4 signature
        except (TypeError, ValueError):
            return
        if (
            interface_name != IFACE_MEDIA_PLAYER
            or not isinstance(changed, dict)
            or not changed
        ):
            return  # not a MediaPlayer1 change (or nothing usable in it)
        with self._lock:
            active_path = self._player_path
        if active_path is None:
            # InterfacesAdded may have been missed (e.g. subscribed while the
            # player already existed): adopt it lazily on first update.
            last_segment = (object_path or "").rsplit("/", 1)[-1]
            if last_segment.startswith("player"):
                self._activate_player(object_path, changed)
            return
        if object_path != active_path:
            return  # stale update from a player that has since been replaced
        self._apply_properties_update(object_path, changed)

    def _apply_properties_update(self, path: str, changed: dict) -> None:
        """Apply Track/Status/Position changes; emit only what changed."""
        new_metadata: Optional[TrackMetadata] = None
        new_status: Optional[str] = None
        with self._lock:
            if path != self._player_path:
                return
            if "Track" in changed:
                self.metadata = TrackMetadata.from_bluez_track(changed.get("Track"))
                new_metadata = self.metadata
            if "Status" in changed:
                status = self._normalize_status(changed.get("Status"))
                if status is not None and status != self.state.status:
                    self.state.status = status
                    new_status = status
            if "Position" in changed:
                self.state.position_ms = _as_ms(changed.get("Position"))
        # Emit outside the lock so subscribers may call back safely.
        if new_metadata is not None:
            self.sig_metadata_changed.emit(new_metadata)
        if new_status is not None:
            self.sig_status_changed.emit(new_status)

    # ------------------------------------------------------------------
    # AVRCP controls (callable from any thread — spec 06 §3)
    # ------------------------------------------------------------------
    def play(self) -> bool:
        """Remote ``Play()``; returns ``False`` when no player is connected."""
        return self._invoke_player_method("Play")

    def pause(self) -> bool:
        """Remote ``Pause()``; returns ``False`` when no player is connected."""
        return self._invoke_player_method("Pause")

    def next(self) -> bool:
        """Remote ``Next()``; returns ``False`` when no player is connected."""
        return self._invoke_player_method("Next")

    def previous(self) -> bool:
        """Remote ``Previous()``; returns ``False`` when no player is connected."""
        return self._invoke_player_method("Previous")

    def _invoke_player_method(self, method_name: str) -> bool:
        with self._lock:
            path = self._player_path
            bus = self._bus
        if bus is None or path is None:
            logger.debug("Ignoring %s(): no active media player", method_name)
            return False
        with self._control_lock:  # serialize button presses from the UI
            try:
                # bus.get() re-introspects: cheap on the local bus and always
                # consistent with `path` even across reconnects.
                player = bus.get(BLUEZ_BUS_NAME, path)[IFACE_MEDIA_PLAYER]
                getattr(player, method_name)()
            except Exception as error:  # noqa: BLE001 - device may vanish mid-call
                logger.warning("%s() failed: %s", method_name, error)
                return False
        logger.debug("%s() sent to %s", method_name, path)
        return True

    @staticmethod
    def _normalize_status(value: object) -> Optional[str]:
        """Return a known status string (spec 06 §3) or ``None`` if unusable."""
        if value is None:
            return None
        status = str(value).strip().lower()
        return status if status in VALID_STATUSES else None




