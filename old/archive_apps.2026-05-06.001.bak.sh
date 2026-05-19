#!/bin/bash
set -euo pipefail

dest="${1:-/Users/Shared/App Versions}"
mkdir -p "$dest"

find /Applications -maxdepth 2 -name "*.app" -type d | while IFS= read -r app; do
    plist="$app/Contents/Info.plist"
    mobile=""
    if [[ ! -f "$plist" ]]; then
        plist="$app/WrappedBundle/Info.plist"
        mobile="mobile@"
    fi
    if [[ ! -f "$plist" ]]; then
        echo "SKIP (no Info.plist): $app"
        continue
    fi

    name=$(/usr/libexec/PlistBuddy -c "Print :CFBundleName" "$plist" 2>/dev/null) \
        || name=$(basename "$app" .app)
    version=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$plist" 2>/dev/null) \
        || version="unknown"

    zipname="${name}.app@${mobile}${version}.zip"
    if [[ -f "$dest/$zipname" ]]; then
        echo "EXISTS: $zipname"
        continue
    fi

    echo "ARCHIVING: $zipname"
    versioned="${name} ${version}.app"
    tmpdir=$(mktemp -d "$dest/.archive_apps.XXXXXX")
    cp -cR "$app" "$tmpdir/$versioned"
    (cd "$tmpdir" && ditto -c -k --sequesterRsrc --keepParent "$versioned" "$dest/$zipname")
    rm -rf "$tmpdir"
done
