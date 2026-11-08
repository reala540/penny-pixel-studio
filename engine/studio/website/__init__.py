"""Build the public website as static files without exposing studio credentials.

Articles have their own automatic evidence and meaning checks, independent of video rendering or upload.
Rejected, hidden, unsupported or sensitive content is excluded. Saved article snapshots preserve URLs and real
publication/review dates. Modules below collect eligible content, render pages and supply the static assets.
"""

from __future__ import annotations

import html
import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

from .. import config, db, offers
from . import assets, pages, render
from .render import CHANNELS, SITE_HTML, TAGLINE, date, e

BAD_CLAIMS = ("unsupported", "contradicted", "stale")
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
    blocks: list[tuple[str, str]] | None = None   # ("h2", heading) / ("p", paragraph); from paragraphs if not given
    webp: bool = False                # 640 and 1280 wide WebP copies of the image exist
    image_alt: str = ""
    de_title: str | None = None       # German version (AI-tools articles whose translation passed the checks)
    de_blocks: list[tuple[str, str]] | None = None
    modified: datetime | None = None
    checked: datetime | None = None
    notes: list[str] = field(default_factory=list)   # what the AI steps did or why they weren't used

    def __post_init__(self):
        if self.blocks is None:
            self.blocks = [("p", x) for x in self.paragraphs]
        if not self.image_alt:
            self.image_alt = f"Illustration for: {self.title}"

    @property
    def words(self) -> int:
        return sum(len(t.split()) for k, t in self.blocks if k == "p")

    @property
    def minutes(self) -> int:
        return max(1, round(self.words / 230))


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
    from ..review.auto import MONEY_SENSITIVE

    if p.get("fresh_until") and p["fresh_until"] < datetime.now(timezone.utc):
        return "source freshness expired; refresh the evidence before publishing"
    bad = db.one(conn, """select count(*) n from research_claims where script_version_id=%s and status = any(%s)""",
                 (p["sv_id"], list(BAD_CLAIMS)))["n"]
    if bad:
        return f"{bad} claim(s) not backed by a source"
    blockers = [f for f in ((p["quality_report"] or {}).get("findings") or []) if f.get("kind") == "blocker" and f.get("code") != "package_part"]
    if blockers:
        return f"blocking problem: {blockers[0].get('text', '')[:80]}"
    if p["channel_slug"] == "money":
        text = " ".join([p["title"], body.get("title", "")] + [s.get("narration", "") for s in body.get("scenes", [])])
        hits = sorted({m.group(0).lower() for m in MONEY_SENSITIVE.finditer(text)})
        if hits:
            return f"sensitive money topic ({', '.join(hits[:3])})"
    from ..script.quality import INVENTED_TEST

    opening = f"{body.get('title', '')} {p['title']} {body.get('hook', '')}"
    if TEST_CLAIM.search(opening) or INVENTED_TEST.search(opening):
        return "claims a hands-on test that didn't happen"
    if sum(len(x.split()) for x in article_paragraphs(body)) < MIN_WORDS:
        return "too little left once repeats and video-only lines are removed"
    return None


def _sentence_words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9%$.]+", s.lower()) if len(w) > 2}


HEADING_SKIP = re.compile(r"what you'?ll learn|recap|summary|wrap[- ]?up|subscribe|next steps|in this video|^intro(duction)?$",
                          re.IGNORECASE)


def _heading(scene: dict) -> str | None:
    """A title card's headline makes a section heading, when it reads like one."""
    v = scene.get("visual") or {}
    h = (v.get("headline") or "").strip()
    if v.get("type") != "title_card" or not h or len(h) > 70 or re.search(r"\d", h) or not h[0].isupper() \
            or HEADING_SKIP.search(h):
        return None
    return h


def article_blocks(body: dict) -> list[tuple[str, str]]:
    """The narration as an article: sections under the video's own title cards, one paragraph per scene, without what
    only a video says, without claimed hands-on tests, without sums read out loud, and without sentences that repeat
    an earlier one (a video repeats key numbers; an article says them once)."""
    from ..script.quality import INVENTED_TEST

    kept: list[set[str]] = []
    out: list[tuple[str, str]] = []
    pending_heading = None
    for scene in body.get("scenes", []):
        heading = _heading(scene)
        if heading:
            pending_heading = heading
        sentences, dropped_last = [], False
        for sent in re.split(r"(?<=[.!?])\s+", (scene.get("narration") or "").strip()):
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
        if pending_heading:
            out.append(("h2", pending_heading))
            out.append(("p", text))
            pending_heading = None
        elif out and out[-1][0] == "p" and (len(out[-1][1].split()) < SHORT_PARAGRAPH or len(text.split()) < SHORT_PARAGRAPH):
            out[-1] = ("p", f"{out[-1][1]} {text}")
        else:
            out.append(("p", text))
    return out


def article_paragraphs(body: dict) -> list[str]:
    return [t for k, t in article_blocks(body) if k == "p"]


DUPLICATE_TITLE = 0.7    # share of title words in common with an earlier article: the later one is a near-duplicate


def _title_words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) > 2}


def collect(conn, storage, work: Path, check_video=video_is_public, router=None) -> tuple[list[Article], list[str]]:
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
          join script_versions sv on sv.id = p.current_script_version_id
         where p.parent_project_id is null and p.format = 'long' and p.status not in ('draft', 'failed', 'rejected', 'archived')
           and (%s or exists (select 1 from approvals a where a.target_type = 'project' and a.target_id = p.id and a.decision = 'approved'))
         order by p.created_at""", (router is not None,))
    articles, skipped = [], []
    images = work / "images"
    images.mkdir(parents=True, exist_ok=True)
    hidden = (db.get_setting(conn, "website_hidden", {}) or {}).get("hidden") or {}
    titles: list[set[str]] = []
    for p in rows:
        body = p["body"] or {}
        if not p["first_posted"] and router is None:
            continue  # not posted yet: it appears once its video is out
        if hidden.get(str(p["id"])):
            skipped.append(f"{p['title'][:70]}: taken off the website by you")
            continue
        from . import editorial
        if str(p["id"]) == editorial.LAUNCH_ARTICLE:
            slug = slugify("Minimum Wage Search Spike: What It Means for Your Paycheck", p["id"])
            articles.append(Article(str(p["id"]), "money", slug, editorial.TITLE,
                "A worked example and worksheet for comparing a raise with inflation over the same period.",
                [t for k,t in editorial.BLOCKS if k == "p"], p["first_posted"] or editorial.REVISED,
                blocks=editorial.BLOCKS, sources=editorial.SOURCES, modified=editorial.REVISED,
                checked=editorial.REVISED, notes=["Corrected financial method; hypothetical example recalculated by code"]))
            continue
        reason = why_left_out(conn, p, body)
        title = body.get("title") or p["title"]
        tw = _title_words(title)
        if not reason and tw and any(len(tw & t) / len(tw | t) >= DUPLICATE_TITLE for t in titles):
            reason = "too similar to an article already on the website"
        if reason:
            skipped.append(f"{p['title'][:70]}: {reason}")
            continue
        titles.append(tw)
        slug = slugify(title, p["id"])
        blocks = article_blocks(body)
        saved_article = db.one(conn, "select * from website_articles where project_id=%s", (p["id"],))
        if saved_article:
            slug = saved_article["slug"]
        else:
            # Preserve any address that was already published before the registry existed.
            prior = db.one(conn, """select x->>'slug' slug from audit_logs a,
                jsonb_array_elements(coalesce(a.details->'published','[]'::jsonb)) x
                where a.action='website_built' and x->>'id'=%s order by a.created_at limit 1""", (str(p["id"]),))
            slug = prior["slug"] if prior else slug
        hook = (body.get("hook") or "").strip()
        if hook and not (TEST_CLAIM.search(hook) or VIDEO_TALK.search(hook)):
            blocks = [("p", hook)] + blocks
        notes, got = [], {}
        if _options().get("ai_rewrite", True):   # a cached result is used even when no AI service is passed
            from . import enhance

            got = enhance.enhance(router, storage, p["sv_id"], title, p["channel_slug"], blocks, work,
                                  german=_options().get("german", True))
            if got.get("en"):
                blocks = [tuple(b) for b in got["en"]]
                notes.append("rewritten as an article (independently checked for meaning)")
            elif got.get("en_note"):
                notes.append(got["en_note"])
            if got.get("de_note"):
                notes.append(got["de_note"])
        if router is not None:
            try:
                from .. import preflight
                from .enhance import check_meaning
                unchanged = (saved_article and str(saved_article["script_version_id"]) == str(p["sv_id"])
                    and saved_article["title"] == title and saved_article["blocks"] == [list(b) for b in blocks]
                    and saved_article["checked_at"] > datetime.now(timezone.utc) - timedelta(hours=48))
                if not unchanged:
                    preflight.check(conn, router, p["id"], article=True)
                    review = check_meaning(router, title, article_blocks(body), blocks,
                                           set((p["quality_report"] or {}).get("writers") or []))
                else:
                    from .enhance import MeaningReview
                    review = MeaningReview.model_validate(saved_article["review"])
                if not review.faithful or review.issues:
                    skipped.append(f"{title}: article did not pass independent review")
                    continue
                saved_article = db.one(conn, """insert into website_articles(project_id,script_version_id,slug,title,blocks,review)
                    values (%s,%s,%s,%s,%s,%s) on conflict(project_id) do update set
                    script_version_id=excluded.script_version_id,title=excluded.title,blocks=excluded.blocks,
                    review=excluded.review,checked_at=case when %s then website_articles.checked_at else now() end,modified_at=case when website_articles.blocks<>excluded.blocks
                    or website_articles.title<>excluded.title then now() else website_articles.modified_at end returning *""",
                    (p["id"],p["sv_id"],slug,title,db.j(blocks),db.j(review.model_dump()),bool(unchanged)))
            except Exception as exc:
                skipped.append(f"{title}: final article check unavailable ({type(exc).__name__})")
                continue
        paragraphs = [t for k, t in blocks if k == "p"]
        art = Article(str(p["id"]), p["channel_slug"], slug, title, (body.get("promise") or paragraphs[0])[:300],
                      paragraphs, saved_article["published_at"] if saved_article else p["first_posted"], sources=_sources(conn, body), blocks=blocks, notes=notes)
        if saved_article:
            art.modified, art.checked = saved_article["modified_at"], saved_article["checked_at"]
        if got.get("de"):
            art.de_title, art.de_blocks = got["de"]["title"], [tuple(b) for b in got["de"]["blocks"]]
        if p["youtube_url"] and check_video(p["youtube_url"]):
            art.video_url, art.video_id = p["youtube_url"], _video_id(p["youtube_url"])
        art.image = _image(conn, storage, p["id"], images / f"{slug}.jpg", work)
        art.webp = bool(art.image) and _webp(images / art.image)
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


def _webp(jpg: Path) -> bool:
    """640 and 1280 pixel wide WebP copies: phones download a third of the bytes."""
    try:
        from PIL import Image

        with Image.open(jpg) as im:
            im = im.convert("RGB")
            for w in (640, 1280):
                h = round(im.height * w / im.width)
                im.resize((w, h), Image.LANCZOS).save(jpg.with_name(f"{jpg.stem}-{w}.webp"), "WEBP", quality=78, method=5)
        return True
    except Exception:   # the JPEG still works on its own
        return False


def _image(conn, storage, project_id, dest: Path, work: Path) -> str | None:
    from ..publish.runner import _thumbnail

    got = _thumbnail(conn, storage, project_id, work / "tmp" / str(project_id))
    if not got:
        return None
    shutil.copyfile(got, dest)
    return dest.name


# ------------------------------------------------------------------------------------------------- building

def _socials(conn) -> list[dict]:
    """Public links to the brand's own connected accounts, for the footer and the Organization data."""
    out = []
    for a in db.all_(conn, """select a.platform, a.handle, a.external_id, a.label from social_accounts a
                              join oauth_connections c on c.social_account_id = a.id
                              where a.enabled and c.status = 'connected' order by a.platform, a.label"""):
        h = (a["handle"] or "").strip()
        if a["platform"] == "youtube" and h.startswith("@"):
            out.append({"name": f"YouTube ({a['label'].replace('YouTube', '').strip() or h})", "url": f"https://www.youtube.com/{h}"})
        elif a["platform"] == "x" and h:
            out.append({"name": "X", "url": f"https://x.com/{h.lstrip('@')}"})
        elif a["platform"] == "facebook" and a["external_id"]:
            out.append({"name": "Facebook", "url": f"https://www.facebook.com/{a['external_id']}"})
    return out


def _options() -> dict:
    return config.services().get("website") or {}


def _related(a: Article, articles: list[Article], n: int = 3) -> list[Article]:
    same = [x for x in articles if x is not a and x.channel == a.channel]
    other = [x for x in articles if x is not a and x.channel != a.channel]
    return (same + other)[:n]


def _search_index(articles: list[Article]) -> list[dict]:
    from . import resources
    return [{"t": a.title, "d": a.description, "c": CHANNELS.get(a.channel, (a.channel,))[0], "u": f"/articles/{a.slug}/",
             "p": date(a.published), "k": " ".join(" ".join(t for k, t in a.blocks if k == "p").split()[:80])}
            for a in articles] + [{"t": title, "d": description, "c": "Guides and tools", "u": path,
                                   "p": "", "k": description}
                                  for path, (title, description, _) in resources.pages().items()]


def _csp(options: dict) -> str:
    form = (options.get("newsletter") or {}).get("form_action") or ""
    form_host = re.match(r"https://[^/]+", form).group(0) if form.startswith("https://") else ""
    events = (options.get("analytics") or {}).get("events_url") or ""
    events_host = re.match(r"https://[A-Za-z0-9.-]+(?::[0-9]+)?(?=/|$)", events)
    connect_extra = " " + events_host.group(0) if events_host else ""
    return ("default-src 'self'; img-src 'self' data: https://i.ytimg.com; style-src 'self'; "
            f"script-src 'self' https://static.cloudflareinsights.com; connect-src 'self' https://cloudflareinsights.com{connect_extra}; "
            "frame-src https://www.youtube-nocookie.com; "
            f"form-action 'self'{(' ' + form_host) if form_host else ''}; base-uri 'self'; object-src 'none'; frame-ancestors 'none'")


def _icons(out: Path) -> None:
    """The app icons (180 and 512 pixels) and the default sharing picture, drawn from the logo's shapes."""
    from PIL import Image, ImageDraw

    def icon(size: int) -> Image.Image:
        im = Image.new("RGB", (size, size), "#101B32")
        d = ImageDraw.Draw(im)
        u = size / 32
        d.ellipse([(12.5 - 6.2) * u, (16 - 6.2) * u, (12.5 + 6.2) * u, (16 + 6.2) * u], fill="#F0BC55")
        d.rounded_rectangle([17.5 * u, 9.8 * u, 27 * u, 22.2 * u], radius=2.4 * u, fill="#4776F5")
        return im

    icon(180).save(out / "icon-180.png")
    icon(512).save(out / "icon-512.png")
    cover = config.REPO_ROOT / "brand-assets" / "penny-pixel-facebook-cover-1640x924.png"
    if cover.exists():
        with Image.open(cover) as im:
            im.convert("RGB").resize((1200, 676)).save(out / "og-default.png")
    else:
        og = Image.new("RGB", (1200, 630), "#101B32")
        og.paste(icon(240), (480, 195))
        og.save(out / "og-default.png")


def build(articles: list[Article], out: Path, images_dir: Path | None = None, socials: list[dict] | None = None,
          options: dict | None = None) -> dict:
    """Write the whole website into `out` (replacing what was there)."""
    options = _options() if options is None else options
    socials = socials or []
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    if images_dir and images_dir.exists():
        shutil.copytree(images_dir, out / "images", dirs_exist_ok=True)
    (out / "assets" / "site.css").write_text(assets.CSS.strip() + "\n")
    (out / "assets" / "site.js").write_text(assets.JS.strip() + "\n")
    (out / "favicon.svg").write_text(assets.FAVICON)
    _icons(out)
    options = dict(options)
    for kind in ("css", "js"):
        original = out / "assets" / f"site.{kind}"
        digest = hashlib.sha256(original.read_bytes()).hexdigest()[:12]
        hashed = original.with_name(f"site-{digest}.{kind}")
        shutil.copyfile(original, hashed)
        options[f"_{kind}_url"] = f"/assets/{hashed.name}"
    site = render.Site(site_url(), articles, socials, options)
    files: dict[str, str] = {"/": site.home(), "/search/": site.search_page()}
    for a in articles:
        files[f"/articles/{a.slug}/"] = site.article(a, _related(a, articles))
    files.update(site.listing("/latest/", "Latest articles", "Every article, newest first.", articles))
    for c in site.channels:
        files.update(site.listing(f"/{c}/", CHANNELS[c][0], CHANNELS[c][1], [a for a in articles if a.channel == c]))
    if site.videos:
        files["/videos/"] = site.videos_page()
    for a in site.german:
        files[f"/de/artikel/{a.slug}/"] = site.german_article(a)
    if site.german:
        files["/de/"] = site.german_home()
        files["/de/ueber-uns/"] = site.german_about()
    from . import resources
    resources.write_downloads(out)
    for path, (title, desc, body) in {**pages.standing_pages(options.get("contact_email"), socials), **resources.pages()}.items():
        files[path] = site.simple(path, title, desc, body)
    for path, page in files.items():
        d = out / path.strip("/")
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(page)
    (out / "404.html").write_text(site.not_found())
    (out / "search-index.json").write_text(json.dumps(_search_index(articles), ensure_ascii=False))
    url = site_url()
    now = datetime.now(timezone.utc).date().isoformat()
    lastmod = {f"/articles/{a.slug}/": (a.modified or a.published).date().isoformat() for a in articles}
    listed = [p for p in files if "/page/" not in p and p != "/search/"]
    (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                     + "".join(f"<url><loc>{e(url + p)}</loc>" +
                                               (f"<lastmod>{lastmod[p]}</lastmod>" if p in lastmod else "") +
                                               "</url>\n" for p in listed)
                                     + "</urlset>\n")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nDisallow: /search/\nSitemap: {url}/sitemap.xml\n")
    items = "".join(f"<item><title>{e(a.title)}</title><link>{e(url)}/articles/{e(a.slug)}/</link>"
                    f"<guid>{e(url)}/articles/{e(a.slug)}/</guid><pubDate>{a.published:%a, %d %b %Y %H:%M:%S +0000}</pubDate>"
                    f"<description>{e(a.description)}</description></item>" for a in articles[:30])
    (out / "feed.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><title>{SITE_HTML}</title>'
                                  f"<link>{e(url)}/</link><description>{e(TAGLINE)}</description><language>en</language>{items}</channel></rss>\n")
    (out / "_headers").write_text("/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n"
                                  "  X-Frame-Options: DENY\n  Permissions-Policy: camera=(), microphone=(), geolocation=()\n"
                                  f"  Content-Security-Policy: {_csp(options)}\n"
                                  "/assets/*\n  Cache-Control: public, max-age=86400\n/images/*\n  Cache-Control: public, max-age=604800\n")
    return {"articles": len(articles), "ai": sum(a.channel == "ai" for a in articles),
            "money": sum(a.channel == "money" for a in articles), "videos": len(site.videos), "german": len(site.german),
            "pages": len(files) + 1}


def article_html(a: Article, related: list[Article] | None = None) -> str:
    """One article page on its own (used by tests and previews)."""
    return render.Site(site_url(), [a], [], {}).article(a, related or [])


def build_site(conn, storage, out: Path, router=None) -> dict:
    """Collect and write the website; the summary says what was published and what was left out, and why."""
    work = config.runtime().work_dir / "site"
    if work.exists():
        shutil.rmtree(work)
    articles, skipped = collect(conn, storage, work, router=router)
    summary = build(articles, out, work / "images", socials=_socials(conn))
    redirects = []
    current = {a.project_id: a.slug for a in articles}
    prior = db.all_(conn, """select distinct x->>'id' id,x->>'slug' slug from audit_logs a,
        jsonb_array_elements(coalesce(a.details->'published','[]'::jsonb)) x where a.action='website_built'""")
    for old in prior:
        if old["id"] in current and old["slug"] != current[old["id"]] and re.fullmatch(r"[a-z0-9-]+", old["slug"] or ""):
            redirects.append(f"/articles/{old['slug']}/ /articles/{current[old['id']]}/ 301")
    (out / "_redirects").write_text("\n".join(sorted(set(redirects))) + "\n")
    summary["left_out"] = skipped
    summary["notes"] = [f"{a.title[:60]}: {n}" for a in articles for n in a.notes]
    db.audit(conn, "website_built", "website", None,
             {"articles": summary["articles"], "left_out": skipped[:20], "url": site_url(),
              "notes": summary["notes"][:40], "german": summary.get("german", 0),
              "published": [{"id": a.project_id, "title": a.title, "slug": a.slug} for a in articles[:200]]}, actor="engine")
    return summary
