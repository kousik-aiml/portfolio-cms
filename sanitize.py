"""Whitelist HTML sanitiser for rich-text fields (no third-party dependency)."""
import re
from html import escape
from html.parser import HTMLParser

ALLOWED = {
    "p", "br", "b", "strong", "i", "em", "u", "ul", "ol", "li", "a",
    "h3", "h4", "blockquote", "code", "pre",
}
RENAME = {"div": "p", "h1": "h3", "h2": "h3", "h5": "h4", "h6": "h4"}
DROP_CONTENT = {"script", "style", "iframe", "object", "embed", "template", "noscript", "svg", "math"}
VOID = {"br"}
SAFE_HREF = re.compile(r"^(https?://|mailto:)", re.I)


class _Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.stack = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in DROP_CONTENT:
            self.skip += 1
            return
        if self.skip:
            return
        tag = RENAME.get(tag, tag)
        if tag not in ALLOWED:
            return
        if tag == "a":
            href = ""
            for k, v in attrs:
                if k.lower() == "href" and v and SAFE_HREF.match(v.strip()):
                    href = v.strip()
            if not href:
                return
            self.out.append(f'<a href="{escape(href, quote=True)}" target="_blank" rel="noopener noreferrer">')
        elif tag in VOID:
            self.out.append("<br>")
            return
        else:
            self.out.append(f"<{tag}>")
        self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag.lower() == "br" and not self.skip:
            self.out.append("<br>")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        tag = RENAME.get(tag, tag)
        if tag in ALLOWED and tag not in VOID and tag in self.stack:
            while self.stack:
                top = self.stack.pop()
                self.out.append(f"</{top}>")
                if top == tag:
                    break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(escape(data, quote=False))

    def result(self):
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")
        return "".join(self.out)


def sanitize_html(value):
    if not value:
        return ""
    cleaner = _Cleaner()
    cleaner.feed(str(value))
    cleaner.close()
    html = cleaner.result().strip()
    # collapse "empty" editors such as <p><br></p>
    if not re.sub(r"<[^>]+>|&nbsp;|\s", "", html):
        return ""
    return html


def strip_tags(value):
    """Plain-text version of rich text (for summaries / search)."""
    text = re.sub(r"<(br|/p|/li|/h3|/h4|/blockquote)[^>]*>", " ", value or "")
    text = re.sub(r"<[^>]+>", "", text)
    from html import unescape
    return re.sub(r"\s+", " ", unescape(text)).strip()
