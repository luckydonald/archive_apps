from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path


STEPS: tuple[str, ...] = ("archive", "created", "changed", "new", "rest")
VERIFY_STEPS: tuple[str, ...] = ("changed", "new", "rest")


@dataclass
class Config:
    dest: Path
    local_cache: Path | None
    steps: frozenset[str]       # the selected steps, see STEPS
    app_filters: list[str]      # --app values; empty = everything
    force_full: bool            # verify by extraction and ignore the checksum index
    verify_abort: bool
    keep_temp: bool
    external_symlink_policy: str   # "archive" | "skip" | "abort"
    on_mismatch: str | None        # None | "overwrite" | "both" | "skip"
    mismatch_swap: str | None      # None | "yes" | "no"
    on_verify_mismatch: str | None  # None | "retry" | "delete" | "keep"
    mark_apps: bool = True         # write Finder color + comment onto the live apps


@dataclass
class MismatchTask:
    label: str
    app: Path
    name: str
    mobile: str
    version: str
    versioned: str
    zipname: str
    checksumname: str
    zipstem: str
    live_manifest_hash: str
    live_checksums: str
    zip_checksums: str | None   # set only when the checksum file didn't exist yet


@dataclass
class SwapTask:
    label: str
    name: str
    mobile: str
    version: str
    zipname: str
    checksumname: str
    newzip: str
    newcheck: str
    suffix: str


@dataclass
class VerifyMismatchTask:
    label: str
    app: Path
    versioned: str
    zipname: str
    checksumname: str
    zipstem: str
    live_manifest_hash: str
    live_checksums: str


@dataclass
class RunContext:
    cfg: Config
    preserve_tmps: list[Path] = field(default_factory=list)
    verify_failure_summary: list[tuple[str, str]] = field(default_factory=list)
    external_symlink_summary: list[str] = field(default_factory=list)
    index_scratch: Path | None = None  # this run's private checksum-index scratch file, if any
    created: list[VerifyMismatchTask] = field(default_factory=list)  # zips created this run, verified by the `created` step
    processed_zips: set[str] = field(default_factory=set)  # zips already verified this run, skipped by later steps
    hash_cache: dict[Path, str] = field(default_factory=dict)  # sha256 of zips already hashed this run
    deferred_mismatches: list[MismatchTask] = field(default_factory=list)
    deferred_swaps: list[SwapTask] = field(default_factory=list)
    deferred_verify_mismatches: list[VerifyMismatchTask] = field(default_factory=list)
    zip_colors: dict[str, int] = field(default_factory=dict)  # zip name -> Finder color label, applied at end of run
    seen_zipnames: set[str] = field(default_factory=set)      # zips of apps handled this run (never grayed)
    app_zips: dict[Path, tuple[str, str, str, str]] = field(default_factory=dict)  # app -> (name, mobile, version, zipname)


def parse_step_list(value: str, flag: str) -> set[str]:
    """Parse a comma separated list of step names (`all` = every step); exits on an unknown name."""
    result: set[str] = set()
    for part in value.split(","):
        part = part.strip()
        if part == "all":
            result.update(STEPS)
        elif part in STEPS:
            result.add(part)
        elif part:
            print(f"Error: unknown step in {flag}: {part} (known: {', '.join(STEPS)}, all)", file=sys.stderr)
            sys.exit(1)
        # end if
    # end for
    return result
# end def


def resolve_steps(explicit: set[str] | None, aliases: set[str], skip: set[str]) -> frozenset[str]:
    """Combine `--steps` and the `--verify-*` aliases (a union), default to every step, then subtract `--skip-steps`."""
    if explicit is None and not aliases:
        base = set(STEPS)
    else:
        base = (explicit or set()) | aliases
    # end if
    return frozenset(base - skip)
# end def


def parse_args(argv: list[str]) -> Config:
    explicit_steps: set[str] | None = None
    alias_steps: set[str] = set()
    skip_steps: set[str] = set()
    app_filters: list[str] = []
    force_full = False
    dest_arg = ""
    local_cache_arg: str | None = None
    external_symlink_policy = "archive"
    verify_abort = False
    keep_temp = False
    mark_apps = True
    on_mismatch: str | None = None
    mismatch_swap: str | None = None
    on_verify_mismatch: str | None = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help"):
            print("Usage: archive-apps [options] [destination]")
            print("  --steps=LIST      comma separated steps to run, default: all")
            print("                    archive  create missing zips and compare existing ones with the live apps")
            print("                    created  verify the zips created in this run")
            print("                    changed  verify zips whose hash differs from the checksum index")
            print("                    new      verify zips not yet in the checksum index")
            print("                    rest     verify all remaining zips (slow, safe to interrupt)")
            print("  --skip-steps=LIST steps to leave out")
            print("  --app=APP         only handle this app or zip file (repeatable)")
            print("                    APP forms: Xcode / Xcode.app / /Applications/Xcode.app")
            print("                              Xcode.app@15.4.zip / full/path/to/Foo.zip")
            print("  --force-full      verify by extraction and ignore the checksum index")
            print("  --verify-zip=APP  alias: --app=APP --force-full --steps=changed,new,rest")
            print("  --verify-zips     alias: --steps=changed,new,rest (every zip, no archiving)")
            print("  --verify-new      alias: --steps=new")
            print("  --verify-changed  alias: --steps=changed")
            print("                    several aliases and --steps combine; without any, all steps run")
            print("  --verify-abort    stop immediately on the first verification failure")
            print("  --keep-temp       preserve temp workdirs and leftover .tmp files for reuse")
            print("  --local-cache[=path]")
            print("                    stage new zips on local disk, then move to destination;")
            print("                    local temp is deleted after transfer (no copy retained)")
            print("                    path defaults to /Users/Shared/App Versions")
            print("                    magic values: default (same as omitting path), none (disable)")
            print("  --external-symlink-policy=archive|skip|abort")
            print("                    handling for symlinks that resolve outside the app bundle")
            print("                    default: archive, with an end-of-run warning summary")
            print("  --on-mismatch=overwrite|both|skip")
            print("                    preset the checksum-mismatch choice; default: prompt")
            print("                    interactively (60s timeout defers to end of run)")
            print("  --mismatch-swap=yes|no")
            print("                    preset the 'swap in as canonical' follow-up to [b]oth;")
            print("                    required when --on-mismatch=both is set")
            print("  --on-verify-mismatch=retry|delete|keep")
            print("                    preset the choice when a freshly-created zip fails its")
            print("                    own post-creation verification; default: prompt")
            print("                    interactively (60s timeout defers to end of run)")
            print("  --no-mark-apps    do not write the Finder color/comment onto the apps in /Applications")
            print("  destination       archive directory (default: /Users/Shared/App Versions)")
            sys.exit(0)
        elif arg == "--verify-zip":
            print("Error: --verify-zip requires a value: --verify-zip=APP", file=sys.stderr)
            sys.exit(1)
        elif arg.startswith("--verify-zip="):
            app_filters.append(arg[len("--verify-zip="):])
            force_full = True
            alias_steps.update(VERIFY_STEPS)
        elif arg == "--verify-zips":
            alias_steps.update(VERIFY_STEPS)
        elif arg == "--verify-new":
            alias_steps.add("new")
        elif arg == "--verify-changed":
            alias_steps.add("changed")
        elif arg.startswith("--steps="):
            explicit_steps = (explicit_steps or set()) | parse_step_list(arg[len("--steps="):], "--steps")
        elif arg.startswith("--skip-steps="):
            skip_steps |= parse_step_list(arg[len("--skip-steps="):], "--skip-steps")
        elif arg.startswith("--app="):
            app_filters.append(arg[len("--app="):])
        elif arg == "--force-full":
            force_full = True
        elif arg == "--verify-abort":
            verify_abort = True
        elif arg == "--no-mark-apps":
            mark_apps = False
        elif arg == "--keep-temp":
            keep_temp = True
        elif arg in ("--local-cache", "--local-cache=", "--local-cache=default"):
            local_cache_arg = "/Users/Shared/App Versions"
        elif arg == "--local-cache=none":
            local_cache_arg = ""
        elif arg.startswith("--local-cache="):
            local_cache_arg = arg[len("--local-cache="):]
        elif arg.startswith("--external-symlink-policy="):
            val = arg[len("--external-symlink-policy="):]
            if val not in ("archive", "skip", "abort"):
                print(f"Error: unknown --external-symlink-policy value: {val}", file=sys.stderr)
                sys.exit(1)
            external_symlink_policy = val
        elif arg.startswith("--on-mismatch="):
            val = arg[len("--on-mismatch="):]
            if val not in ("overwrite", "both", "skip"):
                print(f"Error: unknown --on-mismatch value: {val}", file=sys.stderr)
                sys.exit(1)
            on_mismatch = val
        elif arg.startswith("--mismatch-swap="):
            val = arg[len("--mismatch-swap="):]
            if val not in ("yes", "no"):
                print(f"Error: unknown --mismatch-swap value: {val}", file=sys.stderr)
                sys.exit(1)
            mismatch_swap = val
        elif arg.startswith("--on-verify-mismatch="):
            val = arg[len("--on-verify-mismatch="):]
            if val not in ("retry", "delete", "keep"):
                print(f"Error: unknown --on-verify-mismatch value: {val}", file=sys.stderr)
                sys.exit(1)
            on_verify_mismatch = val
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}", file=sys.stderr)
            sys.exit(1)
        else:
            dest_arg = arg
        i += 1

    steps = resolve_steps(explicit_steps, alias_steps, skip_steps)
    if not steps:
        print("Error: no steps selected", file=sys.stderr)
        sys.exit(1)
    # end if

    if on_mismatch == "both" and mismatch_swap is None:
        print("Error: --on-mismatch=both requires --mismatch-swap=yes|no", file=sys.stderr)
        sys.exit(1)

    dest = Path(dest_arg or "/Users/Shared/App Versions").resolve()
    dest.mkdir(parents=True, exist_ok=True)

    local_cache: Path | None = None
    if local_cache_arg is not None and local_cache_arg != "":
        lc = Path(local_cache_arg).resolve()
        lc.mkdir(parents=True, exist_ok=True)
        if lc == dest:
            print("Error: --local-cache path must differ from the destination", file=sys.stderr)
            sys.exit(1)
        local_cache = lc

    return Config(
        dest=dest,
        local_cache=local_cache,
        steps=steps,
        app_filters=app_filters,
        force_full=force_full,
        verify_abort=verify_abort,
        keep_temp=keep_temp,
        external_symlink_policy=external_symlink_policy,
        on_mismatch=on_mismatch,
        mismatch_swap=mismatch_swap,
        on_verify_mismatch=on_verify_mismatch,
        mark_apps=mark_apps,
    )
