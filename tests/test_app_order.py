import plistlib
from pathlib import Path

from archive_apps.archive import app_identity, order_apps


def _app(root: Path, name: str, version: str, mobile: bool = False, plist: bool = True) -> Path:
    app = root / f"{name}.app"
    if plist:
        info = app / ("WrappedBundle" if mobile else "Contents") / "Info.plist"
        info.parent.mkdir(parents=True)
        info.write_bytes(plistlib.dumps({"CFBundleName": name, "CFBundleShortVersionString": version}))
    else:
        app.mkdir(parents=True)
    return app


def test_app_identity(tmp_path):
    assert app_identity(_app(tmp_path, "Foo", "1.0")) == ("Foo", "", "1.0")
    assert app_identity(_app(tmp_path, "Bar", "2.0", mobile=True)) == ("Bar", "mobile@", "2.0")
    assert app_identity(_app(tmp_path, "Baz", "3.0", plist=False)) is None


def test_unzipped_first_and_no_plist_last(tmp_path):
    apps_dir, dest = tmp_path / "apps", tmp_path / "dest"
    apps_dir.mkdir()
    dest.mkdir()
    zipped = [_app(apps_dir, f"Zipped{i}", "1.0") for i in range(5)]
    zipped.append(_app(apps_dir, "ZippedMobile", "1.0", mobile=True))
    unzipped = [_app(apps_dir, f"New{i}", "1.0") for i in range(5)]
    old_version = _app(apps_dir, "Old", "2.0")  # only an older version is backed up
    broken = _app(apps_dir, "Broken", "1.0", plist=False)
    for i in range(5):
        (dest / f"Zipped{i}.app@1.0.zip").write_bytes(b"x")
    (dest / "ZippedMobile.app@mobile@1.0.zip").write_bytes(b"x")
    (dest / "Old.app@1.0.zip").write_bytes(b"x")

    for _ in range(20):
        ordered = order_apps(zipped + unzipped + [old_version, broken], dest)
        assert sorted(ordered) == sorted(zipped + unzipped + [old_version, broken])
        assert set(ordered[:6]) == set(unzipped + [old_version])
        assert set(ordered[6:-1]) == set(zipped)
        assert ordered[-1] == broken
