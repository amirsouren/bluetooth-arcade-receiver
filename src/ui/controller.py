"""Qt controller bridge (specs/09_implementation_checklist.txt -> STEP 3).

``AppController`` is the single QObject exposed to QML.  It implements the
backend contract of specs/05_backend_contracts.txt §2 (read-only properties +
slots) and safely absorbs events arriving from the BlueZ GLib thread
(specs/08_risks_and_fallbacks.txt §3)::

    BluezService (GLib worker thread)
        -- event_bus.Signal --> internal Qt signal (``_dbus*``)
        -- Qt.QueuedConnection (explicit) --> private slots run on GUI thread
        -- notify --> QML property bindings

State is therefore only ever mutated on the Qt GUI thread: D-Bus callbacks
merely re-emit Qt signals and Qt delivers them through queued connections.
"""

import logging
from typing import Optional

from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    Property,
    Qt,
    Signal,
    Slot,
)

from ..core.config import (
    FALLBACK_STREAMING_TITLE,
    STATUS_DISCONNECTED,
    STATUS_FORWARD_SEEK,
    STATUS_PAUSED,
    STATUS_PLAYING,
    STATUS_REVERSE_SEEK,
    STATUS_STOPPED,
)
from ..core.models import (
    DISCONNECTED_LABEL,
    FALLBACK_ALBUM,
    FALLBACK_ARTIST,
    FALLBACK_TITLE,
    TrackMetadata,
)
from ..services.bluez_service import BluezService

logger = logging.getLogger(__name__)

__all__ = ["AppController"]

# Backend status (spec 06 §3) -> UI vocabulary "playing"/"paused"/"idle"/
# "disconnected" (spec 05 §2).
_STATUS_MAP = {
    STATUS_PLAYING: "playing",
    STATUS_PAUSED: "paused",
    STATUS_STOPPED: "idle",
    STATUS_FORWARD_SEEK: "idle",
    STATUS_REVERSE_SEEK: "idle",
    STATUS_DISCONNECTED: "disconnected",
}


def _to_ui_status(status: str) -> str:
    """Map any backend status onto the four-value UI contract (spec 05 §2)."""
    return _STATUS_MAP.get(status, "idle")


class AppController(QObject):
    """QML-facing bridge: backend state as Qt properties + control slots."""

    # --- internal carriers: GLib thread -> GUI thread (spec 08 §3) -----------
    _dbusDeviceConnected = Signal(str, str)  # (device_name, device_path)
    _dbusDeviceDisconnected = Signal()
    _dbusMetadataChanged = Signal(object)    # TrackMetadata
    _dbusStatusChanged = Signal(str)         # raw backend status

    # --- property notify signals (spec 05 §2) --------------------------------
    trackTitleChanged = Signal()
    trackArtistChanged = Signal()
    trackAlbumChanged = Signal()
    playbackStatusChanged = Signal()
    deviceNameChanged = Signal()
    isConnectedChanged = Signal()
    positionMsChanged = Signal()
    durationMsChanged = Signal()

    def __init__(
        self,
        service: Optional[BluezService] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        # A ready-made (e.g. stubbed) backend may be injected for tests/mock
        # mode; otherwise a fresh, *not yet started* BluezService is created.
        self._service = service if service is not None else BluezService()
        self._window = None  # attached later via setWindow() (main.py, STEP 4)

        # Backing fields — spec-safe defaults, never blank (spec 08 §1).
        self._track_title = FALLBACK_TITLE
        self._track_artist = FALLBACK_ARTIST
        self._track_album = FALLBACK_ALBUM
        self._playback_status = "disconnected"
        self._device_name = DISCONNECTED_LABEL
        self._is_connected = False
        self._position_ms = 0
        self._duration_ms = 0

        # Bridge wiring: backend event_bus.Signal -> Qt signal .emit.  The
        # backend invokes these callbacks on its GLib thread; emitting a Qt
        # signal there is safe because every downstream connection below is
        # explicitly queued (spec 08 §3).
        self._cb_connected = self._dbusDeviceConnected.emit
        self._cb_disconnected = self._dbusDeviceDisconnected.emit
        self._cb_metadata = self._dbusMetadataChanged.emit
        self._cb_status = self._dbusStatusChanged.emit
        self._service.sig_device_connected.connect(self._cb_connected)
        self._service.sig_device_disconnected.connect(self._cb_disconnected)
        self._service.sig_metadata_changed.connect(self._cb_metadata)
        self._service.sig_status_changed.connect(self._cb_status)

        # Explicit queued delivery: slots always run on the GUI thread, even
        # when the signal happens to be emitted from that same thread.
        self._dbusDeviceConnected.connect(
            self._onDeviceConnected, Qt.ConnectionType.QueuedConnection
        )
        self._dbusDeviceDisconnected.connect(
            self._onDeviceDisconnected, Qt.ConnectionType.QueuedConnection
        )
        self._dbusMetadataChanged.connect(
            self._onMetadataChanged, Qt.ConnectionType.QueuedConnection
        )
        self._dbusStatusChanged.connect(
            self._onStatusChanged, Qt.ConnectionType.QueuedConnection
        )

    # ------------------------------------------------------------------
    # Backend / lifecycle helpers (called from Python, not from QML)
    # ------------------------------------------------------------------
    @property
    def service(self) -> BluezService:
        """The underlying backend instance (used by tests and main.py)."""
        return self._service

    def start(self) -> bool:
        """Start the backend worker; failures keep the UI in disconnected state."""
        try:
            self._service.start()
        except Exception:  # noqa: BLE001 - degraded mode: app must still open
            logger.error("Bluetooth backend failed to start", exc_info=True)
            return False
        return True

    def shutdown(self) -> None:
        """Detach from the backend and stop its GLib worker (app exit)."""
        self._service.sig_device_connected.disconnect(self._cb_connected)
        self._service.sig_device_disconnected.disconnect(self._cb_disconnected)
        self._service.sig_metadata_changed.disconnect(self._cb_metadata)
        self._service.sig_status_changed.disconnect(self._cb_status)
        try:
            self._service.stop()
        except Exception:  # noqa: BLE001 - teardown must never raise
            logger.debug("Backend stop() raised", exc_info=True)

    def setWindow(self, window: object) -> None:
        """Attach the QML window used by ``closeApp()``/``minimizeApp()``.

        Accepts any object exposing ``close()`` / ``showMinimized()`` (the
        QML window in STEP 4, or a stub in tests).
        """
        self._window = window

    def _update_field(self, name: str, value: object, notify: "Signal") -> bool:
        """Write a backing field and emit its notify signal when it changed."""
        if getattr(self, name) == value:
            return False
        setattr(self, name, value)
        notify.emit()
        return True

    # ------------------------------------------------------------------
    # Read-only Qt properties (specs/05_backend_contracts.txt §2)
    # ------------------------------------------------------------------
    @Property(str, notify=trackTitleChanged)
    def trackTitle(self) -> str:
        """Current track title (UI-ready, never blank)."""
        return self._track_title

    @Property(str, notify=trackArtistChanged)
    def trackArtist(self) -> str:
        """Current track artist (UI-ready, never blank)."""
        return self._track_artist

    @Property(str, notify=trackAlbumChanged)
    def trackAlbum(self) -> str:
        """Current album name (extra property for [F-04], specs/01_mvp_scope.txt)."""
        return self._track_album

    @Property(str, notify=playbackStatusChanged)
    def playbackStatus(self) -> str:
        """One of ``"playing"``, ``"paused"``, ``"idle"``, ``"disconnected"``."""
        return self._playback_status

    @Property(str, notify=deviceNameChanged)
    def deviceName(self) -> str:
        """Alias of the connected phone, or the disconnected label."""
        return self._device_name

    @Property(bool, notify=isConnectedChanged)
    def isConnected(self) -> bool:
        """True while a Bluetooth media player is active."""
        return self._is_connected

    @Property(int, notify=positionMsChanged)
    def positionMs(self) -> int:
        """Playback position in milliseconds (updated with track/status)."""
        return self._position_ms

    @Property(int, notify=durationMsChanged)
    def durationMs(self) -> int:
        """Track duration in milliseconds (0 when unknown)."""
        return self._duration_ms

    # ------------------------------------------------------------------
    # QML control slots (specs/05_backend_contracts.txt §2, spec 01 [F-03])
    # ------------------------------------------------------------------
    @Slot()
    def play(self) -> None:
        """Remote Play()."""
        self._service.play()

    @Slot()
    def pause(self) -> None:
        """Remote Pause()."""
        self._service.pause()

    @Slot()
    def togglePlayPause(self) -> None:
        """Play when idle/paused, pause while playing; no-op when disconnected."""
        if not self._is_connected:
            return
        if self._playback_status == STATUS_PLAYING:
            self._service.pause()
        else:
            self._service.play()

    @Slot()
    def nextTrack(self) -> None:
        """Remote Next()."""
        self._service.next()

    @Slot()
    def previousTrack(self) -> None:
        """Remote Previous()."""
        self._service.previous()

    @Slot()
    def closeApp(self) -> None:
        """Close the window (falls back to quitting the Qt event loop)."""
        window = self._window
        if window is not None:
            window.close()
            return
        app = QCoreApplication.instance()
        if app is not None:
            app.quit()

    @Slot()
    def minimizeApp(self) -> None:
        """Minimize the window to the dock/taskbar."""
        if self._window is not None:
            self._window.showMinimized()
        else:
            logger.debug("minimizeApp(): no window attached yet")

    # ------------------------------------------------------------------
    # Backend event slots — always executed on the GUI thread
    # ------------------------------------------------------------------
    @Slot(str, str)
    def _onDeviceConnected(self, device_name: str, device_path: str) -> None:
        logger.info("Device connected: %s (%s)", device_name, device_path)
        self._update_field("_device_name", device_name, self.deviceNameChanged)
        self._update_field("_is_connected", True, self.isConnectedChanged)

    @Slot()
    def _onDeviceDisconnected(self) -> None:
        logger.info("Device disconnected")
        # Reset to spec defaults directly — deliberately *not* through the
        # metadata fallback so disconnected UI shows plain defaults.
        self._update_field("_is_connected", False, self.isConnectedChanged)
        self._update_field("_device_name", DISCONNECTED_LABEL, self.deviceNameChanged)
        self._update_field("_track_title", FALLBACK_TITLE, self.trackTitleChanged)
        self._update_field("_track_artist", FALLBACK_ARTIST, self.trackArtistChanged)
        self._update_field("_track_album", FALLBACK_ALBUM, self.trackAlbumChanged)
        self._update_field("_position_ms", 0, self.positionMsChanged)
        self._update_field("_duration_ms", 0, self.durationMsChanged)
        self._update_field("_playback_status", "disconnected", self.playbackStatusChanged)

    @Slot(object)
    def _onMetadataChanged(self, metadata: object) -> None:
        if not isinstance(metadata, TrackMetadata):
            return
        title = metadata.title
        if title == FALLBACK_TITLE:
            # Phone sent no metadata: never show blanks (spec 08 §1).
            title = FALLBACK_STREAMING_TITLE
        artist = metadata.artist
        if (
            artist == FALLBACK_ARTIST
            and self._is_connected
            and self._device_name not in ("", DISCONNECTED_LABEL)
        ):
            artist = self._device_name
        self._update_field("_track_title", title, self.trackTitleChanged)
        self._update_field("_track_artist", artist, self.trackArtistChanged)
        self._update_field("_track_album", metadata.album, self.trackAlbumChanged)
        self._update_field("_duration_ms", metadata.duration_ms, self.durationMsChanged)
        # int attribute read across threads is GIL-safe; position is refined
        # by F-08 (Phase 2) later on.
        self._update_field(
            "_position_ms", self._service.state.position_ms, self.positionMsChanged
        )

    @Slot(str)
    def _onStatusChanged(self, status: str) -> None:
        self._update_field(
            "_playback_status", _to_ui_status(status), self.playbackStatusChanged
        )
        if self._is_connected:
            self._update_field(
                "_position_ms", self._service.state.position_ms, self.positionMsChanged
            )


