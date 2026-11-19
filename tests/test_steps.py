from pathlib import Path

import pytest

from archive_apps import steps
from archive_apps.cli import STEPS, RunContext, parse_args, resolve_steps
from archive_apps.filters import app_matches, parse_app_filter, zip_matches
from archive_apps.utils import sha256_file
from archive_apps.verify import classify_zip, is_indexed


def cfg_of(tmp_path: Path, *args: str):
    return parse_args([*args, str(tmp_path / "dest")])


def test_default_runs_every_step(tmp_path):
    assert cfg_of(tmp_path).steps == frozenset(STEPS)


def test_steps_and_skip_steps(tmp_path):
    assert cfg_of(tmp_path, "--steps=archive,new").steps == {"archive", "new"}
    assert cfg_of(tmp_path, "--skip-steps=rest").steps == set(STEPS) - {"rest"}
    assert cfg_of(tmp_path, "--steps=all", "--skip-steps=archive,created").steps == {"changed", "new", "rest"}


def test_aliases_select_only_their_steps(tmp_path):
    assert cfg_of(tmp_path, "--verify-new").steps == {"new"}
    assert cfg_of(tmp_path, "--verify-changed").steps == {"changed"}
    assert cfg_of(tmp_path, "--verify-zips").steps == {"changed", "new", "rest"}
    assert cfg_of(tmp_path, "--verify-new", "--verify-changed").steps == {"new", "changed"}
    assert cfg_of(tmp_path, "--verify-new", "--steps=archive").steps == {"new", "archive"}


def test_verify_zip_alias_expands(tmp_path):
    cfg = cfg_of(tmp_path, "--verify-zip=Xcode")
    assert cfg.app_filters == ["Xcode"]
    assert cfg.force_full
    assert cfg.steps == {"changed", "new", "rest"}


def test_app_and_force_full_flags(tmp_path):
    cfg = cfg_of(tmp_path, "--app=A", "--app=B.app", "--force-full")
    assert cfg.app_filters == ["A", "B.app"]
    assert cfg.force_full
    assert cfg.steps == frozenset(STEPS)


def test_unknown_step_and_empty_selection_exit(tmp_path):
    with pytest.raises(SystemExit):
        cfg_of(tmp_path, "--steps=bogus")
    with pytest.raises(SystemExit):
        cfg_of(tmp_path, "--steps=new", "--skip-steps=new")
    assert resolve_steps(None, set(), {"rest"}) == set(STEPS) - {"rest"}


@pytest.mark.parametrize("arg,expected", [
    ("Xcode", ("app", "Xcode")),
    ("Xcode.app", ("app", "Xcode")),
    ("/Applications/Xcode.app", ("app", "Xcode")),
    ("/Applications/Xcode.app/Contents/MacOS/Xcode", ("app", "Xcode")),
    ("Xcode.app@15.4.zip", ("zip", "Xcode.app@15.4.zip")),
    ("/some/dir/Foo.app@1.0.zip", ("zip", "Foo.app@1.0.zip")),
])
def test_parse_app_filter(arg, expected):
    assert parse_app_filter(arg) == expected


def test_zip_matches():
    assert zip_matches("Xcode.app@15.4.zip", [])
    assert zip_matches("Xcode.app@15.4.zip", ["Xcode"])
    assert zip_matches("Xcode.app@mobile@1.0.zip", ["Xcode.app"])
    assert not zip_matches("Xcode Helper.app@1.0.zip", ["Xcode"])
    assert zip_matches("Foo.app@1.0.zip", ["/x/Foo.app@1.0.zip"])
    assert not zip_matches("Foo.app@1.1.zip", ["Foo.app@1.0.zip"])


def test_app_matches():
    app = Path("/Applications/Visual Studio Code.app")
    assert app_matches(app, "Code", "Code.app@1.0.zip", [])
    assert app_matches(app, "Code", "Code.app@1.0.zip", ["Code"])
    assert app_matches(app, "Code", "Code.app@1.0.zip", ["Visual Studio Code.app"])
    assert app_matches(app, "Code", "Code.app@1.0.zip", ["Code.app@1.0.zip"])
    assert not app_matches(app, "Code", "Code.app@1.0.zip", ["Other"])


def make_zip(dest: Path, name: str, checksums: bool = True) -> Path:
    zip_path = dest / f"{name}.zip"
    zip_path.write_bytes(name.encode())
    if checksums:
        (dest / f"{name}.checksums.txt").write_text("abc  file\n")
    return zip_path


def index_of(*zips: Path) -> dict[str, str]:
    index: dict[str, str] = {}
    for z in zips:
        index[z.name] = sha256_file(z)
        checksumfile = z.with_name(z.stem + ".checksums.txt")
        if checksumfile.exists():
            index[checksumfile.name] = sha256_file(checksumfile)
    return index


def test_classify_zip(tmp_path):
    ctx = RunContext(cfg=cfg_of(tmp_path))
    dest = ctx.cfg.dest
    unchanged = make_zip(dest, "A.app@1")
    changed_zip = make_zip(dest, "B.app@1")
    changed_checks = make_zip(dest, "C.app@1")
    unindexed = make_zip(dest, "D.app@1")
    no_checks = make_zip(dest, "E.app@1", checksums=False)
    index = index_of(unchanged, changed_zip, changed_checks, no_checks)
    index["E.app@1.checksums.txt"] = "deadbeef"  # indexed, but the file is gone
    changed_zip.write_bytes(b"different")
    changed_checks.with_name("C.app@1.checksums.txt").write_text("other\n")

    assert classify_zip(unchanged, index, ctx) == "unchanged"
    assert classify_zip(changed_zip, index, ctx) == "changed"
    assert classify_zip(changed_checks, index, ctx) == "changed"
    assert classify_zip(unindexed, index, ctx) == "new"
    assert classify_zip(no_checks, index, ctx) == "new"
    assert is_indexed(unchanged, index)
    assert not is_indexed(no_checks, index)


def test_order_zips_installed_first():
    zips = [Path(f"{n}.app@1.zip") for n in ("Gone1", "Here", "Gone2", "Also")] + [Path("Here.app@0.9.zip")]
    for _ in range(20):
        ordered = steps.order_zips(zips, {"Here.app@", "Also.app@"})
        assert sorted(ordered) == sorted(zips)
        assert {z.name for z in ordered[:3]} == {"Here.app@1.zip", "Here.app@0.9.zip", "Also.app@1.zip"}


def test_render_checklist():
    states = {"archive": "done", "created": "running", "changed": "pending", "new": "pending", "rest": "skipped"}
    text = steps.render_checklist(states, {"archive": "3 zip(s) created"})
    lines = text.splitlines()
    assert lines[0] == "Steps:"
    assert lines[1].startswith("  [x] 1 archive") and lines[1].endswith("3 zip(s) created")
    assert lines[2].startswith("  [>] 2 verify created")
    assert lines[3].startswith("  [ ] 3 verify changed")
    assert lines[5].startswith("  [-] 5 verify rest")
    states["rest"] = "pending"
    assert "safe to interrupt" in steps.render_checklist(states, {}).splitlines()[5]


def stub_steps(monkeypatch, calls: list[str]) -> None:
    monkeypatch.setattr(steps, "open_index_scratch", lambda ctx: calls.append("scratch"))
    monkeypatch.setattr(steps, "run_archive", lambda ctx: calls.append("archive"))
    monkeypatch.setattr(steps, "verify_created", lambda ctx: calls.append("created") or (0, 0, 0))
    monkeypatch.setattr(steps, "finalize_archive", lambda ctx: calls.append("finalize"))
    monkeypatch.setattr(steps, "installed_prefixes", lambda ctx: set())
    monkeypatch.setattr(steps, "verify_changed", lambda ctx, zips, index: calls.append("changed") or steps.Counts())
    monkeypatch.setattr(
        steps, "verify_zip_list", lambda ctx, zips, label: calls.append(label.lower()) or steps.Counts(),
    )


def test_steps_run_in_priority_order(tmp_path, monkeypatch):
    calls: list[str] = []
    stub_steps(monkeypatch, calls)
    steps.run_steps(RunContext(cfg=cfg_of(tmp_path)))
    assert calls == ["scratch", "archive", "created", "finalize", "changed", "new", "rest"]


def test_skipped_steps_are_not_run(tmp_path, monkeypatch):
    calls: list[str] = []
    stub_steps(monkeypatch, calls)
    steps.run_steps(RunContext(cfg=cfg_of(tmp_path, "--verify-new")))
    assert calls == ["scratch", "new"]
    calls.clear()
    steps.run_steps(RunContext(cfg=cfg_of(tmp_path, "--steps=archive")))
    assert calls == ["scratch", "archive", "finalize"]


def test_failure_gives_exit_code_and_summary(tmp_path, monkeypatch, capsys):
    calls: list[str] = []
    stub_steps(monkeypatch, calls)
    ctx = RunContext(cfg=cfg_of(tmp_path, "--steps=created"))
    monkeypatch.setattr(
        steps, "verify_created", lambda c: c.verify_failure_summary.append(("X.zip", "boom")) or (0, 1, 0),
    )
    with pytest.raises(SystemExit) as exc:
        steps.run_steps(ctx)
    assert exc.value.code == 1
    assert "X.zip" in capsys.readouterr().out


def test_summary_printed_on_interrupt(tmp_path, monkeypatch, capsys):
    calls: list[str] = []
    stub_steps(monkeypatch, calls)
    ctx = RunContext(cfg=cfg_of(tmp_path))
    ctx.verify_failure_summary.append(("Y.zip", "bad"))

    def interrupted(c, zips, label):
        raise KeyboardInterrupt

    monkeypatch.setattr(steps, "verify_zip_list", interrupted)
    with pytest.raises(KeyboardInterrupt):
        steps.run_steps(ctx)
    assert "Y.zip" in capsys.readouterr().out
