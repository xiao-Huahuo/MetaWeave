"""Scanner webpage HTML-to-Markdown parser.

Use ``HtmlMarkdownParser`` for the readable structural subset collected by the
scanner crawler; network access and asset localization remain in the service.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser


class HtmlMarkdownParser(HTMLParser):
    """Convert the readable structural subset of HTML into Markdown."""

    def __init__(self) -> None:
        """Initialize block, link, image, and page-title state."""

        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.images: list[tuple[str, str]] = []
        self.title_parts: list[str] = []
        self._skip_depth = 0
        self._title_depth = 0
        self._link_href = ""
        self._pre_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Open Markdown blocks and retain link/image metadata."""

        name = tag.lower()
        values = {key.lower(): value or "" for key, value in attrs}
        if name in {"script", "style", "noscript", "template"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if name == "title":
            self._title_depth += 1
        elif name in {"p", "div", "section", "article", "header", "footer", "table", "tr", "blockquote"}:
            self.parts.append("\n\n")
        elif re.fullmatch(r"h[1-6]", name):
            self.parts.append(f"\n\n{'#' * int(name[1])} ")
        elif name == "li":
            self.parts.append("\n- ")
        elif name == "br":
            self.parts.append("\n")
        elif name == "a":
            self._link_href = values.get("href", "").strip()
            if self._link_href:
                self.parts.append("[")
        elif name == "pre":
            self._pre_depth += 1
            self.parts.append("\n\n```\n")
        elif name == "code" and not self._pre_depth:
            self.parts.append("`")
        elif name == "img" and values.get("src"):
            alt = values.get("alt", "").strip() or "image"
            src = values["src"].strip()
            self.images.append((src, alt))
            self.parts.append(f"\n\n![{alt}]({src})\n\n")

    def handle_endtag(self, tag: str) -> None:
        """Close Markdown links, code spans, and fenced blocks."""

        name = tag.lower()
        if name in {"script", "style", "noscript", "template"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if name == "title":
            self._title_depth = max(0, self._title_depth - 1)
        elif name == "a" and self._link_href:
            self.parts.append(f"]({self._link_href})")
            self._link_href = ""
        elif name == "pre":
            self._pre_depth = max(0, self._pre_depth - 1)
            self.parts.append("\n```\n")
        elif name == "code" and not self._pre_depth:
            self.parts.append("`")

    def handle_data(self, data: str) -> None:
        """Append visible text while preserving preformatted whitespace."""

        if self._skip_depth or not data:
            return
        if self._title_depth:
            self.title_parts.append(data.strip())
            return
        self.parts.append(data if self._pre_depth else re.sub(r"\s+", " ", data))

    def markdown(self) -> str:
        """Return normalized Markdown without excessive blank lines."""

        value = "".join(self.parts).replace(" \n", "\n")
        return re.sub(r"\n{3,}", "\n\n", value).strip()

    def title(self) -> str:
        """Return the HTML title accumulated from visible title text."""

        return " ".join(part for part in self.title_parts if part).strip()
