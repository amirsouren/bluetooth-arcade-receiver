"""Global constants, theme palette and default values.

Sources:
- specs/00_project_overview.txt  (target window mode, tech stack)
- specs/04_ui_spec_arcade.txt    (geometry, colours, typography)
- specs/05_backend_contracts.txt (status vocabulary)
- specs/06_dbus_bluez_notes.txt  (D-Bus names, interfaces, timeouts)
"""

# --- Application ---------------------------------------------------------------
APP_NAME = "Bluetooth Arcade Receiver"
APP_ID = "bluetooth-arcade-receiver"  # .desktop launcher id (checklist STEP 5)
APP_VERSION = "0.1.0"

# --- Window geometry (spec 04 §1) ---------------------------------------------
WINDOW_WIDTH = 390
WINDOW_HEIGHT = 160

# --- Colour palette (spec 04 §2, §5) ------------------------------------------
COLOR_BASE_CANVAS = "#090a10"
COLOR_FRAME = "#1a1c2e"
COLOR_BORDER_GLOW = "#00e5ff"
COLOR_TEXT_PRIMARY = "#00ffaa"
COLOR_TEXT_SECONDARY = "#ff007f"
COLOR_TEXT_MUTED = "#6c7086"

COLOR_PILL_PLAYING_BG = "#003322"
COLOR_PILL_PLAYING_TEXT = "#00ffaa"
COLOR_PILL_PAUSED_BG = "#331122"
COLOR_PILL_PAUSED_TEXT = "#ff007f"
COLOR_PILL_DISCONNECTED_BG = "#222222"
COLOR_PILL_DISCONNECTED_TEXT = "#888888"

COLOR_BUTTON_BG = "#140d1a"
COLOR_BUTTON_BORDER = "#ff007f"
COLOR_BUTTON_HOVER_BG = "#ff007f"
COLOR_BUTTON_HOVER_TEXT = "#090a10"
COLOR_BUTTON_PRESSED_BG = "#cc0066"

# --- Typography (spec 04 §3) ---------------------------------------------------
FONT_PIXEL_FAMILY = "Press Start 2P"      # assets/fonts/PressStart2P-Regular.ttf
FONT_FALLBACK_MONO = "Ubuntu Mono"
FONT_SIZE_TITLE_PX = 12
FONT_SIZE_ARTIST_PX = 10
FONT_SIZE_SMALL_PX = 8
TITLE_MARQUEE_THRESHOLD_PX = 200          # auto-scroll titles wider than this

# --- D-Bus / BlueZ (spec 06 §1, §3) -------------------------------------------
BLUEZ_BUS_NAME = "org.bluez"
BLUEZ_ROOT_PATH = "/"
IFACE_OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"
IFACE_PROPERTIES = "org.freedesktop.DBus.Properties"
IFACE_MEDIA_PLAYER = "org.bluez.MediaPlayer1"
IFACE_DEVICE = "org.bluez.Device1"

DBUS_START_TIMEOUT_S = 10.0   # max wait for the GLib worker thread to come up
DBUS_CALL_TIMEOUT_S = 5.0     # budget for an AVRCP control round-trip

# --- Playback status vocabulary (spec 06 §3 status values, spec 05 §2) --------
STATUS_PLAYING = "playing"
STATUS_PAUSED = "paused"
STATUS_STOPPED = "stopped"
STATUS_FORWARD_SEEK = "forward-seek"
STATUS_REVERSE_SEEK = "reverse-seek"
STATUS_IDLE = "idle"                # UI-facing mapping of "stopped" (spec 05 §2)
STATUS_DISCONNECTED = "disconnected"
VALID_STATUSES = frozenset(
    {
        STATUS_PLAYING,
        STATUS_PAUSED,
        STATUS_STOPPED,
        STATUS_FORWARD_SEEK,
        STATUS_REVERSE_SEEK,
        STATUS_IDLE,
        STATUS_DISCONNECTED,
    }
)

# --- UI fallbacks (spec 08 §1, spec 05 §1) ------------------------------------
FALLBACK_STREAMING_TITLE = "STREAMING AUDIO"   # shown when the phone sends no metadata
FALLBACK_DEVICE_NAME = "Bluetooth Device"      # last-resort device label
