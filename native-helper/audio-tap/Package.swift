// swift-tools-version:5.9
// Standalone Swift package for the meeting audio-tap sidecar.
//
// Built into `native-helper/audio-tap/.build/release/uxie-audio-tap` by
// `swift build -c release`. Bundled into Uxie.app via electron-builder
// `mac.extraResources`, then spawned as a subprocess by `audio_meeting.py`
// when a meeting recording starts.

import PackageDescription

let package = Package(
    name: "uxie-audio-tap",
    platforms: [
        // ScreenCaptureKit available 12.3+, but SCContentFilter / unified
        // audio config we use is cleanest on 13+. Keeping the floor at 13
        // matches the rest of Uxie.
        .macOS(.v13),
    ],
    targets: [
        .executableTarget(
            name: "uxie-audio-tap",
            path: "Sources/UxieAudioTap"
        ),
    ]
)
