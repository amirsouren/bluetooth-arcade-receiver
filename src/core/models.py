"""Backend data contracts (specs/05_backend_contracts.txt §1).

Plain dataclasses shared between the services layer and the Qt controller.
No Qt and no D-Bus imports here — the models are transport-agnostic.
"""

from dataclasses import dataclass

# Spec 05 §1 defaults — the UI must never render blank fields
# (see also specs/08_risks_and_fallbacks.txt §1).
FALLBACK_TITLE = "No Track"
FALLBACK_ARTIST = "Unknown Artist"
FALLBACK_ALBUM = "Unknown Album"

# Default ``PlayerState.device_name`` / UI label while nothing is connected.
DISCONNECTED_LABEL = "Disconnected"


def _clean_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _clean_int(value: object) -> int:
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


@dataclass
class TrackMetadata:
    """Track metadata extracted from ``org.bluez.MediaPlayer1.Track``.

    Field names and defaults are defined by specs/05_backend_contracts.txt §1.
    """

    title: str = FALLBACK_TITLE
    artist: str = FALLBACK_ARTIST
    album: str = FALLBACK_ALBUM
    duration_ms: int = 0
    track_number: int = 0

    @classmethod
    def from_bluez_track(cls, track: object) -> "TrackMetadata":
        """Build from an *unpacked* BlueZ ``Track`` property dict.

        Missing or empty entries fall back to the spec defaults so partially
        populated AVRCP metadata never produces empty UI strings
        (specs 05 §1 and 08 §1).
        """
        if not isinstance(track, dict):
            track = {}
        return cls(
            title=_clean_str(track.get("Title")) or FALLBACK_TITLE,
            artist=_clean_str(track.get("Artist")) or FALLBACK_ARTIST,
            album=_clean_str(track.get("Album")) or FALLBACK_ALBUM,
            duration_ms=_clean_int(track.get("Duration")),
            track_number=_clean_int(track.get("TrackNumber")),
        )


@dataclass
class PlayerState:
    """Connection + playback state of the active Bluetooth source device.

    Defined by specs/05_backend_contracts.txt §1.
    """

    device_name: str = DISCONNECTED_LABEL
    device_address: str = ""
    status: str = "stopped"  # "playing", "paused", "stopped", "disconnected"
    position_ms: int = 0
    connected: bool = False
