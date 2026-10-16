import QtQuick
import QtQuick.Controls

// Root arcade window (specs/04_ui_spec_arcade.txt §1):
// frameless, always-on-top, non-resizable 390x160, draggable 24px top bar.
ApplicationWindow {
    id: root

    width: 390
    height: 160
    minimumWidth: 390
    maximumWidth: 390
    minimumHeight: 160
    maximumHeight: 160
    visible: true
    title: "Bluetooth Arcade Receiver"
    color: Theme.baseCanvas
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint

    // Frameless windows lose the system border: draw our own neon frame.
    Rectangle {
        anchors.fill: parent
        color: "transparent"
        border.color: Theme.borderGlow
        border.width: 1
        z: 1000
    }

    // ---------------- TOP BAR (24px) ----------------
    Rectangle {
        id: topBar
        width: parent.width
        height: 24
        color: Theme.frame

        // Full-width drag handle: the status bar moves the window (§1).
        // Placed first so the indicator/buttons above it receive clicks.
        MouseArea {
            id: dragZone
            anchors.fill: parent
            onPressed: (mouse) => {
                if (mouse.button === Qt.LeftButton)
                    root.startSystemMove()   // native, flicker-free on Qt 6
            }
        }

        // Connection indicator dot.
        Rectangle {
            id: btDot
            x: 8
            anchors.verticalCenter: parent.verticalCenter
            width: 8
            height: 8
            radius: 4
            color: controller.isConnected ? Theme.textPrimary : Theme.textMuted
        }

        // "BT: CONNECTED [DEVICE]" / "BT: WAITING FOR BLUETOOTH..."
        NeonText {
            id: btLabel
            x: 22
            anchors.verticalCenter: parent.verticalCenter
            width: 260
            elide: Text.ElideRight
            glow: false
            font.pixelSize: Theme.smallFontSize
            neonColor: controller.isConnected ? Theme.textPrimary : Theme.textMuted
            text: controller.isConnected
                  ? "BT: CONNECTED [" + controller.deviceName.toUpperCase() + "]"
                  : "BT: WAITING FOR BLUETOOTH..."
        }

        // Window buttons: [_] minimize, [✕] close (spec 04 §1/§4).
        Rectangle {
            id: minButton
            anchors.right: closeButton.left
            anchors.rightMargin: 4
            anchors.verticalCenter: parent.verticalCenter
            width: 20
            height: 16
            radius: 2
            color: minMouse.containsMouse ? Theme.buttonHoverBg : "transparent"
            Text {
                anchors.centerIn: parent
                text: "\u2013"
                font.family: pixelFontFamily
                font.pixelSize: 10
                color: minMouse.containsMouse ? Theme.buttonHoverText : Theme.textMuted
            }
            MouseArea {
                id: minMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: controller.minimizeApp()
            }
        }

        Rectangle {
            id: closeButton
            anchors.right: parent.right
            anchors.rightMargin: 6
            anchors.verticalCenter: parent.verticalCenter
            width: 20
            height: 16
            radius: 2
            color: closeMouse.containsMouse ? Theme.buttonHoverBg : "transparent"
            Text {
                anchors.centerIn: parent
                text: "\u2715"
                font.family: pixelFontFamily
                font.pixelSize: 9
                color: closeMouse.containsMouse ? Theme.buttonHoverText : Theme.textMuted
            }
            MouseArea {
                id: closeMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: controller.closeApp()
            }
        }

        // Hairline separator under the bar.
        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: 1
            color: Theme.borderGlow
            opacity: 0.4
        }
    }

    // ---------------- BODY: mini-player below the top bar ----------------
    ArcadePlayer {
        anchors.top: topBar.bottom
        width: parent.width
        height: parent.height - topBar.height
    }
}
