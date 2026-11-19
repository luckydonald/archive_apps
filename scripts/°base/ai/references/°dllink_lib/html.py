from __future__ import annotations

import html.parser
import re
import urllib.parse
from pathlib import Path

from .models import DownloadPlan


class EditLinkParser(html.parser.HTMLParser):
    def __init__(self, page_url: str) -> None:
        super().__init__()
        self.page_url = page_url
        self.href: str | None = None
        self.text: list[str] = []
        self.blob_url: str | None = None
    # end def

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a" and self.blob_url is None:
            self.href = dict(attrs).get("href")
            self.text.clear()
        # end if
    # end def

    def handle_data(self, data: str) -> None:
        if self.href:
            self.text.append(data)
        # end if
    # end def

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self.href:
            return
        # end if
        href, self.href = self.href, None
        try:
            parts = urllib.parse.urlsplit(urllib.parse.urljoin(self.page_url, href))
        except ValueError:
            return
        if parts.scheme not in {"http", "https"} or parts.netloc.lower() != "github.com":
            return
        # end if
        path = parts.path.split("/")
        if len(path) < 6 or not path[-1].lower().endswith((".md", ".mdx")):
            return
        # end if
        label = " ".join("".join(self.text).split())
        if path[3] == "edit" or (
            path[3] == "blob" and re.fullmatch(r"Edit (?:this page )?on GitHub", label, re.IGNORECASE)
        ):
            path[3] = "blob"
            self.blob_url = urllib.parse.urlunsplit(parts._replace(path="/".join(path), query="", fragment=""))
        # end if
    # end def
# end class


class RevisionParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_code = False
        self.revision: str | None = None
        self._recent_text = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "code" and "Revision" in self._recent_text[-80:]:
            self.in_code = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "code":
            self.in_code = False

    def handle_data(self, data: str) -> None:
        if self.in_code and self.revision is None:
            value = data.strip()
            if re.fullmatch(r"[0-9A-Za-z._-]+", value):
                self.revision = value
        self._recent_text = (self._recent_text + data)[-200:]


def readthedocs_revision(html: str) -> str | None:
    parser = RevisionParser()
    parser.feed(html)
    return parser.revision


class TextHTMLParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"p", "br", "div", "section", "article", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text + " ")

    def markdown(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + "\n"


def html_to_markdown(html: str) -> str:
    try:
        from markdownify import markdownify as md  # type: ignore
    except ImportError:
        parser = TextHTMLParser()
        parser.feed(html)
        return parser.markdown()
    return md(html, heading_style="ATX").strip() + "\n"


def final_output_path(plan: DownloadPlan, html_text: str) -> Path:
    host = urllib.parse.urlsplit(plan.source_url).netloc.lower()
    if host.endswith("readthedocs.io"):
        revision = readthedocs_revision(html_text)
        if revision:
            return (
                plan.output_path.parent / f"{revision}.md"
                if plan.output_path.name == "_.md"
                else plan.output_path / f"{revision}.md"
            )
    return plan.output_path
