"""titanatlas.world focused repair r3, 2026-10-20. Token-aware (HTMLParser offsets), fail-closed, never edits in place.

(1) about/: remove the superseded LOWER Ollie section — the <section class="section wrap">
    whose immediate content is the standalone <div class="ollie-card"> (hero uses <aside class="ollie-card">).
    Requires exactly 1 hero aside.ollie-card and exactly 1 lower div.ollie-card; if the lower card is
    already absent the page is a no-op; otherwise fail. Following siblings stay byte-identical.
(2) why-atlas/: remove a stray SOH byte before <body>, ensure </head> is present, fix the broken
    /assets/synoct-footer.css href, remove the extra aside.titan-advanced-beta and the legacy
    chrome interior (details.atlas-owner-note + details.atlas-mobile-menu), splice the canonical
    chrome interior (approved banner + canonical header from the home page, About parent
    aria-current="true"), and add defer atlas-site-repair.js + consciousness.js. main..footer
    bytes are preserved exactly.
"""
import os, sys, re, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage_family_strip import Tags, elem_ranges


def h(b): return hashlib.sha256(b).hexdigest()


def cls_has(attrs, tok):
    return tok in (attrs.get("class") or "").split()


def inner_range(t, want_tag, cls_token):
    """(content_start, content_end) — inside the matching element."""
    for i, ev in enumerate(t.events):
        kind, tag, attrs, s, e = ev
        if kind != "start" or tag != want_tag or not cls_has(attrs, cls_token):
            continue
        depth, j = 1, i + 1
        while j < len(t.events):
            k2, tag2, _, s2, e2 = t.events[j]
            if tag2 == tag:
                depth += 1 if k2 == "start" else -1
                if depth == 0:
                    return e, s2
            j += 1
        raise SystemExit("unclosed <%s.%s>" % (tag, cls_token))
    return None


def sections_with_direct_ollie(t, html):
    """section.section.wrap ranges whose first element child is div.ollie-card."""
    out = []
    for i, ev in enumerate(t.events):
        kind, tag, attrs, s, e = ev
        if kind != "start" or tag != "section" or not (cls_has(attrs, "section") and cls_has(attrs, "wrap")):
            continue
        j = i + 1
        while j < len(t.events) and t.events[j][0] != "start":
            j += 1
        if j < len(t.events) and t.events[j][1] == "div" and cls_has(t.events[j][2] or {}, "ollie-card"):
            depth, k = 1, i + 1
            while k < len(t.events):
                k2, tag2, _, s2, e2 = t.events[k]
                if tag2 == "section":
                    depth += 1 if k2 == "start" else -1
                    if depth == 0:
                        out.append((s, e2))
                        break
                k += 1
            else:
                raise SystemExit("unclosed section.section.wrap at %d" % s)
    return out


def transform_about(html):
    t = Tags(html)
    heroes = [r for r in elem_ranges(t, "aside", "ollie-card")]
    lowers = sections_with_direct_ollie(t, html)
    if len(heroes) != 1:
        raise SystemExit("about: expected exactly 1 hero aside.ollie-card, found %d" % len(heroes))
    if not lowers:
        return html, "noop (already 1 Ollie)"
    if len(lowers) != 1:
        raise SystemExit("about: unexpected %d lower Ollie sections" % len(lowers))
    s, e = lowers[0]
    # the section must contain exactly the div.ollie-card element and whitespace — nothing else
    # find inner offsets of THIS section: its start-tag end and matching end-tag start
    for i, ev in enumerate(t.events):
        if ev[0] == "start" and ev[1] == "section" and ev[3] == s:
            istart = ev[4]
            break
    else:
        raise SystemExit("about: section range mismatch")
    iend = e - len("</section>")
    inner = html[istart:iend]
    cards = [r for r in elem_ranges(t, "div", "ollie-card") if s <= r[0] and r[1] <= e]
    if len(cards) != 1:
        raise SystemExit("about: section contains %d ollie-card elements" % len(cards))
    rest = inner[:cards[0][0] - istart] + inner[cards[0][1] - istart:]
    if rest.strip() or "<" in rest:
        raise SystemExit("about: section has extra content beside the lower Ollie card")
    out = html[:s] + html[e:]
    return out, "removed lower Ollie section (%d bytes)" % (e - s)


def transform_why(html, home_html):
    problems = []
    raw = html.encode("utf8") if isinstance(html, str) else html
    s = raw.decode("utf8")
    # 1. stray SOH byte(s) before <body>; ensure </head>
    if s.count("\x01") > 1:
        raise SystemExit("why: unexpected %d SOH bytes" % s.count("\x01"))
    s = s.replace("\x01", "")
    if "</head>" not in s[:s.find("<body")]:
        s = s[:s.find("<body")] + "</head>\n" + s[s.find("<body"):]
    # 2. broken stylesheet href
    broken = 'href="/assets/synoct-footer.css"'
    if s.count(broken) == 1:
        s = s.replace(broken, 'href="/assets/synoct-footer/synoct-footer.css"')
    elif s.count(broken):
        raise SystemExit("why: %d broken synoct-footer hrefs" % s.count(broken))
    else:
        problems.append("synoct-footer href already fixed")
    # 3. defer scripts (once)
    ins = ""
    if 'src="/assets/atlas-site-repair.js"' not in s:
        ins += '<script src="/assets/atlas-site-repair.js" defer></script>'
    if 'src="/assets/consciousness.js"' not in s:
        ins += '<script src="/assets/consciousness.js" defer></script>'
    if ins:
        s = s.replace("</head>", ins + "\n</head>", 1)
    # 4. remove aside.titan-advanced-beta (token-aware)
    t = Tags(s)
    adv = elem_ranges(t, "aside", "titan-advanced-beta")
    if len(adv) == 1:
        s = s[:adv[0][0]] + s[adv[0][1]:]
    elif len(adv) > 1:
        raise SystemExit("why: %d titan-advanced-beta asides" % len(adv))
    else:
        problems.append("advanced-beta aside already absent")
    # 5. replace chrome interior with canonical home interior
    ht = Tags(home_html)
    hr = inner_range(ht, "div", "titan-owner-chrome")
    if not hr:
        raise SystemExit("why: home chrome interior not found")
    chrome_inner = home_html[hr[0]:hr[1]]
    chrome_inner = chrome_inner.replace('href="#explore"', 'href="#main"')
    chrome_inner = chrome_inner.replace('<a href="/about/">About</a>', '<a href="/about/" aria-current="true">About</a>', 1)
    t = Tags(s)
    wr = inner_range(t, "div", "titan-owner-chrome")
    if not wr:
        raise SystemExit("why: chrome interior not found")
    legacy = s[wr[0]:wr[1]]
    for tok in ("atlas-owner-note", "atlas-mobile-menu"):
        if tok not in legacy:
            problems.append("%s not present in chrome" % tok)
    s = s[:wr[0]] + chrome_inner + s[wr[1]:]
    # 6. post-checks
    for tok in ("atlas-owner-note", "atlas-mobile-menu", '<aside class="titan-advanced-beta"', "\x01"):
        if tok in s:
            raise SystemExit("why: leftover %s" % tok)
    if s.count('id="siteHeaderOrb"') != 1:
        raise SystemExit("why: header orb count != 1")
    return s, "; ".join(problems) if problems else "repaired"


def main():
    src_root, out_root = sys.argv[1], sys.argv[2]
    src_root = os.path.abspath(src_root)
    out_root = os.path.abspath(out_root)
    if src_root == out_root:
        raise SystemExit("refusing in-place run: source and output roots must differ")
    if os.path.exists(out_root):
        raise SystemExit("refusing existing output root: %s" % out_root)
    home_html = open(os.path.join(src_root, "index.html"), encoding="utf8").read()
    outs, reports = {}, {}
    # validate everything before writing anything
    for rel, fn in (("about/index.html", transform_about),
                    ("why-atlas/index.html", lambda h_: transform_why(h_, home_html))):
        src = open(os.path.join(src_root, rel), encoding="utf8").read()
        outs[rel], reports[rel] = fn(src)
    # preservation checks
    w_src = open(os.path.join(src_root, "why-atlas/index.html"), encoding="utf8").read()
    for marker in ('id="about-form"', '<section class="section wrap" id="email-us"'):
        if marker not in outs["about/index.html"]:
            raise SystemExit("about: lost %s" % marker)
    if outs["why-atlas/index.html"].find("<main") == -1 or \
       w_src[w_src.find("<footer"):w_src.find("</footer>")] not in outs["why-atlas/index.html"]:
        raise SystemExit("why: footer bytes changed")
    for rel, out in outs.items():
        dst = os.path.join(out_root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "w", encoding="utf8", newline="").write(out)
        print("wrote", rel, "->", reports[rel])


if __name__ == "__main__":
    main()
