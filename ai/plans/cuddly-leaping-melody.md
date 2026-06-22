# Plan: Progress bar for checksums_from_zip

## Context

`checksums_from_zip` hashes every file inside a zip via Python streaming.
For large zips (Xcode = 4.5 GB, 3800+ entries) this takes many minutes with
zero visible feedback — bash is blocked on the command substitution and Python
only writes to stdout (captured) until completely done.

Key insight: while Python runs, bash is blocked. Python's stderr goes straight
to the terminal without conflicting with bash's captured stdout. Writing an
updating `\r` progress bar to stderr gives real-time feedback with no
architectural changes.

---

## Approach

Add a TTY-gated progress bar inside the Python heredoc in `checksums_from_zip()`.

### Why stderr / why Python-only

- bash is blocked on `actual=$(checksums_from_zip "$zip")` — stdout is piped,
  stderr is not. Python owns the terminal during its execution.
- The outer bash loop already shows `VERIFY 034/144: …` per zip. The slow part
  is *within* a single zip — that's where the bar is valuable.
- No changes to bash needed.

### What to add to the Python heredoc (`archive_apps.sh` lines ~218–343)

**1. Add `import os` to the import line.**

**2. Pre-build `entries` list before hashing** (currently the loop is inline):
```python
entries = [info for info in z.infolist()
           if not info.filename.endswith('/')
           and '__MACOSX' not in info.filename
           and info.filename.startswith(app_prefix)]
_total = len(entries)
_tty   = os.isatty(sys.stderr.fileno())
_step  = max(1, _total // 200)   # ~200 bar updates regardless of zip size
```

**3. Add `_bar(i)` helper** (defined before the try block):
```python
def _bar(i):
    pct    = i * 100 // _total if _total else 100
    filled = i * 40  // _total if _total else 40
    b = '=' * filled + ('>' if filled < 40 else '') + ' ' * (39 - filled)
    sys.stderr.write(f'\r  [{b}] {i}/{_total} ({pct}%)')
    sys.stderr.flush()
```

**4. Iterate `entries` with `enumerate`, call `_bar` at `_step` intervals:**
```python
results   = []
unreadable = []
for _i, info in enumerate(entries, 1):
    name = info.filename
    rel  = name[len(app_prefix):]
    try:
        sha = hashlib.sha256()
        with z.open(info) as f:
            ...
        results.append(sha.hexdigest() + '  ' + rel)
    except Exception:
        ...  # fallback chain unchanged

    if _tty and (_i % _step == 0 or _i == _total):
        _bar(_i)
```

**5. Clear the bar before printing results:**
```python
if _tty:
    sys.stderr.write('\r\033[K')
    sys.stderr.flush()
locale.setlocale(...)
print('\n'.join(results))
```

### Bar appearance

```
  [===================>                    ] 345/1247 (28%)
```

- Fixed 40-char bar, fits in 80 cols with fraction and percentage.
- `\r\033[K` clears the line when done; the bash VERIFIED/FAILED line follows cleanly.
- No-TTY (piped output): `_tty = False`, bar is completely suppressed.

---

## File to modify

- `archive_apps.sh` — Python heredoc inside `checksums_from_zip()` only

## Change summary

| What | Where |
|------|-------|
| Add `import os` | line ~219 |
| Pre-build `entries` list + `_total`, `_tty`, `_step` | after `app_prefix` is found, ~line 300 |
| Add `_bar(i)` helper | before the `try` block |
| Replace inline `for info in z.infolist()` with `for _i, info in enumerate(entries, 1)` | ~line 303 |
| Remove now-redundant per-entry filters (moved into `entries` list comprehension) | same |
| Call `_bar(_i)` after each entry when `_tty` | end of loop body |
| Clear bar before `print('\n'.join(results))` | ~line 336 |

---

## Verification

```bash
# Should show animated bar while running, then clean result line:
./archive_apps.sh --verify-zips /tmp/test_dest 2>&1 | head -10
# Confirm no bar artifact left after each zip completes

# Piped (no bar expected):
./archive_apps.sh --verify-zips /tmp/test_dest 2>/dev/null | grep VERIFIED
```
