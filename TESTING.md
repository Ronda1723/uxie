# MiniFlow — UI & Functional Test Plan

This is the authoritative reference for what we test, where, and how. Each row names the concern, the automated coverage (if any), and the manual acceptance steps.

**Status legend** — ✅ automated · 🟡 automated-in-part · ⚪ manual only.

---

## 1. LLM provider layer (Python)

Automated with pytest in [`miniflow-engine/tests/test_llm.py`](miniflow-engine/tests/test_llm.py) and [`test_config.py`](miniflow-engine/tests/test_config.py).

| # | Scenario | Status | Where |
|---|---|---|---|
| 1.1 | `list_providers` returns catalog with OpenAI / Anthropic / Gemini / Ollama entries | ✅ | `test_llm.py::test_list_providers_shape` |
| 1.2 | `build_model_string` prefixes Anthropic / Gemini correctly | ✅ | `test_build_model_string_anthropic_prefixed` |
| 1.3 | `build_model_string` is idempotent for already-prefixed models | ✅ | `test_build_model_string_idempotent` |
| 1.4 | Unknown provider raises `ValueError` | ✅ | `test_build_model_string_unknown_provider_raises` |
| 1.5 | Ollama tool-capability gate accepts llama3.1 / qwen2.5 / mistral-nemo, rejects phi-3 / codellama | ✅ | `test_ollama_tool_capability_gate` |
| 1.6 | `chat()` serializes messages + tools + api_key, returns normalized `LLMResponse` | ✅ | `test_chat_normalizes_response` |
| 1.7 | `chat()` omits `tools` when provider doesn't support them | ✅ | `test_chat_omits_tools_when_provider_unsupported` |
| 1.8 | `set_active_llm_provider("foo")` for unknown provider raises | ✅ | `test_config.py::test_set_active_llm_unknown_provider_raises` |
| 1.9 | Changing provider persists across reads | ✅ | `test_set_active_llm_provider_persists` |
| 1.10 | Setting model + base_url for Ollama persists | ✅ | `test_set_llm_provider_model_and_base_url` |
| 1.11 | `get_active_llm()` returns key from Keychain | ✅ | `test_get_active_llm_returns_key_from_keychain` |
| 1.12 | `get_active_llm()` returns `api_key=None` when not set | ✅ | `test_get_active_llm_returns_none_key_when_unset` |
| 1.13 | Clearing an API key removes it from Keychain + fallback file | ✅ | `test_clear_llm_api_key` |
| 1.14 | `llm_provider_status()` marks Ollama as configured (no key needed) | ✅ | `test_llm_provider_status_marks_active_and_configured` |
| 1.15 | Legacy `miniflow_keys.json` with `openai` key is still readable as a fallback | ✅ | `test_legacy_openai_key_migrates_without_keyring` |
| 1.16 | Upgrade: existing `llm_providers.json` with only old providers auto-merges new defaults | ✅ | `test_llm_config_merges_new_defaults_on_upgrade` |
| 1.17 | Saving `openai` via legacy `save_api_key` mirrors it into Keychain | ✅ | `test_legacy_save_and_get_openai_key` |

### Manual LLM smoke tests (one per provider)
1. In Settings → LLM Providers, pick provider P.
2. Paste a real key (use a low-quota test account).
3. Pick the smallest available tool-capable model.
4. Say "Open Finder" → verify `open_application` fires.
5. Say "What's the weather in Paris?" (a DICTATION case) → verify the transcript is typed, not GPT's answer.
6. Disconnect network → trigger a command → expect an `llm-error` action in the popover.

---

## 2. Agent loop (Python)

Automated in [`miniflow-engine/tests/test_agent.py`](miniflow-engine/tests/test_agent.py).

| # | Scenario | Status |
|---|---|---|
| 2.1 | No configured provider → dictation fallback, no LLM call | ✅ |
| 2.2 | Provider returns no tool_calls → dictation, user's transcript is forwarded (NOT the model's text) | ✅ |
| 2.3 | Single local tool call (`open_application`) ends up invoking `open -a Finder` | ✅ |
| 2.4 | Connector tool call (`slack_send_message`) routes via `connector_registry.execute_connector_tool` with the token provider | ✅ |
| 2.5 | LLM raising `RuntimeError` produces an `llm-error` action and halts the loop | ✅ |
| 2.6 | Infinite tool-call loop is capped at `max_turns=8` | ✅ |

### Manual agent acceptance

- "Draft an email to X about Y" with Gmail connected → verify draft appears in Gmail Drafts.
- "Create a GitHub issue titled 'smoke test'" with GitHub connected → verify issue appears in your test repo.
- Hold Fn, say nothing, release → expect no error, no agent run, status returns to idle.

---

## 3. Hotkey — Python config module

Automated in [`miniflow-engine/tests/test_hotkey.py`](miniflow-engine/tests/test_hotkey.py).

| # | Scenario | Status |
|---|---|---|
| 3.1 | Default hotkey is `{hold_to_talk, fn, null}` | ✅ |
| 3.2 | `set_hotkey({mode, modifier, key})` persists round-trip | ✅ |
| 3.3 | Invalid mode/modifier/key rejected with `ValueError` | ✅ |
| 3.4 | `press_to_toggle` with a bare modifier rejected (ambiguous) | ✅ |
| 3.5 | Modifier-and-key both null rejected | ✅ |
| 3.6 | `reset_hotkey()` restores default | ✅ |
| 3.7 | Corrupt JSON file falls back to defaults without crashing | ✅ |
| 3.8 | Missing fields backfilled from defaults | ✅ |
| 3.9 | `SIGHUP` sent to helper when pidfile exists | ✅ |
| 3.10 | No signal sent when pidfile missing | ✅ |

---

## 4. Rust native helper

Automated in [`native-helper/src/*.rs`](native-helper/src) — run `cargo test`.

| # | Scenario | Status |
|---|---|---|
| 4.1 | `keymap::key_to_code("a")` returns 0x00 | ✅ |
| 4.2 | Unknown key resolves to `None` | ✅ |
| 4.3 | Function keys + navigation keys resolve correctly | ✅ |
| 4.4 | `HotkeyConfig` parses press_to_toggle + cmd + space | ✅ |
| 4.5 | `HotkeyConfig` parses bare-Fn modifier-only | ✅ |
| 4.6 | `HotkeyConfig::default()` matches Python defaults | ✅ |

### Manual helper acceptance (requires Input Monitoring + Accessibility permissions)
1. `cd native-helper && cargo run --release` in a terminal.
2. Hold Fn → stdout prints `{"press":true}`. Release → `{"release":true}`.
3. Type `{"action":"type","text":"hello world"}` into stdin → text appears in the frontmost app.
4. Edit `~/miniflow/hotkey.json` to `{mode:"hold_to_talk", modifier:"option", key:"space"}` → `kill -HUP <helper-pid>` → now only ⌥+Space triggers, not Fn.
5. Press ⌘+Q inside the popover → helper exits cleanly with code 0.

---

## 5. Electron main process

Automated in [`miniflow-electron/tests/unit/`](miniflow-electron/tests/unit).

| # | Scenario | Status | Where |
|---|---|---|---|
| 5.1 | `api.invoke` POSTs JSON and unwraps the response | ✅ | `api.test.ts` |
| 5.2 | `api.invoke` throws on HTTP error status | ✅ | `api.test.ts` |
| 5.3 | `api.invoke` throws when backend returns `{error}` | ✅ | `api.test.ts` |
| 5.4 | `waitUntilHealthy` resolves when `/health` is ok | ✅ | `api.test.ts` |
| 5.5 | `waitUntilHealthy` times out gracefully | ✅ | `api.test.ts` |
| 5.6 | `HelperManager` parses `{"press":true}` → emits `press` | ✅ | `helper-dispatch.test.ts` |
| 5.7 | `HelperManager` parses `{"release":true}` → emits `release` | ✅ | `helper-dispatch.test.ts` |
| 5.8 | `HelperManager` parses `{"toggle":true,"on":true/false}` correctly | ✅ | `helper-dispatch.test.ts` |
| 5.9 | Partial stdout chunks are buffered across writes | ✅ | `helper-dispatch.test.ts` |
| 5.10 | `helper.type("hello")` writes JSON command to stdin | ✅ | `helper-dispatch.test.ts` |
| 5.11 | Non-JSON line from helper emits error, does not crash | ✅ | `helper-dispatch.test.ts` |

### Manual main-process acceptance
- `MINIFLOW_ENGINE_EXTERNAL=1 npm start` with no backend running → expect "Python backend is not running" error in console, app still boots into the popover.
- Backend up → popover should show live "Status: idle" after a second.
- Kill the Python process while the app is running → WebSocket reconnect loop fires every 2s (check main-process stdout).

---

## 6. Electron renderer (React)

Automated with @testing-library/react in [`tests/unit/`](miniflow-electron/tests/unit).

### 6.1 ProviderPicker

| # | Scenario | Status |
|---|---|---|
| 6.1.1 | All 3+ providers listed, active one marked with pill | ✅ |
| 6.1.2 | Clicking a provider calls `setActiveLLM` | ✅ |
| 6.1.3 | Base-URL field appears only when Ollama is active | ✅ |
| 6.1.4 | Save button calls `setLLMModel` + `setLLMKey` | ✅ |
| 6.1.5 | Clear button calls `clearLLMKey` (OpenAI path) | ✅ |

#### Manual provider-picker acceptance
- Switch from OpenAI → Anthropic. Verify the key input is empty, and that the API-key prompt says "paste your API key".
- Switch back to OpenAI (already configured). Placeholder reads "•••••••• (already saved)".
- Pick Ollama. Enter `http://localhost:11434`. Click save. Confirm `~/miniflow/llm_providers.json` reflects the change.

### 6.2 HotkeyRecorder

| # | Scenario | Status |
|---|---|---|
| 6.2.1 | Renders default Fn hotkey on load | ✅ |
| 6.2.2 | Reset button calls `resetHotkey` | ✅ |
| 6.2.3 | Clicking recorder enters listening mode | ✅ |
| 6.2.4 | Pressing ⌘+Space saves `{cmd, space}` | ✅ |
| 6.2.5 | Pressing a bare letter (no modifier) shows warning, does not save | ✅ |
| 6.2.6 | Escape cancels without saving | ✅ |

#### Manual hotkey-recorder acceptance
1. Default Fn visible. Hold Fn → listening indicator lights up, release → capture stops.
2. Click recorder, press ⌥+D. Verify `~/miniflow/hotkey.json` updated. Verify helper reloaded (`miniflow.log` shows "hotkey config reloaded").
3. Hold ⌥+D in any app → command fires.
4. Switch to **Press to toggle** with ⌥+D configured → tapping ⌥+D once starts recording, tapping again stops.
5. Try to enable **Press to toggle** while the hotkey is modifier-only → the UI blocks it with a warning.
6. Click **Use Fn (default)** → reverts without resetting the mode.

### 6.3 History

| # | Scenario | Status |
|---|---|---|
| 6.3.1 | Empty history renders "No entries yet." | ⚪ |
| 6.3.2 | Non-empty history renders timestamp, transcript, action summary | ⚪ |
| 6.3.3 | Clear → confirmation dialog → refresh | ⚪ |

#### Manual history acceptance
- Record 3 commands. Open the History tab. Verify each has a correct timestamp, transcript, and action list.
- Click Clear → confirm → list empties.

---

## 7. End-to-end (Playwright)

[`tests/e2e/settings.spec.ts`](miniflow-electron/tests/e2e/settings.spec.ts)

| # | Scenario | Status |
|---|---|---|
| 7.1 | App launches and shows three tabs | 🟡 (requires built .app + backend) |
| 7.2 | Switching tabs changes content | 🟡 |
| 7.3 | Popover anchors below tray icon | ⚪ |
| 7.4 | Popover hides on blur | ⚪ |
| 7.5 | Quit from right-click menu gracefully kills helper + backend | ⚪ |

#### Manual E2E acceptance
- Run `./build_electron.sh`. Open the built DMG, drag to Applications, `xattr -cr`, launch.
- Tray icon appears. Click → popover opens below icon. Click outside → hides.
- Force-quit (⌘Q) while backend healthy → both helper and Python process disappear from `ps aux`.

---

## 8. Integrations — manual (until Electron UI lands)

Back-end endpoints are tested via curl; each connector's `execute()` is exercised by the pytest suite indirectly through agent tool-call tests.

For each of Slack / Gmail / GitHub / Calendar / Linear / Notion / Jira / Spotify / Discord:
1. `curl -X POST http://127.0.0.1:8765/invoke/start_oauth -H 'Content-Type: application/json' -d '{"provider":"<p>"}'`
2. Complete the browser flow → the success page closes.
3. `curl -X POST http://127.0.0.1:8765/invoke/get_connected_providers -d '{}'` → contains `"<p>"`.
4. Hold hotkey, say a sentence that triggers a `<p>_*` tool → verify result.

---

## 9. Regression suites — commands to run before every release

```bash
# 1. Python (should be 43 passing)
cd miniflow-engine && env -u SSL_CERT_FILE -u REQUESTS_CA_BUNDLE \
  ./venv/bin/python -m pytest tests/ -q

# 2. Rust helper (should be 6 passing)
cd native-helper && cargo test -q

# 3. Electron unit tests (should be 22 passing)
cd miniflow-electron && npx jest --silent

# 4. Type-check everything
cd miniflow-electron && npx tsc -p tsconfig.main.json --noEmit
cd miniflow-electron && npx tsc -p tsconfig.json --noEmit

# 5. Full build (Python + Rust + Electron DMG)
./build_electron.sh
```

Grand total of automated checks: **71 tests** + 2 type-check configs.

---

## 10. Release acceptance checklist

- [ ] All 71 automated tests pass.
- [ ] `npx tsc --noEmit` clean for both main and renderer tsconfigs.
- [ ] `cargo build --release` produces a binary under 1 MB after strip.
- [ ] Fresh install on a clean macOS user: hotkey permission dialog fires, helper pidfile is written, healthy `/health` within 5s.
- [ ] At least one provider per major family (OpenAI, Anthropic, Ollama) smoke-tested end-to-end with one voice command each.
- [ ] Hotkey customization persists across app restart.
- [ ] At least two connectors (Slack + Gmail) exercised.
- [ ] `miniflow.log` shows no unhandled exceptions during a 5-minute usage session.
- [ ] DMG opens, app launches, no Gatekeeper scare after `xattr -cr`.
