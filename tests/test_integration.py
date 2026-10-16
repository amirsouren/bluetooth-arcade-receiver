"""End-to-end edge-case tests: real BluezService wired to real AppController.

Offline half of the spec 07 §2 hardware matrix (rows 01-06) plus the STEP 5
edge cases (bluetooth off, disconnect mid-song).  Backend events travel
through the production bridge — event_bus.Signal -> Qt Signal -> queued slot
(spec 08 §3) — exactly as they do against a real phone.  The FakeBus and
fixtures from the backend suite are reused.

Run from the project root:  ``python -m pytest tests/ -q``
"""

import pathlib
import sys
import threading
import time

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))  # project root -> src package
sys.path.insert(0, str(_HERE))         # -> sibling test modules

from PySide6.QtCore import QCoreApplication  # noqa: E402

from src.core.config import IFACE_DEVICE, IFACE_MEDIA_PLAYER  # noqa: E402
from src.core.models import DISCONNECTED_LABEL, FALLBACK_TITLE  # noqa: E402
from src.services.bluez_service import BluezService  # noqa: E402
from src.ui.controller import AppController  # noqa: E402
from test_bluez_service import (  # noqa: E402
    DEVICE_PATH,
    DEVICE_PROPS,
    PLAYER_PATH,
    PLAYER_PROPS,
    FakeBus,
)


@pytest.fixture(scope="session")
def qapp():
    """One QCoreApplication for the session (headless-safe)."""
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([sys.argv[0]])
    return app


def _pump(app, rounds=6):
    """Spin the GUI loop so queued backend events get absorbed."""
    for _ in range(rounds):
        app.processEvents()
        time.sleep(0.005)


def _make_stack(bus):
    backend = BluezService(bus=bus)
    controller = AppController(service=backend)
    assert controller.start() is True
    return backend, controller


def _connected_stack(app):
    bus = FakeBus(managed_objects={
        DEVICE_PATH: {IFACE_DEVICE: DEVICE_PROPS},
        PLAYER_PATH: {IFACE_MEDIA_PLAYER: PLAYER_PROPS},
    })
    backend, controller = _make_stack(bus)
    _pump(app)
    return bus, backend, controller


def test_row01_04_connect_metadata_controls(qapp):
    """Rows 01-04: connect -> live metadata -> control round-trips."""
    bus, _backend, controller = _connected_stack(qapp)
    try:
        assert controller.isConnected is True          # row 01: CONNECTED
        assert controller.deviceName == "Galaxy S23"
        # row 02: title & artist displayed while playing
        assert controller.trackTitle == "Nightcall"
        assert controller.trackArtist == "Kavinsky"
        assert controller.durationMs == 259000
        assert controller.positionMs == 1200
        assert controller.playbackStatus == "playing"

        # row 03: Pause in UI -> the call reaches the backend...
        controller.pause()
        assert bus.player.calls == ["Pause"]
        # ...and the phone reports the new status back over AVRCP.
        bus.fire("PropertiesChanged",
                 (IFACE_MEDIA_PLAYER, {"Status": "paused"}, []),
                 object_path=PLAYER_PATH)
        _pump(qapp)
        assert controller.playbackStatus == "paused"

        # row 04: Next in UI -> new track metadata (immediate here, <500ms)
        controller.nextTrack()
        assert bus.player.calls == ["Pause", "Next"]
        bus.fire("PropertiesChanged",
                 (IFACE_MEDIA_PLAYER, {"Track": {"Title": "Resonance",
                                                 "Artist": "HOME",
                                                 "Album": "Odyssey",
                                                 "Duration": 212000}}, []),
                 object_path=PLAYER_PATH)
        _pump(qapp)
        assert controller.trackTitle == "Resonance"
        assert controller.durationMs == 212000
    finally:
        controller.shutdown()


def test_row05_disconnect_mid_song_resets_ui(qapp):
    """Row 05: phone vanishes mid-song -> UI resets, controls disable safely."""
    bus, _backend, controller = _connected_stack(qapp)
    try:
        assert controller.trackTitle == "Nightcall"
        # Removal arrives on a foreign thread, like the real GLib worker's.
        thread = threading.Thread(
            target=bus.fire,
            args=("InterfacesRemoved", (PLAYER_PATH, [IFACE_MEDIA_PLAYER])),
        )
        thread.start()
        thread.join(2.0)
        _pump(qapp)

        assert controller.isConnected is False
        assert controller.playbackStatus == "disconnected"
        assert controller.trackTitle == FALLBACK_TITLE
        assert controller.deviceName == DISCONNECTED_LABEL
        assert controller.durationMs == 0

        # Controls remain safe no-ops after the disconnect.
        before = len(bus.player.calls)
        controller.play()
        controller.togglePlayPause()
        assert len(bus.player.calls) == before
    finally:
        controller.shutdown()


def test_row06_reconnect_restores_metadata(qapp):
    """Row 06: reconnect -> player re-detected, metadata restored."""
    bus, _backend, controller = _connected_stack(qapp)
    try:
        bus.fire("InterfacesRemoved", (PLAYER_PATH, [IFACE_MEDIA_PLAYER]))
        _pump(qapp)
        assert controller.isConnected is False

        bus.fire("InterfacesAdded",
                 (PLAYER_PATH, {IFACE_MEDIA_PLAYER: PLAYER_PROPS}))
        _pump(qapp)
        assert controller.isConnected is True
        assert controller.deviceName == "Galaxy S23"
        assert controller.trackTitle == "Nightcall"
        assert controller.playbackStatus == "playing"
    finally:
        controller.shutdown()


def test_bluetooth_off_startup_then_recovery(qapp):
    """Edge case: Bluetooth/BlueZ off at launch -> degraded, later recovery."""
    bus = FakeBus(fail_get=True)  # org.bluez not on the bus
    _backend, controller = _make_stack(bus)
    try:
        _pump(qapp)
        assert controller.isConnected is False
        assert controller.playbackStatus == "disconnected"

        # Stack comes up later and announces the already-paired phone.
        bus.fire("InterfacesAdded", (DEVICE_PATH, {IFACE_DEVICE: DEVICE_PROPS}))
        bus.fire("InterfacesAdded",
                 (PLAYER_PATH, {IFACE_MEDIA_PLAYER: PLAYER_PROPS}))
        _pump(qapp)
        assert controller.isConnected is True
        assert controller.deviceName == "Galaxy S23"
    finally:
        controller.shutdown()

