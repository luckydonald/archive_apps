# Synology Drive On-Demand Sync: Dataless Files & Programmatic Download

## Background

`archive_apps.sh` archives `/Applications/*.app` bundles to a destination directory.
When the destination is on a Synology Drive "Smart Sync" (on-demand) mount, previously
archived zip files may be **cloud-only placeholders** — the macOS BSD flag `dataless`
is set and the file's bytes are not stored locally.

The script's checksum-verification branch copies the existing zip to a temp dir
(`cp "$dest/$zipname" "$tmpcheck/archive.zip"`). When the zip is `dataless`, this
`cp` fails with **"Operation not permitted"**. Because the script runs under
`set -euo pipefail`, this aborts the entire run.

### Affected path (example)

```
/Users/user/Library/CloudStorage/SynologyDrive-Shed/Install/macOS X/macOS 26 - Tahoe - M1/Applications.zip/data/NextcloudTalk.app@mobile@21.0.1.zip
```

### Confirmation

```
$ ls -leO "…/NextcloudTalk.app@mobile@21.0.1.zip"
-rw-r--r--@ 1 user wheel  compressed,dataless  37168371  May 12 08:43  …
```

The `compressed,dataless` BSD flags confirm the file is a FileProvider placeholder.
`mdls` cannot find it (Spotlight skips dataless items). `cat` returns an error.

---

## Script Fix Applied

**File:** `archive_apps.sh`, checksum-verification branch (line ~42).

**Change:** Wrapped the `cp` in an error check:

```bash
# Before:
cp "$dest/$zipname" "$tmpcheck/archive.zip"

# After:
if ! cp "$dest/$zipname" "$tmpcheck/archive.zip" 2>/dev/null; then
    echo "  SKIPPED (zip not readable; possibly not synced locally)"
    rm -rf "$tmpcheck"
    continue
fi
```

This makes the script skip unreadable (dataless/cloud-only) zips gracefully instead
of aborting the whole run.

---

## Investigation: Can We Trigger "Make Available Offline" Programmatically?

### Environment

| Item | Value |
|------|-------|
| NAS | `golden-oak-library` at `192.168.178.70:6690` |
| NAS ping | 2 ms — online |
| Synology Drive session | `Shed` (session ID 21) |
| On-demand sync enabled | `is_mac_on_demand_sync_enable = 1` (from `sys.sqlite`) |
| FileProvider bundle ID | `com.synology.CloudStationUI.FileProvider` |
| Extension point | `com.apple.fileprovider-nonui` |

### macOS FileProvider Architecture

Synology Drive registers as a macOS **FileProvider** domain. "Make Available Offline"
is **not** a FinderSync custom menu item — it is a native macOS Finder menu entry
for all FileProvider domains. The action flow:

```
Finder
  └─ NSFileProviderManager  (FileProvider.framework)
       └─ XPC → SynologyDriveFileProvider.appex
                   └─ Downloads file from NAS
```

### "Pin" Action (= Make Available Offline)

Declared in `SynologyDriveFileProvider.appex/Contents/Info.plist`:

```xml
<key>NSExtensionFileProviderActionIdentifier</key>
<string>com.synology.CloudStationUI.FileProvider.Action.Pin</string>
<key>NSExtensionFileProviderActionName</key>
<string>context_menu_pin_to_local</string>
<key>NSExtensionFileProviderActionActivationRule</key>
<string>SUBQUERY(fileproviderItems, $item, $item.userInfo.showPin == YES).@count > 0</string>
```

Other related actions:
- `…Action.Unpin` — remove pin (keep as on-demand)
- `…Action.Evict` — evict local copy (free disk space)

### Approaches Tried

#### 1. `brctl download` — ✗ iCloud-only

```
brctl: Unable to start downloads: Path is outside of any CloudDocs app library
```

#### 2. Raw `cat` / file read — ✗ Operation not permitted

Dataless files cannot be read by standard CLI tools; they return EPERM immediately
without triggering a download from the FileProvider extension.

#### 3. `NSFileCoordinator` coordinated read (Swift CLI) — ✗ File handle nil

Even with a coordinated read intent (which is supposed to trigger FileProvider's
`fetchContents` or `startProvidingItem`), `FileHandle(forReadingAtPath:)` returned
nil. FileProvider log showed no download activity triggered.

#### 4. Finder via AppleScript (`duplicate POSIX file … to …`) — ✗ AppleEvent timeout (-1712)

Finder attempted the copy but timed out before the FileProvider materialized the file.

#### 5. `daemon.sock` reverse engineering — ✗ Generic ack only

The `cloud-drive-daemon` listens on:
```
/Users/user/Library/Group Containers/group.com.synology.CloudStationUI/daemon.sock
```

Protocol: custom TLV with `IconOverlay::PStream` / `PObject`.
- Header: `0x42` (map begin)
- Fields: `0x10 <uint16 len> <bytes>` (string)
- Footer: `0x40` (map end)

Every message sent returns `{"ack": "ok"}` regardless of content. This socket
appears to be a heartbeat/status channel, not a command channel for triggering
downloads.

#### 6. `NSFileProviderManager.getIdentifierForUserVisibleFile` — ✓ Works

```swift
NSFileProviderManager.getIdentifierForUserVisibleFile(at: targetURL) { id, domain, error in
    // id    = NSFileProviderItemIdentifier("951648423963049011")
    // domain = NSFileProviderDomainIdentifier("21")  (the Shed session)
}
```

This **works from a CLI** — the item identifier and domain are resolved correctly.

#### 7. `NSFileProviderManager.requestDownloadForItemWithIdentifier` — ✗ -2001 Not Authenticated

This is the correct API for triggering a download programmatically (what Finder calls
internally when "Make Available Offline" is clicked). Called via `objc_msgSend` with
`dlsym` since the method is private:

```swift
typealias MsgSend = @convention(c) (
    AnyObject, Selector,
    NSFileProviderItemIdentifier, NSRange,
    @escaping (Error?) -> Void
) -> Void
let fn = unsafeBitCast(dlsym(dlopen(nil, RTLD_LAZY), "objc_msgSend"), to: MsgSend.self)
fn(manager, sel, itemIdentifier, NSRange(location: 0, length: 0)) { err in … }
```

Result:
```
Error Domain=NSFileProviderErrorDomain Code=-2001 "The application cannot be used right now."
  NSUnderlyingError: NSFileProviderErrorDomain Code=-2014
```

`NSFileProviderError.notAuthenticated (-2001)` — the FileProvider framework rejects
write/modification operations from processes that lack the
`com.apple.developer.fileprovider` entitlement. Standard CLI tools and `swift -`
inline scripts do not have this entitlement.

`NSFileProviderManager.getDomainsWithCompletionHandler` also fails with -2001 from
CLI context (read operations are fine; state-changing ones are gated).

---

## Why It Can't Be Done Without a Signed App

The macOS FileProvider security model distinguishes:

| Operation | CLI | Signed app (no entitlement) | Signed app + `com.apple.developer.fileprovider` |
|-----------|-----|-----------------------------|------------------------------------------------|
| Resolve item identifier | ✓ | ✓ | ✓ |
| Read file (coordinated) | ✗ (Synology Drive specific) | probably ✓ | ✓ |
| Request download | ✗ | unknown | ✓ |
| List domains | ✗ | unknown | ✓ |

The entitlement is a production entitlement granted by Apple (provisioning profile),
not something that can be self-signed for distribution.

---

## Practical Options

### Option A — Disable on-demand sync for the Shed folder (recommended for scripted use)

In **Synology Drive Client → sync task for Shed → switch "Smart Sync" to "Full Sync"**.
This downloads all files permanently. The script works without modification beyond
the SKIPPED fix already applied.

Drawback: uses more local disk space.

### Option B — Build a signed helper utility

A minimal Swift app bundle (`syno-pin`) with the `com.apple.developer.fileprovider`
entitlement can call `requestDownloadForItemWithIdentifier` and wait for completion.
`archive_apps.sh` would call it before the checksum step:

```bash
syno-pin "$dest/$zipname" && cp "$dest/$zipname" "$tmpcheck/archive.zip"
```

Requires: Apple Developer account, provisioning profile, code signing.

### Option C — Accept the skip (current state)

The script already skips dataless zips gracefully with:
```
SKIPPED (zip not readable; possibly not synced locally)
```

When the file is later synced locally (e.g., by clicking "Make Available Offline"
in Finder, or by turning off Smart Sync), re-running the script will pick it up and
write the checksums file normally.

---

## Key File Locations

| Path | Purpose |
|------|---------|
| `~/Library/CloudStorage/SynologyDrive-Shed/` | Smart Sync mount root |
| `~/Library/Group Containers/group.com.synology.CloudStationUI/daemon.sock` | Daemon heartbeat socket |
| `~/Library/Application Support/SynologyDrive/data/db/sys.sqlite` | Session config (on-demand flag) |
| `~/Library/Application Support/SynologyDrive/log/file-provider-lib.log` | FileProvider activity log |
| `.../SynologyDriveFileProvider.appex/Contents/Info.plist` | FileProvider action declarations |
