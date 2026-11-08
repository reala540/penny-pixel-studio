# The Penny & Pixel website

Public address: **https://pennyandpixel.pages.dev** (Cloudflare Pages, free).

## How it fits with the studio

```
studio database (Supabase) ──► `studio site` (GitHub Actions, "Website" workflow) ──► plain files ──► Cloudflare Pages
     approved, posted videos          checks + cleans + renders                         HTML/CSS/JS/images      public site
```

- The website is **separate and read-only**: plain files, no login, no database, no keys. The studio pushes files to it;
  it never calls back, and no page links to the dashboard (a test checks this).
- It is rebuilt after every "Publish due posts" run and daily at 07:23 Nairobi (04:23 UTC), or by hand:
  Actions → Website → Run workflow.
- Rollback: Cloudflare keeps every deployment. In Cloudflare → Workers & Pages → pennyandpixel → Deployments, any earlier
  deployment can be made live again with **Rollback**. Nothing in the studio database is changed by a build.

## What becomes an article

One article per **approved** long video that has **been posted**. The article says what the approved video says (its
narration was checked fact by fact against dated sources), cleaned for reading:
removed are video-only lines ("in this video", "subscribe"), leftovers of the writer's instructions, sums read out loud,
near-repeated sentences, sentences left hanging by a removal, and claims of hands-on tests that didn't happen. The video's
own title cards become section headings, with a contents list when there are three or more.

Left off, with the reason shown on the dashboard's Home ("Your website") and in the audit log (`website_built`):

| Rule | Why |
|---|---|
| Any claim unsupported, contradicted or stale, or a blocker still listed | Only checked content is published |
| Sensitive money topic (investing, tax, loans, credit, insurance, retirement…) | Same list as Smart Mode; the website never asks the owner |
| Title or opening claims a hands-on test that didn't happen | Honesty rule |
| Under 250 words left after cleaning | Thin pages hurt the whole site in search |
| Title too similar to an earlier article | No near-duplicates |
| Taken off by the owner (`settings.website_hidden`) | Corrections and unpublishing |

Code: `engine/studio/website/__init__.py` (collecting and rules), `render.py` (pages), `pages.py` (standing pages),
`assets.py` (design system: CSS, logo, one script). Tests: `engine/tests/test_website.py`.

## Pages

Home (hero, latest with a lead story, a section per category that has articles, videos when there are public ones,
newsletter when configured), `/ai/`, `/money/`, `/latest/` (24 per page), `/videos/`, `/search/`, every article, and
About, Contact, Editorial policy, AI content policy, Corrections, Advertise with us, Privacy, Terms, Affiliate disclosure,
404. Empty categories, the Videos page and the newsletter don't appear until they have something real behind them.

Each article: breadcrumbs, category, title, byline ("By the Penny & Pixel team"), publication date ("facts as of this
date"), reading time, the video (click to play, loads only on click) or the thumbnail, contents list, sections, money note,
labeled affiliate offer when one matches, dated sources, an AI note with a link to corrections, share links (X, Facebook,
LinkedIn, email, copy link) and related articles.

## Design system

Colours: Midnight Navy `#101B32`, Electric Blue `#4776F5` (accents only: 4.06:1 on white is below AA for text), link blue
`#2F5BD8` (5.8:1), Warm Gold `#F0BC55`, Soft White `#F5F7FB`, Charcoal `#202736`, muted `#5A6478` (5.6:1). Dark mode
follows the device setting. System fonts only (no downloads): sans for interface, a serif for reading. Cards, buttons,
tags, notes and forms are shared classes in one 10 KB stylesheet.

## SEO

Unique titles and descriptions, canonical URLs, Open Graph and X cards, `sitemap.xml` (search and paginated pages left
out), `robots.txt`, RSS (`feed.xml`), breadcrumbs, structured data (Organization and WebSite on the home page; Article and
BreadcrumbList on articles; VideoObject only when a public YouTube video exists; no ratings, reviews or FAQ markup).
Search Console: the site isn't submitted. To do it: Search Console → Add property → URL prefix
`https://pennyandpixel.pages.dev/` → verify (HTML file method: the owner sends the file name and it is added like the
dashboard's) → Sitemaps → `sitemap.xml`.

## Performance and accessibility (measured on a local build, 8 Nov 2026)

Checked with Chromium at 320, 375, 390, 768, 1024 and 1440 px on 10 page types: no horizontal overflow, one `h1` per
page, every image has alt text, every visible control has a name, tap targets at least 44 px, skip link, keyboard focus
outlines, mobile menu without JavaScript (`<details>`). Throttled phone (4× slower CPU, 1.6 Mbps, 150 ms latency):
largest contentful paint 0.51 s on Home and 0.33 s on an article, layout shift 0. These come from a local server, so
real-world numbers over the internet will be higher; measure the live site with PageSpeed Insights.

## Security

`_headers` sets a Content-Security-Policy (only the site's own files, YouTube thumbnails, the youtube-nocookie player and
Cloudflare Web Analytics; no inline scripts or styles; no framing), `nosniff`, `Referrer-Policy`, `X-Frame-Options: DENY`
and `Permissions-Policy`. All text is escaped; affiliate links are `rel="sponsored nofollow"`.

## Settings (`config/services.yaml` → `website`)

| Key | Default | What it does |
|---|---|---|
| `url` | `https://pennyandpixel.pages.dev` | The address used in links and the sitemap (`SITE_URL` repository variable wins) |
| `project` | `pennyandpixel` | Cloudflare Pages project (`SITE_PROJECT` variable wins) |
| `contact_email` | none | Shown on Contact, Corrections and Advertise; otherwise readers are sent to the social accounts |
| `newsletter.form_action`, `.provider` | none | A free provider's sign-up address (e.g. Buttondown's embed form). The form appears only when set; consent is required; the provider stores subscriptions and handles unsubscribing |
| `analytics.cloudflare_token` | none | Cloudflare Web Analytics (free, cookie-free). Alternatively switch it on in the Pages project (Metrics → Web Analytics) |

Secrets used by the workflow: `CLOUDFLARE_API_TOKEN` (needs Cloudflare Pages: Edit; it already works),
`CLOUDFLARE_ACCOUNT_ID`, and the studio's usual database and storage secrets.

## Free-tier use

| Service | Limit that matters (free plan) | Our use |
|---|---|---|
| Cloudflare Pages | 500 builds a month (Cloudflare's own builds; we upload ready-made files instead), 20,000 files per site, 25 MiB per file, static requests and bandwidth not metered | A few uploads a day; about 5 files per article |
| GitHub Actions | Unlimited minutes for public repositories | About 2 minutes per website build |
| Supabase | The existing project; the build only reads | A handful of queries per build |
| YouTube oEmbed | Public, no key | One check per article per build |

Limits change; check the providers' pricing pages before relying on them.

## Not done, and why

- **Google AdSense:** it won't accept a free `pages.dev` address; a custom domain (about $10 a year) would be needed. No
  advertising code is included.
- **Newsletter, analytics, contact email:** need the owner's free accounts or settings (see above); until then nothing is
  shown, so nothing pretends to work.
- **"Popular" articles:** no analytics data yet, so the home page shows newest first instead of inventing popularity.
- **Videos on the site:** YouTube uploads stay private until Google's API audit passes, so no video is embedded yet;
  articles show the thumbnail. Embeds appear by themselves once videos are public.
- **German-language section:** not started. Translating money content needs checking by someone who reads German.
- **Article quality:** articles are cleaned video scripts, so some read a little repetitively. A rewrite-and-recheck step
  would improve them; it isn't built yet.
