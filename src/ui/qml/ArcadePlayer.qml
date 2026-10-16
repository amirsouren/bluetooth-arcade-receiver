import QtQuick

// Main mini-player layout (specs/04_ui_spec_arcade.txt §4):
//   left : 90x90 retro animated cassette   right: title marquee, artist, pill
//   base : neon PREV / PLAY-PAUSE / NEXT controls (spec 01 [F-03])
// The 24px top bar lives in main.qml; this fills the remaining 136px.
Item {
    id: root

    // Center-left: retro animated cassette (fallback art, spec 08 §4)
    AnimatedCassette {
        id: art
        x: 8
        y: 6
        spinning: controller.playbackStatus === "playing"
    }

    // Status pill helpers (spec 04 §2: pill palette + label)
    readonly property string statusLabel:
        controller.playbackStatus === "playing" ? "PLAYING" :
        controller.playbackStatus === "paused"  ? "PAUSED"  :
        controller.playbackStatus === "idle"    ? "IDLE"    :
                                                  "DISCONNECTED"
    readonly property color statusBg:
        controller.playbackStatus === "playing" ? Theme.pillPlayingBg :
        controller.playbackStatus === "paused"  ? Theme.pillPausedBg  :
                                                  Theme.pillDisconnectedBg
    readonly property color statusFg:
        controller.playbackStatus === "playing" ? Theme.pillPlayingText :
        controller.playbackStatus === "paused"  ? Theme.pillPausedText  :
                                                  Theme.pillDisconnectedText

    // Center-right: track info column
    Column {
        id: info
        x: 106
        y: 6
        width: root.width - 106 - 10
        spacing: 4

        // Track title, uppercase, auto-scroll when overflowing (spec 04 §3)
        Item {
            id: titleClip
            width: info.width
            height: 18
            clip: true

            NeonText {
                id: titleText
                neonColor: Theme.textPrimary
                font.pixelSize: Theme.titleFontSize   // 12px
                font.bold: true
                text: controller.trackTitle.toUpperCase()

                property bool marquee: contentWidth > titleClip.width
                property real marqueeX: 0
                x: marquee ? marqueeX : 0
                onTextChanged: marqueeX = 0

                SequentialAnimation {
                    id: scrollAnim
                    running: titleText.marquee
                    loops: Animation.Infinite
                    PauseAnimation { duration: 900 }
                    NumberAnimation {
                        target: titleText
                        property: "marqueeX"
                        from: 0
                        to: -(titleText.contentWidth - titleClip.width + 16)
                        duration: Math.max(1400, (titleText.contentWidth - titleClip.width) * 35)
                        easing.type: Easing.Linear
                    }
                    PauseAnimation { duration: 900 }
                    NumberAnimation {
                        target: titleText
                        property: "marqueeX"
                        from: -(titleText.contentWidth - titleClip.width + 16)
                        to: 0
                        duration: Math.max(1400, (titleText.contentWidth - titleClip.width) * 35)
                        easing.type: Easing.Linear
                    }
                }
            }
        }

        // Artist — spec 04 §3: 10px regular monospace, neon pink
        NeonText {
            id: artistText
            width: info.width
            elide: Text.ElideRight
            neonColor: Theme.textSecondary
            font.family: "Ubuntu Mono"
            font.pixelSize: Theme.artistFontSize   // 10px
            font.bold: false
            text: controller.trackArtist
        }

        // STATUS: [ PLAYING ] state pill (spec 04 §2/§4)
        Row {
            id: statusRow
            spacing: 6

            NeonText {
                text: "STATUS:"
                glow: false
                neonColor: Theme.textMuted
                font.pixelSize: Theme.smallFontSize   // 8px
                height: 16
                verticalAlignment: Text.AlignVCenter
            }

            Rectangle {
                id: pill
                radius: 2
                width: pillText.width + 14
                height: 16
                color: root.statusBg
                Behavior on color { ColorAnimation { duration: 150 } }

                NeonText {
                    id: pillText
                    anchors.centerIn: parent
                    glow: false
                    neonColor: root.statusFg
                    font.pixelSize: Theme.smallFontSize   // 8px
                    text: root.statusLabel
                }
            }
        }
    }

    // Bottom: neon controls (spec 04 §4/§5)
    Row {
        id: controls
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 8
        spacing: 10

        ArcadeButton {
            width: 96
            label: "|<< PREV"
            enabled: controller.isConnected
            onClicked: controller.previousTrack()
        }

        // Play/Pause flips its glyph with the state (spec 07 §1)
        ArcadeButton {
            width: 116
            label: controller.playbackStatus === "playing" ? "|| PAUSE" : ">/|| PLAY"
            enabled: controller.isConnected
            onClicked: controller.togglePlayPause()
        }

        ArcadeButton {
            width: 96
            label: "NEXT >>|"
            enabled: controller.isConnected
            onClicked: controller.nextTrack()
        }
    }
}
