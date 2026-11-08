"""The public Penny & Pixel website: one article for every approved, published video.

The website is separate from the studio. It is built here as plain files (HTML, pictures, a sitemap) and uploaded to
Cloudflare Pages by the `site` workflow. It has no login, no database and no keys, and never links to the dashboard:
visitors only ever read pages.

An article says exactly what its approved video says (the narration, checked fact by fact against dated sources),
so no new, unchecked claims are written for the website. A package is left out when:
  - it isn't approved, or its long video hasn't been posted yet
  - any claim is unsupported, contradicted or stale, or a blocking problem is still listed
  - it is a sensitive money topic (investing, tax, loans...): those wait for the owner in the studio, and the
    website never asks the owner anything
A package that is rejected later simply disappears at the next build.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import config, db, offers

SITE_NAME = "Penny & Pixel"
TAGLINE = "AI tools and money skills, explained simply"
CHANNELS = {"ai": ("AI tools", "Pixel explains what AI tools can really do, without the hype."),
            "money": ("Money", "Penny explains budgeting, saving, paychecks and credit with real numbers.")}
MONEY_NOTE = "This is general education, not personal financial advice. Consider your own situation or speak to a licensed professional."
AI_NOTE = ("Written from our video script. Researched with AI tools; every fact is checked against the sources listed "
           "below, with their dates.")
BAD_CLAIMS = ("unsupported", "contradicted", "stale")
PER_PAGE = 30
MIN_WORDS = 250          # less than this after cleaning isn't worth a page (thin pages hurt the whole site in search)
# A hands-on test the studio never ran ("I just added it to a test site", "our live test"): the package is left out
# when its title or opening says so, and any such sentence is removed from the article
TEST_CLAIM = re.compile(r"\blive test\b|\bour (own )?(live )?test\b|\b(I|we)( have| just|'ve)?\s+(added|set up|ran|tried|tested|"
                        r"built|put)\b[^.]{0,60}\btest", re.IGNORECASE)
# Things only a video says, and leftovers of the writer's instructions ("as described in the passage")
VIDEO_TALK = re.compile(r"\b(in this video|this video|the video is|in the video|in today's video|the passage|subscribe|"
                        r"hit the bell|like this video|consider your own situation|not personal (financial )?advice)\b",
                        re.IGNORECASE)   # the money note is shown once, under the article
# A sentence that leans on the one before it ("That single number tells us...") goes when that one was removed
LEANS_BACK = re.compile(r"^(that|this|these|those|it|they|so|then)\b", re.IGNORECASE)
SHORT_PARAGRAPH = 30     # words: a shorter paragraph joins the one before it
# Arithmetic read out loud ("$0.05 / (1 + 0.006) - $0.05") is hard to follow on a page: the sentence is dropped, the
# result stays in the sentences that state it
SPOKEN_SUM = re.compile(r"\d\s*[*/×]\s*[\d($]|\)\s*[-+*/]\s*\$?\d|=\s*\$?-?\d|\btimes \d+ times\b")
NEAR_REPEAT = 0.6        # share of a sentence's words already said in one earlier sentence: it's a repeat


def site_url() -> str:
    """The website's address: the SITE_URL repository variable, else config/services.yaml (website.url)."""
    return (os.environ.get("SITE_URL") or (config.services().get("website") or {}).get("url")
            or "https://pennyandpixel.pages.dev").rstrip("/")


@dataclass
class Article:
    project_id: str
    channel: str
    slug: str
    title: str
    description: str
    paragraphs: list[str]
    published: datetime
    sources: list[dict] = field(default_factory=list)
    video_url: str | None = None
    video_id: str | None = None
    image: str | None = None          # file name inside images/
    offer: dict | None = None


def slugify(title: str, project_id: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:70].strip("-") or "article"
    return f"{base}-{str(project_id).replace('-', '')[:6]}"   # stable: the same package keeps its address


def _video_id(url: str | None) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]+)", url or "")
    return m.group(1) if m else None


def video_is_public(url: str, client: httpx.Client | None = None) -> bool:
    """YouTube answers its public oEmbed address only for videos anyone can watch (private ones return 401/404)."""
    try:
        r = (client or httpx.Client(timeout=15)).get("https://www.youtube.com/oembed", params={"url": url, "format": "json"})
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def why_left_out(conn, p: dict, body: dict) -> str | None:
    """The reason a package isn't published on the website, or None."""
    from .review.auto import MONEY_SENSITIVE

    bad = db.one(conn, """select count(*) n from research_claims where script_version_id=%s and status = any(%s)""",
                 (p["sv_id"], list(BAD_CLAIMS)))["n"]
    if bad:
        return f"{bad} claim(s) not backed by a source"
    blockers = [f for f in ((p["quality_report"] or {}).get("findings") or []) if f.get("kind") == "blocker"]
    if blockers:
        return f"blocking problem: {blockers[0].get('text', '')[:80]}"
    if p["channel_slug"] == "money":
        text = " ".join([p["title"], body.get("title", "")] + [s.get("narration", "") for s in body.get("scenes", [])])
        hits = sorted({m.group(0).lower() for m in MONEY_SENSITIVE.finditer(text)})
        if hits:
            return f"sensitive money topic ({', '.join(hits[:3])})"
    from .script.quality import INVENTED_TEST

    opening = f"{body.get('title', '')} {p['title']} {body.get('hook', '')}"
    if TEST_CLAIM.search(opening) or INVENTED_TEST.search(opening):
        return "claims a hands-on test that didn't happen"
    if sum(len(x.split()) for x in article_paragraphs(body)) < MIN_WORDS:
        return "too little left once repeats and video-only lines are removed"
    return None


def _sentence_words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9%$.]+", s.lower()) if len(w) > 2}


def article_paragraphs(body: dict) -> list[str]:
    """The narration as article paragraphs: the opening, then one paragraph per scene, without what only a video says,
    without claimed hands-on tests, and without sentences that repeat an earlier one (a video repeats key numbers;
    an article says them once)."""
    from .script.quality import INVENTED_TEST

    kept: list[set[str]] = []
    out: list[str] = []
    for raw in [s.get("narration", "") for s in body.get("scenes", [])]:
        sentences, dropped_last = [], False
        for sent in re.split(r"(?<=[.!?])\s+", (raw or "").strip()):
            if not sent:
                continue
            w = _sentence_words(sent)
            if (VIDEO_TALK.search(sent) or TEST_CLAIM.search(sent) or INVENTED_TEST.search(sent) or SPOKEN_SUM.search(sent)
                    or (w and any(len(w & k) / len(w) >= NEAR_REPEAT for k in kept))
                    or (dropped_last and LEANS_BACK.match(sent))):
                dropped_last = True
                continue
            dropped_last = False
            kept.append(w)
            sentences.append(sent)
        if not sentences:
            continue
        text = " ".join(sentences)
        if out and (len(out[-1].split()) < SHORT_PARAGRAPH or len(text.split()) < SHORT_PARAGRAPH):
            out[-1] = f"{out[-1]} {text}"
        else:
            out.append(text)
    return out


def collect(conn, storage, work: Path, check_video=video_is_public) -> tuple[list[Article], list[str]]:
    """Every package that may be on the website, and a line for each one that is left out."""
    rows = db.all_(conn, """
        select p.*, sv.id sv_id, sv.body,
               (select pp.url from published_posts pp join scheduled_posts sp on sp.id = pp.scheduled_post_id
                  join content_variants v on v.id = sp.variant_id
                 where v.project_id = p.id and v.kind = 'long_video' and pp.platform = 'youtube'
                 order by pp.published_at limit 1) youtube_url,
               (select min(pp.published_at) from published_posts pp join scheduled_posts sp on sp.id = pp.scheduled_post_id
                  join content_variants v on v.id = sp.variant_id where v.project_id = p.id and v.kind = 'long_video') first_posted
          from content_projects p
          join script_versions sv on sv.id = coalesce(p.approved_script_version_id, p.current_script_version_id)
         where p.parent_project_id is null and p.format = 'long' and p.status in ('approved', 'scheduled', 'published')
           and exists (select 1 from approvals a where a.target_type = 'project' and a.target_id = p.id and a.decision = 'approved')
         order by p.created_at""")
    articles, skipped = [], []
    images = work / "images"
    images.mkdir(parents=True, exist_ok=True)
    for p in rows:
        body = p["body"] or {}
        if not p["first_posted"]:
            continue  # not posted yet: it appears once its video is out
        reason = why_left_out(conn, p, body)
        if reason:
            skipped.append(f"{p['title'][:70]}: {reason}")
            continue
        title = body.get("title") or p["title"]
        slug = slugify(title, p["id"])
        paragraphs = article_paragraphs(body)
        hook = (body.get("hook") or "").strip()
        if hook and not (TEST_CLAIM.search(hook) or VIDEO_TALK.search(hook)):
            paragraphs = [hook] + paragraphs
        art = Article(str(p["id"]), p["channel_slug"], slug, title, (body.get("promise") or paragraphs[0])[:300],
                      paragraphs, p["first_posted"], sources=_sources(conn, body))
        if p["youtube_url"] and check_video(p["youtube_url"]):
            art.video_url, art.video_id = p["youtube_url"], _video_id(p["youtube_url"])
        art.image = _image(conn, storage, p["id"], images / f"{slug}.jpg", work)
        art.offer = offers.match(conn, p["channel_slug"], f"{title} {' '.join(paragraphs)}")
        articles.append(art)
    articles.sort(key=lambda a: a.published, reverse=True)
    return articles, skipped


def _sources(conn, body: dict) -> list[dict]:
    """The sources behind the facts this script cites, each once, with its publisher and date."""
    used = {k for c in body.get("claims", []) for k in c.get("fact_refs", [])}
    ids = []
    for f in body.get("facts", []):
        if f.get("key") in used and f.get("source_id") and f["source_id"] not in ids:
            ids.append(f["source_id"])
    if not ids:
        return []
    rows = db.all_(conn, """select id, title, publisher, url, published_at from research_sources
                            where id::text = any(%s) and url is not null""", (ids,))
    order = {i: n for n, i in enumerate(ids)}
    return sorted(rows, key=lambda r: order.get(str(r["id"]), 0))


def _image(conn, storage, project_id, dest: Path, work: Path) -> str | None:
    from .publish.runner import _thumbnail

    got = _thumbnail(conn, storage, project_id, work / "tmp" / str(project_id))
    if not got:
        return None
    shutil.copyfile(got, dest)
    return dest.name


# ------------------------------------------------------------------------------------------------- rendering

def _e(s) -> str:
    return html.escape(str(s or ""), quote=True)


CSS = """
:root{--ink:#14121F;--paper:#FBF8F2;--gold:#E3A72F;--cyan:#19B3CF;--muted:#5b5866;--line:#e6e1d6}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:18px/1.65 Georgia,'Times New Roman',serif}
a{color:inherit}header,footer{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:760px;margin:0 auto;padding:0 18px}
header{border-bottom:1px solid var(--line);background:#fff}header .wrap{display:flex;align-items:center;gap:14px;padding:14px 18px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:10px;text-decoration:none;font-weight:700;font-size:20px}
nav{display:flex;gap:16px;font-size:15px;margin-left:auto}nav a{text-decoration:none;color:var(--muted)}nav a:hover{color:var(--ink)}
h1{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;line-height:1.2;font-size:34px;margin:28px 0 10px}
h2{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:22px;margin:34px 0 10px}
.meta{font:14px system-ui,sans-serif;color:var(--muted)}
.lede{font-size:21px;color:#2b2838}
.card{display:block;text-decoration:none;border-bottom:1px solid var(--line);padding:18px 0}
.card h2{margin:4px 0 6px;font-size:21px}.card p{margin:0;color:var(--muted);font-size:16px}
.card img,.hero{width:100%;height:auto;border-radius:10px;display:block;margin:10px 0}
.tag{display:inline-block;font:600 12px system-ui,sans-serif;text-transform:uppercase;letter-spacing:.05em;color:#fff;background:var(--ink);border-radius:4px;padding:2px 7px}
.tag.money{background:#8a6410}.tag.ai{background:#0e7f94}
.video{position:relative;padding-top:56.25%;margin:18px 0}.video iframe{position:absolute;inset:0;width:100%;height:100%;border:0;border-radius:10px}
.note{font:15px/1.5 system-ui,sans-serif;background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:22px 0}
ol.sources{font:15px/1.5 system-ui,sans-serif;padding-left:22px}ol.sources li{margin:6px 0}
.pager{display:flex;justify-content:space-between;font:15px system-ui,sans-serif;margin:24px 0}
footer{border-top:1px solid var(--line);margin-top:48px;padding:22px 0;font-size:14px;color:var(--muted)}footer a{margin-right:14px}
@media (max-width:600px){body{font-size:17px}h1{font-size:28px}}
"""

LOGO = ('<svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="#1B1F2A"/>'
        '<circle cx="12" cy="16" r="6" fill="#E3A72F"/><rect x="17" y="10" width="11" height="12" rx="2" fill="#19B3CF"/></svg>')


def _page(title: str, description: str, path: str, body: str, *, head_extra: str = "", image: str | None = None,
          og_type: str = "website") -> str:
    url = site_url() + path
    full = title if title == SITE_NAME else f"{title} · {SITE_NAME}"
    img = f'<meta property="og:image" content="{_e(site_url() + "/images/" + image)}">' if image else ""
    return f"""<!doctype html>
<html lang="en-US"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(full)}</title><meta name="description" content="{_e(description)}"><link rel="canonical" href="{_e(url)}">
<meta property="og:site_name" content="{SITE_NAME}"><meta property="og:title" content="{_e(title)}">
<meta property="og:description" content="{_e(description)}"><meta property="og:url" content="{_e(url)}"><meta property="og:type" content="{og_type}">{img}
<meta name="twitter:card" content="summary_large_image"><link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="alternate" type="application/rss+xml" title="{SITE_NAME}" href="/feed.xml"><link rel="stylesheet" href="/style.css">{head_extra}
</head><body>
<header><div class="wrap"><a class="brand" href="/">{LOGO}<span>{SITE_NAME}</span></a>
<nav><a href="/ai/">AI tools</a><a href="/money/">Money</a><a href="/about/">About</a></nav></div></header>
<main class="wrap">{body}</main>
<footer><div class="wrap"><p>{_e(TAGLINE)}.</p>
<p><a href="/about/">About</a><a href="/privacy/">Privacy</a><a href="/affiliate-disclosure/">Affiliate disclosure</a><a href="/feed.xml">RSS</a></p>
<p>&copy; {datetime.now(timezone.utc).year} {SITE_NAME}</p></div></footer>
</body></html>
"""


def _date(d: datetime) -> str:
    return f"{d:%B} {d.day}, {d:%Y}"


def _card(a: Article) -> str:
    label = CHANNELS[a.channel][0] if a.channel in CHANNELS else a.channel
    img = f'<img src="/images/{_e(a.image)}" alt="" loading="lazy" width="1280" height="720">' if a.image else ""
    return (f'<a class="card" href="/articles/{_e(a.slug)}/">{img}<span class="tag {_e(a.channel)}">{_e(label)}</span>'
            f'<h2>{_e(a.title)}</h2><p>{_e(a.description)}</p><p class="meta">{_date(a.published)}</p></a>')


def article_html(a: Article) -> str:
    label = CHANNELS[a.channel][0] if a.channel in CHANNELS else a.channel
    parts = [f'<p class="meta"><span class="tag {_e(a.channel)}">{_e(label)}</span> · {_date(a.published)} · '
             'facts as of this date</p>',
             f"<h1>{_e(a.title)}</h1>"]
    if a.video_id:
        parts.append(f'<div class="video"><iframe src="https://www.youtube-nocookie.com/embed/{_e(a.video_id)}" '
                     f'title="{_e(a.title)}" loading="lazy" allowfullscreen '
                     'allow="accelerometer; encrypted-media; gyroscope; picture-in-picture"></iframe></div>')
    elif a.image:
        parts.append(f'<img class="hero" src="/images/{_e(a.image)}" alt="" width="1280" height="720">')
    for i, p in enumerate(a.paragraphs):
        cls = ' class="lede"' if i == 0 else ""
        parts.append(f"<p{cls}>{_e(p)}</p>")
    if a.channel == "money":
        parts.append(f'<p class="note">{_e(MONEY_NOTE)}</p>')
    if a.offer:
        o = a.offer
        parts.append(f'<div class="note"><p>{_e(o["disclosure"])}</p><p><a href="{_e(o["url"])}" rel="sponsored nofollow noopener" '
                     f'target="_blank">{_e(o["name"])}</a>{(" – " + _e(o["blurb"])) if o.get("blurb") else ""}</p>'
                     + (f'<p>{_e(offers.MONEY_NOTE)}</p>' if a.channel == "money" else "") + "</div>")
    if a.video_url and not a.video_id:
        parts.append(f'<p><a href="{_e(a.video_url)}">Watch the video on YouTube</a></p>')
    if a.sources:
        items = "".join(f'<li><a href="{_e(s["url"])}" rel="noopener" target="_blank">{_e(s["title"] or s["url"])}</a>'
                        f'{(" · " + _e(s["publisher"])) if s.get("publisher") else ""}'
                        f'{(" · " + _date(s["published_at"])) if isinstance(s.get("published_at"), datetime) else ""}</li>'
                        for s in a.sources)
        parts.append(f'<h2>Sources</h2><ol class="sources">{items}</ol>')
    parts.append(f'<p class="note">{_e(AI_NOTE)}</p>')
    ld = {"@context": "https://schema.org", "@type": "Article", "headline": a.title[:110], "description": a.description,
          "datePublished": a.published.isoformat(), "mainEntityOfPage": f"{site_url()}/articles/{a.slug}/",
          "author": {"@type": "Organization", "name": SITE_NAME}, "publisher": {"@type": "Organization", "name": SITE_NAME}}
    if a.image:
        ld["image"] = f"{site_url()}/images/{a.image}"
    ld_json = json.dumps(ld).replace("</", "<\\/")
    head = f'<script type="application/ld+json">{ld_json}</script>'
    return _page(a.title, a.description, f"/articles/{a.slug}/", "\n".join(parts), head_extra=head, image=a.image,
                 og_type="article")


STATIC = {
    "about": ("About", "Who we are and how we check every fact.", f"""<h1>About {SITE_NAME}</h1>
<p>{SITE_NAME} makes simple, practical guides about two things that change everyday life: AI tools and money.</p>
<p><b>Pixel</b> explains what AI tools like ChatGPT can really do at work and at home, without the hype. <b>Penny</b> explains
budgeting, saving, paychecks, credit and other money basics, with real numbers and their sources.</p>
<h2>How we work</h2>
<p>Every article comes from one of our videos. We research each topic with the help of AI tools, then check every fact
against a named source with its date, and list those sources under the article. When something is an opinion, we say so.
We never claim to have tested something ourselves unless we did.</p>
<p>Money articles are general education, not personal financial advice.</p>"""),
    "privacy": ("Privacy policy", "What this website collects (almost nothing) and why.", f"""<h1>Privacy policy</h1>
<p>{SITE_NAME} is a reading website. It has no accounts, no sign-up forms and no comments, and it doesn't use cookies of its own.</p>
<h2>What is collected</h2>
<p>Our hosting provider, Cloudflare, processes standard technical information (such as your IP address and browser type) to
deliver and protect the pages. See the <a href="https://www.cloudflare.com/privacypolicy/">Cloudflare privacy policy</a>.</p>
<h2>Videos</h2>
<p>Some articles include a YouTube video, loaded from youtube-nocookie.com. When you play it, YouTube's own terms and the
<a href="https://policies.google.com/privacy">Google Privacy Policy</a> apply.</p>
<h2>Links</h2>
<p>Articles link to their sources and, sometimes, to affiliate offers (see our <a href="/affiliate-disclosure/">affiliate
disclosure</a>). Other websites have their own privacy policies.</p>"""),
    "affiliate-disclosure": ("Affiliate disclosure", "How affiliate links work on this website.", f"""<h1>Affiliate disclosure</h1>
<p>Some articles contain affiliate links. If you buy or sign up through one, {SITE_NAME} may earn a commission at no extra
cost to you. Affiliate links are always labeled where they appear.</p>
<p>Affiliate offers never change what our articles say: articles are written from our checked research first, and an offer
is added only if it matches the topic. Money articles are general education, not personal financial advice: compare options
before you sign up for anything.</p>"""),
}


def build(articles: list[Article], out: Path, images_dir: Path | None = None) -> dict:
    """Write the whole website into `out` (replacing what was there)."""
    if out.exists():
        shutil.rmtree(out)
    (out / "articles").mkdir(parents=True)
    if images_dir and images_dir.exists():
        shutil.copytree(images_dir, out / "images", dirs_exist_ok=True)
    (out / "style.css").write_text(CSS.strip() + "\n")
    (out / "favicon.svg").write_text(LOGO.replace('width="30" height="30" ', "").replace(' aria-hidden="true"', "")
                                     .replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" '))
    for a in articles:
        d = out / "articles" / a.slug
        d.mkdir(parents=True)
        (d / "index.html").write_text(article_html(a))

    def listing(path: str, title: str, intro: str, items: list[Article], heading: str):
        pages = [items[i:i + PER_PAGE] for i in range(0, len(items), PER_PAGE)] or [[]]
        for n, chunk in enumerate(pages, 1):
            here = path if n == 1 else f"{path}page/{n}/"
            nav = []
            if n > 1:
                nav.append(f'<a href="{path if n == 2 else f"{path}page/{n - 1}/"}">← Newer</a>')
            if n < len(pages):
                nav.append(f'<a href="{path}page/{n + 1}/">Older →</a>')
            cards = "".join(_card(a) for a in chunk) or "<p>New articles are on their way.</p>"
            body = f"<h1>{_e(heading)}</h1><p class=\"lede\">{_e(intro)}</p>{cards}<div class=\"pager\">{''.join(nav)}</div>"
            d = out / here.strip("/")
            d.mkdir(parents=True, exist_ok=True)
            (d / "index.html").write_text(_page(title, intro, here, body))

    listing("/", SITE_NAME, f"{TAGLINE}. Every fact checked against its source.", articles, SITE_NAME)
    for ch, (label, intro) in CHANNELS.items():
        listing(f"/{ch}/", label, intro, [a for a in articles if a.channel == ch], label)
    for slug, (title, desc, body) in STATIC.items():
        (out / slug).mkdir(parents=True, exist_ok=True)
        (out / slug / "index.html").write_text(_page(title, desc, f"/{slug}/", body))
    (out / "404.html").write_text(_page("Page not found", "This page doesn't exist.", "/404.html",
                                        '<h1>Page not found</h1><p>Try the <a href="/">latest articles</a>.</p>'))
    now = datetime.now(timezone.utc).date().isoformat()
    urls = [("/", now)] + [(f"/{c}/", now) for c in CHANNELS] + [(f"/{s}/", now) for s in STATIC] + \
           [(f"/articles/{a.slug}/", a.published.date().isoformat()) for a in articles]
    (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                     + "".join(f"<url><loc>{_e(site_url() + u)}</loc><lastmod>{d}</lastmod></url>\n" for u, d in urls)
                                     + "</urlset>\n")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {site_url()}/sitemap.xml\n")
    items = "".join(f"<item><title>{_e(a.title)}</title><link>{_e(site_url())}/articles/{_e(a.slug)}/</link>"
                    f"<guid>{_e(site_url())}/articles/{_e(a.slug)}/</guid><pubDate>{a.published:%a, %d %b %Y %H:%M:%S +0000}</pubDate>"
                    f"<description>{_e(a.description)}</description></item>" for a in articles[:30])
    (out / "feed.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><title>{SITE_NAME}</title>'
                                  f"<link>{_e(site_url())}/</link><description>{_e(TAGLINE)}</description>{items}</channel></rss>\n")
    (out / "_headers").write_text("/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n"
                                  "  X-Frame-Options: DENY\n")
    return {"articles": len(articles), "ai": sum(a.channel == "ai" for a in articles),
            "money": sum(a.channel == "money" for a in articles)}


def build_site(conn, storage, out: Path) -> dict:
    """Collect and write the website; the summary says what was published and what was left out, and why."""
    work = config.runtime().work_dir / "site"
    if work.exists():
        shutil.rmtree(work)
    articles, skipped = collect(conn, storage, work)
    summary = build(articles, out, work / "images")
    summary["left_out"] = skipped
    db.audit(conn, "website_built", "website", None, {"articles": summary["articles"], "left_out": skipped[:20]}, actor="engine")
    return summary
