"""Check the exact saved version before it crosses a publishing boundary."""
from . import db, produce
from .errors import NeedsReview
from .script import verify
from .script.models import Script


def check(conn, router, project_id, *, article=False):
    p = db.one(conn, "select * from content_projects where id=%s", (project_id,))
    if p and p.get("parent_project_id"):
        records = check(conn, router, p["parent_project_id"])
        from .website.enhance import check_meaning
        parent = db.one(conn, "select sv.body,p.quality_report from script_versions sv join content_projects p on p.current_script_version_id=sv.id where p.id=%s",
                        (p["parent_project_id"],))
        short = db.one(conn, "select body from script_versions where id=%s", (p["current_script_version_id"],))
        if not short:
            raise NeedsReview("Short has no saved script")
        review = check_meaning(router, short["body"]["title"],
                              [("p", s["narration"]) for s in parent["body"]["scenes"]],
                              [("p", s["narration"]) for s in short["body"]["scenes"]],
                              set((parent["quality_report"] or {}).get("writers") or []) |
                              set((p["quality_report"] or {}).get("writers") or []))
        if not review.faithful or review.issues:
            raise NeedsReview("Short failed its final meaning check")
        return records
    sv = db.one(conn, "select * from script_versions where id=%s", (p["current_script_version_id"],)) if p else None
    if not sv:
        raise NeedsReview("No saved script is available for a final fact check")
    script = Script.model_validate(sv["body"])
    facts = produce.saved_facts(conn, project_id, script)
    if not facts or not facts.facts:
        raise NeedsReview("No linked evidence is available for a final fact check")
    ids = list({f.source_id for f in facts.facts if f.source_id})
    sources = produce._sources_for(conn, ids)
    writers = set((p["quality_report"] or {}).get("writers") or [])
    from .script import pipeline, quality
    problems = pipeline.blocking(quality.check_long(script, p["channel_slug"], min_seconds=quality.shortest_long_seconds()))
    if problems and not article:
        raise NeedsReview("Final script checks: " + "; ".join(problems))
    records = verify.check_claims(router, script, facts, sources, exclude=writers)
    if not records or any(r["status"] in ("unsupported", "contradicted", "stale", "partially_supported") for r in records):
        raise NeedsReview("Final fact check did not pass; the bot must repair or refresh the evidence before publishing")
    return records
