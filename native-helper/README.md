# miniflow-fn-helper

Tiny macOS-only Rust binary that:

1. Listens for the configured hotkey (`~/miniflow/hotkey.json`) using `CGEventTap`.
2. Emits JSON lines on stdout: `{"press"}`, `{"release"}`, `{"toggle","on":…}`.
3. Reads JSON commands from stdin — `{"action":"type","text":"…"}` injects synthetic
   keystrokes into the frontmost app, `{"action":"reload"}` re-reads the config,
   `{"action":"quit"}` exits cleanly.
4. Reloads config on `SIGHUP` (pid written to `~/miniflow/miniflow-fn-helper.pid`).

Runs as a child process of the Electron main process. No network, no disk writes
other than the pidfile.

## Build

```bash
cd native-helper
cargo build --release
# Binary at target/release/miniflow-fn-helper
```

## macOS permissions

- **Input Monitoring** — required to see key events (System Settings → Privacy & Security → Input Monitoring).
- **Accessibility** — required to POST synthetic keystrokes (System Settings → Privacy & Security → Accessibility).

Both dialogs are triggered the first time the binary runs.

## Why Rust (and not Swift/Objective-C)?

- Single small static binary (~600KB release build after LTO+strip).
- No Xcode dependency in the build pipeline.
- Matches the rest of the project's "no Swift" direction.

The heavy lifting — `CGEventTap`, `CGEventSource`, `CGEvent.post` — is all
CoreGraphics C API, reached through the `core-graphics` crate.
