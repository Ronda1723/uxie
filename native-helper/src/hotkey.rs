//! Load `~/miniflow/hotkey.json`. Now supports TWO triggers:
//!   - dictation: grammar-corrected typing path
//!   - command:   full agent / tool-calling path
//!
//! Schema:
//!   {
//!     "dictation": { "mode": "hold_to_talk", "modifier": "fn",     "key": null },
//!     "command":   { "mode": "hold_to_talk", "modifier": "option", "key": "space" }
//!   }
//!
//! Legacy flat schema ({ mode, modifier, key } at root) is auto-migrated to
//! dictation + a default command binding.

use std::fs;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Mode { HoldToTalk, PressToToggle }

impl Default for Mode { fn default() -> Self { Mode::HoldToTalk } }

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Modifier { Fn, Cmd, Option, Control, Shift, Globe }

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct HotkeyBinding {
    #[serde(default)]
    pub mode: Mode,
    #[serde(default = "default_modifier")]
    pub modifier: Option<Modifier>,
    #[serde(default)]
    pub key: Option<String>,
}

fn default_modifier() -> Option<Modifier> { Some(Modifier::Fn) }

impl Default for HotkeyBinding {
    fn default() -> Self {
        Self { mode: Mode::HoldToTalk, modifier: Some(Modifier::Fn), key: None }
    }
}

impl HotkeyBinding {
    pub fn is_modifier_only(&self) -> bool {
        self.key.is_none() && self.modifier.is_some()
    }
}

#[derive(Debug, Clone)]
pub struct HotkeyConfig {
    pub dictation: HotkeyBinding,
    pub command: Option<HotkeyBinding>,
}

impl Default for HotkeyConfig {
    fn default() -> Self {
        Self {
            dictation: HotkeyBinding::default(),
            // Command mode: press-to-toggle (tap once to start, tap again to stop).
            // Matches miniflow-engine/hotkey.py DEFAULT_COMMAND.
            command: Some(HotkeyBinding {
                mode: Mode::PressToToggle,
                modifier: Some(Modifier::Option),
                key: Some("space".into()),
            }),
        }
    }
}

#[derive(Debug, Deserialize)]
struct RawNested {
    dictation: Option<HotkeyBinding>,
    command: Option<HotkeyBinding>,
}

pub fn config_path() -> PathBuf {
    let home = dirs::home_dir().unwrap_or_else(|| PathBuf::from("."));
    home.join("miniflow").join("hotkey.json")
}

pub fn load() -> HotkeyConfig {
    let raw = match fs::read_to_string(config_path()) {
        Ok(s) => s,
        Err(_) => return HotkeyConfig::default(),
    };
    // Try the new nested format first
    if let Ok(parsed) = serde_json::from_str::<RawNested>(&raw) {
        if parsed.dictation.is_some() || parsed.command.is_some() {
            let def = HotkeyConfig::default();
            return HotkeyConfig {
                dictation: parsed.dictation.unwrap_or(def.dictation),
                command: parsed.command.or(def.command),
            };
        }
    }
    // Fall back to the legacy flat schema ({ mode, modifier, key })
    if let Ok(flat) = serde_json::from_str::<HotkeyBinding>(&raw) {
        let def = HotkeyConfig::default();
        return HotkeyConfig { dictation: flat, command: def.command };
    }
    eprintln!("[helper] hotkey.json parse failed; using defaults");
    HotkeyConfig::default()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_matches_python_defaults() {
        let c = HotkeyConfig::default();
        assert_eq!(c.dictation.modifier, Some(Modifier::Fn));
        assert_eq!(c.dictation.key, None);
        let cmd = c.command.expect("command default present");
        assert_eq!(cmd.modifier, Some(Modifier::Option));
        assert_eq!(cmd.key.as_deref(), Some("space"));
        assert_eq!(cmd.mode, Mode::PressToToggle);
    }

    #[test]
    fn parse_nested() {
        let js = r#"{
          "dictation": {"mode":"hold_to_talk","modifier":"fn","key":null},
          "command":   {"mode":"hold_to_talk","modifier":"cmd","key":"d"}
        }"#;
        let c = serde_json::from_str::<RawNested>(js).unwrap();
        assert_eq!(c.dictation.unwrap().modifier, Some(Modifier::Fn));
        assert_eq!(c.command.unwrap().key.as_deref(), Some("d"));
    }

    #[test]
    fn parse_flat_legacy() {
        let js = r#"{"mode":"hold_to_talk","modifier":"control","key":null}"#;
        let b: HotkeyBinding = serde_json::from_str(js).unwrap();
        assert!(b.is_modifier_only());
        assert_eq!(b.modifier, Some(Modifier::Control));
    }
}
