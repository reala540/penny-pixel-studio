"""Dashboard addresses for Telegram and in-app notifications: the same destinations the dashboard uses
(dashboard/src/lib/activity.ts jobDestination and lib/routes.ts). Opening any of them only shows things."""
from urllib.parse import urlencode

from . import config


def _base() -> str:
    return config.runtime().dashboard_url.rstrip("/")


def project(project_id, tab: str | None = None) -> str:
    return f"{_base()}/content/{project_id}" + (f"?tab={tab}" if tab else "")


def post(post_id) -> str:
    """The post itself, in whatever week it falls."""
    return f"{_base()}/calendar?post={post_id}"


def job(job: dict) -> str:
    """Progress or results of one request."""
    kind, inp = job.get("job_type"), job.get("input") or {}
    if kind == "check_providers":
        return f"{_base()}/settings/ai?job={job['id']}#key-check"
    idea = inp.get("generated_idea_id") or inp.get("content_idea_id")
    if kind == "produce_idea" and idea:
        q = {"step": "progress", "kind": "generated" if inp.get("generated_idea_id") else "research", "id": idea}
        if inp.get("channel") in ("ai", "money"):
            q["channel"] = inp["channel"]
        return f"{_base()}/create?{urlencode(q)}"
    if job.get("project_id"):
        return project(job["project_id"])
    return f"{_base()}/activity?job={job['id']}#job-detail"


def idea_run(run_id) -> str:
    return f"{_base()}/content/ideas?source=generator&run={run_id}"


def research_since(started_at) -> str:
    stamp = started_at.isoformat() if hasattr(started_at, "isoformat") else str(started_at)
    return f"{_base()}/content/ideas?{urlencode({'source': 'research', 'since': stamp})}"


def needs_you() -> str:
    return f"{_base()}/content?tab=needs-you"


def settings(section: str) -> str:
    return f"{_base()}/settings/{section}"
