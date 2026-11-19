from __future__ import annotations

import random
import sys
from dataclasses import dataclass
from pathlib import Path

from .archive import app_identity, find_apps, finalize_archive, run_archive, verify_created
from .cli import STEPS, RunContext
from .filters import zip_matches
from .verify import (
    classify_zip, is_indexed, merge_checksum_index, open_index_scratch,
    print_external_symlink_summary, print_verify_failure_summary, read_index, verify_one_zip,
)

STEP_TITLES: dict[str, str] = {
    "archive": "archive",
    "created": "verify created",
    "changed": "verify changed",
    "new": "verify new",
    "rest": "verify rest",
}
STEP_HINTS: dict[str, str] = {"rest": "slow, safe to interrupt"}
STATE_MARKS: dict[str, str] = {"done": "[x]", "running": "[>]", "pending": "[ ]", "skipped": "[-]"}


@dataclass
class Counts:
    verified: int = 0
    failed: int = 0
    skipped: int = 0

    def describe(self) -> str:
        parts = [f"{self.verified} verified"]
        if self.failed:
            parts.append(f"{self.failed} FAILED")
        # end if
        if self.skipped:
            parts.append(f"{self.skipped} skipped")
        # end if
        return ", ".join(parts)
    # end def
# end class


def render_checklist(states: dict[str, str], notes: dict[str, str]) -> str:
    """Plain text checklist of the steps, e.g. `  [x] 1 archive         12 zip(s) created`."""
    width = max(len(title) for title in STEP_TITLES.values())
    lines = ["Steps:"]
    for number, step in enumerate(STEPS, 1):
        note = notes.get(step) or (STEP_HINTS.get(step, "") if states[step] in ("pending", "running") else "")
        lines.append(f"  {STATE_MARKS[states[step]]} {number} {STEP_TITLES[step].ljust(width)}  {note}".rstrip())
    # end for
    return "\n".join(lines)
# end def


def order_zips(zips: list[Path], installed_prefixes: set[str]) -> list[Path]:
    """Zips of the installed apps first, the others after; each group in random order, so an interrupted run still makes progress over runs."""
    shuffled = list(zips)
    random.shuffle(shuffled)
    return sorted(shuffled, key=lambda z: 0 if z.name.startswith(tuple(installed_prefixes)) else 1)
# end def


def installed_prefixes(ctx: RunContext) -> set[str]:
    """`{name}.app@{mobile}` of every installed app, as the zips of that app start with it."""
    identities = [app_identity(app) for app in find_apps()]
    return {f"{name}.app@{mobile}" for name, mobile, _ in filter(None, identities)}
# end def


def verify_zip_list(ctx: RunContext, zips: list[Path], label: str) -> Counts:
    counts = Counts()
    total = len(zips)
    width = len(str(total))
    for i, zip_path in enumerate(zips, 1):
        print(f"VERIFY {label} {str(i).zfill(width)}/{total}: {zip_path.name}")
        ctx.processed_zips.add(zip_path.name)
        result = verify_one_zip(zip_path, ctx)
        if result is True:
            counts.verified += 1
        elif result is False:
            counts.failed += 1
        else:
            counts.skipped += 1
        # end if
    # end for
    return counts
# end def


def verify_changed(ctx: RunContext, zips: list[Path], index: dict[str, str]) -> Counts:
    """Hash the indexed zips and fully verify those that differ from their index entry."""
    counts = Counts()
    candidates = [z for z in zips if z.name not in ctx.processed_zips and is_indexed(z, index)]
    total = len(candidates)
    width = len(str(total))
    for i, zip_path in enumerate(candidates, 1):
        print(f"HASH {str(i).zfill(width)}/{total}: {zip_path.name}")
        if classify_zip(zip_path, index, ctx) != "changed":
            print("  UNCHANGED ✅: hash matches index")
            continue
        # end if
        print("  CHANGED 🔸: hash differs from index, verifying")
        ctx.processed_zips.add(zip_path.name)
        result = verify_one_zip(zip_path, ctx)
        if result is True:
            counts.verified += 1
        elif result is False:
            counts.failed += 1
        else:
            counts.skipped += 1
        # end if
    # end for
    return counts
# end def


def run_steps(ctx: RunContext) -> None:
    """Run the selected steps in priority order: archive, verify created, changed, new, then all remaining zips."""
    cfg = ctx.cfg
    selected = cfg.steps
    states = {step: ("pending" if step in selected else "skipped") for step in STEPS}
    notes: dict[str, str] = {}

    def begin(step: str) -> None:
        states[step] = "running"
        print()
        print(render_checklist(states, notes))
        print()
    # end def

    def finish(step: str, note: str) -> None:
        states[step] = "done"
        notes[step] = note
    # end def

    open_index_scratch(ctx)
    try:
        if "archive" in selected:
            begin("archive")
            run_archive(ctx)
            finish("archive", f"{len(ctx.created)} zip(s) created")
        # end if

        if "created" in selected:
            begin("created")
            counts = Counts(*verify_created(ctx))
            finish("created", counts.describe())
        # end if

        if "archive" in selected or "created" in selected:
            finalize_archive(ctx)
        # end if

        if selected & {"changed", "new", "rest"}:
            prefixes = installed_prefixes(ctx)
            zips = [z for z in cfg.dest.glob("*.zip") if zip_matches(z.name, cfg.app_filters)]
            if cfg.app_filters and not zips:
                print(f"WARN: no zips in {cfg.dest} match --app {', '.join(cfg.app_filters)}")
            # end if
            zips = order_zips(zips, prefixes)
            index = {} if cfg.force_full else read_index(cfg)

            if "changed" in selected:
                begin("changed")
                finish("changed", verify_changed(ctx, zips, index).describe())
            # end if

            if "new" in selected:
                begin("new")
                pending = [z for z in zips if z.name not in ctx.processed_zips and not is_indexed(z, index)]
                finish("new", verify_zip_list(ctx, pending, "NEW").describe())
            # end if

            if "rest" in selected:
                begin("rest")
                pending = [z for z in zips if z.name not in ctx.processed_zips]
                finish("rest", verify_zip_list(ctx, pending, "REST").describe())
            # end if
        # end if

        if ctx.index_scratch is not None:
            merge_checksum_index(ctx.index_scratch, ctx)
            ctx.index_scratch = None
        # end if
        print()
        print(render_checklist(states, notes))
    finally:
        print_external_symlink_summary(ctx)
        print_verify_failure_summary(ctx)
    # end try
    if ctx.verify_failure_summary:
        sys.exit(1)
    # end if
# end def
