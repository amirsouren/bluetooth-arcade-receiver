import QtQuick

// Interactive retro button with hover/pressed states (spec 04 §5):
//   Default : border 1px #ff007f, background #140d1a, text #ff007f
//   Hover   : background #ff007f, text #090a10, 4px glow
//   Pressed : scale 0.95, background #cc0066
// Disabled buttons fade to 35% opacity (spec 07 §2 test 05: controls
// disable safely while no device is connected).
Rectangle {
    id: root

    property alias label: labelText.text
    property color accent: Theme.buttonBorder

    signal clicked()

    width: 96
    height: 30
    radius: 2
    color: mouse.containsPress ? Theme.buttonPressedBg
         : mouse.containsMouse  ? Theme.buttonHoverBg
         : Theme.buttonBg
    border.width: 1
    border.color: mouse.containsMouse ? Theme.buttonHoverBg : accent
    opacity: enabled ? 1.0 : 0.35
    scale: mouse.containsPress ? 0.95 : 1.0

    Behavior on color  { ColorAnimation { duration: 80 } }
    Behavior on scale   { NumberAnimation { duration: 70 } }
    Behavior on opacity { NumberAnimation { duration: 150 } }

    // ~4px hover glow ring — box-shadow approximation without Qt5Compat.
    // (Sits outside the button; the parent Row does not clip.)
    Rectangle {
        anchors.fill: parent
        anchors.margins: -3
        radius: 5
        color: "transparent"
        border.width: 2
        border.color: Theme.buttonHoverBg
        opacity: mouse.containsMouse && root.enabled ? 0.35 : 0.0
        Behavior on opacity { NumberAnimation { duration: 120 } }
    }

    Text {
        id: labelText
        anchors.centerIn: parent
        font.family: pixelFontFamily
        font.pixelSize: 8
        color: mouse.containsMouse ? Theme.buttonHoverText : accent
        Behavior on color { ColorAnimation { duration: 80 } }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
