#!/bin/bash
set -euo pipefail

case "${1:-}" in
    -h|--help)
        echo "Usage: $(basename "$0") [destination]"
        echo "  destination: directory to archive apps into (default: /Users/Shared/App Versions)"
        exit 0 ;;
esac

dest="${1:-/Users/Shared/App Versions}"
mkdir -p "$dest"
dest=$(cd "$dest" && pwd)

if [[ "$(stat -f "%d" "$dest")" == "$(stat -f "%d" /Applications)" ]]; then
    cp_flags=(-cR)
else
    cp_flags=(-R)
fi

cleanup() { rm -f "$dest"/*.zip.tmp "$dest"/*.txt.tmp; }
trap cleanup EXIT

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
    checksumname="${name}.app@${mobile}${version}.checksums.txt"
    if [[ -f "$dest/$zipname" ]]; then
        echo "EXISTS: $zipname"
        if [[ -f "$dest/$checksumname" ]]; then
            echo "  CHECKSUM: verified"
        else
            echo "  CHECKSUMMING from zip: $checksumname"
            tmpcheck=$(mktemp -d)
            if ! cp "$dest/$zipname" "$tmpcheck/archive.zip" 2>/dev/null; then
                echo "  SKIPPED (zip not readable; possibly not synced locally)"
                rm -rf "$tmpcheck"
                continue
            fi
            ditto -x -k "$tmpcheck/archive.zip" "$tmpcheck"
            rm -f "$tmpcheck/archive.zip"
            zipapp=$(find "$tmpcheck" -maxdepth 1 -name "*.app" -type d | head -1)
            zip_checksums=$(find "$zipapp" -type f -print0 | sort -z | xargs -0 shasum -a 256 | sed "s|$zipapp/||")
            live_checksums=$(find "$app" -type f -print0 | sort -z | xargs -0 shasum -a 256 | sed "s|$app/||")

            if [[ "$zip_checksums" == "$live_checksums" ]]; then
                rm -rf "$tmpcheck"
                echo "$zip_checksums" > "$dest/$checksumname.tmp"
                mv "$dest/$checksumname.tmp" "$dest/$checksumname"
                echo "  CHECKSUM: match"
            else
                zip_size=$(du -sh "$zipapp" | cut -f1)
                live_size=$(du -sh "$app" | cut -f1)
                rm -rf "$tmpcheck"
                printf "  MISMATCH: %s\n  zip (uncompressed): %s   live app: %s\n" "$zipname" "$zip_size" "$live_size"
                printf "  [o]verwrite zip / [b]oth / [s]kip: "
                read -r choice < /dev/tty
                case "$choice" in
                    o|O)
                        rm -f "$dest/$zipname"
                        versioned="${name} ${version}.app"
                        tmpdir=$(mktemp -d "$dest/.archive_apps.XXXXXX")
                        cp "${cp_flags[@]}" "$app" "$tmpdir/$versioned"
                        (cd "$tmpdir" && ditto -c -k --sequesterRsrc --keepParent "$versioned" "$dest/$zipname.tmp")
                        rm -rf "$tmpdir"
                        mv "$dest/$zipname.tmp" "$dest/$zipname"
                        echo "$live_checksums" > "$dest/$checksumname.tmp"
                        mv "$dest/$checksumname.tmp" "$dest/$checksumname"
                        ;;
                    b|B)
                        echo "$zip_checksums" > "$dest/$checksumname.tmp"
                        mv "$dest/$checksumname.tmp" "$dest/$checksumname"
                        suffix=$(date +%Y%m%d_%H%M%S)
                        newzip="${name}.app@${mobile}${version}~${suffix}.zip"
                        newcheck="${name}.app@${mobile}${version}~${suffix}.checksums.txt"
                        versioned="${name} ${version}.app"
                        tmpdir=$(mktemp -d "$dest/.archive_apps.XXXXXX")
                        cp "${cp_flags[@]}" "$app" "$tmpdir/$versioned"
                        (cd "$tmpdir" && ditto -c -k --sequesterRsrc --keepParent "$versioned" "$dest/$newzip.tmp")
                        rm -rf "$tmpdir"
                        mv "$dest/$newzip.tmp" "$dest/$newzip"
                        echo "$live_checksums" > "$dest/$newcheck.tmp"
                        mv "$dest/$newcheck.tmp" "$dest/$newcheck"
                        ;;
                    *)
                        echo "  SKIPPED"
                        ;;
                esac
            fi
        fi
        continue
    fi

    echo "ARCHIVING: $zipname"
    versioned="${name} ${version}.app"
    tmpdir=$(mktemp -d "$dest/.archive_apps.XXXXXX")
    cp "${cp_flags[@]}" "$app" "$tmpdir/$versioned"
    (cd "$tmpdir" && ditto -c -k --sequesterRsrc --keepParent "$versioned" "$dest/$zipname.tmp")
    rm -rf "$tmpdir"
    mv "$dest/$zipname.tmp" "$dest/$zipname"

    find "$app" -type f -print0 | sort -z | xargs -0 shasum -a 256 | sed "s|$app/||" > "$dest/$checksumname.tmp"
    mv "$dest/$checksumname.tmp" "$dest/$checksumname"
done
