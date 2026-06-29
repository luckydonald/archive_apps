#!/bin/bash
set -euo pipefail

verify_mode="none"
verify_zip_arg=""
dest_arg=""
local_cache_arg="__unset__"
external_symlink_policy="archive"
external_symlink_summary=()
verify_abort=0
verify_failure_summary=()
keep_temp=0

for arg in "$@"; do
    case "$arg" in
        -h|--help)
            echo "Usage: $(basename "$0") [options] [destination]"
            echo "  --verify-zip=APP  verify zip(s) for a specific app or exact zip file"
            echo "                    APP forms: Xcode / Xcode.app / /Applications/Xcode.app"
            echo "                              Xcode.app@15.4.zip / full/path/to/Foo.zip"
            echo "                    matches all version zips for that app; exits after verifying"
            echo "  --verify-zips     extract and verify all zips against their checksum files"
            echo "  --verify-new      verify only zips/checksums not yet in the checksum index"
            echo "  --verify-changed  verify zips whose index hash differs from current file"
            echo "  --verify-abort    stop immediately on the first verification failure"
            echo "  --keep-temp       preserve temp workdirs and leftover .tmp files for reuse"
            echo "  --local-cache[=path]"
            echo "                    stage new zips on local disk, then move to destination;"
            echo "                    local temp is deleted after transfer (no copy retained)"
            echo "                    path defaults to /Users/Shared/App Versions"
            echo "                    magic values: default (same as omitting path), none (disable)"
            echo "  --external-symlink-policy=archive|skip|abort"
            echo "                    handling for symlinks that resolve outside the app bundle"
            echo "                    default: archive, with an end-of-run warning summary"
            echo "  destination       archive directory (default: /Users/Shared/App Versions)"
            exit 0 ;;
        --verify-zip)
            echo "Error: --verify-zip requires a value: --verify-zip=APP" >&2; exit 1 ;;
        --verify-zip=*)   verify_zip_arg="${arg#*=}" ;;
        --verify-zips)    verify_mode="zips" ;;
        --verify-new)     verify_mode="new" ;;
        --verify-changed) verify_mode="changed" ;;
        --verify-abort)   verify_abort=1 ;;
        --keep-temp)      keep_temp=1 ;;
        --local-cache)              local_cache_arg="/Users/Shared/App Versions" ;;
        --local-cache=|--local-cache=default) local_cache_arg="/Users/Shared/App Versions" ;;
        --local-cache=none)         local_cache_arg="" ;;
        --local-cache=*)            local_cache_arg="${arg#*=}" ;;
        --external-symlink-policy=archive|skip|abort)
            external_symlink_policy="${arg#*=}" ;;
        -*)
            echo "Unknown option: $arg" >&2; exit 1 ;;
        *)
            dest_arg="$arg" ;;
    esac
done

dest="${dest_arg:-/Users/Shared/App Versions}"
mkdir -p "$dest"
dest=$(cd "$dest" && pwd)

local_cache=""
if [[ "$local_cache_arg" != "__unset__" && -n "$local_cache_arg" ]]; then
    mkdir -p "$local_cache_arg"
    local_cache=$(cd "$local_cache_arg" && pwd)
    if [[ "$local_cache" == "$dest" ]]; then
        echo "Error: --local-cache path must differ from the destination" >&2
        exit 1
    fi
fi

if [[ -n "$verify_zip_arg" && "$verify_mode" != "none" ]]; then
    echo "Error: --verify-zip cannot be combined with --verify-zips/--verify-new/--verify-changed" >&2
    exit 1
fi

if [[ "$(stat -f "%d" "$dest")" == "$(stat -f "%d" /Applications)" ]]; then
    cp_flags=(-cR)
else
    cp_flags=(-R)
fi

_preserve_tmps=()

cleanup() {
    if [[ -f "$dest/_checksum_index_.txt.tmp" ]]; then
        sort -k2 "$dest/_checksum_index_.txt.tmp" > "$dest/_checksum_index_.txt" 2>/dev/null || true
        [[ $keep_temp -eq 1 ]] || rm -f "$dest/_checksum_index_.txt.tmp"
    fi
    if [[ $keep_temp -eq 1 ]]; then
        return 0
    fi
    rm -f "$dest"/*.zip.tmp
    for _cf in "$dest"/*.checksums.txt.tmp; do
        [[ -f "$_cf" ]] || continue
        local _skip=0
        for _pf in "${_preserve_tmps[@]+"${_preserve_tmps[@]}"}"; do
            [[ "$_cf" == "$_pf" ]] && _skip=1 && break
        done
        [[ $_skip -eq 1 ]] || rm -f "$_cf"
    done
    for _td in "$dest"/.archive_apps.*; do
        [[ -d "$_td" ]] && rm_retry "$_td"
    done
}
trap cleanup EXIT

rm_retry() {
    local dir="$1" attempt total current path use_bar=0 start_ts
    for attempt in 1 2 3 4 5; do
        if [[ ! -e "$dir" ]]; then
            return 0
        fi

        total=$(find "$dir" -depth -print 2>/dev/null | wc -l | tr -d ' ')
        [[ -t 2 && ${total:-0} -gt 0 ]] && use_bar=1 || use_bar=0

        if [[ $use_bar -eq 1 ]]; then
            current=0
            start_ts=$(date +%s)
            while IFS= read -r path; do
                rm -rf "$path"
                current=$(( current + 1 ))
                _render_progress_bar "DELETE" "$current" "$total" "$start_ts"
            done < <(find "$dir" -depth -print 2>/dev/null)
            _clear_progress_bar
            _print_elapsed "DELETE" "$start_ts"
        else
            rm -rf "$dir"
        fi

        [[ ! -e "$dir" ]] && return 0
        sleep 1
    done
    echo "ERROR: failed to remove $dir after 5 attempts" >&2
    exit 1
}

_format_duration() {
    local seconds="$1"
    local hours minutes secs
    if [[ ${seconds:-0} -lt 0 ]]; then
        seconds=0
    fi
    hours=$(( seconds / 3600 ))
    minutes=$(( (seconds % 3600) / 60 ))
    secs=$(( seconds % 60 ))
    if [[ $hours -gt 0 ]]; then
        printf '%d:%02d:%02d' "$hours" "$minutes" "$secs"
    else
        printf '%02d:%02d' "$minutes" "$secs"
    fi
}

_format_eta_target() {
    local now_ts="$1" remaining="$2"
    local target_ts day_offset day_label time_fmt
    if [[ ${remaining:-0} -lt 0 ]]; then
        remaining=0
    fi
    target_ts=$(( now_ts + remaining ))
    day_offset=$(( remaining / 86400 ))
    time_fmt="+%H:%M:%S"
    if [[ $day_offset -gt 0 ]]; then
        time_fmt="+%H:%M"
    fi
    if [[ $day_offset -eq 1 ]]; then
        day_label=" (+1 day)"
    elif [[ $day_offset -gt 1 ]]; then
        day_label=" (+${day_offset} days)"
    else
        day_label=""
    fi
    printf '%s%s' "$(date -r "$target_ts" "$time_fmt")" "$day_label"
}

_render_progress_bar() {
    local label="$1" current="$2" total="$3" start_ts="${4:-0}"
    local pct filled bar i now elapsed remaining eta eta_target
    if [[ ${total:-0} -le 0 ]]; then
        return 0
    fi
    pct=$(( current * 100 / total ))
    filled=$(( current * 40 / total ))
    bar=""
    for ((i=0; i<filled; i++)); do
        bar="${bar}="
    done
    if [[ $filled -lt 40 ]]; then
        bar="${bar}>"
    fi
    while [[ ${#bar} -lt 40 ]]; do
        bar="${bar} "
    done
    eta="--:--"
    eta_target="--:--:--"
    if [[ $start_ts -gt 0 ]]; then
        now=$(date +%s)
        elapsed=$(( now - start_ts ))
        if [[ $current -gt 0 && $elapsed -gt 0 ]]; then
            remaining=$(( (total - current) * elapsed / current ))
            eta=$(_format_duration "$remaining")
            eta_target=$(_format_eta_target "$now" "$remaining")
        elif [[ $current -ge $total ]]; then
            eta="00:00"
            eta_target=$(_format_eta_target "$now" 0)
        fi
    fi
    printf '\r  %s [%s] %d/%d (%d%%, eta %s @ %s)' "$label" "$bar" "$current" "$total" "$pct" "$eta" "$eta_target" > /dev/stderr
}

_clear_progress_bar() {
    printf '\r\033[K' > /dev/stderr
}

_print_elapsed() {
    local label="${1%" "}" start_ts="$2"
    printf '  %s done in %s\n' "$label" "$(_format_duration "$(( $(date +%s) - start_ts ))")" >&2
}

_progress_bar_filter() {
    local label="$1" total="$2"
    local line current=0 step start_ts
    step=$(( total / 200 ))
    [[ $step -lt 1 ]] && step=1
    start_ts=$(date +%s)

    while IFS= read -r line; do
        [[ "$line" == copying\ * ]] || continue
        current=$(( current + 1 ))
        if (( current % step == 0 || current == total )); then
            _render_progress_bar "$label" "$current" "$total" "$start_ts"
        fi
    done

    _clear_progress_bar
    _print_elapsed "$label" "$start_ts"
}

_rsync_progress_bar_filter() {
    local label="$1" total="$2"
    local line checked current=0 start_ts
    start_ts=$(date +%s)

    while IFS= read -r line; do
        if [[ "$line" =~ to-check=([0-9]+)/([0-9]+) ]]; then
            checked="${BASH_REMATCH[1]}"
            current="$checked"
            if [[ $current -gt $total ]]; then
                current="$total"
            fi
            _render_progress_bar "$label" "$current" "$total" "$start_ts"
        fi
    done

    _clear_progress_bar
    _print_elapsed "$label" "$start_ts"
}

_rsync_file_progress_bar_filter() {
    local label="$1"
    local line pct start_ts
    start_ts=$(date +%s)
    while IFS= read -r line; do
        if [[ "$line" =~ ([0-9]+)% ]]; then
            pct="${BASH_REMATCH[1]}"
            _render_progress_bar "$label" "$pct" 100 "$start_ts"
        fi
    done
    _clear_progress_bar
    _print_elapsed "$label" "$start_ts"
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

_sanitize_temp_component() {
    local value="$1"
    value=$(printf '%s' "$value" | tr -cs '[:alnum:].@_-' '_')
    value=${value#_}
    value=${value%_}
    printf '%s' "${value:-app}"
}

_archive_workdir_path() {
    local archive_stem="$1" manifest_hash="$2"
    local safe_stem
    safe_stem=$(_sanitize_temp_component "$archive_stem")
    printf '%s/.archive_apps.%s.%s' "${local_cache:-$dest}" "$safe_stem" "$manifest_hash"
}

_copy_archive_app_fresh() {
    local app="$1" workapp="$2"
    local total use_bar=0

    total=$(find "$app" -not -type d | wc -l | tr -d ' ')
    [[ -t 2 && $total -gt 0 ]] && use_bar=1

    if [[ $use_bar -eq 1 && "${cp_flags[*]}" != *c* ]]; then
        { ditto -V "$app" "$workapp"; } 2>&1 | _progress_bar_filter "COPY" "$total"
    else
        cp "${cp_flags[@]}" "$app" "$workapp"
    fi
}

_repair_archive_app_copy() {
    local app="$1" workapp="$2"
    local total use_bar=0

    total=$(find "$app" -not -type d | wc -l | tr -d ' ')
    [[ -t 2 && $total -gt 0 ]] && use_bar=1

    if [[ $use_bar -eq 1 ]]; then
        rsync -a --delete --extended-attributes --progress "$app/" "$workapp/" 2>&1 | tr '\r' '\n' | \
            _rsync_progress_bar_filter "COPY" "$total"
    else
        rsync -a --delete --extended-attributes "$app/" "$workapp/"
    fi
}

_ensure_archive_copy() {
    local app="$1" versioned="$2" workdir="$3"
    local workapp="$workdir/$versioned"

    mkdir -p "$workdir"

    if [[ -e "$workapp" && ! -d "$workapp" ]]; then
        rm_retry "$workapp"
    fi

    if [[ -d "$workapp" ]]; then
        echo "  COPY: reusing preserved temp copy"
        if _repair_archive_app_copy "$app" "$workapp"; then
            return 0
        fi
        echo "  COPY WARN: preserved temp copy repair failed; recreating"
        rm_retry "$workapp"
    fi

    _copy_archive_app_fresh "$app" "$workapp"
}

_archive_app_to_zip() {
    local app="$1" versioned="$2" dest_zip="$3" manifest_hash="$4" archive_stem="$5"
    local workdir total use_bar=0
    workdir=$(_archive_workdir_path "$archive_stem" "$manifest_hash")

    _ensure_archive_copy "$app" "$versioned" "$workdir"
    total=$(find "$app" -not -type d | wc -l | tr -d ' ')
    [[ -t 2 && $total -gt 0 ]] && use_bar=1

    if [[ $use_bar -eq 1 ]]; then
        { (cd "$workdir" && ditto -V -c -k --sequesterRsrc --keepParent "$versioned" "$dest_zip"); } 2>&1 | \
            _progress_bar_filter "ZIP " "$total"
    else
        (cd "$workdir" && ditto -c -k --sequesterRsrc --keepParent "$versioned" "$dest_zip")
    fi
}

_delete_validated_workdir() {
    local archive_stem="$1" manifest_hash="$2"
    local workdir
    workdir=$(_archive_workdir_path "$archive_stem" "$manifest_hash")
    [[ -d "$workdir" ]] && rm_retry "$workdir"
}

# Create a zip in local_cache (if set) or dest, then move it to dest.
# With local_cache: rsync the finished .tmp to the destination with a progress bar,
# then delete the local .tmp (no local copy is retained).
_archive_and_store_zip() {
    local app="$1" versioned="$2" zipname="$3" manifest_hash="$4" archive_stem="$5"
    local staging="${local_cache:-$dest}"
    _archive_app_to_zip "$app" "$versioned" "$staging/$zipname.tmp" "$manifest_hash" "$archive_stem"
    if [[ -n "$local_cache" ]]; then
        rsync --progress "$local_cache/$zipname.tmp" "$dest/$zipname.tmp" 2>&1 | tr '\r' '\n' | \
            _rsync_file_progress_bar_filter "SEND"
        mv "$dest/$zipname.tmp" "$dest/$zipname"
        rm -f "$local_cache/$zipname.tmp"
    else
        mv "$dest/$zipname.tmp" "$dest/$zipname"
    fi
}

# Write a checksum file to dest.
_write_checksums() {
    local content="$1" checksumname="$2"
    safe_write "$content" "$dest/$checksumname.tmp"
    safe_mv "$dest/$checksumname.tmp" "$dest/$checksumname"
}

# Remove a zip from dest and, if a local_cache copy exists, from there too.
_remove_zip() {
    local zipname="$1"
    rm -f "$dest/$zipname"
    [[ -n "$local_cache" ]] && rm -f "$local_cache/$zipname" || true
    [[ -n "$local_cache" ]] && rm -f "$local_cache/$zipname.tmp" || true
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

_sha256_text() {
    local text="$1"
    printf '%s' "$text" | shasum -a 256 | awk '{print $1}'
}

_collect_app_manifest() {
    local app="$1" mode="${2:-full}"
    python3 - "$app" "$mode" <<'PYEOF'
import hashlib, locale, os, stat, sys

app_root = os.path.abspath(sys.argv[1])
mode = sys.argv[2]
lines = []
locale.setlocale(locale.LC_COLLATE, 'C')

for root, dirs, files in os.walk(app_root, topdown=True, followlinks=False):
    dirs.sort(key=locale.strxfrm)
    names = sorted(dirs + files, key=locale.strxfrm)
    for name in names:
        path = os.path.join(root, name)
        rel = os.path.relpath(path, app_root)
        st = os.lstat(path)
        if stat.S_ISREG(st.st_mode):
            sha = hashlib.sha256()
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(65536), b''):
                    sha.update(chunk)
            lines.append((rel, f"{sha.hexdigest()}  {rel}"))
        elif mode == 'full' and stat.S_ISLNK(st.st_mode):
            target = os.readlink(path).encode('utf-8', 'surrogateescape')
            sha = hashlib.sha256(target).hexdigest()
            lines.append((rel, f"{sha}  {rel}"))

lines.sort(key=lambda item: locale.strxfrm(item[0]))
for _, line in lines:
    print(line)
PYEOF
}

_collect_external_live_symlinks() {
    local app="$1"
    python3 - "$app" <<'PYEOF'
import locale, os, stat, sys

app_root = os.path.abspath(sys.argv[1])
entries = []
for root, dirs, files in os.walk(app_root, topdown=True, followlinks=False):
    dirs.sort(key=locale.strxfrm)
    names = sorted(dirs + files, key=locale.strxfrm)
    for name in names:
        path = os.path.join(root, name)
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            continue
        if not stat.S_ISLNK(st.st_mode):
            continue
        rel = os.path.relpath(path, app_root)
        target = os.readlink(path)
        resolved = os.path.realpath(path)
        try:
            common = os.path.commonpath([app_root, resolved])
        except ValueError:
            common = None
        if common != app_root:
            entries.append((rel, target, resolved))

entries.sort(key=lambda item: locale.strxfrm(item[0]))
for rel, target, resolved in entries:
    print(f"{rel}\t{target}\t{resolved}")
PYEOF
}

_count_live_symlinks() {
    local app="$1"
    python3 - "$app" <<'PYEOF'
import os, stat, sys

app_root = os.path.abspath(sys.argv[1])
count = 0
for root, dirs, files in os.walk(app_root, topdown=True, followlinks=False):
    for name in dirs + files:
        path = os.path.join(root, name)
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(st.st_mode):
            count += 1
print(count)
PYEOF
}

_record_external_symlink_summary() {
    local app_label="$1" source_label="$2" entries="$3"
    [[ -n "$entries" ]] || return 0
    external_symlink_summary+=("__APP__"$'\t'"$app_label"$'\t'"$source_label")
    while IFS= read -r line; do
        [[ -n "$line" ]] || continue
        external_symlink_summary+=("$line")
    done <<< "$entries"
}

_handle_external_symlinks() {
    local app_label="$1" source_label="$2" total_count="$3" entries="$4"
    local external_count=0
    if [[ -n "$entries" ]]; then
        external_count=$(printf '%s\n' "$entries" | awk 'NF { n++ } END { print n + 0 }')
    fi
    echo "  SYMLINKS: checked $source_label; found $total_count symlink(s), $external_count external"
    [[ -n "$entries" ]] || return 0
    _record_external_symlink_summary "$app_label" "$source_label" "$entries"
    echo "  SYMLINK WARN: external target(s) detected; policy=$external_symlink_policy"
    case "$external_symlink_policy" in
        archive) return 0 ;;
        skip)
            echo "  SKIPPED ⚠️: external symlink policy"
            return 1 ;;
        abort)
            echo "  ABORTED ❌: external symlink policy"
            exit 1 ;;
    esac
}

_print_external_symlink_summary() {
    [[ ${#external_symlink_summary[@]} -gt 0 ]] || return 0
    echo
    echo "External symlink summary:"
    local line
    for line in "${external_symlink_summary[@]}"; do
        if [[ "$line" == __APP__* ]]; then
            IFS=$'\t' read -r _marker app_label source_label <<< "$line"
            echo "  $app_label [$source_label]"
            continue
        fi
        IFS=$'\t' read -r rel target resolved <<< "$line"
        echo "    $rel -> $target"
        echo "      resolved: $resolved"
    done
}

_record_verify_failure() {
    local zipname="$1" reason="$2"
    verify_failure_summary+=("$zipname"$'\t'"$reason")
}

_print_verify_failure_summary() {
    local line zipname reason
    [[ ${#verify_failure_summary[@]} -gt 0 ]] || return 0
    echo
    echo "Verification failure summary:"
    for line in "${verify_failure_summary[@]}"; do
        IFS=$'\t' read -r zipname reason <<< "$line"
        echo "  $zipname"
        echo "    $reason"
    done
}

_verify_checksum_file_contents() {
    local checksumfile="$1" actual_full="$2" actual_legacy="$3"
    local existing
    existing=$(cat "$checksumfile")
    if [[ "$existing" == "$actual_full" ]]; then
        echo "  VERIFIED ✅: checksum matches"
        return 0
    fi
    if [[ "$existing" == "$actual_legacy" ]]; then
        echo "  VERIFIED ✅: legacy checksum matches; upgrading"
        safe_write "$actual_full" "${checksumfile}.tmp"
        safe_mv "${checksumfile}.tmp" "$checksumfile"
        return 0
    fi
    echo "  FAILED ❌: checksum differs"
    return 1
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
    local zip="$1" mode="${2:-full}"
    if ! head -c 4 "$zip" > /dev/null 2>/dev/null; then
        return 1
    fi
    python3 - "$zip" "$mode" <<'PYEOF'
import sys, zipfile, hashlib, locale, subprocess, struct, zlib as _zlib, os, stat, time

zpath = sys.argv[1]
manifest_mode = sys.argv[2]

def _fix_zip_name(info):
    # ditto stores filenames as UTF-8 bytes without the ZIP UTF-8 flag (bit 11),
    # so Python's zipfile decodes them as cp437. Re-encode to get the raw bytes
    # and decode as UTF-8 to recover the original filename.
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode('cp437').decode('utf-8')
    except (UnicodeDecodeError, UnicodeEncodeError):
        return info.filename

def _find_zip64_offset(fp, info):
    # Python bug: when only header_offset needs ZIP64 (file/compress sizes < 4 GB),
    # Python misassigns the 8-byte ZIP64 offset field to file_size and leaves
    # header_offset at the sentinel 0xFFFFFFFF.  The true offset is still in
    # info.extra — try every 8-byte field in the ZIP64 block and validate with
    # the local-file-header signature.  No "> 4 GB" guard: entries in the first
    # 4 GB of a ZIP64 archive have valid offsets ≤ 0xFFFFFFFF that the old
    # guard silently skipped, causing all such entries to fall through to the
    # (broken on macOS) unzip fallback.
    extra = info.extra or b''
    i = 0
    while i + 4 <= len(extra):
        tag, size = struct.unpack_from('<HH', extra, i)
        i += 4
        if tag == 0x0001:  # ZIP64 extended information
            n = (min(size, len(extra) - i) // 8) * 8
            for j in range(0, n, 8):
                v = struct.unpack_from('<Q', extra, i + j)[0]
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
        all_entries = [(info, _fix_zip_name(info)) for info in z.infolist()]
        app_prefix = None
        for _info, name in all_entries:
            parts = name.split('/')
            if not name.endswith('/') and '__MACOSX' not in name \
               and len(parts) > 1 and parts[0].endswith('.app'):
                app_prefix = parts[0] + '/'
                break
        if app_prefix is None:
            sys.exit(1)
        entries = [(info, name) for info, name in all_entries
                   if not name.endswith('/')
                   and '__MACOSX' not in name
                   and name.startswith(app_prefix)]
        _total = len(entries)
        _tty   = os.isatty(sys.stderr.fileno())
        _step  = max(1, _total // 200)
        _start = time.time()

        def _fmt_duration(seconds):
            seconds = max(0, int(seconds))
            hours, rem = divmod(seconds, 3600)
            minutes, secs = divmod(rem, 60)
            if hours > 0:
                return f"{hours:d}:{minutes:02d}:{secs:02d}"
            return f"{minutes:02d}:{secs:02d}"

        def _fmt_eta_target(now_ts, remaining):
            remaining = max(0, int(remaining))
            target_ts = now_ts + remaining
            day_offset = remaining // 86400
            time_fmt = "%H:%M:%S" if day_offset == 0 else "%H:%M"
            day_label = ""
            if day_offset == 1:
                day_label = " (+1 day)"
            elif day_offset > 1:
                day_label = f" (+{day_offset} days)"
            return time.strftime(time_fmt, time.localtime(target_ts)) + day_label

        def _bar(i):
            pct = i * 100 // _total if _total else 100
            filled = i * 40 // _total if _total else 40
            bar = '=' * filled
            if filled < 40:
                bar += '>'
            bar = bar.ljust(40)
            eta = "--:--"
            eta_target = "--:--:--"
            now_ts = int(time.time())
            elapsed = now_ts - int(_start)
            if i > 0 and elapsed > 0 and _total:
                remaining = (_total - i) * elapsed // i
                eta = _fmt_duration(remaining)
                eta_target = _fmt_eta_target(now_ts, remaining)
            elif i >= _total:
                eta = "00:00"
                eta_target = _fmt_eta_target(now_ts, 0)
            sys.stderr.write(
                f'\r  VERIFY [{bar}] {i}/{_total} ({pct}%, eta {eta} @ {eta_target})'
            )
            sys.stderr.flush()
        results    = []
        unreadable = []
        for _i, (info, name) in enumerate(entries, 1):
            rel  = name[len(app_prefix):]
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            is_link = stat.S_IFMT(unix_mode) == stat.S_IFLNK
            if is_link and manifest_mode != 'full':
                continue
            try:
                if is_link:
                    target = z.read(info).rstrip(b'\n')
                    results.append(hashlib.sha256(target).hexdigest() + '  ' + rel)
                else:
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
                if not is_link:
                    true_offset = _find_zip64_offset(z.fp, info)
                    if true_offset is not None:
                        try:
                            h = _hash_at_offset(z.fp, info, true_offset)
                        except Exception:
                            pass
                    if h is None:
                        h = _hash_via_unzip(info.filename)
                if h is not None:
                    results.append(h + '  ' + rel)
                else:
                    unreadable.append(rel)
                    results.append('(unreadable)  ' + rel)
            if _tty and (_i % _step == 0 or _i == _total):
                _bar(_i)
        if _tty:
            sys.stderr.write('\r\033[K')
            sys.stderr.write('  VERIFY done in ' + _fmt_duration(int(time.time() - _start)) + '\n')
            sys.stderr.flush()
        locale.setlocale(locale.LC_COLLATE, 'C')
        results.sort(key=lambda x: locale.strxfrm(x.split('  ', 1)[1]))
        print('\n'.join(results))
        if unreadable:
            print(str(len(unreadable)) + ' entries could not be read', file=sys.stderr)
            sys.exit(2)
except Exception as e:
    if '_start' in dir() and os.isatty(sys.stderr.fileno()):
        sys.stderr.write('\r\033[K  VERIFY failed after ' + _fmt_duration(int(time.time() - _start)) + '\n')
        sys.stderr.flush()
    print('Error: ' + str(e), file=sys.stderr)
    sys.exit(1)
PYEOF
}

external_symlinks_from_zip() {
    local zip="$1"
    if ! head -c 4 "$zip" > /dev/null 2>/dev/null; then
        return 1
    fi
    python3 - "$zip" <<'PYEOF'
import locale, os, posixpath, stat, sys, zipfile

zpath = sys.argv[1]
try:
    with zipfile.ZipFile(zpath) as z:
        app_prefix = None
        for name in z.namelist():
            parts = name.split('/')
            if not name.endswith('/') and '__MACOSX' not in name and len(parts) > 1 and parts[0].endswith('.app'):
                app_prefix = parts[0]
                break
        if app_prefix is None:
            sys.exit(1)
        entries = []
        app_root = "/" + app_prefix
        for info in z.infolist():
            if info.filename.endswith('/') or '__MACOSX' in info.filename or not info.filename.startswith(app_prefix + '/'):
                continue
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_IFMT(mode) != stat.S_IFLNK:
                continue
            rel = info.filename[len(app_prefix) + 1:]
            target = z.read(info).rstrip(b'\n').decode('utf-8', 'surrogateescape')
            link_dir = posixpath.dirname("/" + info.filename)
            resolved = posixpath.normpath(posixpath.join(link_dir, target))
            if not resolved.startswith(app_root + "/") and resolved != app_root:
                entries.append((rel, target, resolved))
        entries.sort(key=lambda item: locale.strxfrm(item[0]))
        for rel, target, resolved in entries:
            print(f"{rel}\t{target}\t{resolved}")
except Exception:
    sys.exit(1)
PYEOF
}

count_symlinks_from_zip() {
    local zip="$1"
    if ! head -c 4 "$zip" > /dev/null 2>/dev/null; then
        return 1
    fi
    python3 - "$zip" <<'PYEOF'
import stat, sys, zipfile

zpath = sys.argv[1]
try:
    with zipfile.ZipFile(zpath) as z:
        app_prefix = None
        for name in z.namelist():
            parts = name.split('/')
            if not name.endswith('/') and '__MACOSX' not in name and len(parts) > 1 and parts[0].endswith('.app'):
                app_prefix = parts[0]
                break
        if app_prefix is None:
            sys.exit(1)
        count = 0
        for info in z.infolist():
            if info.filename.endswith('/') or '__MACOSX' in info.filename or not info.filename.startswith(app_prefix + '/'):
                continue
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_IFMT(mode) == stat.S_IFLNK:
                count += 1
        print(count)
except Exception:
    sys.exit(1)
PYEOF
}

_resolve_verify_zip_arg() {
    local arg="$1" dest="$2"
    local zippath appname

    # Specific zip file (check before .app tests: "Xcode.app@15.4.zip" ends in .zip)
    if [[ "$arg" == *.zip ]]; then
        if [[ "$arg" == */* ]]; then
            zippath="$arg"
        else
            zippath="$dest/$arg"
        fi
        if [[ -f "$zippath" ]]; then
            printf '%s\n' "$zippath"
            return 0
        fi
        echo "Error: zip not found: $zippath" >&2
        return 1
    fi

    # Path into a bundle (contains .app/) → extract outer bundle name
    if [[ "$arg" == *\.app/* ]]; then
        appname=$(basename "${arg%%.app/*}.app")
        appname="${appname%.app}"
    # Ends in .app → strip suffix
    elif [[ "$arg" == *.app ]]; then
        appname=$(basename "$arg")
        appname="${appname%.app}"
    # Bare app name
    else
        appname="$arg"
    fi

    local found=()
    while IFS= read -r _z; do found+=("$_z"); done < <(find "$dest" -maxdepth 1 -name "${appname}.app@*.zip" | sort)
    if [[ ${#found[@]} -eq 0 ]]; then
        echo "Error: no zips found for app '$appname' in $dest" >&2
        return 1
    fi
    printf '%s\n' "${found[@]}"
}

if [[ -n "$verify_zip_arg" ]]; then
    _vz_zips=()
    _vz_out=$(_resolve_verify_zip_arg "$verify_zip_arg" "$dest") || exit 1
    while IFS= read -r _l; do [[ -n "$_l" ]] && _vz_zips+=("$_l"); done <<< "$_vz_out"

    total=${#_vz_zips[@]}
    width=${#total}
    echo "Verifying $total zip(s) [--verify-zip]…"
    i=0
    for zip in "${_vz_zips[@]}"; do
        i=$(( i + 1 ))
        printf -v idx '%0*d' "$width" "$i"
        zipname=$(basename "$zip")
        checksumfile="${zip%.zip}.checksums.txt"
        echo "VERIFY $idx/$total: $zipname"

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
        zip_symlink_count=$(count_symlinks_from_zip "$zip" || true)
        zip_external_symlinks=$(external_symlinks_from_zip "$zip" || true)
        if ! _handle_external_symlinks "$zipname" "verify zip" "${zip_symlink_count:-0}" "$zip_external_symlinks"; then
            continue
        fi

        if [[ -f "$checksumfile" ]]; then
            actual_legacy=$(checksums_from_zip "$zip" legacy)
            if ! _verify_checksum_file_contents "$checksumfile" "$actual" "$actual_legacy"; then
                _record_verify_failure "$zipname" "checksum file differs"
                [[ $verify_abort -eq 1 ]] && { echo "  ABORTED ❌: verification failed (--verify-abort)"; _print_verify_failure_summary; exit 1; }
                continue
            fi
        else
            echo "  CHECKSUM: no checksum file found"
        fi
    done
    _print_verify_failure_summary
    [[ ${#verify_failure_summary[@]} -eq 0 ]] || exit 1
    exit 0
fi

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
        zip_symlink_count=$(count_symlinks_from_zip "$zip" || true)
        zip_external_symlinks=$(external_symlinks_from_zip "$zip" || true)
        if ! _handle_external_symlinks "$zipname" "verify zip" "${zip_symlink_count:-0}" "$zip_external_symlinks"; then
            continue
        fi

        if [[ -f "$checksumfile" ]]; then
            actual_legacy=$(checksums_from_zip "$zip" legacy)
            if ! _verify_checksum_file_contents "$checksumfile" "$actual" "$actual_legacy"; then
                _record_verify_failure "$zipname" "checksum file differs"
                if [[ $verify_abort -eq 1 ]]; then
                    echo "  ABORTED ❌: verification failed (--verify-abort)"
                    _print_verify_failure_summary
                    exit 1
                fi
                continue
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
    _print_verify_failure_summary
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
    zipstem="${zipname%.zip}"
    versioned="${name} ${version}.app"
    echo "ARCHIVING $idx/$total: $zipname"
    live_symlink_count=$(_count_live_symlinks "$app")
    live_external_symlinks=$(_collect_external_live_symlinks "$app")
    if ! _handle_external_symlinks "$zipname" "live app" "$live_symlink_count" "$live_external_symlinks"; then
        continue
    fi

    if [[ -f "$dest/$zipname" ]]; then
        echo "  ARCHIVE: found"

        if [[ -f "$dest/$checksumname" ]]; then
            echo "  CHECKSUM: found"
            echo "  app: $(du -sh "$app" | cut -f1)"
            echo "  zip: $(du -sh "$dest/$zipname" | cut -f1)"
            zip_symlink_count=$(count_symlinks_from_zip "$dest/$zipname" || true)
            zip_external_symlinks=$(external_symlinks_from_zip "$dest/$zipname" || true)
            if ! _handle_external_symlinks "$zipname" "existing zip" "${zip_symlink_count:-0}" "$zip_external_symlinks"; then
                continue
            fi
            live_checksums=$(_collect_app_manifest "$app" full)
            live_checksums_legacy=$(_collect_app_manifest "$app" legacy)
            live_manifest_hash=$(_sha256_text "$live_checksums")
            if _verify_checksum_file_contents "$dest/$checksumname" "$live_checksums" "$live_checksums_legacy"; then
                echo "  VERIFIED ✅: archived checksum matches current app"
            else
                echo "  MISMATCH ❌: archived checksum does not match current app"
                printf "  [o]verwrite zip / [b]oth / [s]kip: "
                _tty_read choice "s"
                case "$choice" in
                    o|O)
                        _remove_zip "$zipname"
                        _archive_and_store_zip "$app" "$versioned" "$zipname" "$live_manifest_hash" "$zipstem"
                        _write_checksums "$live_checksums" "$checksumname"
                        ;;
                    b|B)
                        suffix=$(date +%Y%m%d_%H%M%S)
                        newzip="${name}.app@${mobile}${version}~${suffix}.zip"
                        newcheck="${name}.app@${mobile}${version}~${suffix}.checksums.txt"
                        _archive_and_store_zip "$app" "$versioned" "$newzip" "$live_manifest_hash" "$zipstem"
                        _write_checksums "$live_checksums" "$newcheck"
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
            zip_symlink_count=$(count_symlinks_from_zip "$dest/$zipname" || true)
            zip_external_symlinks=$(external_symlinks_from_zip "$dest/$zipname" || true)
            if ! _handle_external_symlinks "$zipname" "existing zip" "${zip_symlink_count:-0}" "$zip_external_symlinks"; then
                continue
            fi
            live_checksums=$(_collect_app_manifest "$app" full)
            live_manifest_hash=$(_sha256_text "$live_checksums")
            echo "  app: $(du -sh "$app" | cut -f1)"
            if [[ "$zip_checksums" == "$live_checksums" ]]; then
                _write_checksums "$zip_checksums" "$checksumname"
                echo "  CHECKSUM: written"
                echo "  VERIFIED ✅: zip checksum matches current app"
            else
                echo "  MISMATCH ❌: zip checksum does not match current app"
                printf "  [o]verwrite zip / [b]oth / [s]kip: "
                _tty_read choice "s"
                case "$choice" in
                    o|O)
                        _remove_zip "$zipname"
                        _archive_and_store_zip "$app" "$versioned" "$zipname" "$live_manifest_hash" "$zipstem"
                        _write_checksums "$live_checksums" "$checksumname"
                        ;;
                    b|B)
                        _write_checksums "$zip_checksums" "$checksumname"
                        suffix=$(date +%Y%m%d_%H%M%S)
                        newzip="${name}.app@${mobile}${version}~${suffix}.zip"
                        newcheck="${name}.app@${mobile}${version}~${suffix}.checksums.txt"
                        _archive_and_store_zip "$app" "$versioned" "$newzip" "$live_manifest_hash" "$zipstem"
                        _write_checksums "$live_checksums" "$newcheck"
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
    live_checksums=$(_collect_app_manifest "$app" full)
    live_manifest_hash=$(_sha256_text "$live_checksums")
    _archive_and_store_zip "$app" "$versioned" "$zipname" "$live_manifest_hash" "$zipstem"
    echo "  ZIP+HASH: created"
    echo "  zip: $(du -sh "$dest/$zipname" | cut -f1)"
    _write_checksums "$live_checksums" "$checksumname"
    echo "  CHECKSUM: written for app"

    echo "  CHECKSUM: verifying zip..."
    if zip_checksums=$(checksums_from_zip "$dest/$zipname"); then
        zip_symlink_count=$(count_symlinks_from_zip "$dest/$zipname" || true)
        zip_external_symlinks=$(external_symlinks_from_zip "$dest/$zipname" || true)
        if ! _handle_external_symlinks "$zipname" "new zip" "${zip_symlink_count:-0}" "$zip_external_symlinks"; then
            continue
        fi
        if [[ "$zip_checksums" == "$live_checksums" ]]; then
            echo "  CREATED ✅: archived checksum matches app"
            _delete_validated_workdir "$zipstem" "$live_manifest_hash"
        else
            echo "  MISMATCH ❌: archived checksum does not match original app"
        fi
    else
        echo "  SKIPPED ⚠️: zip not readable for post-archive verification"
    fi
done
_print_external_symlink_summary
