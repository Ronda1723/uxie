//! Map human-readable key strings (matching `hotkey.py`'s VALID_KEYS)
//! to macOS CGKeyCode values.

use core_graphics::event::CGKeyCode;

pub fn key_to_code(key: &str) -> Option<CGKeyCode> {
    // Table derived from /System/Library/Frameworks/Carbon.framework/.../Events.h
    // Only the keys listed in hotkey.py VALID_KEYS are wired up.
    match key {
        // Letters
        "a" =>  Some(0x00), "s" => Some(0x01), "d" => Some(0x02), "f" => Some(0x03),
        "h" =>  Some(0x04), "g" => Some(0x05), "z" => Some(0x06), "x" => Some(0x07),
        "c" =>  Some(0x08), "v" => Some(0x09), "b" => Some(0x0B), "q" => Some(0x0C),
        "w" =>  Some(0x0D), "e" => Some(0x0E), "r" => Some(0x0F), "y" => Some(0x10),
        "t" =>  Some(0x11), "o" => Some(0x1F), "u" => Some(0x20), "i" => Some(0x22),
        "p" =>  Some(0x23), "l" => Some(0x25), "j" => Some(0x26), "k" => Some(0x28),
        "n" =>  Some(0x2D), "m" => Some(0x2E),
        // Digits (top row)
        "0" => Some(0x1D), "1" => Some(0x12), "2" => Some(0x13), "3" => Some(0x14),
        "4" => Some(0x15), "5" => Some(0x17), "6" => Some(0x16), "7" => Some(0x1A),
        "8" => Some(0x1C), "9" => Some(0x19),
        // Function keys
        "f1" => Some(0x7A), "f2" => Some(0x78), "f3" => Some(0x63), "f4" => Some(0x76),
        "f5" => Some(0x60), "f6" => Some(0x61), "f7" => Some(0x62), "f8" => Some(0x64),
        "f9" => Some(0x65), "f10" => Some(0x6D), "f11" => Some(0x67), "f12" => Some(0x6F),
        // Control/navigation
        "space" => Some(0x31), "return" => Some(0x24), "tab" => Some(0x30),
        "escape" => Some(0x35), "delete" => Some(0x33),
        "up" => Some(0x7E), "down" => Some(0x7D), "left" => Some(0x7B), "right" => Some(0x7C),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn letters_and_digits_resolve() {
        assert_eq!(key_to_code("a"), Some(0x00));
        assert_eq!(key_to_code("0"), Some(0x1D));
    }
    #[test]
    fn unknown_is_none() {
        assert_eq!(key_to_code("zz"), None);
        assert_eq!(key_to_code(""), None);
    }
    #[test]
    fn fn_keys_and_nav() {
        assert_eq!(key_to_code("f1"), Some(0x7A));
        assert_eq!(key_to_code("space"), Some(0x31));
        assert_eq!(key_to_code("escape"), Some(0x35));
    }
}
