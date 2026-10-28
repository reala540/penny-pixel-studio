"""Each platform's text limits, checked before approval so a post never fails at posting time for its length.
The dashboard shows the same rules (dashboard/src/lib/limits.ts); keep the two in step."""
from __future__ import annotations

import re

URL_RE = re.compile(r"https?://|www\.|\b[\w-]+\.(com|net|org|io|co|ai|ke)\b", re.IGNORECASE)  # as the X adapter

# title / body are characters; caption = body plus its hashtags as posted; hashtags = how many
LIMITS: dict[tuple[str, str], dict] = {
    ("youtube", "long_video"): {"title": 100, "body": 5000, "tags_total": 500, "hashtags": 15},
    ("youtube", "short_video"): {"title": 100, "body": 5000, "tags_total": 500, "hashtags": 15},
    ("x", "text_post"): {"body": 280, "no_links": True},
    ("facebook", "text_post"): {"body": 63206},
    ("facebook", "reel"): {"caption": 2200, "hashtags": 5},
    ("facebook", "long_video"): {"title": 255, "body": 5000},
    ("facebook", "story"): {},
    ("tiktok", "short_video"): {"caption": 2200, "hashtags": 5},
}


def caption(body: str | None, hashtags: list[str] | None) -> str:
    tags = " ".join(f"#{h.lstrip('#')}" for h in hashtags or [] if h)
    return f"{body or ''} {tags}".strip()


def problems(platform: str, kind: str, title: str | None, body: str | None, tags: list[str] | None = None,
             hashtags: list[str] | None = None) -> list[str]:
    """Plain reasons this post breaks its platform's limits (empty when it fits)."""
    rule = LIMITS.get((platform, kind), {})
    out: list[str] = []
    if rule.get("title") and len(title or "") > rule["title"]:
        out.append(f"title is {len(title or '')} characters (limit {rule['title']})")
    if rule.get("body") and len(body or "") > rule["body"]:
        out.append(f"text is {len(body or '')} characters (limit {rule['body']})")
    if rule.get("caption"):
        n = len(caption(body, hashtags))
        if n > rule["caption"]:
            out.append(f"caption with hashtags is {n} characters (limit {rule['caption']})")
    if rule.get("tags_total"):
        n = sum(len(t) for t in tags or []) + max(len(tags or []) - 1, 0)
        if n > rule["tags_total"]:
            out.append(f"tags add up to {n} characters (limit {rule['tags_total']})")
    if rule.get("hashtags") and len(hashtags or []) > rule["hashtags"]:
        out.append(f"{len(hashtags or [])} hashtags (at most {rule['hashtags']})")
    if rule.get("no_links") and URL_RE.search(body or ""):
        out.append("contains a link (links are blocked on X to protect the budget)")
    if kind in ("text_post",) and not (body or "").strip():
        out.append("the post text is empty")
    return out
