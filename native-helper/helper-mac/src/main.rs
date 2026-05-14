//! MiniFlow native helper binary.
//!
//! Watches the keyboard for TWO configured hotkeys (dictation + command) and
//! emits JSON-per-line press/release events on stdout, each tagged with a
//! "mode" ("dictation" or "command") so the Electron main process knows which
//! agent path to trigger. Stdin accepts `{"action":"type","text":"..."}` to
//! perform synthetic typing via CGEvent.

mod hotkey;
mod injector;
mod keymap;

use std::io::{self, BufRead, Write};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;

use core_foundation::runloop::{kCFRunLoopCommonModes, CFRunLoop};
use core_graphics::event::{
    CGEvent, CGEventFlags, CGEventTap, CGEventTapLocation, CGEventTapOptions,
    CGEventTapPlacement, CGEventType,
};
use serde::{Deserialize, Serialize};

use hotkey::{HotkeyBinding, HotkeyConfig, Mode, Modifier};

const PIDFILE: &str = "miniflow/miniflow-fn-helper.pid";

#[derive(Serialize)]
#[serde(tag = "type")]
#[serde(rename_all = "snake_case")]
enum OutEvent {
    Press  { mode: String },
    Release { mode: String },
    Toggle { mode: String, on: bool },
    Error  { message: String },
}

#[derive(Deserialize)]
#[serde(tag = "action", rename_all = "snake_case")]
enum InCmd {
    Type { text: String },
    Reload,
    Quit,
}

fn write_pidfile() -> std::io::Result<()> {
    let home = dirs::home_dir()
        .ok_or_else(|| std::io::Error::new(std::io::ErrorKind::Other, "no home dir"))?;
    let path = home.join(PIDFILE);
    if let Some(p) = path.parent() { std::fs::create_dir_all(p)?; }
    std::fs::write(path, std::process::id().to_string())
}

fn modifier_bit(m: Modifier) -> CGEventFlags {
    match m {
        Modifier::Fn | Modifier::Globe => CGEventFlags::CGEventFlagSecondaryFn,
        Modifier::Cmd     => CGEventFlags::CGEventFlagCommand,
        Modifier::Option  => CGEventFlags::CGEventFlagAlternate,
        Modifier::Control => CGEventFlags::CGEventFlagControl,
        Modifier::Shift   => CGEventFlags::CGEventFlagShift,
    }
}

// ── Per-hotkey state ────────────────────────────────────────────────────────

#[derive(Default)]
struct BindingState {
    pressed: bool,
    toggled_on: bool,
}

struct State {
    cfg: HotkeyConfig,
    dictation: BindingState,
    command: BindingState,
}

impl State {
    fn new(cfg: HotkeyConfig) -> Self {
        Self { cfg, dictation: Default::default(), command: Default::default() }
    }
}

fn emit(ev: &OutEvent) {
    let line = serde_json::to_string(ev).unwrap_or_else(|_| "{}".into());
    println!("{line}");
    let _ = io::stdout().flush();
}

// ── Hotkey evaluation ───────────────────────────────────────────────────────
//
// Each incoming event is evaluated independently against both hotkey bindings.
// Returns an OutEvent (or None) indicating what to emit for this binding.

fn evaluate(
    binding: &HotkeyBinding,
    state: &mut BindingState,
    etype: CGEventType,
    event: &CGEvent,
    mode_label: &str,
) -> Option<OutEvent> {
    let flags = event.get_flags();

    // Modifier-only binding (e.g. bare Fn).
    //
    // We only respond to `FlagsChanged` events here — that's what the OS
    // emits when a modifier key transitions. Apple keyboards also stamp
    // the SecondaryFn flag on regular key events (arrow keys, F-keys,
    // Help, Page Up/Down, etc), so without this filter every right-arrow
    // press would trigger dictation press/release.
    if binding.is_modifier_only() {
        if !matches!(etype, CGEventType::FlagsChanged) {
            return None;
        }
        let m = binding.modifier?;
        let required = modifier_bit(m);
        let is_down_now = flags.contains(required);
        return match (state.pressed, is_down_now) {
            (false, true) => {
                state.pressed = true;
                Some(OutEvent::Press { mode: mode_label.into() })
            }
            (true, false) => {
                state.pressed = false;
                Some(OutEvent::Release { mode: mode_label.into() })
            }
            _ => None,
        };
    }

    // Modifier + key binding — must be a key event AND match the configured key
    let key = binding.key.as_deref()?;
    let target_code = keymap::key_to_code(key)?;
    let keycode = event.get_integer_value_field(
        core_graphics::event::EventField::KEYBOARD_EVENT_KEYCODE,
    ) as u16;
    if keycode != target_code { return None; }

    if let Some(m) = binding.modifier {
        if !flags.contains(modifier_bit(m)) { return None; }
    }

    match (binding.mode, etype) {
        (Mode::HoldToTalk, CGEventType::KeyDown) if !state.pressed => {
            state.pressed = true;
            Some(OutEvent::Press { mode: mode_label.into() })
        }
        (Mode::HoldToTalk, CGEventType::KeyUp) if state.pressed => {
            state.pressed = false;
            Some(OutEvent::Release { mode: mode_label.into() })
        }
        (Mode::PressToToggle, CGEventType::KeyDown) => {
            state.toggled_on = !state.toggled_on;
            Some(OutEvent::Toggle { mode: mode_label.into(), on: state.toggled_on })
        }
        _ => None,
    }
}

fn on_event(state: &Arc<Mutex<State>>, etype: CGEventType, event: &CGEvent) {
    let mut st = state.lock().unwrap();

    if let Some(ev) = evaluate(&st.cfg.dictation.clone(), &mut st.dictation, etype, event, "dictation") {
        emit(&ev);
    }
    if let Some(cmd_cfg) = st.cfg.command.clone() {
        if let Some(ev) = evaluate(&cmd_cfg, &mut st.command, etype, event, "command") {
            emit(&ev);
        }
    }
}

// ── Stdin ───────────────────────────────────────────────────────────────────

fn stdin_loop(state: Arc<Mutex<State>>, quit: Arc<AtomicBool>) {
    let stdin = io::stdin();
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break; };
        if line.trim().is_empty() { continue; }

        match serde_json::from_str::<InCmd>(&line) {
            Ok(InCmd::Type { text }) => injector::inject_text(&text),
            Ok(InCmd::Reload) => {
                let new_cfg = hotkey::load();
                let mut st = state.lock().unwrap();
                st.cfg = new_cfg;
                st.dictation = Default::default();
                st.command = Default::default();
            }
            Ok(InCmd::Quit) => {
                quit.store(true, Ordering::SeqCst);
                CFRunLoop::get_main().stop();
                break;
            }
            Err(e) => emit(&OutEvent::Error { message: format!("bad stdin cmd: {e}") }),
        }
    }
}

// ── Main ────────────────────────────────────────────────────────────────────

fn main() {
    if let Err(e) = write_pidfile() {
        eprintln!("[helper] warning: could not write pidfile: {e}");
    }

    let state = Arc::new(Mutex::new(State::new(hotkey::load())));
    let quit = Arc::new(AtomicBool::new(false));

    // SIGHUP → reload config
    let state_hup = state.clone();
    let mut signals = signal_hook::iterator::Signals::new(&[signal_hook::consts::SIGHUP])
        .expect("SIGHUP handler");
    thread::spawn(move || {
        for _ in signals.forever() {
            let new_cfg = hotkey::load();
            if let Ok(mut st) = state_hup.lock() {
                st.cfg = new_cfg;
                st.dictation = Default::default();
                st.command = Default::default();
            }
            eprintln!("[helper] hotkey config reloaded");
        }
    });

    let state_stdin = state.clone();
    let quit_stdin = quit.clone();
    thread::spawn(move || stdin_loop(state_stdin, quit_stdin));

    let state_tap = state.clone();
    let tap = CGEventTap::new(
        CGEventTapLocation::HID,
        CGEventTapPlacement::HeadInsertEventTap,
        CGEventTapOptions::ListenOnly,
        vec![CGEventType::FlagsChanged, CGEventType::KeyDown, CGEventType::KeyUp],
        move |_proxy, etype, event| {
            on_event(&state_tap, etype, event);
            None
        },
    );

    let tap = match tap {
        Ok(t) => t,
        Err(_) => {
            emit(&OutEvent::Error {
                message: "failed to create CGEventTap. Grant Input Monitoring / Accessibility permission.".into(),
            });
            std::process::exit(2);
        }
    };

    let loop_source = tap.mach_port.create_runloop_source(0).expect("runloop source");
    CFRunLoop::get_main().add_source(&loop_source, unsafe { kCFRunLoopCommonModes });
    tap.enable();
    emit(&OutEvent::Error { message: "ready".into() });
    CFRunLoop::run_current();
}
