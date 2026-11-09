"""Every page of the website as plain HTML. Pages only show what exists: a category, the Videos page or the
newsletter appears only when there is something real behind it. Nothing here links to the studio."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from urllib.parse import quote

from . import assets

SITE_NAME = "Penny & Pixel"
SITE_HTML = html.escape(SITE_NAME)
TAGLINE = "AI tools and money skills, explained simply"
HERO_TITLE = 'Make technology work for you. <em>Make money make sense.</em>'
HERO_TEXT = ("Practical AI guides for freelancers and small businesses, money explainers and short videos to help you make smarter "
             "decisions. Every fact is checked against a named source.")
CHANNELS = {"ai": ("AI tools", "Pixel explains what AI tools can really do, without the hype."),
            "money": ("Money", "Penny explains budgeting, saving, paychecks and credit with real numbers.")}
UNCHECKED_NOTE = ("This article was published before our usual final source check. Please check the listed sources "
                  "before relying on it.")
MONEY_NOTE = ("This is general education, not personal financial advice. Rules, prices and taxes differ by country and "
              "change over time; consider your own situation or speak to a licensed professional.")
AI_NOTE = ("How this article was made: it is written from our video script, researched with AI tools. Every fact is "
           "checked against the sources listed below, with their dates. We don't claim hands-on tests we didn't run.")
PER_PAGE = 24


def e(s) -> str:
    return html.escape(str(s or ""), quote=True)


def date(d: datetime) -> str:
    return f"{d:%B} {d.day}, {d:%Y}"


def _json_ld(obj) -> str:
    return '<script type="application/ld+json">' + json.dumps(obj, ensure_ascii=False).replace("</", "<\\/") + "</script>"


class Site:
    """What every page needs to know about the whole site."""

    def __init__(self, url: str, articles: list, socials: list[dict], options: dict):
        self.url, self.articles, self.socials, self.opt = url.rstrip("/"), articles, socials, options
        self.channels = [c for c in CHANNELS if any(a.channel == c for a in articles)]
        self.videos = [a for a in articles if a.video_id]
        self.year = datetime.now(timezone.utc).year

    # ------------------------------------------------------------------ frame
    def nav_links(self, here: str) -> list[tuple[str, str]]:
        links = [(f"/{c}/", CHANNELS[c][0]) for c in self.channels]
        if self.articles:
            links.append(("/latest/", "Latest"))
        if self.videos:
            links.append(("/videos/", "Videos"))
        links += [("/guides/ai-for-small-business/", "Start here"), ("/search/", "Search"), ("/about/", "About")]
        return links

    def page(self, title: str, description: str, path: str, body: str, *, image: str | None = None,
             og_type: str = "website", ld: list | None = None, noindex: bool = False, lang: str = "en",
             alternates: dict[str, str] | None = None, nav_links: list | None = None, footer: str | None = None) -> str:
        url = self.url + path
        full = title if title == SITE_NAME else f"{title} · {SITE_NAME}"
        img = self.url + (f"/images/{image}" if image else "/og-default.png")
        items = []
        for link in nav_links or self.nav_links(path):
            href, text, hl = (*link, None)[:3]   # an optional third value is the linked page's language
            current = ' aria-current="page"' if href != "/" and path.startswith(href) else ""
            other = f' lang="{hl}" hreflang="{hl}"' if hl else ""
            items.append(f'<a href="{href}"{current}{other}>{e(text)}</a>')
        nav = "".join(items)
        alt = "".join(f'<link rel="alternate" hreflang="{k}" href="{e(self.url + v)}">' for k, v in (alternates or {}).items())
        analytics = ""
        token = (self.opt.get("analytics") or {}).get("cloudflare_token")
        if token:   # Cloudflare Web Analytics: free, cookie-free; only when the owner has added a token
            analytics = ('<script defer src="https://static.cloudflareinsights.com/beacon.min.js" '
                         f"data-cf-beacon='{e(json.dumps({'token': token}))}'></script>")
        events_url = (self.opt.get("analytics") or {}).get("events_url")
        if events_url and __import__("re").match(r"^https://[A-Za-z0-9.-]+(?::[0-9]+)?(?:/|$)", events_url):
            analytics += f'<meta name="site-events-url" content="{e(events_url)}">'
        lds = "".join(_json_ld(x) for x in (ld or []))
        return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{e(full)}</title><meta name="description" content="{e(description)}"><link rel="canonical" href="{e(url)}">
{'<meta name="robots" content="noindex">' if noindex else ''}
<meta name="theme-color" content="#101B32"><meta property="og:site_name" content="{SITE_HTML}"><meta property="og:locale" content="{"de_DE" if lang == "de" else "en_US"}">{alt}{self.verification()}
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{e(url)}"><meta property="og:type" content="{og_type}"><meta property="og:image" content="{e(img)}">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{e(title)}">
<meta name="twitter:description" content="{e(description)}"><meta name="twitter:image" content="{e(img)}">
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="apple-touch-icon" href="/icon-180.png">
<link rel="alternate" type="application/rss+xml" title="{SITE_HTML}" href="/feed.xml">
<link rel="stylesheet" href="{e(self.opt.get("_css_url", "/assets/site.css"))}"><script defer src="{e(self.opt.get("_js_url", "/assets/site.js"))}"></script>{analytics}{lds}
</head><body>
<a class="skip" href="#main">{"Zum Inhalt" if lang == "de" else "Skip to content"}</a>
<header class="top"><div class="wrap">
<a class="brand" href="/" aria-label="{SITE_HTML} home">{assets.logo(32)}<span>{SITE_HTML}</span></a>
<nav class="nav desktop" aria-label="Main">{nav}</nav>
<details class="menu"><summary>{"Menü" if lang == "de" else "Menu"}</summary><nav class="nav" aria-label="Main (mobile)">{nav}</nav></details>
</div></header>
<main id="main">{body}</main>
{footer if footer is not None else self.footer()}
</body></html>
"""

    def verification(self) -> str:
        code = self.opt.get("google_site_verification")
        return f'<meta name="google-site-verification" content="{e(code)}">' if code else ""

    @property
    def german(self) -> list:
        return [a for a in self.articles if a.de_blocks]

    def footer(self) -> str:
        cats = "".join(f'<li><a href="/{c}/">{e(CHANNELS[c][0])}</a></li>' for c in self.channels)
        follow = "".join(f'<li><a href="{e(s["url"])}" rel="me noopener">{e(s["name"])}</a></li>' for s in self.socials)
        return f"""<footer class="foot"><div class="wrap"><div class="cols">
<div><a class="brand" href="/">{assets.logo(28)}<span>{SITE_HTML}</span></a><p>{e(TAGLINE)}. Every fact checked against a named source.</p></div>
<nav aria-label="Read"><h2>Read</h2><ul>{cats}<li><a href="/latest/">Latest</a></li>{'<li><a href="/videos/">Videos</a></li>' if self.videos else ''}<li><a href="/search/">Search</a></li></ul></nav>
<nav aria-label="About"><h2>About</h2><ul><li><a href="/about/">About us</a></li><li><a href="/contact/">Contact</a></li>
<li><a href="/editorial-policy/">Editorial policy</a></li><li><a href="/ai-content-policy/">AI content policy</a></li>
<li><a href="/corrections/">Corrections</a></li><li><a href="/advertise/">Advertise with us</a></li></ul></nav>
<nav aria-label="Legal"><h2>Legal</h2><ul><li><a href="/privacy/">Privacy policy</a></li><li><a href="/terms/">Terms of use</a></li>
<li><a href="/affiliate-disclosure/">Affiliate disclosure</a></li><li><a href="/feed.xml">RSS feed</a></li>{'<li><a href="/de/" lang="de" hreflang="de">Deutsch</a></li>' if self.german else ''}</ul></nav>
{f'<nav aria-label="Follow"><h2>Follow</h2><ul>{follow}</ul></nav>' if follow else ''}
</div><p class="small">&copy; {self.year} {SITE_HTML}. General education only, not personal financial advice.</p></div></footer>"""

    # ------------------------------------------------------------------ pieces
    def picture(self, a, eager: bool = False, sizes: str = "(max-width:760px) 100vw, 380px") -> str:
        if not a.image:   # never an empty grey box: the brand mark and the topic instead
            label = CHANNELS.get(a.channel, (a.channel,))[0]
            return (f'<span class="noimg {e(a.channel)}" role="img" aria-label="{e(label)}">{assets.logo(56)}'
                    f'<span>{e(label)}</span></span>')
        stem = a.image.rsplit(".", 1)[0]
        webp = (f'<source type="image/webp" srcset="/images/{e(stem)}-640.webp 640w, /images/{e(stem)}-1280.webp 1280w" '
                f'sizes="{sizes}">' if a.webp else "")
        return (f'<picture>{webp}<img src="/images/{e(a.image)}" alt="{e(a.image_alt)}" width="1280" height="720" '
                f'{"fetchpriority=\"high\"" if eager else "loading=\"lazy\" decoding=\"async\""}></picture>')

    def tag(self, channel: str) -> str:
        return f'<a class="tag {e(channel)}" href="/{e(channel)}/">{e(CHANNELS.get(channel, (channel,))[0])}</a>'

    def card(self, a) -> str:
        return (f'<article class="card"><a class="cover" href="/articles/{e(a.slug)}/" tabindex="-1" aria-hidden="true">{self.picture(a)}</a>'
                f'<div class="body">{self.tag(a.channel)}<h3><a href="/articles/{e(a.slug)}/">{e(a.title)}</a></h3>'
                f'<p>{e(a.description)}</p><p class="meta">{date(a.published)} · {a.minutes} min read</p></div></article>')

    def lead(self, a) -> str:
        return (f'<article class="lead-story"><a class="cover" href="/articles/{e(a.slug)}/" tabindex="-1" aria-hidden="true">'
                f'{self.picture(a, eager=True, sizes="(max-width:860px) 100vw, 640px")}</a><div class="body">{self.tag(a.channel)}'
                f'<h3><a href="/articles/{e(a.slug)}/">{e(a.title)}</a></h3><p>{e(a.description)}</p>'
                f'<p class="meta">{date(a.published)} · {a.minutes} min read</p></div></article>')

    def video_box(self, a) -> str:
        """A thumbnail with a play button; the YouTube player loads only when the reader clicks."""
        thumb = f"https://i.ytimg.com/vi/{e(a.video_id)}/hqdefault.jpg"
        return (f'<div class="video" data-yt="{e(a.video_id)}" data-title="{e(a.title)}">'
                f'<img src="{thumb}" alt="" width="480" height="360" loading="lazy" decoding="async">'
                f'<a class="play" href="https://www.youtube.com/watch?v={e(a.video_id)}" rel="noopener"><span>▶ Watch on YouTube</span></a>'
                f'<button class="play" type="button" hidden aria-label="Play the video: {e(a.title)}"><span>▶ Play video</span></button></div>')

    def newsletter(self) -> str:
        """Shown only when a free provider's sign-up address is configured: the provider stores the subscription,
        sends the confirmation and handles unsubscribing. Nothing is pretended."""
        n = self.opt.get("newsletter") or {}
        if not n.get("form_action"):
            return ""
        return f"""<section class="section"><div class="wrap"><div class="newsletter">
<h2 class="title">Get new guides by email</h2><p>Practical guides for freelancers and small businesses. Unsubscribe any time. <a href="/downloads/ai-workflow-checklist.txt" download>Get the free workflow checklist</a>.</p>
<form action="{e(n['form_action'])}" method="post" target="_blank" rel="noopener">
<label class="sr" for="nl-email">Email address</label><div class="field"><input id="nl-email" name="email" type="email" autocomplete="email" required placeholder="you@example.com">
<button type="submit">Subscribe</button></div>
<label class="consent"><input type="checkbox" required><span>I agree to receive emails from {SITE_HTML}. Sign-ups are handled by {e(n.get('provider', 'our newsletter provider'))}; see our <a href="/privacy/">privacy policy</a>.</span></label>
</form></div></div></section>"""

    # ------------------------------------------------------------------ pages
    def home(self) -> str:
        arts = self.articles
        label = {"ai": "Explore AI tools", "money": "Explore money guides"}
        cta = '<a class="btn primary" href="/guides/ai-for-small-business/">Start with a practical AI workflow</a>' + "".join(f'<a class="btn ghost" href="/{c}/">{label[c]}</a>'
                      for i, c in enumerate(self.channels))
        body = [f'<section class="hero"><div class="wrap"><h1>{HERO_TITLE}</h1><p>{e(HERO_TEXT)}</p><div class="cta">{cta}</div></div></section>']
        if arts:
            rest = "".join(self.card(a) for a in arts[1:7])
            body.append(f'<section class="section" aria-labelledby="latest-title"><div class="wrap"><div class="row">'
                        f'<h2 class="title" id="latest-title">Latest</h2><a href="/latest/">All articles →</a></div>'
                        f'<p class="lead">Newest first. Each one is built from checked sources.</p>{self.lead(arts[0])}'
                        f'{f"<div class=grid>{rest}</div>" if rest else ""}</div></section>')
        else:
            body.append('<section class="section"><div class="wrap"><p class="empty">Our first articles are on their way. '
                        'Each one is published once its facts have been checked.</p></div></section>')
        for c in self.channels:
            items = [a for a in arts if a.channel == c][:3]
            body.append(f'<section class="section" aria-labelledby="sec-{c}"><div class="wrap"><div class="row">'
                        f'<h2 class="title" id="sec-{c}">{e(CHANNELS[c][0])}</h2><a href="/{c}/">{ {"ai": "More AI tools", "money": "More money guides"}.get(c, "More")} →</a></div>'
                        f'<p class="lead">{e(CHANNELS[c][1])}</p><div class="grid">{"".join(self.card(a) for a in items)}</div></div></section>')
        if self.videos:
            vids = "".join(f'<div>{self.video_box(a)}<h3><a href="/articles/{e(a.slug)}/">{e(a.title)}</a></h3></div>' for a in self.videos[:3])
            body.append(f'<section class="section" aria-labelledby="sec-videos"><div class="wrap"><div class="row">'
                        f'<h2 class="title" id="sec-videos">Videos</h2><a href="/videos/">All videos →</a></div>'
                        f'<p class="lead">Short explainers from our YouTube channels, each with its full article.</p><div class="grid">{vids}</div></div></section>')
        body.append(self.newsletter())
        ld = [{"@context": "https://schema.org", "@type": "Organization", "name": SITE_NAME, "url": self.url + "/",
               "logo": self.url + "/icon-512.png", **({"sameAs": [s["url"] for s in self.socials]} if self.socials else {})},
              {"@context": "https://schema.org", "@type": "WebSite", "name": SITE_NAME, "url": self.url + "/"}]
        return self.page(SITE_NAME, f"{TAGLINE}. Practical AI guides and money explainers, every fact checked against its source.",
                         "/", "".join(body), ld=ld, alternates={"en": "/", "de": "/de/", "x-default": "/"} if self.german else None)

    def listing(self, path: str, title: str, intro: str, items: list) -> dict[str, str]:
        """A paginated list of cards: {path: html} for every page."""
        out = {}
        chunks = [items[i:i + PER_PAGE] for i in range(0, len(items), PER_PAGE)] or [[]]
        for n, chunk in enumerate(chunks, 1):
            here = path if n == 1 else f"{path}page/{n}/"
            nav = []
            if n > 1:
                nav.append(f'<a rel="prev" href="{path if n == 2 else f"{path}page/{n - 1}/"}">← Newer</a>')
            if n < len(chunks):
                nav.append(f'<a rel="next" href="{path}page/{n + 1}/">Older →</a>')
            cards = "".join(self.card(a) for a in chunk) or '<p class="empty">Nothing here yet.</p>'
            heading = title if n == 1 else f"{title} (page {n})"
            body = (f'<div class="wrap"><nav class="crumbs" aria-label="Breadcrumb"><ol><li><a href="/">Home</a></li><li aria-current="page">{e(title)}</li></ol></nav>'
                    f'<section class="section"><h1 class="title big">{e(heading)}</h1><p class="lead">{e(intro)}</p>'
                    f'<div class="grid">{cards}</div><div class="pager">{"".join(nav)}</div></section></div>')
            ld = [{"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": self.url + "/"},
                {"@type": "ListItem", "position": 2, "name": title, "item": self.url + path}]}]
            out[here] = self.page(heading, intro, here, body, ld=ld)
        return out

    def videos_page(self) -> str:
        items = "".join(f'<div>{self.video_box(a)}{self.tag(a.channel)}<h3><a href="/articles/{e(a.slug)}/">{e(a.title)}</a></h3>'
                        f'<p class="meta">{date(a.published)} · <a href="/articles/{e(a.slug)}/">Read the article</a></p></div>' for a in self.videos)
        body = (f'<div class="wrap"><nav class="crumbs" aria-label="Breadcrumb"><ol><li><a href="/">Home</a></li><li aria-current="page">Videos</li></ol></nav>'
                f'<section class="section"><h1 class="title big">Videos</h1>'
                f'<p class="lead">Explainers from our YouTube channels. Each video loads only when you press play.</p>'
                f'<div class="grid">{items}</div></section></div>')
        return self.page("Videos", "Short AI and money explainers from Penny & Pixel's YouTube channels.", "/videos/", body)

    def search_page(self) -> str:
        cats = " ".join(f'<a class="tag {c}" href="/{c}/">{e(CHANNELS[c][0])}</a>' for c in self.channels)
        body = (f'<div class="page"><h1>Search</h1><form id="search-form" action="/search/" method="get" role="search">'
                f'<label class="sr" for="q">Search articles</label><div class="field"><input id="q" name="q" type="search" '
                f'placeholder="Try: inflation, ChatGPT, budget" autocomplete="off"><button type="submit">Search</button></div></form>'
                f'<p id="search-status" class="meta" role="status" aria-live="polite"></p><ul id="results" class="results"></ul>'
                f'<noscript><p>Search needs JavaScript. You can browse the categories instead.</p></noscript>'
                f'<p class="meta">Browse: {cats} <a href="/latest/">Latest</a></p></div>')
        return self.page("Search", "Search Penny & Pixel's AI and money articles.", "/search/", body)

    def article(self, a, related: list) -> str:
        path = f"/articles/{a.slug}/"
        cat = CHANNELS.get(a.channel, (a.channel,))[0]
        parts = [f'<nav class="crumbs" aria-label="Breadcrumb"><ol><li><a href="/">Home</a></li><li><a href="/{e(a.channel)}/">{e(cat)}</a></li>'
                 f'<li aria-current="page">{e(a.title[:60])}{"…" if len(a.title) > 60 else ""}</li></ol></nav>',
                 f'<article class="article">{self.tag(a.channel)}<h1>{e(a.title)}</h1>',
                 f'<p class="byline"><span>By the {SITE_HTML} editorial team</span><span>Published <time datetime="{a.published.date().isoformat()}">{date(a.published)}</time>'
                 f' · source dates are listed below</span><span>{a.minutes} min read</span>'
                 + (f'<span><a href="/de/artikel/{e(a.slug)}/" lang="de" hreflang="de">Auf Deutsch lesen</a></span>' if a.de_blocks else "")
                 + '</p>']
        if a.modified and a.modified != a.published:
            parts.append(f'<p class="meta">Updated {date(a.modified)}. Editorial responsibility: Penny &amp; Pixel. Checks are automated unless a named human reviewer is stated.</p>')
        if a.channel == "money":
            parts.append('<p><a href="/tools/raise-inflation/">Use the raise-and-inflation calculator and worksheet</a></p>')
        if a.video_id:
            parts.append(self.video_box(a))
        elif a.image:
            parts.append(f'<figure class="figure">{self.picture(a, eager=True, sizes="(max-width:760px) 100vw, 720px")}</figure>')
        heads = [(i, t) for i, (k, t) in enumerate(a.blocks) if k == "h2"]
        if len(heads) >= 3:
            items = "".join(f'<li><a href="#s{i}">{e(t)}</a></li>' for i, t in heads)
            parts.append(f'<details class="toc" open><summary>In this article</summary><ol>{items}</ol></details>')
        prose, first = [], True
        for i, (kind, text) in enumerate(a.blocks):
            if kind == "h2":
                prose.append(f'<h2 id="s{i}">{e(text)}</h2>')
            else:
                prose.append(f'<p{" class=\"intro\"" if first else ""}>{e(text)}</p>')
                first = False
        if getattr(a, "unchecked", False):
            parts.append(f'<p class="note">{e(UNCHECKED_NOTE)}</p>')
        parts.append(f'<div class="prose">{"".join(prose)}</div>')
        if a.channel == "money":
            parts.append(f'<p class="note money">{e(MONEY_NOTE)}</p>')
        if a.offer:
            o = a.offer
            parts.append(f'<aside class="note" aria-label="Affiliate offer"><p><strong>Affiliate link.</strong> {e(o["disclosure"])}</p>'
                         f'<p><a href="{e(o["url"])}" data-event="affiliate_click" rel="sponsored nofollow noopener" target="_blank">{e(o["name"])}</a>'
                         f'{(" – " + e(o["blurb"])) if o.get("blurb") else ""}</p></aside>')
        if a.sources:
            items = "".join(f'<li><a href="{e(s["url"])}" rel="noopener" target="_blank">{e(s.get("title") or s["url"])}</a>'
                            f'{(" · " + e(s["publisher"])) if s.get("publisher") else ""}'
                            f'{(" · " + date(s["published_at"])) if isinstance(s.get("published_at"), datetime) else ""}</li>'
                            for s in a.sources)
            parts.append(f'<h2 class="h2s">Sources</h2><ol class="sources">{items}</ol>')
        parts.append(f'<p class="note">{e(AI_NOTE)} Spotted a mistake? See our <a href="/corrections/">corrections policy</a>.</p>')
        link = self.url + path
        parts.append(f'<div class="share" aria-label="Share this article">'
                     f'<a href="https://x.com/intent/post?text={quote(a.title)}&url={quote(link)}" rel="noopener" target="_blank">Share on X</a>'
                     f'<a href="https://www.facebook.com/sharer/sharer.php?u={quote(link)}" rel="noopener" target="_blank">Facebook</a>'
                     f'<a href="https://www.linkedin.com/sharing/share-offsite/?url={quote(link)}" rel="noopener" target="_blank">LinkedIn</a>'
                     f'<a href="mailto:?subject={quote(a.title)}&body={quote(link)}">Email</a>'
                     f'<button type="button" data-copy="{e(link)}" hidden>Copy link</button></div>')
        if related:
            parts.append(f'<section class="related" aria-labelledby="rel-title"><h2 id="rel-title" class="h2s">Keep reading</h2>'
                         f'<div class="grid">{"".join(self.card(r) for r in related)}</div></section>')
        parts.append("</article>")
        ld = [{"@context": "https://schema.org", "@type": "Article", "headline": a.title[:110], "description": a.description,
               "datePublished": a.published.isoformat(), "dateModified": (a.modified or a.published).isoformat(), "mainEntityOfPage": link,
               "author": {"@type": "Organization", "name": SITE_NAME, "url": self.url + "/about/"},
               "publisher": {"@type": "Organization", "name": SITE_NAME, "logo": {"@type": "ImageObject", "url": self.url + "/icon-512.png"}},
               **({"image": [self.url + f"/images/{a.image}"]} if a.image else {}),
               **({"citation": [s["url"] for s in a.sources]} if a.sources else {})},
              {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
                  {"@type": "ListItem", "position": 1, "name": "Home", "item": self.url + "/"},
                  {"@type": "ListItem", "position": 2, "name": cat, "item": f"{self.url}/{a.channel}/"},
                  {"@type": "ListItem", "position": 3, "name": a.title, "item": link}]}]
        if a.video_id:
            ld.append({"@context": "https://schema.org", "@type": "VideoObject", "name": a.title, "description": a.description,
                       "uploadDate": a.published.isoformat(), "thumbnailUrl": f"https://i.ytimg.com/vi/{a.video_id}/hqdefault.jpg",
                       "embedUrl": f"https://www.youtube-nocookie.com/embed/{a.video_id}",
                       "contentUrl": f"https://www.youtube.com/watch?v={a.video_id}"})
        alts = {"en": path, "de": f"/de/artikel/{a.slug}/", "x-default": path} if a.de_blocks else None
        return self.page(a.title, a.description, path, f'<div class="wrap">{"".join(parts)}</div>', image=a.image,
                         og_type="article", ld=ld, alternates=alts)

    def simple(self, path: str, title: str, description: str, body_html: str) -> str:
        alts = {"en": "/about/", "de": "/de/ueber-uns/", "x-default": "/about/"} if path == "/about/" and self.german else None
        return self.page(title, description, path, f'<div class="wrap"><div class="page"><h1>{e(title)}</h1>{body_html}</div></div>',
                         alternates=alts)

    def not_found(self) -> str:
        return self.page("Page not found", "This page doesn't exist.", "/404.html",
                         '<div class="wrap"><div class="page"><h1>We couldn\'t find that page</h1><p>It may have moved, or the '
                         'link may be mistyped.</p><p><a class="btn solid" href="/">Go to the homepage</a></p>'
                         '<p><a href="/search/">Search the articles</a></p></div></div>', noindex=True)

    # ------------------------------------------------------------------ German (AI-tools articles only)
    DE_NOTE = ("Automatisch aus dem Englischen übersetzt. Eine Software hat geprüft, dass alle Zahlen und Namen mit dem "
               "Original übereinstimmen. Die Quellen sind überwiegend englischsprachig. Allgemeine Information, keine Beratung.")

    def german_nav(self) -> list:
        return [("/de/", "Alle Artikel"), ("/de/ueber-uns/", "Über uns"), ("/", "English", "en")]

    def german_footer(self) -> str:
        return (f'<footer class="foot" lang="de"><div class="wrap"><p><a href="/de/">{SITE_HTML} auf Deutsch</a> · '
                f'<a href="/de/ueber-uns/">Über uns</a> · <a href="/" lang="en" hreflang="en">English</a> · '
                f'<a href="/privacy/" lang="en">Privacy policy (English)</a></p>'
                f'<p class="small">&copy; {self.year} {SITE_HTML}. Allgemeine Information, keine persönliche Beratung.</p></div></footer>')

    def german_card(self, a) -> str:
        return (f'<article class="card"><a class="cover" href="/de/artikel/{e(a.slug)}/" tabindex="-1" aria-hidden="true">{self.picture(a)}</a>'
                f'<div class="body"><span class="tag ai">KI-Tools</span><h3><a href="/de/artikel/{e(a.slug)}/">{e(a.de_title)}</a></h3>'
                f'<p class="meta">{a.published:%d.%m.%Y}</p></div></article>')

    def german_home(self) -> str:
        cards = "".join(self.german_card(a) for a in self.german)
        body = (f'<div class="wrap"><section class="section"><h1 class="title big">KI-Tools verständlich erklärt</h1>'
                f'<p class="lead">Praktische Artikel über KI-Werkzeuge, übersetzt aus unserer englischen Ausgabe. Jede Angabe '
                f'ist mit einer Quelle belegt.</p><p class="note">{e(self.DE_NOTE)}</p><div class="grid">{cards}</div></section></div>')
        return self.page(f"{SITE_NAME} auf Deutsch", "Praktische Artikel über KI-Tools, jede Angabe mit Quelle.", "/de/", body,
                         lang="de", nav_links=self.german_nav(), footer=self.german_footer(),
                         alternates={"de": "/de/", "en": "/", "x-default": "/"})

    def german_about(self) -> str:
        body = (f'<div class="wrap"><div class="page"><h1>Über uns</h1><p>{SITE_HTML} veröffentlicht praktische Anleitungen zu '
                'KI-Tools und Geldthemen, vor allem für Leserinnen und Leser in den USA, Großbritannien, Kanada, Australien und '
                'Deutschland.</p><h2>So arbeiten wir</h2><ul><li>Jeder Artikel entsteht aus einem unserer Videos und wird mit '
                'Hilfe von KI-Werkzeugen recherchiert.</li><li>Jede Tatsachenbehauptung wird mit einer genannten Quelle samt '
                'Datum abgeglichen.</li><li>Wir behaupten nie, etwas selbst getestet zu haben, wenn wir es nicht getan haben.'
                '</li><li>Die deutschen Artikel sind automatische Übersetzungen; Geldthemen erscheinen nur auf Englisch.</li></ul>'
                '<p><a href="/about/" lang="en" hreflang="en">About us (English)</a></p></div></div>')
        return self.page("Über uns", f"Wer {SITE_NAME} ist und wie jede Angabe geprüft wird.", "/de/ueber-uns/", body,
                         lang="de", nav_links=self.german_nav(), footer=self.german_footer(),
                         alternates={"de": "/de/ueber-uns/", "en": "/about/", "x-default": "/about/"})

    def german_article(self, a) -> str:
        path = f"/de/artikel/{a.slug}/"
        heads = [(i, t) for i, (k, t) in enumerate(a.de_blocks) if k == "h2"]
        prose, first = [], True
        for i, (kind, text) in enumerate(a.de_blocks):
            if kind == "h2":
                prose.append(f'<h2 id="s{i}">{e(text)}</h2>')
            else:
                cls = ' class="intro"' if first else ""
                prose.append(f"<p{cls}>{e(text)}</p>")
                first = False
        toc = ("".join(f'<li><a href="#s{i}">{e(t)}</a></li>' for i, t in heads))
        sources = "".join(f'<li><a href="{e(s["url"])}" rel="noopener" target="_blank" lang="en">{e(s.get("title") or s["url"])}</a>'
                          f'{(" · " + e(s["publisher"])) if s.get("publisher") else ""}'
                          f'{(" · " + format(s["published_at"], "%d.%m.%Y")) if isinstance(s.get("published_at"), datetime) else ""}</li>'
                          for s in a.sources)
        body = (f'<div class="wrap"><nav class="crumbs" aria-label="Brotkrumen"><ol><li><a href="/de/">Startseite</a></li>'
                f'<li aria-current="page">{e(a.de_title[:60])}</li></ol></nav><article class="article"><span class="tag ai">KI-Tools</span>'
                f'<h1>{e(a.de_title)}</h1><p class="byline"><span>Vom {SITE_HTML}-Team</span><span>Veröffentlicht am '
                f'<time datetime="{a.published.date().isoformat()}">{a.published:%d.%m.%Y}</time> · Stand der Angaben: dieses Datum</span>'
                f'<span><a href="/articles/{e(a.slug)}/" lang="en" hreflang="en">Original (English)</a></span></p>'
                + (self.video_box(a) if a.video_id else (f'<figure class="figure">{self.picture(a, eager=True, sizes="(max-width:760px) 100vw, 720px")}</figure>' if a.image else ""))
                + (f'<details class="toc" open><summary>In diesem Artikel</summary><ol>{toc}</ol></details>' if len(heads) >= 3 else "")
                + f'<div class="prose">{"".join(prose)}</div><p class="note">{e(self.DE_NOTE)}</p>'
                + (f'<h2 class="h2s">Quellen</h2><ol class="sources">{sources}</ol>' if sources else "")
                + "</article></div>")
        ld = [{"@context": "https://schema.org", "@type": "Article", "headline": a.de_title[:110], "inLanguage": "de",
               "datePublished": a.published.isoformat(), "mainEntityOfPage": self.url + path,
               "author": {"@type": "Organization", "name": SITE_NAME}, "publisher": {"@type": "Organization", "name": SITE_NAME},
               **({"image": [self.url + f"/images/{a.image}"]} if a.image else {})}]
        return self.page(a.de_title, (a.de_blocks[0][1] if a.de_blocks else a.description)[:200], path, body, image=a.image,
                         og_type="article", ld=ld, lang="de", nav_links=self.german_nav(), footer=self.german_footer(),
                         alternates={"de": path, "en": f"/articles/{a.slug}/", "x-default": f"/articles/{a.slug}/"})
