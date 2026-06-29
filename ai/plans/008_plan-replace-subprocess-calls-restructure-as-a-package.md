# Plan: Replace subprocess calls + restructure as a package

## Context

`archive_apps.py` was written as a direct port of the shell script, keeping all external tool calls as subprocesses with `# TODO` comments. This pass replaces the ones that have clean Python equivalents, drops the awkward `cp -cR` same-fs branch, and restructures the single file into a proper importable package with a thin outer entry point.

---

## Decisions

| Call | Action |
|------|--------|
| `stat -f "%d"` (same-fs detection) | **Drop entirely** — see cp/ditto merge below |
| `find … \| wc -l` → `_count_files` | `Path.rglob('*')` count |
| `find … -name "*.zip"` / `"*.app"` | `Path.glob` |
| `shasum -a 256` | `hashlib.sha256` (macOS `shasum` is a Perl script; `hashlib` is faster) |
| `PlistBuddy` | `plistlib.load()` |
| `du -sh` | `fmt_size(path)` helper in `utils.py` |
| `rsync --progress` SEND | `copy_with_progress(src, dst, bar)` in `progress.py` — reads in 1 MB chunks, shows % bar |
| `cp -cR` same-fs | **Drop** — always use `ditto` (correct for all cases; same-fs detection removed) |
| `rsync -a --delete --extended-attributes` repair | **Keep** — no stdlib xattr-aware dir-sync |
| `ditto` copy + zip | **Keep** — resource forks, no replacement |
| `_sha256_text` TODO | Remove comment — function was already pure Python |

---

## Package layout

```
archive_apps/
  __init__.py          empty
  __main__.py          main(), RunContext, atexit/signal setup, dispatch
  cli.py               Config dataclass, parse_args()
  utils.py             fmt_size, fmt_duration, fmt_eta_target, sha256_text, sha256_file, sanitize_temp_component
  progress.py          ProgressBar, drain functions, run_with_bar, copy_with_progress
  io.py                tty_read, write_fail_menu, safe_write, safe_append, safe_mv, rm_retry
  zip_ops.py           checksums_from_zip, external_symlinks_from_zip, count_symlinks_from_zip + helpers
  app_ops.py           collect_app_manifest, count_live_symlinks, collect_external_live_symlinks,
                       copy_app_fresh, repair_app_copy, ensure_archive_copy,
                       archive_app_to_zip, archive_and_store_zip, remove_zip, write_checksums
  verify.py            verify_checksum_file_contents, unreadable_prompt, run_verify_zip, run_verify_all
  archive.py           plist_value, handle_external_symlinks, print_external_symlink_summary, run_archive
main.py                thin shebang wrapper: #!/usr/bin/env -S uv run --script → calls archive_apps.__main__:main
pyproject.toml         [project.scripts] archive-apps = "archive_apps.__main__:main"
```

`archive_apps.py` (the single-file version) remains untouched alongside the new package.

---

## RunContext — replaces module-level globals

All mutable state is bundled into a `RunContext` object (defined in `cli.py` or `__main__.py`) and passed explicitly to functions that need it. No module-level globals.

```python
@dataclass
class RunContext:
    cfg: Config
    preserve_tmps: list[Path] = field(default_factory=list)
    verify_failure_summary: list[tuple[str, str]] = field(default_factory=list)
    external_symlink_summary: list[str] = field(default_factory=list)
```

---

## Key implementation notes

### Drop `same_fs` + `cp -cR`
Remove `same_fs` field from `Config` and all detection logic. `copy_app_fresh`:
- `tty`: `ditto -V` (with `ProgressBar` + `_drain_ditto_stderr`)  
- no tty: `ditto` (no progress)

### `copy_with_progress` (replaces rsync SEND)
In `progress.py`:
```python
def copy_with_progress(src: Path, dst: Path, label: str = "SEND") -> None:
    total = src.stat().st_size
    bar = ProgressBar(label, 100)   # progress as 0–100%
    copied = 0
    with open(src, 'rb') as fin, open(dst, 'wb') as fout:
        while chunk := fin.read(1 << 20):
            fout.write(chunk)
            copied += len(chunk)
            bar.set(int(copied * 100 / total) if total else 100)
    bar.done()
```
Called only when `local_cache` is set (the "SEND" path).

### `fmt_size(path)` in `utils.py`
```python
def fmt_size(path: Path) -> str:
    # TODO: pure Python (already is — no subprocess)
    total = path.stat().st_size if path.is_file() else sum(
        f.stat().st_size for f in path.rglob('*') if f.is_file()
    )
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if total < 1024 or unit == 'TB':
            return f"{total:.1f} {unit}"
        total /= 1024
```

### `sha256_file(path)` in `utils.py`
```python
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()
```
Replaces the `shasum -a 256` subprocess calls in `run_verify_all`.

### `plist_value` → `plistlib`
```python
def plist_value(plist_path: Path, key: str) -> str | None:
    try:
        with open(plist_path, 'rb') as f:
            data = plistlib.load(f)
        v = data.get(key)
        return str(v) if v is not None else None
    except Exception:
        return None
```

### `Path.glob` replacements
- `_count_files(path)`: `sum(1 for p in path.rglob('*') if p.is_file() and not p.is_symlink())`
- find `*.zip` in dest: `sorted(cfg.dest.glob('*.zip'))`
- find `*.app` in `/Applications`: `sorted(p for p in Path('/Applications').glob('**/*.app') if p.is_dir() and len(p.relative_to('/Applications').parts) <= 2)`
- `_resolve_verify_zip_arg`: `sorted(cfg.dest.glob(f'{appname}.app@*.zip'))`

---

## Files created/modified

- **Create** `archive_apps/` package (10 files)
- **Create** `main.py` (thin wrapper, ~5 lines)
- **Create** `pyproject.toml`
- **Leave unchanged** `archive_apps.py` (single-file version)
- **Leave unchanged** `archive_apps.sh`
- **Update** `CLAUDE.md` — add package usage section

---

## Verification

```bash
# Help text (via main.py shebang)
./main.py --help

# Via python -m
python -m archive_apps --help

# Via uv tool install
uv tool install .
archive-apps --help

# Verify test fixtures
./main.py --verify-zips test/

# Spot-check a zip
./main.py --verify-zip="Xcode.app@15.4.zip" /path/to/dest
```
