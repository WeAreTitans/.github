#!/usr/bin/env python3
"""titanatlas.world staged implementation, 2026-10-20. Token-aware (HTMLParser offsets), fail-closed, never edits in place.

Usage: python stage_impl.py <SOURCE_ROOT> <OUTPUT_ROOT>
  SOURCE_ROOT  fresh copy of the live site tree (index.html, about/index.html, assets/...).
  OUTPUT_ROOT  must not exist. Only changed files are written, at the same relative paths.

What it does:
  1. about/index.html: "SynOcts" -> "SynOct&rsquo;s" in the Ollie hero card text and its img alt.
  2. platform/index.html: the three Windows nine-orb tiles point at /assets/platform/windows-{-atlas,-eva,-cleo}-720.webp.
     Requires exactly 9 nine-tile blocks and exactly one Windows tile each for Atlas/Eva/Cleo (identified by the 448x512
     Windows logo viewBox inside the tile's nine-os span). Ubuntu and Mac tiles are byte-identical.
  3. Every page: the family footer row becomes one shared strip:
       <div class="footer-family"> ... </div>     -> same wrapper, contents = <div class="family-strip">...</div>
       or, where no footer-family wrapper exists, the contiguous run
       [div.sy-titans] div.titan-footer a.titan-footer__hosting [p.foot-ping] -> <div class="footer-family">...strip...</div>
     Ranges are located with HTMLParser tag offsets; only the matched range is spliced - every other byte is preserved.
     A page whose footer markup matches neither pattern, or has duplicates, is a hard error: NOTHING is written.
"""
import os, re, sys
from html.parser import HTMLParser

OLLIE_FIXES = [("SynOcts own voice and icon", "SynOct&rsquo;s own voice and icon"),
               ('alt="Ollie, SynOcts orange octopus icon"', 'alt="Ollie, SynOct&rsquo;s orange octopus icon"')]

WINDOWS_ART = {"Atlas": "/assets/platform/windows-atlas-720.webp",
               "Eva": "/assets/platform/windows-eva-720.webp",
               "Cleo": "/assets/platform/windows-cleo-720.webp"}

STRIP = ('<div class="family-strip" role="group" aria-label="The Titan family">'
         '<a class="family-strip__synoct" href="https://synoct.com/" aria-label="SynOct: Built by Titans"><picture>'
         '<source type="image/webp" srcset="/assets/synoct-footer/synoct-built-by-titans-320.webp 320w, /assets/synoct-footer/synoct-built-by-titans-480.webp 480w, /assets/synoct-footer/synoct-built-by-titans-640.webp 640w" sizes="min(100vw, 200px)">'
         '<img class="family-strip__synoct-img" src="/assets/synoct-footer/synoct-built-by-titans-480.png" width="1846" height="420" '
         'alt="SynOct: Built by Titans" loading="lazy" decoding="async"></picture></a>'
         '<a class="family-strip__titans" href="https://titanarray.net/" aria-label="Titans. Building binary worlds.">'
         '<img class="family-strip__sigil" src="/assets/titan-footer-sigil-20261016.svg" width="85" height="85" alt="">'
         '<span class="family-strip__word">Titans</span>'
         '<span class="family-strip__tag"><span class="fs-b">Building</span> <span class="fs-y">Binary</span> '
         '<span class="fs-w">Worlds.</span></span></a>'
         '<p class="family-strip__hosted"><span>Hosted by</span><a href="https://hosting.titanarray.net">hosting.titanarray.net</a></p>'
         '<p class="family-strip__ping">Life&#39;s got its pings, fear not &mdash; we&#39;ll pong right back together!</p>'
         '</div>')


def norm(p):
    return p.rstrip("/") or "/"


# ---------- token-aware ranges ----------
class Tags(HTMLParser):
    """Collect (kind, tag, attrs, start, end) events with character offsets."""
    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.html = html
        self.line_off = [0]
        for m in re.finditer("\n", html):
            self.line_off.append(m.end())
        self.events = []
        self.feed(html)

    def off(self):
        r, c = self.getpos()
        return self.line_off[r - 1] + c

    def handle_starttag(self, tag, attrs):
        s = self.off()
        e = s + len(self.get_starttag_text())   # exact tag text; safe for > inside quoted attrs
        self.events.append(("start", tag, dict(attrs), s, e))

    def handle_startendtag(self, tag, attrs):
        s = self.off()
        e = s + len(self.get_starttag_text())
        self.events.append(("start", tag, dict(attrs), s, e))
        self.events.append(("end", tag, None, e - 1, e))

    def handle_endtag(self, tag):
        s = self.off()
        e = self.html.index(">", s) + 1   # end tags cannot contain quoted '>'
        self.events.append(("end", tag, None, s, e))


def elem_ranges(t, want_tag, cls_token):
    """Element ranges (<tag ...> .. matching </tag>) whose class attribute has cls_token as a whole token."""
    out = []
    for i, ev in enumerate(t.events):
        kind, tag, attrs, s, e = ev
        if kind != "start" or tag != want_tag or not attrs:
            continue
        if cls_token not in (attrs.get("class") or "").split():
            continue
        depth = 1
        j = i + 1
        while j < len(t.events):
            k2, tag2, _, s2, e2 = t.events[j]
            if tag2 == tag:
                if k2 == "start":
                    depth += 1
                else:
                    depth -= 1
                    if depth == 0:
                        out.append((s, e2))
                        break
            j += 1
        else:
            raise SystemExit("unclosed <%s.%s> at offset %d" % (tag, cls_token, s))
    return out


TOP = [("/about/", "About", ""), ("/platform/", "Platform", ""), ("/engineering/", "Engineering", ""),
       ("/trust/", "Trust", ""), ("/pricing/", "Pricing", ' data-launch-nav="v1"'),
       ("/downloads/", "Download", ""), ("https://titanatlas.live/", "Login", ' rel="noopener"')]
GROUPS = [
    ("About", "IN ABOUT", [("/about/", "Overview"), ("/abilities/", "Abilities"), ("/meet-atlas", "Meet Atlas"),
                           ("/what-is-atlas/", "What is Atlas"), ("/why-atlas/", "Why Atlas")]),
    ("Platform", "IN PLATFORM", [("/platform/", "Overview"), ("/how-it-works/", "How it works")]),
    ("Engineering", "IN ENGINEERING", [("/engineering/", "Overview"), ("/tech/", "Tech"),
                                       ("/digital-engineering/", "Digital engineering")]),
]
PARENT_HREF = {"About": "/about/", "Platform": "/platform/", "Engineering": "/engineering/"}


def group_of(path):
    for name, label, items in GROUPS:
        if any(norm(path) == norm(h) for h, _ in items) or (name == "Engineering" and norm(path).startswith("/tech/")):
            return name, label, items
    return None


def build_nav_inner(path, group):
    parts = []
    for href, label, extra in TOP:
        cur = ""
        if not href.startswith("http"):
            if norm(path) == norm(href):
                cur = ' aria-current="page"'
            elif group and href == PARENT_HREF[group[0]]:
                cur = ' aria-current="true"'
        parts.append('<a href="%s"%s%s>%s</a>' % (href, extra, cur, label))
    return "".join(parts)


def build_hub(path, group):
    name, label, items = group
    parts = ['<span class="hub-subnav-label">%s</span>' % label]
    for href, text in items:
        cur = ' aria-current="page"' if norm(href) == norm(path) else \
              (' aria-current="true"' if norm(path).startswith("/tech/") and href == "/tech/" else "")
        parts.append('<a href="%s"%s>%s</a>' % (href, cur, text))
    return '<nav class="hub-subnav wrap" aria-label="%s">' % ("In " + name) + "".join(parts) + "</nav>"


def process(html, path):
    rel = path
    group = group_of(rel)
    want_inner = build_nav_inner(rel, group)
    # every site-nav gets the canonical seven links; attributes on <nav> are preserved
    navs = list(re.finditer(r'(<nav class="site-nav"[^>]*>)(.*?)(</nav>)', html, re.S))
    for m in navs:
        old_inner = m.group(2)
        if re.sub(r'<a href.*?</a>', '', old_inner, flags=re.S).strip():
            raise SystemExit("%s: site-nav contains non-link markup" % rel)
    html = re.sub(r'(<nav class="site-nav"[^>]*>).*?(</nav>)', lambda m: m.group(1) + want_inner + m.group(2), html, flags=re.S)
    # group pages carry one hub-subnav above <main>; existing ones are normalized in place
    if group:
        hubs = list(re.finditer(r'<nav class="hub-subnav[^"]*"[^>]*>.*?</nav>', html, re.S))
        want_hub = build_hub(rel, group)
        if len(hubs) > 1:
            raise SystemExit("%s: %d hub-subnav blocks" % (rel, len(hubs)))
        if hubs:
            html = html[:hubs[0].start()] + want_hub + html[hubs[0].end():]
        else:
            mm = re.search(r'<main\b[^>]*>', html)
            if not mm:
                raise SystemExit("%s: group page has no <main> for its hub-subnav" % rel)
            html = html[:mm.end()] + want_hub + html[mm.end():]
    if norm(rel) == "/about":
        for old, new in OLLIE_FIXES:
            if html.count(old) > 1 or (html.count(old) == 0 and new not in html):
                raise SystemExit("%s: expected exactly one %r, found %d" % (path, old, html.count(old)))
            html = html.replace(old, new, 1)

    if norm(rel) == "/platform":
        tiles = re.findall(r'<div class="nine-tile">', html)
        if len(tiles) != 9:
            raise SystemExit("%s: expected 9 nine-tile blocks, found %d" % (path, len(tiles)))
        seen = []
        for name, src in WINDOWS_ART.items():
            # Windows tile = soul img immediately followed by meta whose nine-os embeds the 448x512 logo for NAME
            pat = '<img class="nine-orb" src="/assets/soul-%s.png" alt="%s"><div class="nine-meta"><b>%s</b><span class="nine-os"><svg viewBox="0 0 448 512"' % (name.lower(), name, name)
            if html.count(pat) > 1 or (html.count(pat) == 0 and src not in html):
                raise SystemExit("%s: expected exactly one Windows tile for %s" % (path, name))
            html = html.replace(pat, pat.replace('/assets/soul-%s.png' % name.lower(), src), 1)
            seen.append(name)
        if sorted(seen) != ["Atlas", "Cleo", "Eva"]:
            raise SystemExit("%s: windows tiles %s" % (path, seen))

    # ---- family strip ----
    if "family-strip" in html:
        if html.count('class="family-strip"') != 1:
            raise SystemExit("%s: duplicate family-strip" % path)
        strip_done = True
    else:
        strip_done = False
    if not strip_done:
        t = Tags(html)
        fams = elem_ranges(t, "div", "footer-family")
        if len(fams) > 1:
            raise SystemExit("%s: %d footer-family blocks" % (path, len(fams)))
        n_tit = len(elem_ranges(t, "div", "titan-footer"))
        if not fams and n_tit == 0 and "footer" not in html:
            print("  NO FOOTER MARKUP (skipped):", path)
            return html
        if fams:
            (s, e) = fams[0]
            inner_open = html.index(">", s) + 1          # end of the opening tag
            inner_close = html.rindex("<", inner_open, e)
            html = html[:inner_open] + STRIP + html[inner_close:]
            # a foot-ping left right AFTER the wrapper close (collision page layout) would duplicate the strip's
            strip_end = html.index("</div>", html.index('class="family-strip"')) + len("</div>")
            tail = html[strip_end:]
            m = re.match(r'\s*<p class="foot-ping">.*?</p>', tail, re.S)
            if m:
                html = html[:strip_end] + tail[m.end():]
        else:
            tits = elem_ranges(t, "div", "titan-footer")
            hosts = elem_ranges(t, "a", "titan-footer__hosting")
            pings = elem_ranges(t, "p", "foot-ping")
            sys_ = elem_ranges(t, "div", "sy-titans")
            if len(tits) != 1 or len(hosts) != 1 or len(sys_) > 1 or len(pings) > 1:
                raise SystemExit("%s: no footer-family and loose blocks = sy:%d titans:%d hosting:%d ping:%d"
                                 % (path, len(sys_), len(tits), len(hosts), len(pings)))
            # try the full run first (sy + titan-footer + hosting contiguous); if a wrapper </div> sits
            # between titan-footer and hosting (meet-atlas, 404), fall back to replacing just the contiguous
            # [sy-titans][titan-footer] run and removing the hosting anchor element separately.
            spans = sorted(sys_ + tits + hosts)
            def contiguous(sp):
                s0, e0 = sp[0][0], sp[-1][1]
                gap = html[s0:e0]
                for (a, b) in reversed(sp):
                    gap = gap[:a - s0] + " " * (b - a) + gap[b - s0:]
                return not re.search(r"<", re.sub(r"<!--.*?-->", "", gap, flags=re.S))
            def drop_loose(h, extra_hosting):
                t2 = Tags(h)                                 # offsets on the spliced document
                for r in elem_ranges(t2, "a", "titan-footer__hosting")[:1] if extra_hosting else []:
                    h = h[:r[0]] + h[r[1]:]
                t3 = Tags(h)
                for r in elem_ranges(t3, "p", "foot-ping")[:1]:
                    h = h[:r[0]] + h[r[1]:]
                return h
            if contiguous(spans):
                s, e = spans[0][0], spans[-1][1]
                html = html[:s] + '<div class="footer-family">' + STRIP + "</div>" + html[e:]
                html = drop_loose(html, False)
            elif contiguous(sorted(sys_ + tits)):
                s, e = sorted(sys_ + tits)[0][0], sorted(sys_ + tits)[-1][1]
                html = html[:s] + '<div class="footer-family">' + STRIP + "</div>" + html[e:]
                html = drop_loose(html, True)
            else:
                raise SystemExit("%s: unexpected markup between loose footer blocks" % path)
    return html


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    if os.path.exists(dst):
        raise SystemExit("OUTPUT_ROOT exists, refusing: " + dst)
    pending = {}
    problems = []
    for root, _, files in os.walk(src):
        for f in sorted(files):
            if f != "index.html" and not f.endswith(".html"):
                continue
            p = os.path.join(root, f)
            rel = "/" + os.path.relpath(p, src).replace(os.sep, "/")
            rel = rel[: -len("index.html")] if rel.endswith("index.html") else rel
            html = open(p, "rb").read().decode("utf-8")
            try:
                new = process(html, rel)
            except SystemExit as ex:
                problems.append(str(ex))
                continue
            if new != html:
                pending[p] = new
    if problems:
        for x in problems:
            print("FAIL:", x)
        raise SystemExit("refusing to publish: %d page(s) could not be transformed safely; NOTHING was written" % len(problems))
    for p, new in sorted(pending.items()):
        out = os.path.join(dst, os.path.relpath(p, src))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, "wb").write(new.encode("utf-8"))
        print("wrote", os.path.relpath(p, src).replace(os.sep, "/"))
    print("%d file(s) changed" % len(pending))


if __name__ == "__main__":
    main()
