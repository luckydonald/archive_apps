from __future__ import annotations

import importlib.util
import importlib
import gzip
import io
import sys
import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
LIB_ROOT = ROOT / "scripts" / "°base" / "ai" / "references"
sys.path.insert(0, str(LIB_ROOT))
MODULE = importlib.import_module("°dllink_lib")
cli = importlib.import_module("°dllink_lib.cli")
html_converter = importlib.import_module("°dllink_lib.html")
providers = importlib.import_module("°dllink_lib.providers")
generic_provider = importlib.import_module("°dllink_lib.providers.generic")
config = importlib.import_module("°dllink_lib.config")
http = importlib.import_module("°dllink_lib.http")
links = importlib.import_module("°dllink_lib.links")

ENTRYPOINT_PATH = LIB_ROOT / "download-link.py"
SPEC = importlib.util.spec_from_file_location("download_link_entrypoint", ENTRYPOINT_PATH)
ENTRYPOINT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = ENTRYPOINT
SPEC.loader.exec_module(ENTRYPOINT)


class FakeFetch:
    def __init__(self, responses: dict[tuple[str, str], MODULE.Response]):
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def __call__(self, url: str, method: str = "GET") -> MODULE.Response:
        self.calls.append((url, method))
        return self.responses.get(
            (url, method),
            MODULE.Response(url=url, status=404, content=b"not found", content_type="text/plain"),
        )


class DownloadLinkPathTests(unittest.TestCase):
    def test_openai_html_prefers_markdown_candidate(self):
        url = "https://developers.openai.com/codex/config-advanced#profiles"
        md_url = "https://developers.openai.com/codex/config-advanced.md"
        fetch = FakeFetch({
            (md_url, "GET"): MODULE.Response(
                url=md_url,
                status=200,
                content=b"# Config advanced\n",
                content_type="text/markdown",
            )
        })

        plan = MODULE.resolve_plan(url, Path("ai/references"), fetch)
        plan = MODULE.markdown_plan_if_available(plan, Path("ai/references"), fetch)

        self.assertEqual(
            plan.output_path,
            Path("ai/references/https/developers.openai.com/codex/config-advanced.md"),
        )
        self.assertEqual(plan.download_url, md_url)
        self.assertFalse(plan.convert_html)

    def test_github_branch_blob_resolves_to_commit_permalink_and_raw_url(self):
        url = "https://github.com/j-shelfwood/bugsink-mcp/blob/main/README.md"
        sha = "3010d119bca3a48eced460e8f51f52cda4b51d5b"
        api = "https://api.github.com/repos/j-shelfwood/bugsink-mcp/git/ref/heads/main"
        fetch = FakeFetch({
            (api, "GET"): MODULE.Response(
                url=api,
                status=200,
                content=(f'{{"object": {{"sha": "{sha}"}}}}').encode(),
                content_type="application/json",
            )
        })

        plan = MODULE.resolve_plan(url, Path("ai/references"), fetch)

        self.assertEqual(
            plan.output_path,
            Path(
                "ai/references/https/github.com/j-shelfwood/bugsink-mcp/"
                f"blob/{sha}/README.md"
            ),
        )
        self.assertEqual(
            plan.download_url,
            f"https://raw.githubusercontent.com/j-shelfwood/bugsink-mcp/{sha}/README.md",
        )
        base = "ai/references/https/github.com/j-shelfwood/bugsink-mcp"
        self.assertEqual(plan.link_paths, (Path(f"{base}/blob/main/README.md"), Path(f"{base}/latest/README.md")))

    def test_github_commit_blob_does_not_call_api(self):
        sha = "3010d119bca3a48eced460e8f51f52cda4b51d5b"
        url = f"https://github.com/j-shelfwood/bugsink-mcp/blob/{sha}/README.md"
        fetch = FakeFetch({})

        plan = MODULE.resolve_plan(url, Path("ai/references"), fetch)

        self.assertEqual(fetch.calls, [])
        self.assertEqual(
            plan.download_url,
            f"https://raw.githubusercontent.com/j-shelfwood/bugsink-mcp/{sha}/README.md",
        )
        self.assertEqual(
            plan.link_paths,
            (Path("ai/references/https/github.com/j-shelfwood/bugsink-mcp/latest/README.md"),),
        )

    def test_github_branch_with_slash_tries_prefixes_until_ref_resolves(self):
        sha = "1234567890abcdef1234567890abcdef12345678"
        url = "https://github.com/owner/repo/blob/feature/docs/README.md"
        bad = "https://api.github.com/repos/owner/repo/git/ref/heads/feature"
        good = "https://api.github.com/repos/owner/repo/git/ref/heads/feature/docs"
        fetch = FakeFetch({
            (bad, "GET"): MODULE.Response(url=bad, status=404, content=b"{}", content_type="application/json"),
            (good, "GET"): MODULE.Response(
                url=good,
                status=200,
                content=(f'{{"object": {{"sha": "{sha}"}}}}').encode(),
                content_type="application/json",
            ),
        })

        plan = MODULE.resolve_plan(url, Path("ai/references"), fetch)

        self.assertEqual(plan.download_url, f"https://raw.githubusercontent.com/owner/repo/{sha}/README.md")
        self.assertEqual(
            plan.link_paths,
            (
                Path("ai/references/https/github.com/owner/repo/blob/feature/docs/README.md"),
                Path("ai/references/https/github.com/owner/repo/latest/README.md"),
            ),
        )

    def test_readthedocs_html_uses_footer_revision_filename(self):
        url = "https://pyte.readthedocs.io/en/latest/api.html"
        html = """
        <html><body><main><h1>API reference</h1></main>
        <span class="commit">Revision <code>a267d4ae</code>.</span>
        </body></html>
        """
        fetch = FakeFetch({
            ("https://pyte.readthedocs.io/en/latest/api.md", "GET"): MODULE.Response(
                url="https://pyte.readthedocs.io/en/latest/api.md",
                status=404,
                content=b"",
                content_type="text/plain",
            ),
            ("https://pyte.readthedocs.io/en/latest/api.html.md", "GET"): MODULE.Response(
                url="https://pyte.readthedocs.io/en/latest/api.html.md",
                status=404,
                content=b"",
                content_type="text/plain",
            ),
            (url, "GET"): MODULE.Response(url=url, status=200, content=html.encode(), content_type="text/html"),
        })

        plan = MODULE.resolve_plan(url, Path("ai/references"), fetch)
        plan = MODULE.markdown_plan_if_available(plan, Path("ai/references"), fetch)
        path, content = MODULE.download(plan, fetch)

        self.assertEqual(
            path,
            Path("ai/references/https/pyte.readthedocs.io/en/latest/api.html/a267d4ae.md"),
        )
        self.assertIn(b"API reference", content)

    def test_html_fallback_writes_underscore_markdown(self):
        url = "https://www.equestriadaily.com/2016/02/oc-pony-spotlight-littlepip.html"
        fetch = FakeFetch({
            ("https://www.equestriadaily.com/2016/02/oc-pony-spotlight-littlepip.md", "GET"): MODULE.Response(
                url="https://www.equestriadaily.com/2016/02/oc-pony-spotlight-littlepip.md",
                status=404,
                content=b"",
            ),
            ("https://www.equestriadaily.com/2016/02/oc-pony-spotlight-littlepip.html.md", "GET"): MODULE.Response(
                url="https://www.equestriadaily.com/2016/02/oc-pony-spotlight-littlepip.html.md",
                status=404,
                content=b"",
            ),
            (url, "GET"): MODULE.Response(
                url=url,
                status=200,
                content=b"<html><body><h1>Spotlight</h1></body></html>",
                content_type="text/html",
            ),
        })

        plan = MODULE.resolve_plan(url, Path("ai/references"), fetch)
        plan = MODULE.markdown_plan_if_available(plan, Path("ai/references"), fetch)
        path, _ = MODULE.download(plan, fetch)

        self.assertEqual(
            path,
            Path(
                "ai/references/https/www.equestriadaily.com/2016/02/"
                "oc-pony-spotlight-littlepip.html/_.md"
            ),
        )

    def test_cli_prefers_markdown_from_github_edit_link(self) -> None:
        url = "https://docs.example.com/guide.html"
        sha = "a" * 40
        edit_url = f"https://github.com/owner/repo/edit/{sha}/docs/guide.md"
        raw_url = f"https://raw.githubusercontent.com/owner/repo/{sha}/docs/guide.md"
        html = f'<h1>Rendered guide</h1><a href="{edit_url}"><span>Edit this page</span> on GitHub</a>'
        markdown = b"# Source guide\n"
        fetch = FakeFetch({
            (url, "GET"): MODULE.Response(url, 200, html.encode(), "text/html"),
            (raw_url, "GET"): MODULE.Response(raw_url, 200, markdown, "text/plain"),
        })

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(cli, "fetch_url", fetch):
            output_root = Path(directory)
            exit_code = cli.main([url, "--output-root", directory, "--no-git", "--no-open-ide"])
            self.assertEqual(exit_code, 0)
            self.assertEqual((output_root / "https/docs.example.com/guide.html/_.md").read_bytes(), markdown)
        # end with

        self.assertEqual(fetch.calls, [
            ("https://docs.example.com/guide.md", "GET"),
            ("https://docs.example.com/guide.html.md", "GET"),
            (url, "GET"),
            (raw_url, "GET"),
        ])
    # end def

    def test_edit_href_resolves_branch_and_accepts_mdx(self) -> None:
        url = "https://docs.example.com/guide/"
        sha = "b" * 40
        api = "https://api.github.com/repos/owner/repo/git/ref/heads/main"
        raw_url = f"https://raw.githubusercontent.com/owner/repo/{sha}/docs/guide.mdx"
        html = b'<a aria-label="Edit" href="//github.com/owner/repo/edit/main/docs/guide.mdx?plain=1#L4"></a>'
        fetch = FakeFetch({
            (url, "GET"): MODULE.Response(url, 200, html, "text/html"),
            (api, "GET"): MODULE.Response(api, 200, f'{{"object":{{"sha":"{sha}"}}}}'.encode(), "application/json"),
            (raw_url, "GET"): MODULE.Response(raw_url, 200, b"## MDX\n", "text/plain"),
        })

        plan = MODULE.resolve_plan(url, Path("ai/references"), fetch)
        result = MODULE.download(plan, fetch)

        self.assertEqual(result.path, plan.output_path)
        self.assertEqual(result.content, b"## MDX\n")
        self.assertEqual(result.downloaded_url, raw_url)
        self.assertEqual(fetch.calls, [(url, "GET"), (api, "GET"), (raw_url, "GET")])
    # end def

    def test_html_conversion_survives_unusable_edit_link(self) -> None:
        url = "https://docs.example.com/guide/"
        sha = "c" * 40
        edit_url = f"https://github.com/owner/repo/edit/{sha}/guide.md"
        raw_url = f"https://raw.githubusercontent.com/owner/repo/{sha}/guide.md"
        cases = [
            ("No edit link", "", None),
            ("Non-GitHub link", edit_url.replace("github.com", "github.example"), None),
            ("reStructuredText source", edit_url.removesuffix(".md") + ".rst", None),
            ("Notebook source", edit_url.removesuffix(".md") + ".ipynb", None),
            ("Raw source is missing", edit_url, MODULE.Response(raw_url, 404, b"missing", "text/plain")),
            ("Raw source is HTML", edit_url, MODULE.Response(raw_url, 200, b"<html>error</html>", "text/html")),
        ]
        for name, href, raw_response in cases:
            with self.subTest(name=name):
                html = "<h1>Rendered guide</h1>"
                if href:
                    html += f'<a href="{href}">Edit this page on GitHub</a>'
                # end if
                responses = {(url, "GET"): MODULE.Response(url, 200, html.encode(), "text/html")}
                if raw_response is not None:
                    responses[(raw_url, "GET")] = raw_response
                # end if
                fetch = FakeFetch(responses)
                plan = MODULE.resolve_plan(url, Path("ai/references"), fetch)
                result = MODULE.download(plan, fetch)
                self.assertEqual(result.path, plan.output_path)
                self.assertEqual(result.content, html_converter.html_to_markdown(html).encode())
                self.assertEqual(result.downloaded_url, url)
                expected_calls = [(url, "GET")]
                if raw_response is not None:
                    expected_calls.append((raw_url, "GET"))
                # end if
                self.assertEqual(fetch.calls, expected_calls)
            # end with
        # end for
    # end def

    def test_cloudflare_challenge_falls_back_to_latest_archive_snapshot(self):
        url = "https://nixos.wiki/wiki/NixOS_on_ARM/Raspberry_Pi"
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx?"
            "url=https%3A%2F%2Fnixos.wiki%2Fwiki%2FNixOS_on_ARM%2FRaspberry_Pi&"
            "output=json&filter=statuscode%3A200&filter=mimetype%3Atext%2Fhtml&"
            "fl=timestamp%2Coriginal%2Cstatuscode&limit=1&sort=reverse"
        )
        timestamp = "20250105160600"
        archive_url = f"https://web.archive.org/web/{timestamp}id_/{url}"
        fetch = FakeFetch({
            (url, "GET"): MODULE.Response(url=url, status=403, content=b"<title>Just a moment...</title>"),
            (cdx_url, "GET"): MODULE.Response(
                url=cdx_url,
                status=200,
                content=(
                    '[["timestamp","original","statuscode"],'
                    '["20250105160600","https://nixos.wiki/wiki/NixOS_on_ARM/Raspberry_Pi","200"]]'
                ).encode(),
            ),
            (archive_url, "GET"): MODULE.Response(
                url=archive_url,
                status=200,
                content=b"<html><body><h1>Raspberry Pi</h1></body></html>",
                content_type="text/html",
            ),
        })

        plan = MODULE.resolve_plan(url, Path("ai/references"), fetch)
        result = MODULE.download(plan, fetch)

        self.assertEqual(result.archive_timestamp, timestamp)
        self.assertEqual(result.downloaded_url, archive_url)
        self.assertIn(b"Raspberry Pi", result.content)

    @mock.patch.object(generic_provider, "git_ls_remote_sha", return_value="abcdefabcdefabcdefabcdefabcdefabcdefabcd")
    def test_selfhosted_gitlab_shape_resolves_without_gitlab_hostname(self, _ls_remote):
        url = "https://git.example.test/group/project/-/blob/main/docs/readme.md"

        plan = MODULE.resolve_plan(url, Path("ai/references"), FakeFetch({}))

        self.assertEqual(
            plan.output_path,
            Path(
                "ai/references/https/git.example.test/group/project/-/blob/"
                "abcdefabcdefabcdefabcdefabcdefabcdefabcd/docs/readme.md"
            ),
        )
        self.assertEqual(
            plan.download_url,
            "https://git.example.test/group/project/-/raw/main/docs/readme.md",
        )


class DownloadLinkSymlinkTests(unittest.TestCase):
    def test_write_symlink_is_relative_and_resolves_to_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "blob" / "abc" / "docs" / "x.md"
            target.parent.mkdir(parents=True)
            target.write_text("x")
            link = root / "blob" / "main" / "docs" / "x.md"

            links.write_symlink(target, link)

            self.assertTrue(link.is_symlink())
            self.assertEqual(str(link.readlink()), "../../abc/docs/x.md")
            self.assertEqual(link.read_text(), "x")

    def test_write_symlink_overwrites_older_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old, new = root / "blob" / "old.md", root / "blob" / "new.md"
            old.parent.mkdir(parents=True)
            old.write_text("old")
            new.write_text("new")
            link = root / "latest" / "x.md"

            links.write_symlink(old, link)
            links.write_symlink(new, link)

            self.assertEqual(link.read_text(), "new")

    def test_write_symlink_refuses_real_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "t.md"
            target.write_text("t")
            (root / "dir").mkdir()

            with self.assertRaises(MODULE.DownloadError):
                links.write_symlink(target, root / "dir")

    def test_non_github_plan_has_no_links(self):
        plan = MODULE.resolve_plan("https://example.com/docs/page.md", Path("ai/references"), FakeFetch({}))
        self.assertEqual(plan.link_paths, ())

    def test_github_blob_ignores_plain_and_preview_params(self):
        sha = "3010d119bca3a48eced460e8f51f52cda4b51d5b"
        base = f"https://github.com/mdn/content/blob/{sha}/files/index.md"
        expected = MODULE.resolve_plan(base, Path("ai/references"), FakeFetch({}))
        for query in ("?plain=1", "?preview=1", "?plain=1&preview=1"):
            with self.subTest(query=query):
                plan = MODULE.resolve_plan(base + query, Path("ai/references"), FakeFetch({}))
                self.assertEqual(plan, expected)
            # end with
        # end for

    def test_github_other_page_drops_view_params_but_keeps_the_rest(self):
        plan = MODULE.resolve_plan(
            "https://github.com/mdn/content/issues?plain=1&q=is%3Aopen&preview=1",
            Path("ai/references"),
            FakeFetch({}),
        )
        self.assertEqual(plan.download_url, "https://github.com/mdn/content/issues?q=is%3Aopen")

    def test_non_github_host_keeps_plain_param(self):
        plan = MODULE.resolve_plan("https://example.com/docs/page.md?plain=1", Path("ai/references"), FakeFetch({}))
        self.assertEqual(plan.download_url, "https://example.com/docs/page.md?plain=1")

    def test_main_creates_github_symlinks_even_without_git(self):
        sha = "3010d119bca3a48eced460e8f51f52cda4b51d5b"
        url = "https://github.com/owner/repo/blob/main/docs/a.md"
        api = "https://api.github.com/repos/owner/repo/git/ref/heads/main"
        raw = f"https://raw.githubusercontent.com/owner/repo/{sha}/docs/a.md"
        fetch = FakeFetch({
            (api, "GET"): MODULE.Response(url=api, status=200, content=f'{{"object": {{"sha": "{sha}"}}}}'.encode()),
            (raw, "GET"): MODULE.Response(url=raw, status=200, content=b"# A\n", content_type="text/plain"),
        })

        with tempfile.TemporaryDirectory() as tmp:
            refs = Path(tmp) / "refs"
            with mock.patch.object(cli, "fetch_url", fetch):
                status = cli.main(["--output-root", str(refs), "--no-git", "--no-open-ide", url])

            repo = refs / "https" / "github.com" / "owner" / "repo"
            self.assertEqual(status, 0)
            self.assertEqual((repo / "blob" / "main" / "docs" / "a.md").read_text(), "# A\n")
            self.assertEqual((repo / "latest" / "docs" / "a.md").read_text(), "# A\n")
            self.assertEqual(str((repo / "latest" / "docs" / "a.md").readlink()), f"../../blob/{sha}/docs/a.md")

    def test_main_git_add_and_commit_include_symlinks(self):
        sha = "3010d119bca3a48eced460e8f51f52cda4b51d5b"
        url = f"https://github.com/owner/repo/blob/{sha}/a.md"
        raw = f"https://raw.githubusercontent.com/owner/repo/{sha}/a.md"
        fetch = FakeFetch({(raw, "GET"): MODULE.Response(url=raw, status=200, content=b"# A\n", content_type="text/plain")})
        calls: list[list[str]] = []

        def fake_run(cmd, capture_output=False, text=False):
            calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.object(cli.subprocess, "run", side_effect=fake_run),
                mock.patch.object(cli, "fetch_url", fetch),
            ):
                status = cli.main(["--output-root", str(Path(tmp) / "refs"), "--no-open-ide", url])
            # end with

            latest = str((Path(tmp) / "refs" / "https" / "github.com" / "owner" / "repo" / "latest" / "a.md").resolve())
            self.assertEqual(status, 0)
            self.assertIn(latest, calls[0])
            self.assertIn(latest, calls[1])


class DownloadLinkInputTests(unittest.TestCase):
    def test_decode_content_decompresses_gzip(self):
        self.assertEqual(http.decode_content(gzip.compress(b"# Page\n"), "gzip"), b"# Page\n")

    def test_open_ide_aliases_parse_to_open_ide(self):
        for option in ("--open-ide", "--open", "--ide", "--ide-open"):
            with self.subTest(option=option):
                args = cli.parse_args([f"{option}=code", "https://example.com/docs/page.md"])
                self.assertEqual(args.open_ide, "code")

    def test_disable_aliases_parse_to_existing_flags(self):
        args = cli.parse_args(
            [
                "--no-git",
                "--no-add-git",
                "--no-ide",
                "--no-ide-open",
                "https://example.com/docs/page.md",
            ]
        )

        self.assertTrue(args.no_git_add)
        self.assertTrue(args.no_git_commit)
        self.assertTrue(args.no_open_ide)

    def test_no_git_implies_no_git_add_and_no_git_commit(self):
        args = cli.parse_args(["--no-git", "https://example.com/docs/page.md"])

        self.assertTrue(args.no_git_add)
        self.assertTrue(args.no_git_commit)

    def test_no_git_add_alone_does_not_imply_no_git_commit(self):
        args = cli.parse_args(["--no-git-add", "https://example.com/docs/page.md"])

        self.assertTrue(args.no_git_add)
        self.assertFalse(args.no_git_commit)

    def test_empty_non_tty_stdin_explains_usage(self):
        stdin = io.StringIO("")
        stdin.isatty = lambda: False  # type: ignore[method-assign]
        with mock.patch.object(cli.sys, "stdin", stdin):
            with self.assertRaisesRegex(MODULE.DownloadError, "download-link.py URL"):
                MODULE.read_url_from_input(None)

    def test_main_writes_file(self):
        url = "https://example.com/docs/page.md"
        response = MODULE.Response(url=url, status=200, content=b"# Page\n", content_type="text/markdown")

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(cli, "fetch_url", FakeFetch({(url, "GET"): response})):
                status = MODULE.main(
                    ["--output-root", str(Path(tmp) / "refs"), "--no-git", "--no-open-ide", url]
                )

            self.assertEqual(status, 0)
            self.assertEqual(
                (Path(tmp) / "refs" / "https" / "example.com" / "docs" / "page.md").read_text(),
                "# Page\n",
            )

    def test_main_adds_commits_and_opens_by_default(self):
        url = "https://example.com/docs/page.md"
        response = MODULE.Response(url=url, status=200, content=b"# Page\n", content_type="text/markdown")

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = config.repo_root()
            calls: list[list[str]] = []

            def fake_run(cmd, capture_output=False, text=False):
                calls.append(list(cmd))
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with mock.patch.object(cli, "load_download_link_settings", return_value=config.DownloadLinkSettings(ide="pycharm")):
                with mock.patch.object(cli.subprocess, "run", side_effect=fake_run):
                    with mock.patch.object(cli, "fetch_url", FakeFetch({(url, "GET"): response})):
                        status = cli.main(["--output-root", str(Path(tmp) / "refs"), url])

            self.assertEqual(status, 0)
            self.assertEqual(calls[0][:4], ["git", "-C", str(repo_root), "add"])
            self.assertEqual(calls[1][:4], ["git", "-C", str(repo_root), "commit"])
            self.assertEqual(calls[2][0], "pycharm")
            self.assertEqual(calls[2][-1], str(Path(tmp) / "refs" / "https" / "example.com" / "docs" / "page.md"))

    def test_open_ide_override_wins_over_settings(self):
        url = "https://example.com/docs/page.md"
        response = MODULE.Response(url=url, status=200, content=b"# Page\n", content_type="text/markdown")

        with tempfile.TemporaryDirectory() as tmp:
            calls: list[list[str]] = []

            def fake_run(cmd, capture_output=False, text=False):
                calls.append(list(cmd))
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with mock.patch.object(cli, "load_download_link_settings", return_value=config.DownloadLinkSettings(ide="pycharm")):
                with mock.patch.object(cli.subprocess, "run", side_effect=fake_run):
                    with mock.patch.object(cli, "fetch_url", FakeFetch({(url, "GET"): response})):
                        status = cli.main(["--output-root", str(Path(tmp) / "refs"), "--open-ide=code", url])

            self.assertEqual(status, 0)
            self.assertEqual(calls[2][0], "code")
            self.assertEqual(calls[2][-1], str(Path(tmp) / "refs" / "https" / "example.com" / "docs" / "page.md"))

    def test_no_open_ide_wins_over_override_and_no_git_skips_git(self):
        url = "https://example.com/docs/page.md"
        response = MODULE.Response(url=url, status=200, content=b"# Page\n", content_type="text/markdown")

        with tempfile.TemporaryDirectory() as tmp:
            calls: list[list[str]] = []

            def fake_run(cmd, capture_output=False, text=False):
                calls.append(list(cmd))
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with mock.patch.object(cli, "load_download_link_settings", return_value=config.DownloadLinkSettings(ide="pycharm")):
                with mock.patch.object(cli.subprocess, "run", side_effect=fake_run):
                    with mock.patch.object(cli, "fetch_url", FakeFetch({(url, "GET"): response})):
                        status = cli.main(
                            [
                                "--output-root",
                                str(Path(tmp) / "refs"),
                                "--no-git",
                                "--no-open-ide",
                                "--open-ide=code",
                                url,
                            ]
                        )

            self.assertEqual(status, 0)
            self.assertEqual(calls, [])

    def test_entrypoint_exposes_main(self):
        self.assertIs(ENTRYPOINT.main, cli.main)


if __name__ == "__main__":
    unittest.main()
