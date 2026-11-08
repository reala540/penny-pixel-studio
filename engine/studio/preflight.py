"""Check the exact saved version before it crosses a publishing boundary."""

from . import db, produce
from .errors import NeedsReview, TransientError
from .script import verify
from .script.models import Script


class Failed(NeedsReview):
    def __init__(self, message, records=None, version=None):
        super().__init__(message)
        import json

        self.records = json.loads(json.dumps(records or [], default=str))
        self.version = version


class Changed(TransientError):
    """A newer version needs a new check; do not repair it using an old verdict."""


def _unchanged(conn, project_id, version):
    current = db.one(
        conn,
        "select current_script_version_id from content_projects where id=%s",
        (project_id,),
    )
    if not current or str(current["current_script_version_id"]) != str(version):
        raise Changed("Script changed during final checking; check the new version")


def check(conn, router, project_id, *, article=False, expected_version=None):
    p = db.one(conn, "select * from content_projects where id=%s", (project_id,))
    if expected_version:
        _unchanged(conn, project_id, expected_version)
    if p and p.get("parent_project_id"):
        from .website.enhance import check_meaning

        parent = db.one(
            conn,
            "select sv.body,sv.id version,p.quality_report from script_versions sv join content_projects p on p.current_script_version_id=sv.id where p.id=%s",
            (p["parent_project_id"],),
        )
        records = check(
            conn, router, p["parent_project_id"], expected_version=parent["version"]
        )
        short = db.one(
            conn,
            "select body from script_versions where id=%s",
            (p["current_script_version_id"],),
        )
        if not short:
            raise NeedsReview("Short has no saved script")
        review = check_meaning(
            router,
            short["body"]["title"],
            [("p", s["narration"]) for s in parent["body"]["scenes"]],
            [("p", s["narration"]) for s in short["body"]["scenes"]],
            set((parent["quality_report"] or {}).get("writers") or [])
            | set((p["quality_report"] or {}).get("writers") or []),
        )
        if not review.faithful or review.issues:
            raise Failed(
                "Short failed its final meaning check: " + "; ".join(review.issues),
                version=parent.get("version"),
            )
        _unchanged(conn, p["parent_project_id"], parent["version"])
        _unchanged(conn, project_id, p["current_script_version_id"])
        return records
    sv = (
        db.one(
            conn,
            "select * from script_versions where id=%s",
            (p["current_script_version_id"],),
        )
        if p
        else None
    )
    if not sv:
        raise Failed("No saved script is available for a final fact check")
    script = Script.model_validate(sv["body"])
    facts = produce.saved_facts(conn, project_id, script)
    if not facts or not facts.facts:
        raise Failed(
            "No linked evidence is available for a final fact check", version=sv["id"]
        )
    ids = list({f.source_id for f in facts.facts if f.source_id})
    sources = produce._sources_for(conn, ids)
    from .review.auto import writers_of

    writers = writers_of(conn, [p])
    from .script import pipeline, quality

    problems = pipeline.blocking(
        quality.check_long(
            script, p["channel_slug"], min_seconds=quality.shortest_long_seconds()
        )
    )
    # The rendered duration is authoritative once it exists for this exact saved version.
    duration = db.one(
        conn,
        "select output from generation_jobs where idempotency_key=%s and status='completed'",
        (f"preview:{project_id}:{sv['id']}",),
    )
    actual = ((duration or {}).get("output") or {}).get("seconds")
    if actual:
        problems = [
            i for i in problems if not i.startswith(("Too short:", "Too long:"))
        ]
        from . import config

        if (
            actual < quality.shortest_long_seconds()
            or actual > config.services()["render"]["max_long_minutes"] * 60
        ):
            problems.append("Rendered duration outside the allowed range")
    if problems and not article:
        raise Failed("Final script checks: " + "; ".join(problems), version=sv["id"])
    records = verify.check_claims(router, script, facts, sources, exclude=writers)
    _unchanged(conn, project_id, sv["id"])
    if not records or any(
        r["status"] in ("unsupported", "contradicted", "stale", "partially_supported")
        for r in records
    ):
        raise Failed(
            "Final fact check did not pass; the bot must repair or refresh the evidence before publishing",
            records,
            sv["id"],
        )
    return records
