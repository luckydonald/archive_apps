#!/bin/bash
set -euo pipefail

verify_zips=false
dest_arg=""

for arg in "$@"; do
    case "$arg" in
        -h|--help)
            echo "Usage: $(basename "$0") [--verify-zips] [destination]"
            echo "  --verify-zips  verify all existing zip archives before archiving"
            echo "  destination    directory to archive apps into (default: /Users/Shared/App Versions)"
            exit 0 ;;
        --verify-zips)
            verify_zips=true ;;
        -*)
            echo "Unknown option: $arg" >&2; exit 1 ;;
        *)
            dest_arg="$arg" ;;
    esac
done

dest="${dest_arg:-/Users/Shared/App Versions}"
mkdir -p "$dest"
dest=$(cd "$dest" && pwd)

if [[ "$(stat -f "%d" "$dest")" == "$(stat -f "%d" /Applications)" ]]; then
    cp_flags=(-cR)
else
    cp_flags=(-R)
fi

cleanup() { rm -f "$dest"/*.zip.tmp "$dest"/*.txt.tmp; }
trap cleanup EXIT

# Extract <zip> to a temp dir, compute per-file SHA256 checksums relative to the
# .app root inside, print them to stdout, then clean up.
# Returns 1 if the zip is unreadable (e.g. Synology dataless file).
checksums_from_zip() {
    local zip="$1" tmpcheck zipapp result
    tmpcheck=$(mktemp -d)
    if ! cp "$zip" "$tmpcheck/archive.zip" 2>/dev/null; then
        rm -rf "$tmpcheck"
        return 1
    fi
    ditto -x -k "$tmpcheck/archive.zip" "$tmpcheck"
    rm -f "$tmpcheck/archive.zip"
    zipapp=$(find "$tmpcheck" -maxdepth 1 -name "*.app" -type d | head -1)
    result=$(find "$zipapp" -type f -print0 | sort -z | xargs -0 shasum -a 256 | sed "s|$zipapp/||")
    rm -rf "$tmpcheck"
    printf '%s' "$result"
}

if [[ "$verify_zips" == "true" ]]; then
    mapfile -t _zips < <(find "$dest" -maxdepth 1 -name "*.zip" | sort)
    total=${#_zips[@]}
    echo "Verifying $total zip(s)…"
    i=0
    for zip in "${_zips[@]}"; do
        i=$(( i + 1 ))
        zipname=$(basename "$zip")
        checksumfile="${zip%.zip}.checksums.txt"
        echo "$i/$total VERIFY: $zipname"
        if [[ -f "$checksumfile" ]]; then
            if ! actual=$(checksums_from_zip "$zip"); then
                echo "  CHECKSUM zip: SKIPPED (unreadable)"
                continue
            fi
            if [[ "$(cat "$checksumfile")" == "$actual" ]]; then
                echo "  CHECKSUM zip: match"
            else
                echo "  CHECKSUM zip: mismatch"
            fi
        else
            echo "  CHECKSUM zip: missing, creating…"
            if ! actual=$(checksums_from_zip "$zip"); then
                echo "  SKIPPED (unreadable)"
                continue
            fi
            printf '%s\n' "$actual" > "${checksumfile}.tmp"
            mv "${checksumfile}.tmp" "$checksumfile"
        fi
    done
fi

mapfile -t _apps < <(find /Applications -maxdepth 2 -name "*.app" -type d)
total=${#_apps[@]}
echo "Checking $total app(s)…"
i=0
for app in "${_apps[@]}"; do
    i=$(( i + 1 ))
    plist="$app/Contents/Info.plist"
    mobile=""
    if [[ ! -f "$plist" ]]; then
        plist="$app/WrappedBundle/Info.plist"
        mobile="mobile@"
    fi
    if [[ ! -f "$plist" ]]; then
        echo "$i/$total SKIP (no Info.plist): $app"
        continue
    fi

    name=$(/usr/libexec/PlistBuddy -c "Print :CFBundleName" "$plist" 2>/dev/null) \
        || name=$(basename "$app" .app)
    version=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$plist" 2>/dev/null) \
        || version="unknown"

    zipname="${name}.app@${mobile}${version}.zip"
    checksumname="${name}.app@${mobile}${version}.checksums.txt"
    if [[ -f "$dest/$zipname" ]]; then
        echo "$i/$total EXISTS: $zipname"
        if [[ -f "$dest/$checksumname" ]]; then
            echo "  CHECKSUM zip: found"
        else
            echo "  CHECKSUM zip: missing, creating…"
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
                echo "  CHECKSUM zip: match"
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

    echo "$i/$total ARCHIVING: $zipname"
    versioned="${name} ${version}.app"
    live_checksums=$(find "$app" -type f -print0 | sort -z | xargs -0 shasum -a 256 | sed "s|$app/||")
    tmpdir=$(mktemp -d "$dest/.archive_apps.XXXXXX")
    cp "${cp_flags[@]}" "$app" "$tmpdir/$versioned"
    (cd "$tmpdir" && ditto -c -k --sequesterRsrc --keepParent "$versioned" "$dest/$zipname.tmp")
    rm -rf "$tmpdir"
    mv "$dest/$zipname.tmp" "$dest/$zipname"
    echo "$live_checksums" > "$dest/$checksumname.tmp"
    mv "$dest/$checksumname.tmp" "$dest/$checksumname"

    if zip_checksums=$(checksums_from_zip "$dest/$zipname"); then
        if [[ "$zip_checksums" == "$live_checksums" ]]; then
            echo "  CHECKSUM zip: match"
        else
            echo "  CHECKSUM zip: mismatch"
        fi
    else
        echo "  CHECKSUM zip: SKIPPED (unreadable)"
    fi
done
