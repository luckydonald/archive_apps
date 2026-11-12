# Plan: archive apps without a zip first

## Context

Todo: "Random sort when copying so it's not stuck with the same one every time."
`run_archive` in `archive_apps/archive.py:215` already does `random.shuffle(apps)`, so the random order exists.
The user clarified the intent: apps that have no zip in the destination yet should be processed first, so an interrupted or failing run does not keep redoing existing ones.
The random shuffle stays as the tie-break inside each group.

## Changes

- `archive_apps/archive.py`:
  - Extract the Info.plist lookup, name and version derivation from the loop (lines 224-241) into a helper `app_identity(app) -> tuple[str, str, str] | None` returning `(name, mobile, version)`, or `None` without an Info.plist.
    The loop uses it, so the zip naming exists in one place.
  - Add `order_apps(apps, dest) -> list[Path]`: shuffle, then a stable sort with key `0` if the zip `{name}.app@{mobile}{version}.zip` is missing in `dest`, else `1`.
    Apps without an Info.plist sort last, since they are skipped anyway.
  - `run_archive` calls `order_apps(apps, cfg.dest)` instead of `random.shuffle`.
  - Print the count of apps without a zip next to the `Checking N app(s)…` line.
- `tests/test_app_order.py` (new): build fake `.app` dirs with `Contents/Info.plist` in `tmp_path`, create some zips in a dest dir, and assert that all unzipped apps come before the zipped ones, that no-plist apps come last, and that the result is a permutation of the input.
  The shuffle within groups is not asserted.
- `CLAUDE.md`: one sentence in the architecture section that apps without a zip are processed first, in random order within each group.

No new i18n keys.

## Verification

- `uv run --with pytest python -m pytest tests`, expecting green.
- Dry look at the order with a small script that calls `order_apps` on `/Applications` and a real destination, if one is at hand.

## Closing notes

The `sync_todo` MCP is down this session, so `complete_todo` and the final sync have to be done after the reconnect.
The checkbox in `ai/todos.md` gets ticked in the work commit.
