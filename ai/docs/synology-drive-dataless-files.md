# Synology Drive On-Demand Sync: Dataless Files & Programmatic Download

## Background

`archive_apps.sh` archives `/Applications/*.app` bundles to a destination directory.
When the destination is on a Synology Drive "Smart Sync" (on-demand) mount, previously
archived zip files may be **cloud-only placeholders** — the macOS BSD flag `dataless`
is set and the file's bytes are not stored locally.

The script's checksum-verification branch (around line 42 of `archive_apps.sh`) copies
the existing zip to a temp dir to compare checksums:

```bash
cp "$dest/$zipname" "$tmpcheck/archive.zip"
```

When the zip is `dataless`, this `cp` fails with **"Operation not permitted"**. Because
the script runs under `set -euo pipefail`, this aborts the entire run.

### Trigger: error log entry

```
EXISTS: NextcloudTalk.app@mobile@21.0.1.zip
  CHECKSUMMING from zip: NextcloudTalk.app@mobile@21.0.1.checksums.txt
cp: /Users/user/Library/CloudStorage/SynologyDrive-Shed/Install/macOS X/macOS 26 - Tahoe - M1/Applications.zip/data/NextcloudTalk.app@mobile@21.0.1.zip: Operation not permitted
```

Saved in: `ai/errors/1.md`

---

## Script Fix Applied

**File:** `archive_apps.sh` line ~42, inside the "zip exists but no checksums" branch.

```bash
# Before (aborts entire script on failure):
tmpcheck=$(mktemp -d)
cp "$dest/$zipname" "$tmpcheck/archive.zip"

# After (skips gracefully):
tmpcheck=$(mktemp -d)
if ! cp "$dest/$zipname" "$tmpcheck/archive.zip" 2>/dev/null; then
    echo "  SKIPPED (zip not readable; possibly not synced locally)"
    rm -rf "$tmpcheck"
    continue
fi
```

---

## Discovery 1 — Confirming the File Is a Dataless Placeholder

### What `ls -leO` revealed

```
$ ls -leO "/Users/user/Library/CloudStorage/SynologyDrive-Shed/Install/macOS X/macOS 26 - Tahoe - M1/Applications.zip/data/NextcloudTalk.app@mobile@21.0.1.zip"
-rw-r--r--@ 1 user  wheel  compressed,dataless  37168371  May 12 08:43  …
```

The `compressed,dataless` BSD file flags (shown by `-O`) confirm this is a
**FileProvider placeholder**. The reported size (37 MB) is the remote size; no bytes
are stored locally.

The `@` in the permissions column means extended attributes are present. `xattr`
(without flags) appeared to return only `com.apple.lastuseddate#PS` and
`com.apple.provenance` via libc's `listxattr()`, both standard macOS metadata attrs —
no FileProvider-specific xattr, meaning the `dataless` status comes entirely from the
BSD flag rather than from an xattr.

### `mdls` "could not find" signal

```
$ mdls "…/NextcloudTalk.app@mobile@21.0.1.zip"
could not find …/NextcloudTalk.app@mobile@21.0.1.zip
```

`ls` sees the file; `mdls` (Spotlight) cannot — this is a reliable secondary indicator
that a file is a dataless placeholder. Spotlight does not index files whose data has not
been materialized.

### `brctl download` — iCloud-only

```
brctl: Unable to start downloads: Error Domain=BRCloudDocsErrorDomain Code=6
"Path is outside of any CloudDocs app library, will never sync"
```

`brctl` only handles iCloud Drive (`CloudDocs`). The Synology Drive mount at
`~/Library/CloudStorage/SynologyDrive-Shed/` is a different FileProvider extension and
requires a different trigger.

---

## Discovery 2 — Synology Drive Processes and Their Sockets

### Running processes (relevant subset)

Found via `ps aux | grep -i synology`:

| PID | Binary | Role |
|-----|--------|------|
| 1058 | `cloud-drive-daemon` | Core sync daemon |
| 1036 | `cloud-drive-ui` | Menu-bar UI |
| 886 | `FinderSync.appex` | Finder badge overlays |
| 1115/1114/1109 | `SynologyDriveFileProvider.appex` | macOS FileProvider extension (3 instances) |
| 1054 | `FinderHelper.app` | Bridge between FinderSync and daemon |

### IPC sockets on the daemon (PID 1058)

Found via `lsof -p 1058`:

```
/Users/user/Library/Group Containers/group.com.synology.CloudStationUI/daemon.sock
/Users/user/Library/Group Containers/group.com.synology.CloudStationUI/ui.sock
```

Both Unix-domain sockets are owned by `cloud-drive-daemon`. The daemon also has
several anonymous connected-pair sockets (FDs 16, 33, 36, 37).

### FinderSync listens on TCP localhost

Found via `lsof -p 886`:

```
FinderSyn  886  user  3u  IPv4  …  TCP localhost:blackjack (LISTEN)
```

Port `blackjack` = 1025/tcp. The daemon connects **to** FinderSync to push icon
overlay/status updates. FinderSync is a listener, not an initiator, for that channel.

---

## Discovery 3 — Daemon Config and Session Database

### Config file

`~/Library/Application Support/SynologyDrive/data/config/client.conf` (plain text):

```
punchd_port="49364"       # NAT punch-through port (external, not a local API)
ui_port="0"               # dynamic
log_file_path="…/log/daemon.log"
```

### NAS connection (sys.sqlite)

```
$ sqlite3 "…/data/db/sys.sqlite" "SELECT * FROM connection_table LIMIT 1;"
```

Key fields extracted: NAS hostname `golden-oak-library`, IP `192.168.178.70`, port
`6690`. Confirmed online: 2 ms ping, 0% packet loss.

### Session table — on-demand flag

```
$ sqlite3 "…/data/db/sys.sqlite" \
  "SELECT id, share_name, sync_folder, is_mac_on_demand_sync_enable FROM session_table;"

8   | files_luckydonald | /Users/user/Documents/programming/    | 0
21  | Shed              | ~/Library/CloudStorage/SynologyDrive-Shed/ | 1  ← Smart Sync ON
22  | music             | ~/Library/CloudStorage/SynologyDrive-Music/ | 1
23  | files_luckydonald | ~/Pictures/Scan/                       | 0
24  | files_luckydonald | ~/Library/CloudStorage/SynologyDrive-LPLP-2024/ | 1
```

Session 21 (`Shed`) has `is_mac_on_demand_sync_enable = 1`. This is the database
record that enables Smart Sync and causes files to be stored as `dataless` placeholders.

### FileProvider activity log

```
~/Library/Application Support/SynologyDrive/log/file-provider-lib.log
```

Last entry dated **2026-05-15**. No entries for `NextcloudTalk` or `Applications.zip`
at any point during testing — confirming that **none of our CLI read attempts triggered
the FileProvider extension** to initiate a download.

---

## Discovery 4 — daemon.sock Protocol (PStream / PObject)

### Initial probe

Sending 4 null bytes to `daemon.sock`:

```python
sock.sendall(b'\x00\x00\x00\x00')
resp = sock.recv(1024)
# resp (hex): 4210000361636b1000026f6b40
```

### Protocol decoding

The response decodes as:

```
42               ← begin map (0x42 = 'B')
  10 00 03 "ack" ← string field: key "ack", length 3
  10 00 02 "ok"  ← string field: value "ok", length 2
40               ← end map (0x40 = '@')
```

This is the `IconOverlay::PStream` serialization format, confirmed by the binary
symbols found via `nm` on the FinderSync and cloud-drive-ui binaries:

```
__ZN11IconOverlay7PStream4SendERNS_7ChannelERKNSt…basic_stringI…  → Send(Channel&, string const&)
__ZN11IconOverlay7PStream10SendObjectERNS_7ChannelERKNS_7PObjectE → SendObject(Channel&, PObject const&)
__ZN11IconOverlay7PStream4RecvERNS_7ChannelERNSt…mapI…            → Recv(Channel&, map<string,PObject>&)
__ZN11IconOverlay9IPCSender4sendERKNS_7PObjectE                   → IPCSender::send(PObject const&)
__ZN11IconOverlay9IPCSender4recvERNS_7PObjectE                    → IPCSender::recv(PObject&)
```

`PObject` is a variant type (strings, ints, maps, vectors). `PStream` serializes
`PObject`s over a `Channel`. The format:

| Byte | Meaning |
|------|---------|
| `0x42` | Begin map |
| `0x10` | String field marker |
| 2 bytes big-endian | String length |
| N bytes | String data |
| `0x40` | End map |

### Why daemon.sock is not the right channel

Every message tried — `{"cmd": "get_status"}`, `{"cmd": "force_download"}`, correctly
framed PStream maps with real command strings — returned the identical `{"ack": "ok"}`
response. The socket appears to be a **heartbeat/connection-presence channel** (the
daemon signals liveness), not a command dispatcher. Real commands go elsewhere.

---

## Discovery 5 — FileProvider Extension Info.plist: Pin Action

The FileProvider extension declares its context menu actions in its `Info.plist`:

```
/Users/user/Library/Application Support/SynologyDrive/SynologyDrive.app/Contents/PlugIns/SynologyDriveFileProvider.appex/Contents/Info.plist
```

Extracted via `plutil -p`:

```
"NSExtensionFileProviderActions" => [
  {
    "NSExtensionFileProviderActionIdentifier" => "com.synology.CloudStationUI.FileProvider.Action.HistoryVersion"
    "NSExtensionFileProviderActionName"       => "context_menu_version_browse"
    "NSExtensionFileProviderActionActivationRule" => "fileproviderItems.@count == 1 && …not folder…"
  }
  {
    "NSExtensionFileProviderActionIdentifier" => "com.synology.CloudStationUI.FileProvider.Action.ShareLink"
    "NSExtensionFileProviderActionName"       => "get_file_link"
  }
  {
    "NSExtensionFileProviderActionIdentifier" => "com.synology.CloudStationUI.FileProvider.Action.Pin"
    "NSExtensionFileProviderActionName"       => "context_menu_pin_to_local"
    "NSExtensionFileProviderActionActivationRule" =>
      "SUBQUERY(fileproviderItems, $item, $item.userInfo.showPin == YES).@count > 0"
  }
  {
    "NSExtensionFileProviderActionIdentifier" => "com.synology.CloudStationUI.FileProvider.Action.Unpin"
    "NSExtensionFileProviderActionName"       => "context_menu_unpin"
    "NSExtensionFileProviderActionActivationRule" =>
      "SUBQUERY(fileproviderItems, $item, $item.userInfo.showUnpin == YES).@count > 0"
  }
  {
    "NSExtensionFileProviderActionIdentifier" => "com.synology.CloudStationUI.FileProvider.Action.Evict"
    "NSExtensionFileProviderActionName"       => "context_menu_dehydrate"
    "NSExtensionFileProviderActionActivationRule" =>
      "SUBQUERY(fileproviderItems, $item, $item.userInfo.showEvict == YES).@count > 0"
  }
]
"NSExtensionPointIdentifier"              => "com.apple.fileprovider-nonui"
"NSExtensionPrincipalClass"               => "SynologyDriveFileProvider.FileProviderExtension"
"NSExtensionFileProviderAllowsUserControlledEviction" => false
"NSExtensionFileProviderDocumentGroup"    => "group.com.synology.CloudStationUI"
```

**Key insight:** "Make Available Offline" is the **Pin** action
(`…Action.Pin`), a standard `NSExtensionFileProviderAction`. It is NOT a custom
FinderSync menu item — it is a native macOS Finder entry for all FileProvider domains.
Finder shows it automatically; the extension just declares the activation predicate
and handler.

---

## Discovery 6 — NSFileProviderManager Method Inventory

Because `NSFileProviderManager.performAction(withIdentifier:onItemsAt:)` did not exist
in the Swift overlay, the runtime method list was dumped via `class_copyMethodList`:

```swift
var count: UInt32 = 0
class_copyMethodList(NSFileProviderManager.self, &count)
```

Relevant methods found (instance):

```
getIdentifierForUserVisibleFileAtURL:completionHandler:   ← class method
requestDownloadForItemWithIdentifier:requestedRange:completionHandler:
startDownloadingItemWithIdentifier:requestedRange:completionHandler:
evictItemWithIdentifier:completionHandler:
getServiceWithName:itemIdentifier:completionHandler:
requestModificationOfFields:forItemWithIdentifier:options:completionHandler:
waitForChangesOnItemsBelowItemWithIdentifier:completionHandler:
```

`requestDownloadForItemWithIdentifier:requestedRange:completionHandler:` is the private
method that Finder calls when the user clicks "Make Available Offline". It is not
exposed in the Swift overlay and requires `objc_msgSend` via `dlsym` to call.

---

## Discovery 7 — Item Identifier Resolution (Works from CLI)

```swift
let targetURL = URL(fileURLWithPath: "…/NextcloudTalk.app@mobile@21.0.1.zip")
NSFileProviderManager.getIdentifierForUserVisibleFile(at: targetURL) { id, domainID, error in
    // id:       NSFileProviderItemIdentifier("951648423963049011")
    // domainID: NSFileProviderDomainIdentifier("21")   ← matches session_table.id = 21
}
```

This **works from CLI** — the FileProvider framework resolves the filesystem path to
its opaque item identifier and the domain that owns it without requiring elevated
entitlements (it's a pure lookup, no state change).

---

## Discovery 8 — First Call Attempt: Crash Reveals XPC Is Reachable

The first attempt to invoke `requestDownloadForItemWithIdentifier` used
`NSObject.perform(_:with:with:)`, which does not forward block arguments:

```swift
manager.perform(sel, with: itemIdentifier, with: NSValue(range: range))
// — no completion block passed —
```

This caused a **crash inside FileProvider.framework** with stack:

```
FileProvider  __108-[NSFileProviderManager(Materialize) requestDownloadForItemWithIdentifier:…]_block_invoke_2
FileProvider  -[NSFileProviderManager fetchDomainServicerSynchronously:useOutgoingConnection:completionHandler:]
Foundation    __NSXPCCONNECTION_IS_CALLING_OUT_TO_REPLY_BLOCK__
Foundation    -[NSXPCConnection _decodeAndInvokeReplyBlockWithEvent:sequence:replyInfo:]
libxpc.dylib  _xpc_connection_reply_callout
```

**Critical observation:** The stack trace includes `NSXPCCONNECTION_IS_CALLING_OUT_TO_REPLY_BLOCK__`
and `fetchDomainServicerSynchronously` — the method **did reach the FileProvider
extension over XPC** before crashing. The crash was caused by the nil completion
block, not by a permission rejection. This confirmed that the method itself is
callable and routes correctly to `SynologyDriveFileProvider.appex`.

---

## Discovery 9 — `objc_msgSend` via `dlsym` (Final Attempt)

Swift wraps `objc_msgSend` and marks it unavailable. The C symbol is still accessible
via `dlsym`:

```swift
import Darwin
typealias MsgSend = @convention(c) (
    AnyObject, Selector,
    NSFileProviderItemIdentifier,
    NSRange,
    @escaping (Error?) -> Void
) -> Void
let msgSendPtr = dlsym(dlopen(nil, RTLD_LAZY), "objc_msgSend")!
let fn = unsafeBitCast(msgSendPtr, to: MsgSend.self)

let sel = NSSelectorFromString("requestDownloadForItemWithIdentifier:requestedRange:completionHandler:")
fn(manager, sel, itemIdentifier, NSRange(location: 0, length: 0)) { err in
    // err: NSFileProviderErrorDomain Code=-2001
    //      "The application cannot be used right now."
    //      NSUnderlyingError: NSFileProviderErrorDomain Code=-2014
}
```

`NSFileProviderError.notAuthenticated` (code -2001) is returned. The underlying -2014
is an internal FPXPC error. The FileProvider framework gates **write/modify operations**
to processes holding the `com.apple.developer.fileprovider` production entitlement.
Read-only operations (like resolving item identifiers) are unrestricted.

---

## macOS FileProvider Architecture Summary

```
Finder
 ├─ Reads NSExtensionFileProviderActions from SynologyDriveFileProvider.appex/Info.plist
 │   → shows "Make Available Offline" when $item.userInfo.showPin == YES
 │
 └─ On click → NSFileProviderManager
                 └─ XPC → fileproviderd (system daemon)
                            └─ XPC → SynologyDriveFileProvider.appex
                                       └─ downloads file from NAS (192.168.178.70:6690)
                                          and materializes via FileProvider kernel extension

FinderSync.appex (PID 886)
 ├─ Listens on TCP localhost:1025 (port "blackjack")
 │   ← cloud-drive-daemon connects here to push icon overlay status
 │
 └─ IPCSender → daemon.sock (Unix socket)
     Protocol: IconOverlay::PStream / PObject (TLV, 0x42…0x40 framing)
     Purpose:  heartbeat / presence only — not a download command channel
```

---

## Entitlement Wall

| Operation | CLI / `swift -` | Notes |
|-----------|-----------------|-------|
| `getIdentifierForUserVisibleFile` | ✓ Works | Pure lookup, no state change |
| `NSFileCoordinator` coordinated read | ✗ File handle nil | Synology's FileProvider does not materialize for CLI callers |
| `requestDownloadForItemWithIdentifier` | ✗ -2001 | Requires `com.apple.developer.fileprovider` entitlement |
| `getDomainsWithCompletionHandler` | ✗ -2001 | Same gate |
| `brctl download` | ✗ Wrong provider | iCloud-only |
| `daemon.sock` commands | ✗ Generic ack | Not a command channel |
| Finder AppleScript copy | ✗ Timeout (-1712) | FileProvider didn't materialize in time |

---

## Practical Options

### Option A — Disable Smart Sync for the Shed folder *(recommended for scripted use)*

**Synology Drive Client → sync task Shed → switch "Smart Sync" → "Full Sync"**

All files stay downloaded permanently. The script works without changes beyond the
fix already applied. Cost: local disk space equals the full size of the Shed share.

### Option B — Build a signed helper utility (`syno-pin`)

A minimal Swift `.app` bundle (not a CLI tool) with the `com.apple.developer.fileprovider`
entitlement can successfully call `requestDownloadForItemWithIdentifier` and wait for
the FileProvider to complete the download before returning. The script would call it
before the checksum step:

```bash
if ! cp "$dest/$zipname" "$tmpcheck/archive.zip" 2>/dev/null; then
    if syno-pin "$dest/$zipname"; then
        cp "$dest/$zipname" "$tmpcheck/archive.zip"
    else
        echo "  SKIPPED (zip not readable; possibly not synced locally)"
        rm -rf "$tmpcheck"
        continue
    fi
fi
```

Requires: Apple Developer account, provisioning profile with the FileProvider
entitlement, code signing.

### Option C — Accept the skip *(current state)*

The script already skips dataless zips gracefully:

```
SKIPPED (zip not readable; possibly not synced locally)
```

When the user later makes the file available offline (Finder right-click →
"Make Available Offline", or via Full Sync), re-running the script picks it up and
writes the checksums file normally.

---

## Key File & Binary Locations

| Path | Purpose |
|------|---------|
| `archive_apps.sh` line ~42 | The fixed `cp` call |
| `ai/errors/1.md` | Original error output that triggered this investigation |
| `~/Library/CloudStorage/SynologyDrive-Shed/` | Smart Sync mount root |
| `~/Library/Group Containers/group.com.synology.CloudStationUI/daemon.sock` | PStream heartbeat socket (not a command channel) |
| `~/Library/Group Containers/group.com.synology.CloudStationUI/ui.sock` | UI status socket |
| `~/Library/Application Support/SynologyDrive/data/db/sys.sqlite` | Session table with `is_mac_on_demand_sync_enable` flag |
| `~/Library/Application Support/SynologyDrive/data/config/client.conf` | Daemon config (NAS host not here; it's in `sys.sqlite`) |
| `~/Library/Application Support/SynologyDrive/log/daemon.log` | Live sync event log |
| `~/Library/Application Support/SynologyDrive/log/file-provider-lib.log` | FileProvider materialization log (was silent during all our tests) |
| `.../SynologyDrive.app/Contents/MacOS/cloud-drive-daemon` | Sync daemon binary |
| `.../SynologyDrive.app/Contents/MacOS/cloud-drive-ui` | UI binary (contains PStream/PObject symbols) |
| `.../SynologyDrive.app/Contents/Resources/FinderHelper.app/Contents/PlugIns/FinderSync.appex/Contents/MacOS/FinderSync` | FinderSync binary (contains `IPCSender`, `IPCListener`, `ContextMenuHandler`) |
| `.../SynologyDrive.app/Contents/PlugIns/SynologyDriveFileProvider.appex/Contents/Info.plist` | FileProvider action declarations (Pin/Unpin/Evict) |
