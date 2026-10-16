import QtQuick

// Retro cassette + VU-meter fallback artwork (specs/08_risks_and_fallbacks
// .txt §4): never block waiting for AVRCP cover art — show an animated
// pixel-art cassette instead.  Reels spin and VU bars dance while playing.
Item {
    id: root
    width: 90
    height: 90

    // Driven by the controller: true while playbackStatus === "playing".
    property bool spinning: false

    // Outer art frame (spec 04 §2: frame #1a1c2e + 1px glow-cyan border).
    Rectangle {
        id: frame
        anchors.fill: parent
        color: Theme.baseCanvas
        border.color: Theme.borderGlow
        border.width: 1
        radius: 2
        antialiasing: false
    }

    // Cassette shell.
    Rectangle {
        id: shell
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -8   // leave room for the VU row
        width: 72
        height: 44
        color: Theme.frame
        border.color: Theme.textMuted
        border.width: 1
        radius: 2
        antialiasing: false

        // Label strip with two neon stripes.
        Rectangle {
            id: labelStrip
            anchors.top: parent.top
            anchors.topMargin: 5
            anchors.horizontalCenter: parent.horizontalCenter
            width: 56
            height: 8
            color: Theme.baseCanvas
            Rectangle {
                anchors.left: parent.left
                anchors.leftMargin: 5
                anchors.verticalCenter: parent.verticalCenter
                width: 18
                height: 2
                color: Theme.textSecondary
                antialiasing: false
            }
            Rectangle {
                anchors.right: parent.right
                anchors.rightMargin: 5
                anchors.verticalCenter: parent.verticalCenter
                width: 18
                height: 2
                color: Theme.borderGlow
                antialiasing: false
            }
        }

        // Tape window with the two spinning reels.
        Rectangle {
            id: tapeWindow
            anchors.centerIn: parent
            width: 46
            height: 18
            color: Theme.baseCanvas
            border.color: Theme.borderGlow
            border.width: 1
            radius: 1

            Row {
                anchors.centerIn: parent
                spacing: 14
                Repeater {
                    model: 2
                    Rectangle {
                        id: reel
                        width: 12
                        height: 12
                        Rectangle {
                            anchors.fill: parent
                            radius: 6
                            color: Theme.textMuted
                            antialiasing: false
                        }
                        // Spoke so the rotation is visible.
                        Rectangle {
                            anchors.centerIn: parent
                            width: 12
                            height: 3
                            color: Theme.baseCanvas
                            antialiasing: false
                        }
                        RotationAnimation on rotation {
                            running: root.spinning
                            to: 360
                            duration: 1200
                            loops: Animation.Infinite
                        }
                    }
                }
            }
        }
    }

    // VU-meter row: flat line when idle, dancing bars while playing.
    Row {
        id: vuRow
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: frame.bottom
        anchors.bottomMargin: 6
        spacing: 4

        Repeater {
            model: 5
            Rectangle {
                required property int index
                width: 6
                height: root.spinning ? barHeight : 4
                color: index % 2 === 0 ? Theme.textPrimary : Theme.borderGlow
                antialiasing: false
                property real barHeight: 4

                Behavior on height { NumberAnimation { duration: 220 } }

                SequentialAnimation on barHeight {
                    running: root.spinning
                    loops: Animation.Infinite
                    PauseAnimation { duration: 120 + index * 70 }
                    NumberAnimation {
                        to: 4 + ((index * 7 + 5) % 12)
                        duration: 300
                        easing.type: Easing.InOutQuad
                    }
                    NumberAnimation {
                        to: 4 + ((index * 3 + 2) % 6)
                        duration: 300
                        easing.type: Easing.InOutQuad
                    }
                }
            }
        }
    }
}
