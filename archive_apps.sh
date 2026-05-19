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
    _zips=(); while IFS= read -r _l; do _zips+=("$_l"); done < <(find "$dest" -maxdepth 1 -name "*.zip" | sort)
    total=${#_zips[@]}
    width=${#total}
    echo "Verifying $total zip(s)…"
    i=0
    for zip in "${_zips[@]}"; do
        i=$(( i + 1 ))
        printf -v idx '%0*d' "$width" "$i"
        zipname=$(basename "$zip")
        checksumfile="${zip%.zip}.checksums.txt"
        echo "VERIFY $idx/$total: $zipname"

        tmpcheck=$(mktemp -d)
        if ! cp "$zip" "$tmpcheck/archive.zip" 2>/dev/null; then
            rm -rf "$tmpcheck"
            echo "  SKIPPED ⚠️: not readable (possibly not synced locally)"
            continue
        fi
        ditto -x -k "$tmpcheck/archive.zip" "$tmpcheck"
        rm -f "$tmpcheck/archive.zip"
        zipapp=$(find "$tmpcheck" -maxdepth 1 -name "*.app" -type d | head -1)
        app_size=$(du -sh "$zipapp" | cut -f1)
        actual=$(find "$zipapp" -type f -print0 | sort -z | xargs -0 shasum -a 256 | sed "s|$zipapp/||")
        rm -rf "$tmpcheck"
        zip_size=$(du -sh "$zip" | cut -f1)

        echo "  EXTRACTED: done"
        echo "  zip: $zip_size"
        echo "  app: $app_size"

        if [[ -f "$checksumfile" ]]; then
            if [[ "$(cat "$checksumfile")" == "$actual" ]]; then
                echo "  VERIFIED ✅: checksum still matches expanded app"
            else
                echo "  FAILED ❌: checksum differs"
            fi
        else
            echo "  CHECKSUM: missing, creating…"
            printf '%s\n' "$actual" > "${checksumfile}.tmp"
            mv "${checksumfile}.tmp" "$checksumfile"
            echo "  CHECKSUM: written"
        fi
    done
fi

_apps=(); while IFS= read -r _l; do _apps+=("$_l"); done < <(find /Applications -maxdepth 2 -name "*.app" -type d)
total=${#_apps[@]}
width=${#total}
echo "Checking $total app(s)…"
i=0
for app in "${_apps[@]}"; do
    i=$(( i + 1 ))
    printf -v idx '%0*d' "$width" "$i"

    plist="$app/Contents/Info.plist"
    mobile=""
    if [[ ! -f "$plist" ]]; then
        plist="$app/WrappedBundle/Info.plist"
        mobile="mobile@"
    fi
    if [[ ! -f "$plist" ]]; then
        echo "ARCHIVING $idx/$total: $app"
        echo "  app: $(du -sh "$app" | cut -f1)"
        echo "  SKIPPING ⚠️: no Info.plist"
        continue
    fi

    name=$(/usr/libexec/PlistBuddy -c "Print :CFBundleName" "$plist" 2>/dev/null) \
        || name=$(basename "$app" .app)
    version=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$plist" 2>/dev/null) \
        || version="unknown"

    zipname="${name}.app@${mobile}${version}.zip"
    checksumname="${name}.app@${mobile}${version}.checksums.txt"
    echo "ARCHIVING $idx/$total: $zipname"

    if [[ -f "$dest/$zipname" ]]; then
        echo "  ARCHIVE: found"

        if [[ -f "$dest/$checksumname" ]]; then
            echo "  CHECKSUM: found"
            echo "  app: $(du -sh "$app" | cut -f1)"
            echo "  zip: $(du -sh "$dest/$zipname" | cut -f1)"
            live_checksums=$(find "$app" -type f -print0 | sort -z | xargs -0 shasum -a 256 | sed "s|$app/||")
            if [[ "$(cat "$dest/$checksumname")" == "$live_checksums" ]]; then
                echo "  VERIFIED ✅: archived checksum matches current app"
            else
                echo "  MISMATCH ❌: archived checksum does not match current app"
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
        else
            echo "  CHECKSUM: missing, creating…"
            tmpcheck=$(mktemp -d)
            if ! cp "$dest/$zipname" "$tmpcheck/archive.zip" 2>/dev/null; then
                echo "  SKIPPED ⚠️: zip not readable; possibly not synced locally"
                rm -rf "$tmpcheck"
                continue
            fi
            ditto -x -k "$tmpcheck/archive.zip" "$tmpcheck"
            rm -f "$tmpcheck/archive.zip"
            zipapp=$(find "$tmpcheck" -maxdepth 1 -name "*.app" -type d | head -1)
            zip_checksums=$(find "$zipapp" -type f -print0 | sort -z | xargs -0 shasum -a 256 | sed "s|$zipapp/||")
            live_checksums=$(find "$app" -type f -print0 | sort -z | xargs -0 shasum -a 256 | sed "s|$app/||")
            echo "  app: $(du -sh "$app" | cut -f1)"
            echo "  zip: $(du -sh "$dest/$zipname" | cut -f1)"
            if [[ "$zip_checksums" == "$live_checksums" ]]; then
                rm -rf "$tmpcheck"
                echo "$zip_checksums" > "$dest/$checksumname.tmp"
                mv "$dest/$checksumname.tmp" "$dest/$checksumname"
                echo "  CHECKSUM: written"
                echo "  VERIFIED ✅: zip checksum matches current app"
            else
                zip_size_unc=$(du -sh "$zipapp" | cut -f1)
                rm -rf "$tmpcheck"
                echo "  zip (uncompressed): $zip_size_unc"
                echo "  MISMATCH ❌: zip checksum does not match current app"
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

    echo "  ARCHIVE: missing"
    echo "  app: $(du -sh "$app" | cut -f1)"
    live_checksums=$(find "$app" -type f -print0 | sort -z | xargs -0 shasum -a 256 | sed "s|$app/||")
    versioned="${name} ${version}.app"
    tmpdir=$(mktemp -d "$dest/.archive_apps.XXXXXX")
    cp "${cp_flags[@]}" "$app" "$tmpdir/$versioned"
    (cd "$tmpdir" && ditto -c -k --sequesterRsrc --keepParent "$versioned" "$dest/$zipname.tmp")
    rm -rf "$tmpdir"
    mv "$dest/$zipname.tmp" "$dest/$zipname"
    echo "  ZIP+HASH: created"
    echo "  zip: $(du -sh "$dest/$zipname" | cut -f1)"
    echo "$live_checksums" > "$dest/$checksumname.tmp"
    mv "$dest/$checksumname.tmp" "$dest/$checksumname"
    echo "  CHECKSUM: written"

    if zip_checksums=$(checksums_from_zip "$dest/$zipname"); then
        if [[ "$zip_checksums" == "$live_checksums" ]]; then
            echo "  CREATED ✅: archived checksum matches app"
        else
            echo "  MISMATCH ❌: archived checksum does not match original app"
        fi
    else
        echo "  SKIPPED ⚠️: zip not readable for post-archive verification"
    fi
done
