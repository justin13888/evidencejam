"""Accessibility audit of the generated pages (ROADMAP item 19, WCAG 2.2 AA). Dev only, never a runtime path.

Two layers:

- Static checks, stdlib only, run by `tests/test_accessibility.py` inside `mise run check`: every page has a `lang`,
  a title and one `h1`; headings never skip a level; every table has a caption, header cells are `th` with a
  scope; ids are unique and in-page links resolve; every link has text; scrolling table wrappers can take
  keyboard focus and are named; no script. `product/style.css` is parsed for its colour tokens in both the light
  and the dark scheme, and every foreground/background pair the stylesheet draws is checked for computed
  contrast (4.5:1 for text, 3:1 for borders and the focus ring).
- `--axe`: axe-core, pinned below, run over the same pages in jsdom. jsdom does no layout, so axe reports
  colour contrast as incomplete there; the static contrast check covers it. Needs node and npm, installs into
  `.cache/a11y` inside the checkout, and is kept out of `mise run check`.

Usage: `python scripts/a11y_audit.py [DIR] [--axe]` (DIR defaults to `outputs/`, written by `mise run run`).
Prints one line per finding and exits 1 when there is any. Keyboard use and reflow at 320 px are checked by
hand: `docs/accessibility.md`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "product" / "style.css"
AXE = {"axe-core": "4.14.0", "jsdom": "31.0.1"}  # pinned; installed only by --axe
TEXT, NON_TEXT = 4.5, 3.0  # WCAG 1.4.3 and 1.4.11 minimum ratios
# (foreground token, background token, minimum ratio, where style.css draws the pair)
PAIRS = (
    ("fg", "bg", TEXT, "body text"),
    ("muted", "bg", TEXT, "muted notes, footer, gap cells in the gap map"),
    ("link", "bg", TEXT, "links"),
    ("line", "bg", NON_TEXT, "table borders and quote rules"),
    ("link", "bg", NON_TEXT, "focus ring"),
    *((fg, f"d{i}", TEXT, f"gap map cell, shade {i}") for i in range(1, 5) for fg in ("fg", "link")),
)
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


def _hex(value: str) -> tuple[float, float, float]:
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    return tuple(int(v[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def luminance(color: str) -> float:
    """WCAG 2.2 relative luminance of a #rgb or #rrggbb colour."""
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in _hex(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def schemes(css: str) -> dict[str, dict[str, str]]:
    """Colour tokens per scheme: every `:root { --x: #..; }` block, the dark ones overriding the light."""
    light: dict[str, str] = {}
    dark: dict[str, str] = {}
    token = re.compile(r"--([\w-]+)\s*:\s*(#[0-9a-fA-F]{3,6})\b")
    dark_blocks = re.findall(r"@media\s*\(prefers-color-scheme:\s*dark\)\s*\{\s*:root\s*\{([^}]*)\}", css)
    for block in re.findall(r":root\s*\{([^}]*)\}", re.sub(r"@media[^{]*\{\s*:root\s*\{[^}]*\}\s*\}", "", css)):
        light.update(token.findall(block))
    for block in dark_blocks:
        dark.update(token.findall(block))
    return {"light": light, "dark": {**light, **dark}}


def audit_css(css: str) -> list[str]:
    found = []
    for scheme, tokens in schemes(css).items():
        for fg, bg, need, where in PAIRS:
            if fg not in tokens or bg not in tokens:
                found.append(f"style.css: {scheme} scheme has no --{fg} or --{bg} ({where})")
                continue
            ratio = contrast(tokens[fg], tokens[bg])
            if ratio < need:
                found.append(
                    f"style.css: {scheme} --{fg} {tokens[fg]} on --{bg} {tokens[bg]} is {ratio:.2f}:1, "
                    f"needs {need}:1 ({where})"
                )
    return found


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict[str, str | None]]] = []
        self.lang = self.title = None
        self.headings: list[int] = []
        self.ids: list[str] = []
        self.fragments: list[str] = []
        self.labels: list[str] = []  # aria-labelledby targets
        self.links: list[list[str]] = []  # text pieces of each open link
        self.link_text: list[str] = []
        self.tables: list[dict] = []
        self.found: list[str] = []
        self._title: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if a.get("id"):
            self.ids.append(a["id"] or "")
        self.labels += (a.get("aria-labelledby") or "").split()
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "title":
            self._title = []
        elif re.fullmatch(r"h[1-6]", tag):
            self.headings.append(int(tag[1]))
        elif tag == "a":
            href = a.get("href")
            if href is None:
                self.found.append("a link without href")
            elif href.startswith("#"):
                self.fragments.append(href[1:])
            self.links.append([a.get("aria-label") or ""])
        elif tag == "table":
            parent = self.stack[-1] if self.stack else ("", {})
            self.tables.append({"caption": False, "wrap": parent})
        elif tag == "caption" and self.tables:
            self.tables[-1]["caption"] = True
        elif tag == "th" and a.get("scope") not in ("col", "row", "colgroup", "rowgroup"):
            self.found.append("a th without scope")
        elif tag == "td" and any(t == "thead" for t, _ in self.stack):
            self.found.append("a td in a table head: header cells must be th")
        elif tag == "img" and a.get("alt") is None:
            self.found.append("an img without alt")
        elif tag == "script":
            self.found.append("a script: pages must work without one")
        if tag not in VOID:
            self.stack.append((tag, a))

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._title is not None:
            self.title, self._title = "".join(self._title).strip(), None
        elif tag == "a" and self.links:
            self.link_text.append("".join(self.links.pop()).strip())
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data: str) -> None:
        if self._title is not None:
            self._title.append(data)
        for parts in self.links:
            parts.append(data)


def audit_html(html: str) -> list[str]:
    """Findings for one page, without the file name."""
    p = _Page()
    p.feed(html)
    p.close()
    found = list(p.found)
    if not (p.lang or "").strip():
        found.append("html has no lang")
    if not p.title:
        found.append("no title")
    if p.headings.count(1) != 1:
        found.append(f"{p.headings.count(1)} h1 elements, want 1")
    if p.headings and p.headings[0] != 1:
        found.append(f"first heading is h{p.headings[0]}, want h1")
    for prev, cur in zip(p.headings, p.headings[1:]):
        if cur > prev + 1:
            found.append(f"heading skips from h{prev} to h{cur}")
    dupes = sorted({i for i in p.ids if p.ids.count(i) > 1})
    if dupes:
        found.append(f"duplicate ids: {', '.join(dupes[:5])}")
    missing = sorted(set(p.fragments) - set(p.ids))
    if missing:
        found.append(f"in-page links to missing ids: {', '.join(missing[:5])}")
    unnamed = sorted(set(p.labels) - set(p.ids))
    if unnamed:
        found.append(f"aria-labelledby names missing ids: {', '.join(unnamed[:5])}")
    if any(not t for t in p.link_text):
        found.append("a link with no text")
    for t in p.tables:
        if not t["caption"]:
            found.append("a table without caption")
        tag, attrs = t["wrap"]
        scroller = tag == "div" and "wrap" in (attrs.get("class") or "").split()
        if scroller and (attrs.get("tabindex") != "0" or not (attrs.get("aria-labelledby") or attrs.get("aria-label"))):
            found.append("a scrolling table wrapper that keyboard users cannot focus, or that has no name")
    return found


def audit_dir(out: Path, css: Path | None = None) -> list[str]:
    """Findings for every page under out and for the stylesheet, each prefixed with its file name."""
    pages = sorted(out.glob("*.html"))
    found = [] if pages else [f"{out}: no pages; run `mise run run` first"]
    for page in pages:
        found += [f"{page.name}: {f}" for f in audit_html(page.read_text(encoding="utf-8"))]
    return found + audit_css((css or CSS).read_text(encoding="utf-8"))


AXE_JS = r"""
const fs = require("fs"), path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");
const source = fs.readFileSync(require.resolve("axe-core"), "utf8");
const virtualConsole = new VirtualConsole();  // drops jsdom's "not implemented: canvas" noise
let bad = 0;
(async () => {
  for (const file of process.argv.slice(1)) {
    const opts = { runScripts: "outside-only", pretendToBeVisual: true, virtualConsole };
    const dom = new JSDOM(fs.readFileSync(file, "utf8"), opts);
    dom.window.eval(source);
    const r = await dom.window.axe.run(dom.window.document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"] },
    });
    for (const v of r.violations) {
      bad++;
      console.log(`${path.basename(file)}: axe ${v.id} (${v.impact}): ${v.help}, ${v.nodes.length} node(s)`);
    }
    const open = r.incomplete.map((i) => i.id).join(", ") || "none";
    console.log(`${path.basename(file)}: axe ${r.passes.length} rules passed; incomplete (needs layout): ${open}`);
  }
  process.exit(bad ? 1 : 0);
})();
"""


def run_axe(out: Path) -> int:
    cache = ROOT / ".cache" / "a11y"
    modules = cache / "node_modules"
    if not all((modules / name / "package.json").exists() for name in AXE):
        cache.mkdir(parents=True, exist_ok=True)
        pins = [f"{name}@{version}" for name, version in AXE.items()]
        subprocess.run(["npm", "install", "--prefix", str(cache), "--no-save", "--no-audit", *pins], check=True)
    pages = [str(p) for p in sorted(out.glob("*.html"))]
    env = {"NODE_PATH": str(modules), "PATH": os.environ.get("PATH", "")}
    return subprocess.run(["node", "-e", AXE_JS, *pages], env=env).returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("dir", nargs="?", type=Path, default=ROOT / "outputs")
    ap.add_argument("--axe", action="store_true", help="also run axe-core (needs node and npm)")
    args = ap.parse_args(argv)
    found = audit_dir(args.dir)
    for f in found:
        print(f)
    pages = len(list(args.dir.glob("*.html")))
    print(json.dumps({"pages": pages, "findings": len(found)}))
    code = 1 if found else 0
    if args.axe:
        code |= run_axe(args.dir)
    return code


if __name__ == "__main__":
    sys.exit(main())
