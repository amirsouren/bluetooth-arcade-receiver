"""Entry point: initializes the Qt event loop and the GLib D-Bus worker.

specs/09_implementation_checklist.txt STEP 4 + spec 02 §1 (src/main.py).

Responsibilities:
- create ``QGuiApplication`` + ``QQmlApplicationEngine``;
- expose the context properties consumed by the QML layer:
    * ``controller``      -- AppController (spec 05 §2 contract)
    * ``Theme``           -- colour/typography palette from ``core.config``
    * ``pixelFontFamily`` -- family resolved from assets/fonts/PressStart2P
- load ``ui/qml/main.qml``, hand the window to the controller (close/min
  slots) and shut the backend down on quit.

Run from the project root:  ``venv/bin/python -m src.main``
"""

import logging
import os
import sys
from pathlib import Path

from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from .core.config import (
    APP_ID,
    APP_NAME,
    APP_VERSION,
    COLOR_BASE_CANVAS,
    COLOR_BUTTON_BG,
    COLOR_BUTTON_BORDER,
    COLOR_BUTTON_HOVER_BG,
    COLOR_BUTTON_HOVER_TEXT,
    COLOR_BUTTON_PRESSED_BG,
    COLOR_BORDER_GLOW,
    COLOR_FRAME,
    COLOR_PILL_DISCONNECTED_BG,
    COLOR_PILL_DISCONNECTED_TEXT,
    COLOR_PILL_PAUSED_BG,
    COLOR_PILL_PAUSED_TEXT,
    COLOR_PILL_PLAYING_BG,
    COLOR_PILL_PLAYING_TEXT,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    FONT_FALLBACK_MONO,
    FONT_SIZE_ARTIST_PX,
    FONT_SIZE_SMALL_PX,
    FONT_SIZE_TITLE_PX,
)
from .ui.controller import AppController

logger = logging.getLogger(__name__)

_QML_ENTRY = Path(__file__).resolve().parent / "ui" / "qml" / "main.qml"
_FONT_PATH = (
    Path(__file__).resolve().parent.parent
    / "assets" / "fonts" / "PressStart2P-Regular.ttf"
)


def _theme() -> dict:
    """QML view of the spec 04 palette (single source of truth: core.config)."""
    return {
        "baseCanvas": COLOR_BASE_CANVAS,
        "frame": COLOR_FRAME,
        "borderGlow": COLOR_BORDER_GLOW,
        "textPrimary": COLOR_TEXT_PRIMARY,
        "textSecondary": COLOR_TEXT_SECONDARY,
        "textMuted": COLOR_TEXT_MUTED,
        "pillPlayingBg": COLOR_PILL_PLAYING_BG,
        "pillPlayingText": COLOR_PILL_PLAYING_TEXT,
        "pillPausedBg": COLOR_PILL_PAUSED_BG,
        "pillPausedText": COLOR_PILL_PAUSED_TEXT,
        "pillDisconnectedBg": COLOR_PILL_DISCONNECTED_BG,
        "pillDisconnectedText": COLOR_PILL_DISCONNECTED_TEXT,
        "buttonBg": COLOR_BUTTON_BG,
        "buttonBorder": COLOR_BUTTON_BORDER,
        "buttonHoverBg": COLOR_BUTTON_HOVER_BG,
        "buttonHoverText": COLOR_BUTTON_HOVER_TEXT,
        "buttonPressedBg": COLOR_BUTTON_PRESSED_BG,
        "titleFontSize": FONT_SIZE_TITLE_PX,
        "artistFontSize": FONT_SIZE_ARTIST_PX,
        "smallFontSize": FONT_SIZE_SMALL_PX,
    }


def _load_pixel_font() -> str:
    """Register ``assets/fonts/PressStart2P-Regular.ttf``; return its family."""
    font_id = QFontDatabase.addApplicationFont(str(_FONT_PATH))
    if font_id < 0:
        logger.warning(
            "Could not load pixel font %s - falling back to %r",
            _FONT_PATH,
            FONT_FALLBACK_MONO,
        )
        return FONT_FALLBACK_MONO
    families = QFontDatabase.applicationFontFamilies(font_id)
    family = families[0] if families else FONT_FALLBACK_MONO
    logger.info("Pixel font loaded: %r", family)
    return family


def _avoid_broken_gtk3_theme() -> None:
    """Workaround for broken GTK3/GNOME combinations (fallbacks, spec 08).

    Qt >= 6.5 auto-loads its GTK3 platform theme on GNOME sessions.  On
    systems where the ``org.gnome.settings-daemon.plugins.xsettings`` schema
    no longer contains ``antialiasing`` (observed on Ubuntu 24.04 — even a
    plain ``Gtk.init_check()`` aborts there), loading libqgtk3 kills the
    whole process with a fatal GSettings error.  The arcade widget uses its
    own hard-coded palette and fonts and needs no desktop theme, so — only
    when that exact broken combination is detected, and only if the user has
    not chosen a platform theme themselves — Qt's theme autodetection is
    steered away from GTK3.  Environment changes are process-local.
    """
    if os.environ.get("QT_QPA_PLATFORMTHEME"):
        return  # explicit user choice — respect it
    try:
        from gi.repository import Gio

        source = Gio.SettingsSchemaSource.get_default()
        schema = (
            source.lookup("org.gnome.settings-daemon.plugins.xsettings", True)
            if source is not None
            else None
        )
        broken = schema is not None and not schema.has_key("antialiasing")
    except Exception:  # noqa: BLE001 - never block startup on the probe
        broken = False
    if broken:
        logger.warning(
            "GNOME xsettings schema lacks 'antialiasing' (GTK3 would abort); "
            "using Qt's default platform theme instead"
        )
        os.environ["XDG_CURRENT_DESKTOP"] = "KDE"  # avoids the GTK3 auto-detect


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    logger.info("Starting %s %s", APP_NAME, APP_VERSION)

    _avoid_broken_gtk3_theme()  # must run before Qt picks its platform theme
    app = QGuiApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName(APP_ID)  # matches the STEP 5 .desktop launcher

    # Backend first: the GLib worker starts immediately; events it emits
    # before the UI is up are absorbed once the Qt loop runs (queued, spec 08 §3).
    controller = AppController()
    if not controller.start():
        logger.warning("Running in degraded mode (no D-Bus backend)")

    engine = QQmlApplicationEngine()
    context = engine.rootContext()
    context.setContextProperty("controller", controller)
    context.setContextProperty("Theme", _theme())
    context.setContextProperty("pixelFontFamily", _load_pixel_font())

    engine.load(_QML_ENTRY)
    if not engine.rootObjects():
        logger.error("Failed to load QML UI: %s", _QML_ENTRY)
        controller.shutdown()
        return 1

    # Let closeApp()/minimizeApp() act on the real window (spec 05 §2).
    controller.setWindow(engine.rootObjects()[0])
    app.aboutToQuit.connect(controller.shutdown)

    exit_code = app.exec()
    logger.info("Bye.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
