"""Offline mock player for UI testing (specs/07_testing_plan.txt §1).

Launches the real QML arcade window with an emulated backend that pushes
fake track data — no Bluetooth hardware required:

    Track 1: Nightcall - Kavinsky (259000 ms)
    Track 2: Resonance - HOME     (212000 ms)

The demo connects a fake "Galaxy S23", starts playback and advances a track
every 12 seconds; the UI buttons respond through the *real*
AppController -> mock-backend signal path, so marquee scrolling, the
play/pause glyph flip and the state pill can all be validated offline.

Run from the project root:  ``venv/bin/python tests/mock_player.py``
"""

import sys
from pathlib import Path

# Make the project root importable regardless of how this file is launched.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from src.core.event_bus import Signal
from src.core.models import PlayerState, TrackMetadata
from src.main import (
    _avoid_broken_gtk3_theme,
    _load_pixel_font,
    _QML_ENTRY,
    _theme,
)
from src.ui.controller import AppController

TRACKS = [
    TrackMetadata(
        title="Nightcall", artist="Kavinsky", album="OutRun",
        duration_ms=259000, track_number=1,
    ),
    TrackMetadata(
        title="Resonance", artist="HOME", album="Odyssey",
        duration_ms=212000, track_number=2,
    ),
]
FAKE_DEVICE_PATH = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"


class MockBlueZService:
    """Duck-typed BluezService double that drives the UI like a phone would."""

    def __init__(self):
        self.sig_device_connected = Signal("mock.connected")
        self.sig_device_disconnected = Signal("mock.disconnected")
        self.sig_metadata_changed = Signal("mock.metadata")
        self.sig_status_changed = Signal("mock.status")
        self.state = PlayerState()
        self.metadata = TRACKS[0]
        self._index = 0
        self._connected = False

    # --- lifecycle (called by AppController.start/shutdown) --------------
    def start(self):
        pass

    def stop(self):
        pass

    @property
    def is_running(self):
        return True

    # --- emulated device events (scheduled by the demo) ------------------
    def connect_device(self):
        self._connected = True
        self.state = PlayerState(
            device_name="Galaxy S23",
            device_address="AA:BB:CC:DD:EE:FF",
            status="paused",
            position_ms=0,
            connected=True,
        )
        self.sig_device_connected.emit("Galaxy S23", FAKE_DEVICE_PATH)
        self.set_track(0)
        self.set_status("playing")

    def set_track(self, index):
        self._index = index % len(TRACKS)
        self.metadata = TRACKS[self._index]
        self.state.position_ms = 0
        self.sig_metadata_changed.emit(self.metadata)

    def set_status(self, status):
        self.state.status = status
        self.sig_status_changed.emit(status)

    # --- controls invoked by the real controller slots -------------------
    def play(self):
        if self._connected:
            self.set_status("playing")
            return True
        return False

    def pause(self):
        if self._connected:
            self.set_status("paused")
            return True
        return False

    def next(self):
        if self._connected:
            self.set_track(self._index + 1)
            return True
        return False

    def previous(self):
        if self._connected:
            self.set_track(self._index - 1)
            return True
        return False


def main() -> int:
    _avoid_broken_gtk3_theme()
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Bluetooth Arcade Receiver (Mock)")

    mock = MockBlueZService()
    controller = AppController(service=mock)
    controller.start()

    engine = QQmlApplicationEngine()
    context = engine.rootContext()
    context.setContextProperty("controller", controller)
    context.setContextProperty("Theme", _theme())
    context.setContextProperty("pixelFontFamily", _load_pixel_font())
    engine.load(_QML_ENTRY)
    if not engine.rootObjects():
        controller.shutdown()
        return 1
    controller.setWindow(engine.rootObjects()[0])
    app.aboutToQuit.connect(controller.shutdown)

    # Demo schedule: connect after 600 ms, then advance a track every 12 s.
    QTimer.singleShot(600, mock.connect_device)
    ticker = QTimer()
    ticker.timeout.connect(mock.next)
    ticker.start(12000)

    print("Mock player running — use the buttons, close the window to exit.")
    exit_code = app.exec()
    controller.shutdown()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
