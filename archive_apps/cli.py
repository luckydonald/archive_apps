from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    dest: Path
    local_cache: Path | None
    verify_mode: str            # "none" | "zips" | "new" | "changed"
    verify_zip_arg: str         # "" or the --verify-zip= value
    verify_abort: bool
    keep_temp: bool
    external_symlink_policy: str   # "archive" | "skip" | "abort"
    on_mismatch: str | None        # None | "overwrite" | "both" | "skip"
    mismatch_swap: str | None      # None | "yes" | "no"
    on_verify_mismatch: str | None  # None | "retry" | "delete" | "keep"


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
    deferred_mismatches: list[MismatchTask] = field(default_factory=list)
    deferred_swaps: list[SwapTask] = field(default_factory=list)
    deferred_verify_mismatches: list[VerifyMismatchTask] = field(default_factory=list)


def parse_args(argv: list[str]) -> Config:
    verify_mode = "none"
    verify_zip_arg = ""
    dest_arg = ""
    local_cache_arg: str | None = None
    external_symlink_policy = "archive"
    verify_abort = False
    keep_temp = False
    on_mismatch: str | None = None
    mismatch_swap: str | None = None
    on_verify_mismatch: str | None = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help"):
            print("Usage: archive-apps [options] [destination]")
            print("  --verify-zip=APP  verify zip(s) for a specific app or exact zip file")
            print("                    APP forms: Xcode / Xcode.app / /Applications/Xcode.app")
            print("                              Xcode.app@15.4.zip / full/path/to/Foo.zip")
            print("                    matches all version zips for that app; exits after verifying")
            print("  --verify-zips     extract and verify all zips against their checksum files")
            print("  --verify-new      verify only zips/checksums not yet in the checksum index")
            print("  --verify-changed  verify zips whose index hash differs from current file")
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
            print("  destination       archive directory (default: /Users/Shared/App Versions)")
            sys.exit(0)
        elif arg == "--verify-zip":
            print("Error: --verify-zip requires a value: --verify-zip=APP", file=sys.stderr)
            sys.exit(1)
        elif arg.startswith("--verify-zip="):
            verify_zip_arg = arg[len("--verify-zip="):]
        elif arg == "--verify-zips":
            verify_mode = "zips"
        elif arg == "--verify-new":
            verify_mode = "new"
        elif arg == "--verify-changed":
            verify_mode = "changed"
        elif arg == "--verify-abort":
            verify_abort = True
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

    if verify_zip_arg and verify_mode != "none":
        print(
            "Error: --verify-zip cannot be combined with --verify-zips/--verify-new/--verify-changed",
            file=sys.stderr,
        )
        sys.exit(1)

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
        verify_mode=verify_mode,
        verify_zip_arg=verify_zip_arg,
        verify_abort=verify_abort,
        keep_temp=keep_temp,
        external_symlink_policy=external_symlink_policy,
        on_mismatch=on_mismatch,
        mismatch_swap=mismatch_swap,
        on_verify_mismatch=on_verify_mismatch,
    )
