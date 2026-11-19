from __future__ import annotations

from pathlib import Path


def parse_app_filter(arg: str) -> tuple[str, str]:
    """Return `("zip", zip file name)` or `("app", app name)` for an `--app` value.

    Accepted forms: `Xcode`, `Xcode.app`, `/Applications/Xcode.app`, `/Applications/Xcode.app/Contents/…`,
    `Xcode.app@15.4.zip`, and the full path of a zip.
    """
    if arg.endswith(".zip"):
        return "zip", Path(arg).name
    # end if
    if ".app/" in arg:
        return "app", Path(arg.split(".app/")[0] + ".app").name.removesuffix(".app")
    # end if
    if arg.endswith(".app"):
        return "app", Path(arg).name.removesuffix(".app")
    # end if
    return "app", arg
# end def


def zip_matches(zipname: str, filters: list[str]) -> bool:
    """Whether a zip file name is selected by the `--app` filters (no filters selects everything)."""
    if not filters:
        return True
    # end if
    for arg in filters:
        kind, value = parse_app_filter(arg)
        if kind == "zip" and zipname == value:
            return True
        # end if
        if kind == "app" and zipname.startswith(f"{value}.app@"):
            return True
        # end if
    # end for
    return False
# end def


def app_matches(app: Path, bundle_name: str | None, zipname: str | None, filters: list[str]) -> bool:
    """Whether a live app is selected by the `--app` filters, by its folder name, its `CFBundleName` or the name of its zip."""
    if not filters:
        return True
    # end if
    for arg in filters:
        kind, value = parse_app_filter(arg)
        if kind == "zip" and zipname == value:
            return True
        # end if
        if kind == "app" and value in (app.stem, bundle_name):
            return True
        # end if
    # end for
    return False
# end def
