# Install Uxie (beta, pre-notarization)

Uxie is currently signed but **not yet notarized** by Apple (we're in the middle
of Developer-account enrollment). That means macOS's Gatekeeper will block the
app on first launch with a "damaged, move to trash" message unless you bypass
it once. This is a one-time step — after the first launch, Uxie runs normally.

## Fastest path — one-line installer

Copy-paste into **Terminal** (Spotlight → `Terminal`):

```
curl -fsSL https://raw.githubusercontent.com/uxie-app/uxie-releases/main/install.sh | bash
```

That's it. The script downloads the latest DMG, copies Uxie to
`/Applications`, strips the quarantine flag, and prints where it landed.

Then:

```
open /Applications/Uxie.app
```

First launch will prompt for **Microphone**, **Accessibility**, and
**Input Monitoring** permissions — grant all three (Uxie needs Accessibility
+ Input Monitoring for the `fn` hotkey and typing into the focused app).

## Manual path (if you'd rather not pipe curl into bash)

1. Download the latest DMG directly from
   https://github.com/uxie-app/uxie-releases/releases/latest (grab the
   `Uxie-<version>-arm64.dmg` file)
2. Double-click the DMG, drag **Uxie** onto the **Applications** folder
3. macOS will show **"Uxie is damaged and can't be opened"** on first launch —
   that's Gatekeeper, not a real problem. Fix it with one Terminal command:

   ```
   xattr -dr com.apple.quarantine /Applications/Uxie.app
   ```

4. Open Uxie normally now (Spotlight → `Uxie`, or Applications folder)

## What happens when Uxie is notarized

We'll remove the Gatekeeper warning entirely and auto-update will just work.
You won't need to do anything — existing installs keep running. Planned for
the release right after our Apple Developer org account is approved.

## Uninstall

```
osascript -e 'tell application "Uxie" to quit'
rm -rf /Applications/Uxie.app
rm -rf ~/miniflow      # local settings, logs, JWT
```
