# Uxie — Change & Release Process

This is the gate before any change reaches a user. Skipping steps is how
we ship broken DMGs, leak secrets, or push a backend regression that
breaks live voice commands. Don't.

---

## 1. Pick the lane

Match the change to a lane. The lane decides which checks apply.

| Change type | Lane | Examples |
|---|---|---|
| **Backend-only** (Railway) | **Quick** | Tweak a system prompt, fix a Groq retry, add a connector tool, change a /llm/chat param |
| **UI tweak only** (renderer, no behavior change) | **Standard** | Adjust spacing, recolor a button, fix a typo, add a tooltip |
| **Behavior change** | **Full** | New tool, new state machine in widget, change to mic capture, change to OAuth flow |
| **Public release** (DMG/EXE goes to `uxie-app/uxie-releases`) | **Release** | Any time `package.json` version is bumped |

> **iOS** changes follow the same logic but live in `uxie-app/uxie-ios`. Treat
> a TestFlight push the same way as a Release lane on Mac.

---

## 2. Quick lane — backend-only fix

For changes inside `uxie-backend/`. Railway auto-deploys from `main` so
"merge" = "in production" within ~3 minutes.

Before push:

- [ ] **No real secrets in the diff.** Search for `OAUTH_CLIENT_SECRET`, `JWT_PRIVATE_KEY`, `DEEPGRAM_API_KEY`, `RESEND_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`. Never commit them.
- [ ] **Python file parses cleanly:** `python3 -c "import ast; ast.parse(open('uxie-backend/agent.py').read())"`
- [ ] **No new `print()` debug spam left in.** Use `_log.info(...)` / `_log.debug(...)` consistently.
- [ ] **Reasoned about migration safety.** Any DB column change → must work with the OLD client still hitting the new backend (rolling deploy).
- [ ] **If you changed a tool's behavior**, the iOS-app and Mac-app code that *calls* it doesn't need a corresponding update.

After push (Railway redeploy, ~3 min):

- [ ] `curl -sS https://uxie-production.up.railway.app/health` returns `{"status":"ok",...}`
- [ ] One real voice command end-to-end on either Mac or iOS confirms the change

---

## 3. Standard lane — pure UI tweak

For renderer changes that don't change behavior — colors, spacing, copy.

- [ ] Quick lane checks (no secrets, no debug spam)
- [ ] `npm run build` succeeds in `miniflow-electron/`
- [ ] App launches in dev (`npm run dev`) and the area you touched looks right
- [ ] No `console.log` left in the diff
- [ ] No new dependency added without thinking about it

You can merge without a release. Will be picked up in the next normal release.

---

## 4. Full lane — behavior change

The most common lane. Triggered when ANY of these is true:

- A new tool, capture path, or external integration
- The widget's state machine changes
- The agent loop's flow changes
- A new permission is requested
- An OAuth scope changes
- The signing/notarization flow changes
- A new IPC channel or new file is added to the build

All Standard-lane checks PLUS:

- [ ] **Manual smoke test of the change itself** — walk through the new flow on your Mac and Windows machine (or note explicitly which platform you couldn't test).
- [ ] **Approval flow still works** if you touched the agent or widget.
- [ ] **fn key still triggers capture** if you touched main, helper, or AudioCapture.
- [ ] **Verify dictation still works** if you touched the audio path.
- [ ] **Verify gmail_send approval flow** if you touched the agent or widget.
- [ ] **Memory check.** If you added a long-lived listener, EventEmitter, or interval, you also added cleanup.
- [ ] **Updated CLAUDE.md** if the architecture changed (new file path, new env var, new repo).
- [ ] **Pushed PR description** describes WHY, not just WHAT. Future-you needs the why.

If the change is on the Python backend AND clients (iOS/Mac) need a coordinated update, the deploy must go in this order:
1. Backend change (additive — old client still works)
2. Mac+iOS clients (use new behavior)
3. Backend cleanup (remove the old code path)

Never the other way around.

---

## 5. Release lane — bumping version + shipping a DMG/EXE

Triggered when `miniflow-electron/package.json` `version` field is bumped.

### Pre-build checklist

- [ ] All Full-lane checks for every change since last release.
- [ ] `package.json` version matches what you intend to ship (semver — patch for fixes, minor for features).
- [ ] Tag in your head: what's the user-visible change in one sentence?
- [ ] No experimental code paths gated by `if (DEBUG)` left enabled.
- [ ] Memory footprint check: nothing leaks across a press-release-press cycle of the mic.

### Build

Run the workflow:
```
gh workflow run build.yml --ref main --repo uxie-app/uxie
# OR via UI: https://github.com/uxie-app/uxie/actions/workflows/build.yml → Run workflow
```

The CI will:
1. Build the PyInstaller engine bundle
2. Compile the Rust helper for both macOS arm64 + Windows x64
3. Codesign the .app deeply (every PyInstaller binary individually)
4. `codesign --verify --strict` and `spctl --assess` BEFORE submitting to Apple — these MUST pass
5. Notarize via API key
6. Staple
7. Upload artifact

### Verify the DMG before publishing

Download the macOS artifact, then on a Mac:
- [ ] Double-click the DMG → mounts cleanly, no warnings
- [ ] Drag Uxie.app to Applications → launches without "damaged" or "developer cannot be verified"
- [ ] First launch grants Mic + Accessibility + Input Monitoring as expected
- [ ] Hold fn → bottom widget capsule appears, waveform animates
- [ ] Speak `"send an email to <you> saying test"` → approval sheet appears, tap Do It → email arrives
- [ ] Quit and re-launch — settings persist (keychain JWT not cleared)
- [ ] `xcrun stapler validate /Applications/Uxie.app` → "The validate action worked"
- [ ] `spctl --assess --type execute -vv /Applications/Uxie.app` → "accepted source=Notarized Developer ID"

If any of those fails, **don't publish**. Fix and rebuild.

### Verify the EXE if Windows is in scope

- [ ] Installer runs on a Windows test machine
- [ ] Right-Alt key triggers capture (Windows hotkey)
- [ ] Same gmail_send smoke test passes

### Publish

- [ ] Create release on `uxie-app/uxie-releases` with tag `vX.Y.Z`
- [ ] Upload BOTH Mac DMG and Windows EXE under the same tag (the rule from memory: "Releases ship Mac + Windows together")
- [ ] Release notes: 3–5 bullet points, user-language, not commit messages
- [ ] Confirm `electron-updater` `latest.yml` is present in the release assets
- [ ] One existing user (you) `auto-updates` successfully from the previous version

### Post-release watch

- [ ] Railway logs for 30 min — no spike in 5xx, no new error patterns
- [ ] Check email at `noreply@anthropic.com` (CI failure notifications) and Apple's notary email
- [ ] If a regression surfaces within 1 hour: prefer rollback (re-publish previous DMG as `latest`) over forward-fix

---

## 6. Hotfix flow

When something is **already broken in prod** and users are seeing it:

1. **Diagnose first, push later.** A wrong fix at 2am breaks more than it fixes.
2. **Backend-side break** → make the backend tolerant of the broken thing first (defensive try/catch, default fallback). Push to Railway. Then fix root cause.
3. **Client-side break** → if a flag or env var can disable the broken path, do that first. Then ship a real fix in the next release.
4. **Don't bump major version for a hotfix.** Patch only (e.g. `1.0.20 → 1.0.21`).
5. Skip the "manual smoke test on Windows" gate ONLY if the bug is Mac-specific. Otherwise still do it.

---

## 7. What "code review" looks like

Even solo, treat every PR (or every direct commit if you're working on `main`) as if a reviewer is watching. Self-review checklist:

### Bug-class scan (what's bitten us before)
- [ ] No nested ObservableObject pattern without `objectWillChange.send()` forwarding (broke approval sheet)
- [ ] No SSE consumer without keepalive on the server side (broke `/agent/execute` parking)
- [ ] No URLSession.shared for streaming (60s `timeoutIntervalForRequest` killed sessions)
- [ ] Approval handler captures `sessionID` BEFORE dismiss (race condition we hit)
- [ ] Tool name on Mac/iOS exactly matches `CLIENT_TOOL_SCHEMAS` on backend
- [ ] Timezone is sent in `/agent/execute` body and used in system prompt
- [ ] Gmail-related code uses `gmail.compose` scope (not just `gmail.send`)
- [ ] Any new entitlement added to `entitlements.mac.plist` is the *narrowest* one that works

### Code quality
- [ ] Diff is the smallest possible to achieve the goal
- [ ] No commented-out code blocks (delete or use VCS history)
- [ ] No TODO without a context (`TODO(rounak): why deferred`)
- [ ] Imports tidy — no unused
- [ ] One thing per commit (not "fix bug + refactor + bump dep" in one)

### Security
- [ ] No secret strings in the diff
- [ ] No new outbound network endpoint without auth
- [ ] Input from user goes through validation before hitting LLM/DB
- [ ] User-facing strings don't contain raw error messages with paths/tokens

---

## 8. Project-specific landmines (memorize these)

These have bitten us. Each is one read-this-when-you-touch-X:

- **Touching `audio.py`?** Run `npm run dev`, mic capture should still work. Mac may need to re-grant permission if entitlements changed.
- **Touching `agent.py`?** The widget state machine on Mac AND the iOS HomeView depend on the SSE event names. Don't rename without coordinating.
- **Touching `electron-builder.yml` or `entitlements.mac.plist`?** Full notarization round-trip required before merge — local-only test won't catch Gatekeeper rejection.
- **Touching the iOS app's keyboard or AudioCapture?** iOS keyboards are forbidden from mic. We pivoted away from this once already; don't re-introduce.
- **Touching `oauth_google.py`?** Real OAuth secrets live as env defaults — never `git add miniflow-engine` with a wildcard. Stage by file path.
- **Touching anything Windows-specific?** The Right-Alt hotkey and the helper-win build path. Test on a Windows machine, not just CI.

---

## 9. Things that should NEVER block a release

- Lint warnings unrelated to your change
- Doc typos
- A test that's been failing for two weeks (fix or remove it)
- A dependency upgrade that's tangentially mentioned

A release that rolls back is cheaper than a release that ships late.

---

## 10. When in doubt

- **Smaller diffs.** Split a big change into shippable chunks.
- **Feature flag.** New risky path → wrap it behind a settings toggle, ship the toggle off.
- **Skip the lane if you must, and write down why.** A note in the PR like "skipped Windows check, mac-only refactor" is fine. Silence is not.
