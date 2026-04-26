//! Uxie Windows native helper.
//!
//! Mirror of native-helper/helper-mac/ for Windows. Exposes the EXACT same
//! stdin / stdout JSON protocol so the Electron main process spawning logic
//! is identical across platforms:
//!
//!   stdout (one JSON object per line):
//!     {"type":"press",   "mode":"dictation"}
//!     {"type":"release", "mode":"dictation"}
//!     {"type":"error",   "message":"..."}        # incl. "ready" on startup
//!
//!   stdin (one JSON object per line):
//!     {"action":"type", "text":"hello"}
//!     {"action":"quit"}
//!
//! Hotkey: Right-Alt (VK_RMENU). Chosen because:
//!   - macOS uses `fn`, which Windows can't intercept (firmware-level on most
//!     laptops)
//!   - Right-Alt is rare enough that nobody has muscle memory for it
//!   - Easy to hold-to-talk with one hand
//!
//! Implementation: WH_KEYBOARD_LL (low-level keyboard hook). Required because
//! we need to detect the key globally, even when our window isn't focused —
//! `RegisterHotKey` requires a foreground window, doesn't work for our case.
//!
//! Typing: SendInput with KEYEVENTF_UNICODE, one keydown + keyup per UTF-16
//! code unit. Handles all Unicode (emoji, CJK, accents) correctly.

#![cfg(windows)]

use std::io::{self, BufRead, Write};
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;

use serde::{Deserialize, Serialize};
use windows::Win32::Foundation::{LPARAM, LRESULT, WPARAM};
use windows::Win32::UI::Input::KeyboardAndMouse::{
    SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT, KEYBD_EVENT_FLAGS,
    KEYEVENTF_KEYUP, KEYEVENTF_UNICODE, VIRTUAL_KEY, VK_RMENU,
};
use windows::Win32::UI::WindowsAndMessaging::{
    CallNextHookEx, DispatchMessageW, GetMessageW, SetWindowsHookExW, TranslateMessage,
    UnhookWindowsHookEx, HC_ACTION, KBDLLHOOKSTRUCT, MSG, WH_KEYBOARD_LL, WM_KEYDOWN, WM_KEYUP,
    WM_SYSKEYDOWN, WM_SYSKEYUP,
};

// ── stdout protocol ──────────────────────────────────────────────────────────

#[derive(Serialize)]
#[serde(tag = "type", rename_all = "lowercase")]
enum OutEvent {
    Press { mode: String },
    Release { mode: String },
    Error { message: String },
}

#[derive(Deserialize)]
#[serde(tag = "action", rename_all = "lowercase")]
enum InCmd {
    Type { text: String },
    Quit,
}

fn emit(ev: &OutEvent) {
    if let Ok(mut s) = serde_json::to_string(ev) {
        s.push('\n');
        let _ = io::stdout().write_all(s.as_bytes());
        let _ = io::stdout().flush();
    }
}

// ── Hotkey state ─────────────────────────────────────────────────────────────
// The low-level keyboard hook callback runs on the message-pump thread and
// can't carry user data, so the press latch is global. This is the standard
// pattern for WH_KEYBOARD_LL on Windows.

static PRESSED: AtomicBool = AtomicBool::new(false);

unsafe extern "system" fn keyboard_hook_proc(
    code: i32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    if code == HC_ACTION as i32 {
        let kb = &*(lparam.0 as *const KBDLLHOOKSTRUCT);
        let vk = VIRTUAL_KEY(kb.vkCode as u16);
        let msg = wparam.0 as u32;

        if vk == VK_RMENU {
            // Alt comes through as WM_SYSKEY*, plain keys as WM_KEY*. Cover both.
            match msg {
                WM_KEYDOWN | WM_SYSKEYDOWN => {
                    if !PRESSED.swap(true, Ordering::SeqCst) {
                        emit(&OutEvent::Press { mode: "dictation".into() });
                    }
                }
                WM_KEYUP | WM_SYSKEYUP => {
                    if PRESSED.swap(false, Ordering::SeqCst) {
                        emit(&OutEvent::Release { mode: "dictation".into() });
                    }
                }
                _ => {}
            }
        }
    }
    CallNextHookEx(None, code, wparam, lparam)
}

// ── Synthetic typing ─────────────────────────────────────────────────────────

fn type_unicode(text: &str) {
    // Two INPUTs per UTF-16 code unit (down + up). For surrogate pairs this
    // sends both halves separately, which is what Windows expects for
    // characters outside the BMP (e.g. emoji).
    let code_units: Vec<u16> = text.encode_utf16().collect();
    if code_units.is_empty() {
        return;
    }

    let mut inputs: Vec<INPUT> = Vec::with_capacity(code_units.len() * 2);
    for unit in code_units {
        for is_keyup in [false, true] {
            let mut flags = KEYEVENTF_UNICODE;
            if is_keyup {
                flags = KEYBD_EVENT_FLAGS(flags.0 | KEYEVENTF_KEYUP.0);
            }
            inputs.push(INPUT {
                r#type: INPUT_KEYBOARD,
                Anonymous: INPUT_0 {
                    ki: KEYBDINPUT {
                        wVk: VIRTUAL_KEY(0),
                        wScan: unit,
                        dwFlags: flags,
                        time: 0,
                        dwExtraInfo: 0,
                    },
                },
            });
        }
    }

    unsafe {
        SendInput(&inputs, std::mem::size_of::<INPUT>() as i32);
    }
}

// ── stdin loop ───────────────────────────────────────────────────────────────

fn stdin_loop() {
    let stdin = io::stdin();
    for line in stdin.lock().lines() {
        let Ok(line) = line else { return };
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        match serde_json::from_str::<InCmd>(trimmed) {
            Ok(InCmd::Type { text }) => type_unicode(&text),
            Ok(InCmd::Quit) => std::process::exit(0),
            Err(e) => emit(&OutEvent::Error {
                message: format!("bad stdin command: {e}"),
            }),
        }
    }
}

// ── Entry ────────────────────────────────────────────────────────────────────

fn main() {
    thread::spawn(stdin_loop);

    unsafe {
        let hook = match SetWindowsHookExW(WH_KEYBOARD_LL, Some(keyboard_hook_proc), None, 0) {
            Ok(h) => h,
            Err(e) => {
                emit(&OutEvent::Error {
                    message: format!(
                        "SetWindowsHookExW failed: {e}. Run Uxie as the same user that owns the active session."
                    ),
                });
                std::process::exit(2);
            }
        };

        emit(&OutEvent::Error {
            message: "ready".into(),
        });

        // Standard Win32 message pump — required for low-level hooks to fire.
        let mut msg = MSG::default();
        while GetMessageW(&mut msg, None, 0, 0).as_bool() {
            let _ = TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }

        let _ = UnhookWindowsHookEx(hook);
    }
}
