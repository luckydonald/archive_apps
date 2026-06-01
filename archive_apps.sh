#!/bin/bash
set -euo pipefail

verify_mode="none"
dest_arg=""

for arg in "$@"; do
    case "$arg" in
        -h|--help)
            echo "Usage: $(basename "$0") [options] [destination]"
            echo "  --verify-zips     extract and verify all zips against their checksum files"
            echo "  --verify-new      verify only zips/checksums not yet in the checksum index"
            echo "  --verify-changed  verify zips whose index hash differs from current file"
            echo "  destination       archive directory (default: /Users/Shared/App Versions)"
            exit 0 ;;
        --verify-zips)    verify_mode="zips" ;;
        --verify-new)     verify_mode="new" ;;
        --verify-changed) verify_mode="changed" ;;
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

_preserve_tmps=()

cleanup() {
    rm -f "$dest"/*.zip.tmp
    for _cf in "$dest"/*.checksums.txt.tmp; do
        [[ -f "$_cf" ]] || continue
        local _skip=0
        for _pf in "${_preserve_tmps[@]+"${_preserve_tmps[@]}"}"; do
            [[ "$_cf" == "$_pf" ]] && _skip=1 && break
        done
        [[ $_skip -eq 1 ]] || rm -f "$_cf"
    done
    if [[ -f "$dest/_checksum_index_.txt.tmp" ]]; then
        sort -k2 "$dest/_checksum_index_.txt.tmp" > "$dest/_checksum_index_.txt" 2>/dev/null || true
        rm -f "$dest/_checksum_index_.txt.tmp"
    fi
    for _td in "$dest"/.archive_apps.*; do
        [[ -d "$_td" ]] && rm -rfi "$_td"
    done
}
trap cleanup EXIT

rm_retry() {
    local dir="$1" attempt
    for attempt in 1 2 3 4 5; do
        rm -rf "$dir" && return 0
        sleep 1
    done
    echo "ERROR: failed to remove $dir after 5 attempts" >&2
    exit 1
}

_progress_bar_filter() {
    local label="$1" total="$2"
    awk -v total="$total" -v label="$label" '
        BEGIN { step = int(total/200); if (step < 1) step = 1 }
        { n++
          if (n % step == 0 || n == total) {
            pct    = int(n * 100 / total)
            filled = int(n * 40  / total)
            bar    = ""; for (i=0; i<filled; i++) bar = bar "="
            if (filled < 40) bar = bar ">"
            while (length(bar) < 40) bar = bar " "
            printf "\r  %s [%s] %d/%d (%d%%)", label, bar, n, total, pct > "/dev/stderr"
            fflush("/dev/stderr")
          }
        }
        END { printf "\r\033[K" > "/dev/stderr"; fflush("/dev/stderr") }
    '
}

_shuffle_array() {
    local _arr_name="$1"
    local i j tmp_i tmp_j len
    eval "len=\${#${_arr_name}[@]}"
    for ((i=len-1; i>0; i--)); do
        j=$(( RANDOM % (i + 1) ))
        eval "tmp_i=\${${_arr_name}[i]}"
        eval "tmp_j=\${${_arr_name}[j]}"
        eval "${_arr_name}[i]=\$tmp_j"
        eval "${_arr_name}[j]=\$tmp_i"
    done
}

_archive_app_to_zip() {
    local app="$1" versioned="$2" dest_zip="$3"
    local tmpdir total use_bar=0
    tmpdir=$(mktemp -d "$(dirname "$dest_zip")/.archive_apps.XXXXXX")
    total=$(find "$app" -not -type d | wc -l | tr -d ' ')
    [[ -t 2 && $total -gt 0 ]] && use_bar=1

    if [[ $use_bar -eq 1 && "${cp_flags[*]}" != *c* ]]; then
        { ditto -V "$app" "$tmpdir/$versioned"; } 2>&1 | _progress_bar_filter "COPY" "$total"
    else
        cp "${cp_flags[@]}" "$app" "$tmpdir/$versioned"
    fi

    if [[ $use_bar -eq 1 ]]; then
        { (cd "$tmpdir" && ditto -V -c -k --sequesterRsrc --keepParent "$versioned" "$dest_zip"); } 2>&1 | \
            _progress_bar_filter "ZIP " "$total"
    else
        (cd "$tmpdir" && ditto -c -k --sequesterRsrc --keepParent "$versioned" "$dest_zip")
    fi

    rm_retry "$tmpdir"
}

_WFAIL_DST=""

_tty_read() {
    local __var="$1" __default="${2:-}"
    { read -r "$__var" < /dev/tty; } 2>/dev/null || printf -v "$__var" '%s' "$__default"
}

_write_fail_menu() {
    local desc="$1" content_or_src="$2" orig_dst="$3" mode="$4"
    local cur_dst="$orig_dst" has_alternate=0 choice confirm tmp_fallback
    tmp_fallback="/tmp/$(basename "$orig_dst")"
    while true; do
        echo "  WRITE ERROR: $desc" >&2
        echo "  [a] retry (default)" >&2
        [[ $has_alternate -eq 1 ]] && echo " [a'] retry original path ($orig_dst)" >&2
        echo "  [b] save somewhere else" >&2
        echo "  [c] skip (try /tmp, else print)" >&2
        echo "  [d] exit" >&2
        printf "  Choice [a]: " >&2
        _tty_read choice "c"
        choice="${choice:-a}"
        case "$choice" in
            a)
                _WFAIL_DST="$cur_dst"; return 0 ;;
            "a'")
                [[ $has_alternate -eq 1 ]] || continue
                cur_dst="$orig_dst"; has_alternate=0
                _WFAIL_DST="$cur_dst"; return 0 ;;
            b)
                printf "  New path: " >&2
                _tty_read cur_dst ""
                has_alternate=1; _WFAIL_DST="$cur_dst"; return 0 ;;
            c|d)
                case "$mode" in
                    append)
                        if printf '%s\n' "$content_or_src" >> "$tmp_fallback" 2>/dev/null; then
                            echo "  SAVED ⚠️: $tmp_fallback" >&2
                        else
                            printf '%s\n' "$content_or_src"
                        fi ;;
                    write)
                        if printf '%s\n' "$content_or_src" > "$tmp_fallback" 2>/dev/null; then
                            echo "  SAVED ⚠️: $tmp_fallback" >&2
                        else
                            printf '%s\n' "$content_or_src"
                        fi ;;
                    mv)
                        if mv "$content_or_src" "$tmp_fallback" 2>/dev/null; then
                            echo "  SAVED ⚠️: $tmp_fallback" >&2
                        else
                            cat "$content_or_src" 2>/dev/null || true
                            _preserve_tmps+=("$content_or_src")
                        fi ;;
                esac
                if [[ "$choice" == "d" ]]; then
                    printf "  Type 'sure' to confirm exit: " >&2
                    _tty_read confirm ""
                    [[ "$confirm" == "sure" ]] && exit 1
                    continue
                fi
                return 1 ;;
        esac
    done
}

safe_append() {
    local line="$1" file="$2" target last rc
    _WFAIL_DST="$file"
    while true; do
        target="$_WFAIL_DST"
        if printf '%s\n' "$line" >> "$target" 2>/dev/null; then
            last=$(tail -1 "$target" 2>/dev/null)
            [[ "$last" == "$line" ]] && return 0
            echo "  WARN: readback mismatch (append $target)" >&2
        fi
        _write_fail_menu "append to $(basename "$file")" "$line" "$file" "append"
        rc=$?; [[ $rc -eq 0 ]] || return $(( rc - 1 ))
    done
}

safe_write() {
    local content="$1" file="$2" target last_exp last_act rc
    _WFAIL_DST="$file"
    last_exp=$(printf '%s\n' "$content" | tail -1)
    while true; do
        target="$_WFAIL_DST"
        if printf '%s\n' "$content" > "$target" 2>/dev/null; then
            last_act=$(tail -1 "$target" 2>/dev/null)
            [[ "$last_act" == "$last_exp" ]] && return 0
            echo "  WARN: readback mismatch (write $target)" >&2
        fi
        _write_fail_menu "write $(basename "$file")" "$content" "$file" "write"
        rc=$?; [[ $rc -eq 0 ]] || return $(( rc - 1 ))
    done
}

safe_mv() {
    local src="$1" dst="$2" target expected actual rc
    expected=$(wc -l < "$src" 2>/dev/null | tr -d ' ')
    _WFAIL_DST="$dst"
    while true; do
        target="$_WFAIL_DST"
        if mv "$src" "$target" 2>/dev/null; then
            actual=$(wc -l < "$target" 2>/dev/null | tr -d ' ')
            if [[ -f "$target" && "$actual" -eq "$expected" ]]; then
                return 0
            fi
            echo "  WARN: readback mismatch after mv to $target" >&2
            return 0
        fi
        _write_fail_menu "write $(basename "$dst")" "$src" "$dst" "mv"
        rc=$?; [[ $rc -eq 0 ]] || return $(( rc - 1 ))
    done
}

# Called when checksums_from_zip exits 2 (some entries unreadable).
# Prompts the user; returns 0 to continue processing the zip, 1 to skip it.
_unreadable_prompt() {
    local zip="$1" n="$2"
    echo "  PARTIAL ⚠️: $n entries could not be read"
    printf "  [a]ignore / [b]stop / [c]rename to .bak.zip / [d]delete: "
    _tty_read _up_ans "a"
    case "${_up_ans:-a}" in
        b|B) exit 1 ;;
        c|C)
            local _bak="${zip%.zip}.$(date +%Y-%m-%d_%H-%M-%S).bak.zip"
            if mv "$zip" "$_bak"; then
                echo "  RENAMED: $(basename "$_bak")"
                return 1
            fi
            echo "  RENAME FAILED; ignoring"
            return 0
            ;;
        d|D)
            if rm -f "$zip"; then
                echo "  DELETED: $(basename "$zip")"
                return 1
            fi
            echo "  DELETE FAILED; ignoring"
            return 0
            ;;
        *) echo "  IGNORING: proceeding with partial checksums" ;;
    esac
}

# Stream zip entries through Python's zipfile module, hash each in RAM, print
# per-file SHA256 checksums relative to the .app root.  Writes zero bytes.
# Returns 0 OK, 1 unreadable/corrupt, 2 partial (some entries could not be read).
checksums_from_zip() {
    local zip="$1"
    if ! head -c 4 "$zip" > /dev/null 2>/dev/null; then
        return 1
    fi
    python3 - "$zip" <<'PYEOF'
import sys, zipfile, hashlib, locale, subprocess, struct, zlib as _zlib, os

zpath = sys.argv[1]

def _find_zip64_offset(fp, info):
    # Python bug: when only header_offset needs ZIP64 (file/compress sizes < 4 GB),
    # Python misassigns the 8-byte ZIP64 offset field to file_size and leaves
    # header_offset at the sentinel 0xFFFFFFFF.  The true offset is still in
    # info.extra — scan it for any value > 4 GB that has PK\x03\x04 there.
    extra = info.extra or b''
    i = 0
    while i + 4 <= len(extra):
        tag, size = struct.unpack_from('<HH', extra, i)
        i += 4
        if tag == 0x0001:  # ZIP64 extended information
            n = (min(size, len(extra) - i) // 8) * 8
            for j in range(0, n, 8):
                v = struct.unpack_from('<Q', extra, i + j)[0]
                if v > 0xFFFFFFFF:
                    try:
                        fp.seek(v)
                        if fp.read(4) == b'PK\x03\x04':
                            return v
                    except Exception:
                        pass
        i += size
    return None

def _hash_at_offset(fp, info, header_offset):
    # Read fname_len and extra_len from local header (offsets 26 and 28).
    fp.seek(header_offset + 26)
    fname_len, extra_len = struct.unpack('<HH', fp.read(4))
    fp.seek(header_offset + 30 + fname_len + extra_len)
    sha = hashlib.sha256()
    remaining = info.compress_size
    if info.compress_type == 0:  # stored
        while remaining > 0:
            chunk = fp.read(min(65536, remaining))
            if not chunk:
                return None
            sha.update(chunk)
            remaining -= len(chunk)
    elif info.compress_type == 8:  # deflate
        d = _zlib.decompressobj(-15)
        while remaining > 0:
            chunk = fp.read(min(65536, remaining))
            if not chunk:
                return None
            sha.update(d.decompress(chunk))
            remaining -= len(chunk)
        sha.update(d.flush())
    else:
        return None
    return sha.hexdigest()

def _hash_via_unzip(entry_name):
    # Last-resort fallback: stream via unzip -p (handles other zip quirks).
    proc = subprocess.Popen(
        ['unzip', '-p', zpath, entry_name],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    sha = hashlib.sha256()
    while True:
        chunk = proc.stdout.read(65536)
        if not chunk:
            break
        sha.update(chunk)
    proc.stdout.close()
    proc.wait()
    return sha.hexdigest() if proc.returncode == 0 else None

try:
    with zipfile.ZipFile(zpath) as z:
        app_prefix = None
        for name in z.namelist():
            parts = name.split('/')
            if not name.endswith('/') and '__MACOSX' not in name \
               and len(parts) > 1 and parts[0].endswith('.app'):
                app_prefix = parts[0] + '/'
                break
        if app_prefix is None:
            sys.exit(1)
        entries = [info for info in z.infolist()
                   if not info.filename.endswith('/')
                   and '__MACOSX' not in info.filename
                   and info.filename.startswith(app_prefix)]
        _total = len(entries)
        _tty   = os.isatty(sys.stderr.fileno())
        _step  = max(1, _total // 200)
        def _bar(i):
            pct    = i * 100 // _total if _total else 100
            filled = i * 40  // _total if _total else 40
            b = '=' * filled + ('>' if filled < 40 else '') + ' ' * (39 - filled)
            sys.stderr.write(f'\r  [{b}] {i}/{_total} ({pct}%)')
            sys.stderr.flush()
        results    = []
        unreadable = []
        for _i, info in enumerate(entries, 1):
            name = info.filename
            rel  = name[len(app_prefix):]
            try:
                sha = hashlib.sha256()
                with z.open(info) as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        sha.update(chunk)
                results.append(sha.hexdigest() + '  ' + rel)
            except Exception:
                h = None
                true_offset = _find_zip64_offset(z.fp, info)
                if true_offset is not None:
                    try:
                        h = _hash_at_offset(z.fp, info, true_offset)
                    except Exception:
                        pass
                if h is None:
                    h = _hash_via_unzip(name)
                if h is not None:
                    results.append(h + '  ' + rel)
                else:
                    unreadable.append(rel)
                    results.append('(unreadable)  ' + rel)
            if _tty and (_i % _step == 0 or _i == _total):
                _bar(_i)
        if _tty:
            sys.stderr.write('\r\033[K')
            sys.stderr.flush()
        locale.setlocale(locale.LC_ALL, '')
        results.sort(key=lambda x: locale.strxfrm(x.split('  ', 1)[1]))
        print('\n'.join(results))
        if unreadable:
            print(str(len(unreadable)) + ' entries could not be read', file=sys.stderr)
            sys.exit(2)
except Exception as e:
    print('Error: ' + str(e), file=sys.stderr)
    sys.exit(1)
PYEOF
}

if [[ "$verify_mode" != "none" ]]; then
    index_file="$dest/_checksum_index_.txt"
    index_tmp="$dest/_checksum_index_.txt.tmp"

    if [[ -f "$index_tmp" ]]; then
        echo "RECOVERY: Found leftover temp file: $(basename "$index_tmp")"
        printf "  Restore it? [Y/n]: "
        _tty_read _rc_ans "n"
        if [[ ! "${_rc_ans:-y}" =~ ^[Nn]$ ]]; then
            _rc_live_lines=0
            [[ -f "$index_file" ]] && _rc_live_lines=$(wc -l < "$index_file" | tr -d ' ')
            printf "  Existing file: $_rc_live_lines lines. Merge? [Y/n]: "
            _tty_read _rc_ans "n"
            if [[ ! "${_rc_ans:-y}" =~ ^[Nn]$ ]]; then
                _rc_tmp_lines=$(wc -l < "$index_tmp" | tr -d ' ')
                if [[ $_rc_live_lines -gt 0 ]]; then
                    _rc_merged=$(sort -u "$index_tmp" "$index_file" 2>/dev/null)
                else
                    _rc_merged=$(sort -u "$index_tmp" 2>/dev/null)
                fi
                if [[ -z "$_rc_merged" ]]; then
                    _rc_merged_lines=0
                else
                    _rc_merged_lines=$(printf '%s\n' "$_rc_merged" | wc -l | tr -d ' ')
                fi
                _rc_dup_lines=$(( _rc_tmp_lines + _rc_live_lines - _rc_merged_lines ))
                echo "  Temporary file: $_rc_tmp_lines lines"
                echo "  Existing file:  $_rc_live_lines lines"
                echo "  Merge duplicates: $_rc_dup_lines lines"
                echo "  Resulting file: $_rc_merged_lines lines"
                printf "  Continue? [Y/n]: "
                _tty_read _rc_ans "n"
                if [[ ! "${_rc_ans:-y}" =~ ^[Nn]$ ]]; then
                    _rc_merged_tmp=$(mktemp "$dest/_checksum_index_.XXXXXX.tmp")
                    printf '%s\n' "$_rc_merged" > "$_rc_merged_tmp"
                    safe_mv "$_rc_merged_tmp" "$index_file"
                    echo "  RECOVERY ✅: merged and written"
                    printf "  Delete temp file? [Y/n]: "
                    _tty_read _rc_ans "n"
                    if [[ ! "${_rc_ans:-y}" =~ ^[Nn]$ ]]; then
                        rm -f "$index_tmp"
                        echo "  RECOVERY: temp file deleted"
                    fi
                fi
            fi
        fi
    fi

    if ! : > "$index_tmp" 2>/dev/null; then
        echo "ERROR: cannot create index file at $index_tmp — check that $(dirname "$index_tmp") is writable" >&2
        exit 1
    fi

    _zips=(); while IFS= read -r _l; do _zips+=("$_l"); done < <(find "$dest" -maxdepth 1 -name "*.zip" | sort)
    total=${#_zips[@]}
    width=${#total}
    echo "Verifying $total zip(s) [--verify-$verify_mode]…"
    i=0
    for zip in "${_zips[@]+"${_zips[@]}"}"; do
        i=$(( i + 1 ))
        printf -v idx '%0*d' "$width" "$i"
        zipname=$(basename "$zip")
        checksumfile="${zip%.zip}.checksums.txt"
        checksumname=$(basename "$checksumfile")
        echo "VERIFY $idx/$total: $zipname"

        # Look up stored hashes using grep -F so spaces in filenames are handled correctly
        current_zip_hash="" zip_stored="" cs_stored=""
        if [[ "$verify_mode" != "zips" && -f "$index_file" ]]; then
            zip_stored=$(grep -F "  $zipname"      "$index_file" 2>/dev/null | awk '{print $1}') || true
            cs_stored=$(grep -F "  $checksumname"  "$index_file" 2>/dev/null | awk '{print $1}') || true
        fi

        if [[ "$verify_mode" == "new" ]]; then
            [[ -n "$zip_stored" ]] && echo "  zip: $zip_stored" || echo "  CACHE-MISS 🔸: zip"
            [[ -n "$cs_stored"  ]] && echo "  app: $cs_stored"  || echo "  CACHE-MISS 🔸: app"
            if [[ -n "$zip_stored" && -n "$cs_stored" ]]; then
                echo "  INDEXED ✅: already verified"
                safe_append "$zip_stored  $zipname"     "$index_tmp"
                safe_append "$cs_stored  $checksumname" "$index_tmp"
                continue
            fi

        elif [[ "$verify_mode" == "changed" ]]; then
            current_zip_hash=$(shasum -a 256 "$zip" 2>/dev/null | awk '{print $1}')
            [[ -n "$current_zip_hash" ]] && echo "  zip: $current_zip_hash" || echo "  CACHE-MISS 🔸: zip"
            [[ -n "$zip_stored" && "$current_zip_hash" != "$zip_stored" ]] && echo "  CHANGED 🔸: zip"
            cs_current=""
            if [[ -f "$checksumfile" ]]; then
                cs_current=$(shasum -a 256 "$checksumfile" 2>/dev/null | awk '{print $1}')
                [[ -n "$cs_current" ]] && echo "  app: $cs_current" || echo "  CACHE-MISS 🔸: app"
                [[ -n "$cs_stored" && "$cs_current" != "$cs_stored" ]] && echo "  CHANGED 🔸: app"
            else
                echo "  CACHE-MISS 🔸: app"
            fi
            if [[ -n "$current_zip_hash" && "$current_zip_hash" == "$zip_stored" && \
                  -n "$cs_current" && "$cs_current" == "$cs_stored" ]]; then
                echo "  UNCHANGED ✅: hash matches index"
                safe_append "$current_zip_hash  $zipname"  "$index_tmp"
                safe_append "$cs_current  $checksumname"   "$index_tmp"
                continue
            fi
        fi

        zip_size=$(du -sh "$zip" | cut -f1)
        echo "  zip: $zip_size"
        _czrc=0; actual=$(checksums_from_zip "$zip") || _czrc=$?
        if [[ $_czrc -eq 1 ]]; then
            echo "  SKIPPED ⚠️: zip not readable or corrupt"
            continue
        elif [[ $_czrc -eq 2 ]]; then
            _n=$(printf '%s\n' "$actual" | grep -c '^(unreadable)  ' || true)
            if ! _unreadable_prompt "$zip" "$_n"; then continue; fi
        fi

        if [[ -f "$checksumfile" ]]; then
            if [[ "$(cat "$checksumfile")" == "$actual" ]]; then
                echo "  VERIFIED ✅: checksum still matches expanded app"
            else
                echo "  FAILED ❌: checksum differs"
            fi
        else
            echo "  CHECKSUM: missing, creating…"
            safe_write "$actual" "${checksumfile}.tmp"
            safe_mv "${checksumfile}.tmp" "$checksumfile"
            echo "  CHECKSUM: written"
        fi

        # Add/fix index entries for this zip and its checksums file
        [[ -z "$current_zip_hash" ]] && current_zip_hash=$(shasum -a 256 "$zip" | awk '{print $1}')
        safe_append "$current_zip_hash  $zipname" "$index_tmp"
        if [[ -f "$checksumfile" ]]; then
            cs_hash=$(shasum -a 256 "$checksumfile" | awk '{print $1}')
            safe_append "$cs_hash  $checksumname" "$index_tmp"
        fi
    done

    sort -k2 "$index_tmp" -o "$index_tmp" 2>/dev/null || \
        echo "  WARN: sort of index failed; writing unsorted" >&2
    safe_mv "$index_tmp" "$index_file"
    echo "INDEX: written → $(basename "$index_file")"
fi

_apps=(); while IFS= read -r _l; do _apps+=("$_l"); done < <(find /Applications -maxdepth 2 -name "*.app" -type d)
_shuffle_array _apps
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
                _tty_read choice "s"
                case "$choice" in
                    o|O)
                        rm -f "$dest/$zipname"
                        versioned="${name} ${version}.app"
                        _archive_app_to_zip "$app" "$versioned" "$dest/$zipname.tmp"
                        mv "$dest/$zipname.tmp" "$dest/$zipname"
                        safe_write "$live_checksums" "$dest/$checksumname.tmp"
                        safe_mv "$dest/$checksumname.tmp" "$dest/$checksumname"
                        ;;
                    b|B)
                        suffix=$(date +%Y%m%d_%H%M%S)
                        newzip="${name}.app@${mobile}${version}~${suffix}.zip"
                        newcheck="${name}.app@${mobile}${version}~${suffix}.checksums.txt"
                        versioned="${name} ${version}.app"
                        _archive_app_to_zip "$app" "$versioned" "$dest/$newzip.tmp"
                        mv "$dest/$newzip.tmp" "$dest/$newzip"
                        safe_write "$live_checksums" "$dest/$newcheck.tmp"
                        safe_mv "$dest/$newcheck.tmp" "$dest/$newcheck"
                        ;;
                    *)
                        echo "  SKIPPED"
                        ;;
                esac
            fi
        else
            echo "  CHECKSUM: missing, creating…"
            echo "  zip: $(du -sh "$dest/$zipname" | cut -f1)"
            _czrc=0; zip_checksums=$(checksums_from_zip "$dest/$zipname") || _czrc=$?
            if [[ $_czrc -eq 1 ]]; then
                echo "  SKIPPED ⚠️: zip not readable or corrupt"
                continue
            elif [[ $_czrc -eq 2 ]]; then
                _n=$(printf '%s\n' "$zip_checksums" | grep -c '^(unreadable)  ' || true)
                if ! _unreadable_prompt "$dest/$zipname" "$_n"; then continue; fi
            fi
            live_checksums=$(find "$app" -type f -print0 | sort -z | xargs -0 shasum -a 256 | sed "s|$app/||")
            echo "  app: $(du -sh "$app" | cut -f1)"
            if [[ "$zip_checksums" == "$live_checksums" ]]; then
                safe_write "$zip_checksums" "$dest/$checksumname.tmp"
                safe_mv "$dest/$checksumname.tmp" "$dest/$checksumname"
                echo "  CHECKSUM: written"
                echo "  VERIFIED ✅: zip checksum matches current app"
            else
                echo "  MISMATCH ❌: zip checksum does not match current app"
                printf "  [o]verwrite zip / [b]oth / [s]kip: "
                _tty_read choice "s"
                case "$choice" in
                    o|O)
                        rm -f "$dest/$zipname"
                        versioned="${name} ${version}.app"
                        _archive_app_to_zip "$app" "$versioned" "$dest/$zipname.tmp"
                        mv "$dest/$zipname.tmp" "$dest/$zipname"
                        safe_write "$live_checksums" "$dest/$checksumname.tmp"
                        safe_mv "$dest/$checksumname.tmp" "$dest/$checksumname"
                        ;;
                    b|B)
                        safe_write "$zip_checksums" "$dest/$checksumname.tmp"
                        safe_mv "$dest/$checksumname.tmp" "$dest/$checksumname"
                        suffix=$(date +%Y%m%d_%H%M%S)
                        newzip="${name}.app@${mobile}${version}~${suffix}.zip"
                        newcheck="${name}.app@${mobile}${version}~${suffix}.checksums.txt"
                        versioned="${name} ${version}.app"
                        _archive_app_to_zip "$app" "$versioned" "$dest/$newzip.tmp"
                        mv "$dest/$newzip.tmp" "$dest/$newzip"
                        safe_write "$live_checksums" "$dest/$newcheck.tmp"
                        safe_mv "$dest/$newcheck.tmp" "$dest/$newcheck"
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
    _archive_app_to_zip "$app" "$versioned" "$dest/$zipname.tmp"
    mv "$dest/$zipname.tmp" "$dest/$zipname"
    echo "  ZIP+HASH: created"
    echo "  zip: $(du -sh "$dest/$zipname" | cut -f1)"
    safe_write "$live_checksums" "$dest/$checksumname.tmp"
    safe_mv "$dest/$checksumname.tmp" "$dest/$checksumname"
    echo "  CHECKSUM: written for app"

    echo "  CHECKSUM: verifying zip..."
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
