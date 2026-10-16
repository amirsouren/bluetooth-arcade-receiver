import QtQuick

// Reusable neon-styled label (specs/04_ui_spec_arcade.txt §2/§3).
//
// Glow: a faint, slightly scaled ghost copy sits behind the real text.
// Pure QtQuick on purpose — Qt5Compat.GraphicalEffects is not shipped with
// this PySide6 wheel set, and Qt 6.12's Text.style enum refuses assignments.
// The pixel font family comes from main.py (`pixelFontFamily` context property).
Text {
    id: root

    // Neon colour; the ghost glow derives from it automatically.
    property color neonColor: "#00ffaa"
    // Set false for small technical labels (status pill, window buttons).
    property bool glow: true

    color: neonColor
    font.family: pixelFontFamily
    font.pixelSize: 12
    textFormat: Text.PlainText

    // Ghost halo behind the glyphs: scaled, faint, never interactive.
    Text {
        visible: root.glow
        anchors.fill: parent
        scale: 1.12
        z: -1
        text: root.text
        font: root.font
        color: root.neonColor
        opacity: 0.35
        elide: root.elide
        horizontalAlignment: root.horizontalAlignment
        verticalAlignment: root.verticalAlignment
        textFormat: root.textFormat
    }
}
