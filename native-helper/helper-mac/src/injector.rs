//! Synthetic typing via CGEvent.keyboardSetUnicodeString.
//!
//! Matches the Swift implementation's chunking (20 UTF-16 units per event) to
//! avoid CGEvent buffer overflow on long strings.

use core_graphics::event::{CGEvent, CGEventTapLocation};
use core_graphics::event_source::{CGEventSource, CGEventSourceStateID};

const CHUNK_UTF16_UNITS: usize = 20;

pub fn inject_text(text: &str) {
    if text.is_empty() {
        return;
    }
    let source = match CGEventSource::new(CGEventSourceStateID::HIDSystemState) {
        Ok(s) => s,
        Err(_) => {
            eprintln!("[helper] CGEventSource creation failed");
            return;
        }
    };

    // Encode once as UTF-16 and chunk that array so we never split a surrogate pair.
    let utf16: Vec<u16> = text.encode_utf16().collect();
    for chunk in utf16.chunks(CHUNK_UTF16_UNITS) {
        // Each chunk gets a keyDown + keyUp pair
        if let Ok(down) = CGEvent::new_keyboard_event(source.clone(), 0, true) {
            down.set_string_from_utf16_unchecked(chunk);
            down.post(CGEventTapLocation::HID);
        }
        if let Ok(up) = CGEvent::new_keyboard_event(source.clone(), 0, false) {
            up.set_string_from_utf16_unchecked(chunk);
            up.post(CGEventTapLocation::HID);
        }
        // 1 ms between chunks — fast enough for snappy streaming dictation,
        // slow enough for target apps to keep up with the CGEvent queue.
        std::thread::sleep(std::time::Duration::from_millis(1));
    }
}
