"""Unit tests for the Qt controller bridge (spec 09 STEP 3, spec 05 §2).

Offline: a stub backend replaces ``BluezService``; a ``QCoreApplication``
delivers the controller's explicitly queued connections.  The key scenario
(spec 08 §3) — events emitted from a foreign thread only reach the properties
after the GUI loop is pumped — is covered as well.

Run from the project root:  ``python -m pytest tests/ -q``
"""

import pathlib
import sys
import threading

import pytest

# Make the project root importable regardless of the pytest invocation mode.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from src.core.event_bus import Signal  # noqa: E402
from src.core.models import (  # noqa: E402
    DISCONNECTED_LABEL,
    FALLBACK_ALBUM,
    FALLBACK_ARTIST,
    FALLBACK_TITLE,
    PlayerState,
    TrackMetadata,
)
from src.ui.controller import AppController  # noqa: E402

NIGHTCALL = TrackMetadata(
    title="Nightcall", artist="Kavinsky", album="OutRun",
    duration_ms=259000, track_number=1,
)
PLAYER_PATH = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF/player0"


class StubService:
    """Duck-typed BluezService double: same signals, controls and state."""

    def __init__(self):
        self.sig_device_connected = Signal("stub.connected")
        self.sig_device_disconnected = Signal("stub.disconnected")
        self.sig_metadata_changed = Signal("stub.metadata")
        self.sig_status_changed = Signal("stub.status")
        self.state = PlayerState()
        self.metadata = TrackMetadata()
        self.calls = []
        self.started = False

    # --- lifecycle -------------------------------------------------------
    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    @property
    def is_running(self):
        return self.started

    # --- controls --------------------------------------------------------
    def play(self):
        self.calls.append("play")
        return self.state.connected

    def pause(self):
        self.calls.append("pause")
        return self.state.connected

    def next(self):
        self.calls.append("next")
        return self.state.connected

    def previous(self):
        self.calls.append("previous")
        return self.state.connected


class ExplodingStub(StubService):
    def start(self):
        raise RuntimeError("system D-Bus unavailable")


class StubWindow:
    def __init__(self):
        self.closed = 0
        self.minimized = 0

    def close(self):
        self.closed += 1

    def showMinimized(self):
        self.minimized += 1


@pytest.fixture(scope="session")
def qapp():
    """One QCoreApplication for the whole session (headless-safe)."""
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([sys.argv[0]])
    return app


@pytest.fixture
def harness(qapp):
    """Controller + stub backend wired exactly like production, with a pump."""
    stub = StubService()
    controller = AppController(service=stub)
    assert controller.start() is True
    window = StubWindow()
    controller.setWindow(window)

    def pump():
        qapp.processEvents()

    yield controller, stub, window, pump
    controller.shutdown()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_initial_property_defaults(harness):
    controller, _stub, _window, _pump = harness
    assert controller.trackTitle == FALLBACK_TITLE
    assert controller.trackArtist == FALLBACK_ARTIST
    assert controller.trackAlbum == FALLBACK_ALBUM
    assert controller.playbackStatus == "disconnected"
    assert controller.deviceName == DISCONNECTED_LABEL
    assert controller.isConnected is False
    assert controller.positionMs == 0
    assert controller.durationMs == 0


def test_connect_updates_connection_properties(harness):
    controller, stub, _window, pump = harness
    stub.state = PlayerState(device_name="Galaxy S23", connected=True, status="playing")
    stub.sig_device_connected.emit("Galaxy S23", PLAYER_PATH)
    pump()  # queued delivery requires the GUI loop to spin
    assert controller.isConnected is True
    assert controller.deviceName == "Galaxy S23"


def test_status_mapping_to_ui_vocabulary(harness):
    controller, stub, _window, pump = harness
    expected = [
        ("playing", "playing"),
        ("paused", "paused"),
        ("stopped", "idle"),
        ("forward-seek", "idle"),
        ("reverse-seek", "idle"),
        ("disconnected", "disconnected"),
    ]
    for raw, ui in expected:
        stub.sig_status_changed.emit(raw)
        pump()
        assert controller.playbackStatus == ui, f"raw {raw!r} must map to {ui!r}"
    # Unknown future values degrade safely to "idle" (spec 05 §2 vocabulary).
    stub.sig_status_changed.emit("some-new-thing")
    pump()
    assert controller.playbackStatus == "idle"


def test_metadata_properties_and_spec08_fallbacks(harness):
    controller, stub, _window, pump = harness
    stub.sig_device_connected.emit("Galaxy S23", PLAYER_PATH)
    stub.sig_metadata_changed.emit(NIGHTCALL)
    pump()
    assert controller.trackTitle == "Nightcall"
    assert controller.trackArtist == "Kavinsky"
    assert controller.trackAlbum == "OutRun"
    assert controller.durationMs == 259000

    # Phone sent no metadata -> never blanks: STREAMING AUDIO + device name
    # (specs/08_risks_and_fallbacks.txt §1).
    stub.sig_metadata_changed.emit(TrackMetadata())  # all defaults
    pump()
    assert controller.trackTitle == "STREAMING AUDIO"
    assert controller.trackArtist == "Galaxy S23"


def test_disconnect_resets_state_to_defaults(harness):
    controller, stub, _window, pump = harness
    stub.sig_device_connected.emit("Galaxy S23", PLAYER_PATH)
    stub.sig_metadata_changed.emit(NIGHTCALL)
    stub.sig_status_changed.emit("playing")
    pump()
    assert controller.isConnected is True
    assert controller.trackTitle == "Nightcall"

    stub.state = PlayerState(status="disconnected")
    stub.sig_device_disconnected.emit()
    stub.sig_status_changed.emit("disconnected")
    pump()
    assert controller.isConnected is False
    assert controller.deviceName == DISCONNECTED_LABEL
    assert controller.trackTitle == FALLBACK_TITLE
    assert controller.trackArtist == FALLBACK_ARTIST
    assert controller.playbackStatus == "disconnected"
    assert controller.durationMs == 0
    assert controller.positionMs == 0


def test_control_slots_forward_to_backend(harness):
    controller, stub, _window, _pump = harness
    controller.play()
    controller.pause()
    controller.nextTrack()
    controller.previousTrack()
    assert stub.calls == ["play", "pause", "next", "previous"]


def test_toggle_play_pause(harness):
    controller, stub, _window, pump = harness
    # Disconnected: toggle must be a safe no-op.
    controller.togglePlayPause()
    assert stub.calls == []

    stub.sig_device_connected.emit("Galaxy S23", PLAYER_PATH)
    stub.sig_status_changed.emit("playing")
    pump()
    controller.togglePlayPause()
    assert stub.calls == ["pause"]

    stub.sig_status_changed.emit("paused")
    pump()
    controller.togglePlayPause()
    assert stub.calls == ["pause", "play"]


def test_close_and_minimize_use_attached_window(harness):
    controller, _stub, window, _pump = harness
    controller.closeApp()
    controller.minimizeApp()
    assert window.closed == 1
    assert window.minimized == 1


def test_backend_thread_events_reach_gui_thread_safely(harness):
    """Spec 08 §3: foreign-thread emissions queue; GUI loop absorbs them."""
    controller, stub, _window, pump = harness
    errors = []

    def emit_like_glib_thread():
        try:
            stub.sig_device_connected.emit("Pixel 8", PLAYER_PATH)
            stub.sig_metadata_changed.emit(NIGHTCALL)
            stub.sig_status_changed.emit("playing")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=emit_like_glib_thread, name="FakeGLib")
    thread.start()
    thread.join(2.0)
    assert not errors
    assert not thread.is_alive()
    # Emission done but the GUI loop has not run yet -> still old values.
    assert controller.isConnected is False
    pump()
    assert controller.isConnected is True
    assert controller.deviceName == "Pixel 8"
    assert controller.trackTitle == "Nightcall"
    assert controller.playbackStatus == "playing"


def test_start_and_shutdown_lifecycle(qapp):
    stub = StubService()
    controller = AppController(service=stub)
    assert stub.started is False
    assert controller.start() is True
    assert stub.started is True

    controller.shutdown()
    assert stub.started is False

    # Detached: late backend events must not touch the controller any more.
    stub.sig_device_connected.emit("Ghost", PLAYER_PATH)
    qapp.processEvents()
    assert controller.isConnected is False


def test_start_failure_keeps_app_degraded_not_broken(qapp):
    controller = AppController(service=ExplodingStub())
    assert controller.start() is False  # logged, but no exception escapes
    assert controller.isConnected is False
    # Slots remain callable and harmless without a running backend.
    controller.play()
    controller.togglePlayPause()

