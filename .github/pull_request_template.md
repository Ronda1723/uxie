<!--
  Read PROCESS.md first if you haven't already. The lane you pick decides
  which boxes you actually need. Strike out the ones that don't apply.
-->

## What this changes

<!-- One sentence. What does the user (or developer) get? -->

## Why

<!-- Hidden constraint, prior incident, ticket, or design doc this came from.
     Do NOT just paste the commit subject. -->

## Lane (pick one)

- [ ] **Quick** — backend-only, Railway will redeploy
- [ ] **Standard** — pure UI tweak, no behavior change
- [ ] **Full** — behavior change, new tool, or new file/IPC channel
- [ ] **Release** — `package.json` version bump

## Bug-class scan (must check off)

- [ ] No new secret strings in the diff
- [ ] No `console.log` / `print()` debug spam left in
- [ ] If touched the agent loop or widget — approval sheet still works on Mac AND iOS
- [ ] If touched `entitlements.mac.plist` — used the narrowest entitlement; full notarize round-trip done
- [ ] If touched `audio.py` — mic capture verified manually
- [ ] If new long-lived listener/interval/EventEmitter — cleanup added
- [ ] If renamed an event/tool — Mac AND iOS clients updated together
- [ ] CLAUDE.md updated if architecture changed (new repo, new env var, new file path)

## Manual verification

<!-- What did you actually test? "I tested gmail_send end-to-end on Mac
     v1.0.19" beats "Tested locally". -->

- macOS: <!-- platform you confirmed on, version you tested -->
- iOS: <!-- skipped / tested on iPhone X iOS Y -->
- Windows: <!-- skipped / tested -->

## Skipped lane checks (with reason)

<!-- e.g. "Skipped Windows smoke test — change is Mac-only" -->
