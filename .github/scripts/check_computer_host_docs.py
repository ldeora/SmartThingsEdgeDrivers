"""Check tracked Computer Host LAN Markdown links without network access.

Use the same parser for both revisions; the temporary baseline is a multiset
of defects, not an exemption for an entire file or directory.
"""
from __future__ import annotations

import argparse
from collections import Counter
from functools import lru_cache
from html.parser import HTMLParser
import posixpath
import subprocess
import unicodedata
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

MD = MarkdownIt("commonmark", {"html": True}).enable(["table", "strikethrough"])


def git(*args):
    return subprocess.check_output(["git", *args])


def tracked(revision):
    return set(git("ls-tree", "-r", "--name-only", "-z", revision)
               .decode("utf-8").rstrip("\0").split("\0"))


def in_scope(path):
    return (path == "README.md"
            or path == ".github/ISSUE_TEMPLATE/computer-host-lan-bug.md"
            or path == ".github/computer-host-lan-docs/README.md"
            or (path.startswith("computer-host-lan/") and path.endswith(".md")))


class HtmlLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.anchors = set()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.anchors.add(values["id"])
        if tag == "a" and values.get("name"):
            self.anchors.add(values["name"])
        for attr in (("href",) if tag == "a" else ("src",) if tag == "img" else ()):
            if values.get(attr):
                self.links.append(values[attr])


def walk(tokens):
    for token in tokens:
        yield token
        if token.children:
            yield from walk(token.children)


def heading_text(tokens):
    return "".join(t.content if t.type in ("text", "code_inline", "image")
                   else " " if t.type in ("softbreak", "hardbreak") else ""
                   for t in tokens)


def slug(text):
    # GitHub-style heading IDs: lowercase, space -> hyphen, strip punctuation
    # and symbols except hyphen/underscore. Retain Unicode letters/marks/numbers.
    return "".join("-" if c == " " else c for c in text.strip().lower()
                   if c in " -_" or unicodedata.category(c)[0] in "LMN")


def parse(content):
    tokens = MD.parse(content)
    anchors = set()
    links = []
    used = set()
    for i, t in enumerate(tokens):
        if t.type == "heading_open" and i + 1 < len(tokens):
            base = slug(heading_text(tokens[i + 1].children or []))
            name = base
            n = 0
            while name in used:
                n += 1
                name = f"{base}-{n}"
            used.add(name)
    for t in walk(tokens):
        if t.type in ("link_open", "image"):
            target = t.attrGet("href" if t.type == "link_open" else "src")
            if target:
                links.append(target)
        elif t.type in ("html_inline", "html_block"):
            parser = HtmlLinks()
            parser.feed(t.content)
            parser.close()
            links.extend(parser.links)
            anchors.update(parser.anchors)
    return links, anchors | used


def check(paths, read):
    """Return a multiset of (source, target, reason), independent of line edits."""
    dirs = {""}
    for path in paths:
        parent = posixpath.dirname(path)
        while parent and parent not in dirs:
            dirs.add(parent)
            parent = posixpath.dirname(parent)

    @lru_cache(maxsize=None)
    def document(path):
        return parse(read(path))

    defects = Counter()
    for source in sorted(p for p in paths if in_scope(p)):
        for target in document(source)[0]:
            try:
                url = urlsplit(target)
            except ValueError:
                defects[source, target, "malformed URL"] += 1
                continue
            if url.scheme or url.netloc:
                continue  # External URLs are a separate audit, not a network CI gate.
            path = unquote(url.path)
            dest = (posixpath.normpath(path.lstrip("/")) if path.startswith("/")
                    else posixpath.normpath(posixpath.join(posixpath.dirname(source), path))
                    if path else source)
            if dest == ".":
                dest = ""
            if dest == ".." or dest.startswith("../") or dest not in paths | dirs:
                defects[source, target, "missing repository path"] += 1
                continue
            if url.fragment:
                if dest in dirs:
                    dest = posixpath.join(dest, "README.md")
                # Non-Markdown fragments (e.g. source line numbers) are not
                # headings; they are outside the scope of this check.
                if dest in paths and dest.endswith(".md"):
                    if unquote(url.fragment) not in document(dest)[1]:
                        defects[source, target, "missing Markdown anchor"] += 1
    return defects


def revision_defects(revision):
    # Resolve first so a revision cannot be interpreted as a git option.
    sha = git("rev-parse", "--verify", revision + "^{commit}").decode().strip()
    return check(tracked(sha), lambda p: git("show", f"{sha}:{p}").decode("utf-8"))


def report(label, defects):
    print(f"{label}: {sum(defects.values())}")
    for (source, target, reason), count in sorted(defects.items()):
        print(f"  {source}: {target} ({reason}; occurrences={count})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--baseline", help="Temporary pinned pre-migration commit")
    args = parser.parse_args()
    current = revision_defects(args.revision)
    baseline = revision_defects(args.baseline) if args.baseline else Counter()
    report("Inherited defects still present", current & baseline)
    report("Resolved baseline defects", baseline - current)
    new = current - baseline
    report("New defects" if args.baseline else "Defects", new)
    return int(bool(new))


if __name__ == "__main__":
    raise SystemExit(main())
