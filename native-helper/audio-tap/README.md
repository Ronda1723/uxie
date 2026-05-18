# uxie-audio-tap (parked)

Swift sidecar that **was** going to capture mic + system audio via
`AVAudioEngine` + `ScreenCaptureKit`, mix to 16 kHz mono PCM, and stream
raw samples to stdout for the Python engine to forward to Deepgram.

**Status: not shipping.** When run as a standalone CLI binary,
`AVAudioEngine.installTap` only ever delivered one buffer per session,
which we couldn't reproducibly fix without iterating inside the
`Uxie.app` bundle. As of v1.0.31 the meeting flow falls back to the
existing renderer-mic path (see `miniflow-engine/audio_meeting.py`):
user voice gets transcribed, but other participants on Zoom / Meet /
Teams are not captured.

When picking this back up:
- Try moving the binary into a proper signed sub-bundle inside
  `Uxie.app/Contents/Resources/uxie-audio-tap.app/` with its own
  `Info.plist` (`NSScreenCaptureDescription`, `NSMicrophoneUsageDescription`).
- If `AVAudioEngine` still misbehaves, swap to `AVCaptureSession +
  AVCaptureAudioDataOutput` for the mic path — it's the proven idiom
  for long-form streaming capture on macOS.
- Drop the `Task.detached { ... }; dispatchMain()` pattern in favor of
  a Cocoa-style `NSApp.run()` if Core Audio APIs are still flaky.

To build manually (will compile, will run, will mostly not capture):

    cd native-helper/audio-tap
    swift build -c release
