"""Weekly batch orchestration: config sync, research (Saturday), production (Sunday), distribution plan."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from . import budget, capacity, config, db, jobs, notify, schedule, similarity
from .ai.router import Router
from .errors import NeedsReview
from .media import render as rendering
from .media import stock, thumbnails
from .media.visuals import Theme
from .research import deepen
from .research import engine as research
from .script import pipeline
from .script.models import Script, ShortScript

# ----------------------------------------------------------------------------- config sync


def sync_config(conn) -> dict:
    """Idempotently load YAML config into the database. Owner toggles made in the dashboard are kept."""
    b = config.brand()
    brand = db.one(conn, "select id from brands limit 1")
    if brand is None:
        brand = db.one(conn, "insert into brands (name, tagline, palette) values (%s,%s,%s) returning id",
                       (b["brand"]["name"], b["brand"]["tagline"], db.j(b["brand"].get("palette", {}))))
    channel_ids = {}
    for slug, ch in b["channels"].items():
        row = db.one(conn, """
            insert into channel_profiles (brand_id, slug, display_name, host_persona, topic_focus, voice_profile,
                                          audience_profile, design, disclaimer, launch_date)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            on conflict (slug) do update set display_name=channel_profiles.display_name,
                   audience_profile=excluded.audience_profile,
                   launch_date=coalesce(channel_profiles.launch_date, excluded.launch_date)
            returning id""",
            (brand["id"], slug, ch["display_name"], ch["host_persona"].strip(), ch["topic_focus"],
             db.j(ch["voice_profile"]), db.j(ch["audience_profile"]), db.j(ch["design"]), ch.get("disclaimer"),
             ch.get("launch_date")))
        channel_ids[slug] = row["id"]
    acc = config.accounts()
    for a in acc["accounts"]:
        row = db.one(conn, """
            insert into social_accounts (platform, label, channel_profile_id, topic_mix, weekly_targets)
            values (%s,%s,%s,%s,%s)
            on conflict (platform, label) do update set topic_mix=social_accounts.topic_mix
            returning id""",
            (a["platform"], a["label"], channel_ids.get(a.get("channel")), db.j(a["topic_mix"]),
             db.j({**a["weekly_targets"], "posting_days": a["posting_days"], "posting_times": a["posting_times"],
                   "shorts_days": a.get("shorts_days", []), "shorts_times": a.get("shorts_times", [])})))
        db.run(conn, "insert into oauth_connections (social_account_id) values (%s) on conflict do nothing", (row["id"],))
    for name, p in (config.providers().get("providers") or {}).items():
        db.run(conn, """
            insert into ai_providers (name, enabled, commercial_use_ok, base_url, key_env, notes)
            values (%s,%s,%s,%s,%s,%s)
            on conflict (name) do update set base_url=excluded.base_url, key_env=excluded.key_env,
                   notes=excluded.notes, commercial_use_ok=excluded.commercial_use_ok""",
               (name, p.get("enabled", False), p.get("commercial_use") in ("verified", "assumed"),
                p["base_url"], p.get("key_env"), p.get("notes")))
        for m in p.get("models", []):
            db.run(conn, """
                insert into ai_model_configs (provider, model, roles, context_tokens, daily_request_limit,
                                              daily_token_limit, priority)
                values (%s,%s,%s,%s,%s,%s,%s)
                on conflict (provider, model) do update
                   set roles = case when ai_model_configs.roles_custom then ai_model_configs.roles else excluded.roles end,
                       context_tokens=excluded.context_tokens""",
                   (name, m["id"], m.get("roles", []), m.get("context"), m.get("daily_requests"),
                    m.get("daily_tokens"), m.get("priority", 100)))
    budget.sync_budgets(conn)
    # The schedule in config/accounts.yaml, for "Reset to default" in the dashboard's posting schedule editor.
    db.run(conn, """insert into settings (key, value) values ('posting_schedule_defaults', %s)
                    on conflict (key) do update set value = excluded.value, updated_at = now()""",
           (db.j({a["label"]: {**a["weekly_targets"], "posting_days": a["posting_days"], "posting_times": a["posting_times"],
                               "shorts_days": a.get("shorts_days", []), "shorts_times": a.get("shorts_times", [])}
                  for a in acc["accounts"]}),))
    defaults = {"timezone": acc.get("timezone", "Africa/Nairobi"), "paused": False, "brand_name": b["brand"]["name"],
                "auto_select_topics": True, "quality_threshold": pipeline.CRITIC_MIN,
                "telegram_link_code": None}
    for k, v in defaults.items():
        db.run(conn, "insert into settings (key, value) values (%s,%s) on conflict (key) do nothing", (k, db.j(v)))
    return {"brand_id": str(brand["id"]), "channels": {k: str(v) for k, v in channel_ids.items()}}


def apply_brand_overrides(conn) -> None:
    """Channel voices edited in the dashboard win over config/brand.yaml for this run."""
    channels = config.brand()["channels"]
    for row in db.all_(conn, "select slug, display_name, host_persona, topic_focus, voice_profile, design, disclaimer from channel_profiles"):
        ch = channels.get(row["slug"])
        if not ch:
            continue
        ch["host_persona"] = row["host_persona"] or ch["host_persona"]
        ch["topic_focus"] = row["topic_focus"] or ch["topic_focus"]
        ch["voice_profile"] = {**ch["voice_profile"], **(row["voice_profile"] or {})}
        ch["design"] = {**ch["design"], **(row["design"] or {})}
        ch["disclaimer"] = row["disclaimer"] if row["disclaimer"] is not None else ch.get("disclaimer")


def is_paused(conn) -> bool:
    return bool(db.get_setting(conn, "paused", False))


# ----------------------------------------------------------------------------- research (Saturday)


def research_batch(conn, router: Router, week: date, fetcher=None, *, brief: str = "",
                   channel: str | None = None, n_models: int = 3) -> dict:
    with db.run_lock(conn, "research") as free:
        if not free:
            return {"skipped": "another research run is in progress"}
        return _research_batch(conn, router, week, fetcher, brief=brief, channel=channel, n_models=n_models)


def _research_batch(conn, router: Router, week: date, fetcher=None, *, brief: str = "",
                    channel: str | None = None, n_models: int = 3) -> dict:
    apply_brand_overrides(conn)
    jobs.progress(conn, "Collecting research from your sources", 1, 2)
    report = research.collect(conn, fetcher)
    plan = capacity.plan_batch(conn)
    ideas = {}
    channels = [channel] if channel in ("ai", "money") else list(plan["long_per_channel"])
    for slug in channels:
        n = plan["long_per_channel"].get(slug, 0)
        if n <= 0:
            continue
        jobs.progress(conn, f"Pitching video ideas for the {slug} channel", 2, 2)
        ideas[slug] = len(research.run_ideas(conn, router, slug, n + 1, week,
                                             brief=brief[:2000], n_models=n_models))
    db.audit(conn, "research_batch", "week", week,
             {"sources": report, "ideas": ideas, "brief": brief[:2000], "channel": channel, "models": n_models})
    return {"sources": report, "ideas": ideas, "capacity": plan}


# ----------------------------------------------------------------------------- production (Sunday)


def _sources_for(conn, ids: list) -> list[dict]:
    if not ids:
        return []
    rows = db.all_(conn, """select id, adapter, title, publisher, url, published_at, summary, credibility, topic,
                                   body_text, fresh_until from research_sources where id = any(%s)""", (ids,))
    order = {str(i): n for n, i in enumerate(ids)}
    return sorted(rows, key=lambda r: order.get(str(r["id"]), 0))


def save_script(conn, project_id, body: dict, origin: str, trail: list, claims: list[dict] | None = None,
                facts=None, sources: list[dict] | None = None) -> dict:
    with db.transaction(conn):
        nxt = db.one(conn, "select coalesce(max(version),0)+1 v from script_versions where project_id=%s", (project_id,))["v"]
        words = sum(len(s["narration"].split()) for s in body.get("scenes", [])) + len(body.get("hook", "").split())
        sv = db.one(conn, """insert into script_versions (project_id, version, origin, hook, body, word_count, provider_trail)
                             values (%s,%s,%s,%s,%s,%s,%s) returning *""",
                    (project_id, nxt, origin, body.get("hook"), db.j(body), words, db.j(trail)))
        for i, sc in enumerate(body.get("scenes", []), 1):
            db.run(conn, """insert into scenes (script_version_id, position, narration, est_seconds, visual,
                                                on_screen_text, claim_ids)
                            values (%s,%s,%s,%s,%s,%s,%s)""",
                   (sv["id"], i, sc["narration"], len(sc["narration"].split()) / 2.5, db.j(sc["visual"]),
                    sc.get("on_screen_text"), sc.get("claim_keys", [])))
        if claims is not None and facts is not None:
            fact_src = {f.key: f.source_ref for f in facts.facts}
            label_to_source = {f"S{i}": s for i, s in enumerate(sources or [], 1)}
            for c in claims:
                ref = next((fact_src[k] for k in c["fact_refs"] if k in fact_src), None)
                src = label_to_source.get(ref) if ref else None
                period = next((f.data_period for f in facts.facts if f.key in c["fact_refs"] and f.data_period), None)
                db.run(conn, """insert into research_claims (project_id, script_version_id, claim_key, claim_text, source_id,
                                    source_published_at, data_period, retrieved_at, confidence, status, checker_notes)
                                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                       (project_id, sv["id"], c["key"], c["text"], src["id"] if src else None,
                        src.get("published_at") if src else None, period, c["checked_at"], c["confidence"],
                        c["status"], c["note"]))
        db.run(conn, "update content_projects set current_script_version_id=%s where id=%s", (sv["id"], project_id))
    return sv


def ensure_project(conn, channel: str, fmt: str, title: str, week: date, idea_id=None, parent_id=None, key=None) -> dict:
    key = key or f"{week}:{channel}:{fmt}:{idea_id or title}"
    job = jobs.ensure_job(conn, "project", f"project:{key}", input={"title": title})
    if job["project_id"]:
        return db.one(conn, "select * from content_projects where id=%s", (job["project_id"],))
    with db.transaction(conn):
        p = db.one(conn, """insert into content_projects (channel_slug, idea_id, format, parent_project_id, title,
                                                          status, batch_week)
                            values (%s,%s,%s,%s,%s,'scripting',%s) returning *""",
                   (channel, idea_id, fmt, parent_id, title, week))
        db.run(conn, "update generation_jobs set project_id=%s, status='completed' where id=%s", (p["id"], job["id"]))
    return p


REPEAT_SCRIPT = 0.55  # TF-IDF cosine of the whole narration (with word pairs): same topic ~0.3, near copy 0.6+
REPEAT_TITLE = 0.7


def repeats_earlier(conn, channel: str, project_id, script: Script) -> str | None:
    """The issue to raise if this script is too similar to another long video of the channel from the last 180 days."""
    rows = db.all_(conn, """select p.title, sv.body from content_projects p join script_versions sv on sv.id = p.current_script_version_id
                            where p.channel_slug=%s and p.format='long' and p.id<>%s and p.parent_project_id is null
                              and p.status not in ('rejected','failed') and p.created_at > now() - interval '180 days'
                            order by p.created_at desc limit 200""", (channel, project_id))
    if not rows:
        return None
    text = " ".join(s.narration for s in script.scenes)
    others = [" ".join(sc.get("narration", "") for sc in (r["body"] or {}).get("scenes", [])) for r in rows]
    score, i, _ = similarity.max_similarity(text, others)
    if score >= REPEAT_SCRIPT:
        return f"Too similar to an earlier video, '{rows[i]['title']}' ({score:.0%} alike): make it clearly different"
    t_score, j, _ = similarity.max_similarity(script.title, [r["title"] for r in rows])
    if t_score >= REPEAT_TITLE:
        return f"Title too close to an earlier video, '{rows[j]['title']}' ({t_score:.0%} alike)"
    return None


def produce_project(conn, router: Router, storage, idea: dict, week: date, *, project: dict | None = None,
                    stage=None) -> dict:
    """One idea's package. Every stage is resumable: finished stages are skipped when it runs again.
    `project` reuses an existing package; `stage(label, step, total)` reports progress (the guided Create flow)."""
    channel = idea["channel_slug"]
    project = project or ensure_project(conn, channel, "long", idea["title"], week, idea_id=idea["id"])
    pid = project["id"]
    report = stage or (lambda *_: None)
    if not project.get("current_script_version_id"):
        report("Reading the full articles behind this idea", 1, 4)
        try:  # a feed line is too little for an honest 8-14 minute video: read the articles and add related ones
            print("deep research:", deepen.deepen(conn, router, idea, channel), flush=True)
        except Exception as exc:  # research problems never block: the fact gate in the script step decides
            print("deep research failed:", str(exc)[:200], flush=True)
    sources = _sources_for(conn, list(idea["source_ids"]))
    idea_d = {"title": idea["title"], "angle": idea.get("angle") or ""}
    holder: dict = {}

    def do_script(_):
        result = pipeline.write_long(router, channel, idea_d, sources)
        twin = repeats_earlier(conn, channel, pid, result.script)
        if twin:  # too close to a video the channel already made: a person decides (YouTube penalises repetition)
            result.issues.append(twin)
            result.report["issues"] = result.issues
        sv = save_script(conn, pid, result.script.model_dump(), "ai", result.trail, result.claims, result.facts, sources)
        supported = [c for c in result.claims if c["status"] in ("supported", "partially_supported")]
        fresh = None
        if not (idea.get("score_breakdown") or {}).get("evergreen"):
            used = {k for c in supported for k in c["fact_refs"]}
            labels = {f.source_ref for f in result.facts.facts if f.key in used}
            dates = [s["fresh_until"] for i, s in enumerate(sources, 1) if f"S{i}" in labels and s.get("fresh_until")]
            fresh = min(dates) if dates else None
        status = "needs_attention" if result.needs_attention else "rendering"
        db.run(conn, """update content_projects set quality_report=%s, fresh_until=%s, status=%s, title=%s where id=%s""",
               (db.j(result.report), fresh, status, result.script.title, pid))
        holder["facts"] = result.facts.model_dump()
        return {"script_version_id": str(sv["id"]), "facts": holder["facts"], "needs_attention": result.needs_attention}

    report("Writing the script and checking the facts", 1, 4)
    st = jobs.run_stage(conn, "script", f"script:{pid}", do_script, project_id=pid)
    if not st.ok:
        db.run(conn, "update content_projects set status=%s where id=%s",
               ("needs_attention" if st.status == "needs_review" else "failed", pid))
        return {"project_id": str(pid), "status": st.status, "error": st.job.get("error_message")}
    from .script.models import FactSheet

    facts = FactSheet.model_validate(st.output["facts"])
    sv = db.one(conn, "select * from script_versions where id=%s", (st.output["script_version_id"],))
    script = Script.model_validate(sv["body"])

    def do_package(_):
        pkg, problems, trail = pipeline.make_package(router, channel, script, facts)
        pkg.youtube_description = fill_sources(pkg.youtube_description, sources_used(conn, pid))
        pdata = pkg.model_dump()
        children = []
        for n, short in enumerate(pkg.shorts, 1):
            child = ensure_project(conn, channel, "short", short.title, week, parent_id=pid, key=f"{pid}:short:{n}")
            save_script(conn, child["id"], short.model_dump(), "ai", [trail])
            db.run(conn, "update content_projects set fresh_until=%s, quality_report=%s, status='rendering' where id=%s",
                   (db.one(conn, "select fresh_until from content_projects where id=%s", (pid,))["fresh_until"],
                    db.j({"derived_from": str(pid), "issues": [], "writers": trail.get("companies", [])}), child["id"]))
            children.append(str(child["id"]))
        qr = db.one(conn, "select quality_report from content_projects where id=%s", (pid,))["quality_report"] or {}
        qr["package_problems"] = problems
        # the post texts and Shorts were written by this model: it can't review the package either
        qr["writers"] = sorted(set(qr.get("writers") or []) | set(trail.get("companies") or []))
        db.run(conn, "update content_projects set recipe = recipe || %s, quality_report=%s where id=%s",
               (db.j({"package": pdata}), db.j(qr), pid))
        return {"children": children}

    report("Making the Shorts, titles and post texts", 2, 4)
    pk = jobs.run_stage(conn, "package", f"package:{pid}", do_package, project_id=pid)
    if not pk.ok:
        return {"project_id": str(pid), "status": pk.status, "error": pk.job.get("error_message")}

    out = {"project_id": str(pid), "children": pk.output["children"]}
    report(f"Rendering previews (1 video, {len(pk.output['children'])} Shorts)", 3, 4)
    render_preview(conn, storage, pid, script.model_dump(), channel, "long")
    for cid in pk.output["children"]:
        csv = db.one(conn, """select sv.body from content_projects p join script_versions sv
                              on sv.id=p.current_script_version_id where p.id=%s""", (cid,))
        render_preview(conn, storage, cid, csv["body"], channel, "short")
    report("Making thumbnails", 4, 4)
    make_thumbnails(conn, storage, pid, channel)
    final_status(conn, pid)
    for cid in pk.output["children"]:
        final_status(conn, cid)
    out["status"] = db.one(conn, "select status from content_projects where id=%s", (pid,))["status"]
    return out


def sources_used(conn, project_id) -> list[dict]:
    return db.all_(conn, """select distinct s.publisher, s.title, s.url from research_claims c
                            join research_sources s on s.id=c.source_id
                            join content_projects p on p.current_script_version_id=c.script_version_id
                           where p.id=%s and c.status in ('supported','partially_supported')""", (project_id,))


def fill_sources(description: str, sources: list[dict]) -> str:
    """Replace the [SOURCES] placeholder with real citations (or remove it if there are none)."""
    lines = "\n".join(f"- {s['publisher'] or 'Source'}: {s['title'][:80]} {s['url']}" for s in sources[:12])
    block = f"Sources:\n{lines}" if lines else ""
    text = description.replace("Sources: [SOURCES]", block).replace("[SOURCES]", block)
    if lines and "Sources:" not in text:
        text += "\n\n" + block
    return text.strip()


def attach_photos(conn, storage, project_id, recipe: dict, work: Path) -> dict[int, Path]:
    """Licensed stock photos for 'stock' scenes; scenes without a photo become original type cards."""
    photos: dict[int, Path] = {}
    orientation = "portrait" if recipe["format"] == "short" else "landscape"
    for i, sc in enumerate(recipe["scenes"]):
        v = sc["visual"]
        if v.get("type") != "stock":
            continue
        if sc.get("photo_key"):
            local = work / "photos" / Path(sc["photo_key"]).name
            if not local.exists():
                storage.download(sc["photo_key"], local)
            photos[i] = local
            continue
        hit = stock.find_photo(v.get("stock_query") or v.get("headline") or recipe["title"], work / "photos", orientation)
        if hit is None:
            v["type"] = "title_card"
            continue
        lic = db.one(conn, """insert into license_records (source_url, provider, creator, license, attribution_required,
                                  attribution_text)
                              values (%s,%s,%s,%s,%s,%s)
                              on conflict (source_url) do update set downloaded_at=now() returning id""",
                     (hit.source_url, hit.provider, hit.creator, hit.license, hit.attribution_required,
                      hit.attribution_text))
        key = storage.upload(f"projects/{project_id}/photos/{hit.path.name}", hit.path)
        db.run(conn, """insert into media_assets (project_id, kind, storage_path, bytes, license_record_id)
                        values (%s,'image',%s,%s,%s)""", (project_id, key, hit.path.stat().st_size, lic["id"]))
        sc["photo_key"], sc["license_record_id"] = key, str(lic["id"])
        photos[i] = hit.path
    return photos


def render_preview(conn, storage, project_id, script_body: dict, channel: str, fmt: str) -> dict:
    def do(_):
        recipe = rendering.recipe_from_script(script_body, channel, fmt, script_body.get("title", ""))
        work = config.runtime().work_dir / "render" / str(project_id)
        photos = attach_photos(conn, storage, project_id, recipe, work)
        out = work / "preview.mp4"
        res = rendering.render(recipe, out, "preview", work_dir=config.runtime().work_dir / "render" / "shared",
                               photos=photos)
        key = storage.upload(f"projects/{project_id}/preview.mp4", out, "video/mp4")
        asset = db.one(conn, """insert into media_assets (project_id, kind, storage_path, bytes, duration_seconds)
                                values (%s,'preview_video',%s,%s,%s) returning id""",
                       (project_id, key, res.bytes, res.duration))
        db.run(conn, "update content_projects set recipe = recipe || %s where id=%s",
               (db.j({"render": recipe, "preview_key": key, "preview_seconds": res.duration,
                      "timeline": res.scenes}), project_id))
        capacity.record_render(conn, project_id, "preview", res.seconds_taken, res.duration, res.bytes)
        return {"asset_id": str(asset["id"]), "key": key, "seconds": res.duration, "render_seconds": res.seconds_taken}

    return jobs.run_stage(conn, "render_preview", f"preview:{project_id}:{_script_version(conn, project_id)}", do,
                          project_id=project_id).output


def _script_version(conn, project_id) -> str:
    row = db.one(conn, "select current_script_version_id v from content_projects where id=%s", (project_id,))
    return str(row["v"]) if row else "none"


def make_thumbnails(conn, storage, project_id, channel: str) -> list[dict]:
    def do(_):
        pkg = (db.one(conn, "select recipe from content_projects where id=%s", (project_id,))["recipe"] or {}).get("package") or {}
        heads = pkg.get("thumbnail_headlines") or [pkg.get("youtube_title", "")]
        work = config.runtime().work_dir / "render" / str(project_id) / "thumbs"
        made = thumbnails.make_set(heads, Theme.for_channel(channel), work)
        db.run(conn, "delete from thumbnails where project_id=%s", (project_id,))
        out = []
        for i, t in enumerate(made):
            key = storage.upload(f"projects/{project_id}/thumbs/{t['path'].name}", t["path"], "image/jpeg")
            mkey = storage.upload(f"projects/{project_id}/thumbs/{t['mobile'].name}", t["mobile"], "image/jpeg")
            asset = db.one(conn, """insert into media_assets (project_id, kind, storage_path, bytes)
                                    values (%s,'thumbnail',%s,%s) returning id""",
                           (project_id, key, t["path"].stat().st_size))
            db.run(conn, """insert into thumbnails (project_id, variant_label, headline, template, options, asset_id, selected)
                            values (%s,%s,%s,%s,%s,%s,%s)""",
                   (project_id, t["label"], t["headline"], t["template"], db.j({"mobile_key": mkey, "key": key}),
                    asset["id"], i == 0))
            out.append({"key": key, "mobile_key": mkey})
        return {"thumbnails": out}

    return jobs.run_stage(conn, "thumbnails", f"thumbs:{project_id}", do, project_id=project_id).output


def final_status(conn, project_id) -> None:
    p = db.one(conn, "select status, quality_report, recipe from content_projects where id=%s", (project_id,))
    if p["status"] in ("approved", "scheduled", "published", "rejected"):
        return
    issues = (p["quality_report"] or {}).get("issues") or []
    bad_claims = db.one(conn, """select count(*) n from research_claims c
                                 join content_projects p on p.current_script_version_id = c.script_version_id
                                 where p.id=%s and c.status in ('unsupported','contradicted')""", (project_id,))["n"]
    has_preview = bool((p["recipe"] or {}).get("preview_key"))
    status = "ready_for_review" if has_preview and not issues and not bad_claims else (
        "needs_attention" if has_preview else "failed")
    db.run(conn, "update content_projects set status=%s where id=%s", (status, project_id))


def produce_batch(conn, router: Router, storage, week: date, *, channel: str | None = None) -> dict:
    if is_paused(conn):
        return {"skipped": "paused"}
    with db.run_lock(conn, "production") as free:
        if not free:
            return {"skipped": "another production run is in progress"}
        return _produce_batch(conn, router, storage, week, channel=channel)


def _produce_batch(conn, router: Router, storage, week: date, *, channel: str | None = None) -> dict:
    apply_brand_overrides(conn)
    plan = capacity.plan_batch(conn)
    results = []
    selected_channel = channel if channel in ("ai", "money") else None
    for slug, n in plan["long_per_channel"].items():
        if selected_channel and slug != selected_channel:
            continue
        ideas = db.all_(conn, """select * from content_ideas i where batch_week=%s and channel_slug=%s
                                 and status in ('shortlisted','selected')
                                 and not exists (select 1 from content_projects p where p.idea_id = i.id)
                                 order by is_experiment, score desc limit %s""",
                        (week, slug, n))
        for n_done, idea in enumerate(ideas, 1):
            jobs.progress(conn, f"Making {slug} video {n_done} of {len(ideas)}: {idea['title']}", n_done, len(ideas))
            db.run(conn, "update content_ideas set status='selected' where id=%s", (idea["id"],))
            try:
                results.append(produce_project(conn, router, storage, idea, week))
            except NeedsReview as exc:
                results.append({"idea": idea["title"], "status": "needs_review", "error": str(exc)})
            db.run(conn, "update content_ideas set status='produced' where id=%s", (idea["id"],))
    jobs.progress(conn, "Planning when each post goes out")
    plan_distribution(conn, week, channel=selected_channel)
    from .review import auto  # Auto Review & Post: no-op unless the owner switched it ON

    auto_results = auto.run(conn, router)
    ready = db.one(conn, """select count(*) filter (where status='ready_for_review') ready,
                                   count(*) filter (where status='needs_attention') attention,
                                   count(*) filter (where status='failed') failed
                              from content_projects where batch_week=%s and (%s::text is null or channel_slug=%s)""",
                   (week, selected_channel, selected_channel))
    scope = f"{selected_channel} mission" if selected_channel else "week"
    notify.send(conn, "week_ready", f"Your {scope} is ready for review ({week:%d %b})",
                f"{ready['ready']} ready, {ready['attention']} need attention, {ready['failed']} failed.",
                link=f"{config.runtime().dashboard_url}/review", dedupe_key=f"week_ready:{week}:{selected_channel or 'all'}")
    return {"projects": results, "summary": ready, "capacity": plan, "auto_review": auto_results}


# ----------------------------------------------------------------------------- distribution


def plan_distribution(conn, week: date, *, channel: str | None = None) -> int:
    """Create per-account variants + scheduled posts (pending approval) for the week after `week`."""
    tz = db.get_setting(conn, "timezone", "Africa/Nairobi")
    post_week = week + timedelta(days=7)
    now = datetime.now(timezone.utc)
    selected_channel = channel if channel in ("ai", "money") else None
    accounts = db.all_(conn, """select a.*, c.slug channel from social_accounts a
                                left join channel_profiles c on c.id = a.channel_profile_id
                                where a.enabled and (%s::text is null or c.slug=%s)""", (selected_channel, selected_channel))
    projects = db.all_(conn, """select p.*, i.score from content_projects p left join content_ideas i on i.id=p.idea_id
                                where p.batch_week=%s and p.status in ('ready_for_review','needs_attention')
                                  and (%s::text is null or p.channel_slug=%s)
                                order by p.format, coalesce(i.score,0) desc, p.created_at""",
                       (week, selected_channel, selected_channel))
    longs = [p for p in projects if p["format"] == "long"]
    shorts = [p for p in projects if p["format"] == "short"]
    created = 0
    for acc in accounts:
        t = acc["weekly_targets"]
        mix = acc["topic_mix"] or {"ai": 0.5, "money": 0.5}
        if acc["platform"] == "youtube":
            mine_l = [p for p in longs if p["channel_slug"] == acc["channel"]][: t.get("long_video", 3)]
            mine_s = [p for p in shorts if p["channel_slug"] == acc["channel"]][: t.get("short_video", 6)]
            created += _assign(conn, acc, mine_l, "long_video", slots_for(t, "posting", post_week, tz, now))
            created += _assign(conn, acc, mine_s, "short_video", slots_for(t, "shorts", post_week, tz, now))
        elif acc["platform"] == "tiktok":
            pick = schedule.balance_by_mix([{**p, "topic": p["channel_slug"]} for p in shorts], mix, t.get("short_video", 3))
            created += _assign(conn, acc, pick, "short_video", slots_for(t, "posting", post_week, tz, now))
        elif acc["platform"] == "facebook":
            pick = schedule.balance_by_mix([{**p, "topic": p["channel_slug"]} for p in shorts[::-1]], mix, t.get("reel", 3))
            texts = schedule.balance_by_mix([{**p, "topic": p["channel_slug"]} for p in longs], mix, t.get("text_post", 2))
            sl = slots_for(t, "posting", post_week, tz, now)
            created += _assign(conn, acc, pick, "reel", sl[: len(pick)])
            created += _assign(conn, acc, texts, "text_post", sl[len(pick):])
        elif acc["platform"] == "x":
            pick = schedule.balance_by_mix([{**p, "topic": p["channel_slug"]} for p in longs], mix, t.get("text_post", 3))
            created += _assign(conn, acc, pick, "text_post", slots_for(t, "posting", post_week, tz, now))
    return created


def slots_for(targets: dict, prefix: str, week: date, tz: str, now: datetime) -> list[datetime]:
    days = targets.get(f"{prefix}_days") or []
    times = targets.get(f"{prefix}_times") or []
    return schedule.slots(days, times, week, tz, not_before=now)


def variant_text(project: dict, acc: dict, kind: str) -> tuple[str | None, str, list[str], list[str]]:
    recipe = project["recipe"] or {}
    pkg = recipe.get("package") or {}
    if project["format"] == "short":
        parent = None
        body = None
        title = project["title"]
        return title, "", [], []
    if kind == "long_video":
        return pkg.get("youtube_title") or project["title"], pkg.get("youtube_description", ""), pkg.get("tags", []), []
    if acc["platform"] == "x":
        return None, pkg.get("x_post", ""), [], []
    return None, pkg.get("facebook_post", ""), [], []


def launch_at(conn, channel: str | None) -> datetime | None:
    """Midnight (studio time) of the channel's launch day, or None when it has launched or has no date."""
    row = db.one(conn, "select launch_date from channel_profiles where slug=%s", (channel,)) if channel else None
    if not row or not row["launch_date"]:
        return None
    tz = ZoneInfo(db.get_setting(conn, "timezone", "Africa/Nairobi"))
    return datetime.combine(row["launch_date"], datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)


def _assign(conn, acc: dict, projects: list[dict], kind: str, slots: list[datetime]) -> int:
    n = 0
    free = sorted(slots)
    for project in projects:
        start = launch_at(conn, project["channel_slug"])  # never before the channel's launch day
        when = next((s for s in free if start is None or s >= start), None)
        if when is None:
            continue
        free.remove(when)
        exists = db.one(conn, """select id from content_variants where project_id=%s and social_account_id=%s and kind=%s""",
                        (project["id"], acc["id"], kind))
        if exists:
            continue
        title, body, tags, hashtags = variant_text(project, acc, kind)
        if project["format"] == "short":
            sv = db.one(conn, "select body from script_versions where id=%s", (project["current_script_version_id"],))
            sb = (sv or {}).get("body") or {}
            title, body, hashtags = sb.get("title", project["title"]), sb.get("caption", ""), sb.get("hashtags", [])
            if acc["platform"] == "youtube":
                body = (body + "\n\n" + " ".join(f"#{h.lstrip('#')}" for h in hashtags + ["Shorts"])).strip()
        status = "ready_for_review" if project["status"] == "ready_for_review" else "needs_attention"
        preview = db.one(conn, """select id from media_assets where project_id=%s and kind='preview_video'
                                  order by created_at desc limit 1""", (project["id"],))
        with db.transaction(conn):
            v = db.one(conn, """insert into content_variants (project_id, social_account_id, kind, title, body, tags, hashtags,
                                                              preview_asset_id, status, checks)
                                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
                       (project["id"], acc["id"], kind, title, body, tags, hashtags, preview["id"] if preview else None,
                        status, db.j({"project_status": project["status"]})))
            db.run(conn, """insert into scheduled_posts (variant_id, social_account_id, scheduled_at, status, idempotency_key)
                            values (%s,%s,%s,'pending_approval',%s)""",
                   (v["id"], acc["id"], when, f"post:{v['id']}"))
        n += 1
    return n


# ----------------------------------------------------------------------------- one selected idea (guided Create)

STAGES = ("script", "package", "render_preview", "thumbnails")
DECIDED = ("approved", "scheduled", "published", "rejected", "archived")


def idea_for_production(conn, *, content_idea_id=None, generated_idea_id=None, channel: str | None = None) -> dict:
    """The research idea to make. A generated idea is converted once, keeping its stored sources as the evidence;
    the row lock makes two simultaneous requests get the same research idea."""
    if content_idea_id:
        idea = db.one(conn, "select * from content_ideas where id=%s", (content_idea_id,))
        if not idea:
            raise ValueError("That idea no longer exists.")
        if channel in ("ai", "money") and idea["channel_slug"] != channel:
            raise ValueError("That idea belongs to the other channel.")
        return idea
    if not generated_idea_id:
        raise ValueError("Choose an idea first.")
    with db.transaction(conn):
        g = db.one(conn, "select * from generated_ideas where id=%s for update", (generated_idea_id,))
        if not g:
            raise ValueError("That idea no longer exists.")
        if g["content_idea_id"]:
            return db.one(conn, "select * from content_ideas where id=%s", (g["content_idea_id"],))
        if g["status"] == "rejected":
            raise ValueError("That idea was marked Not for me. Restore it first.")
        ch = g["channel_slug"] if g["channel_slug"] in ("ai", "money") else channel
        if ch not in ("ai", "money"):
            raise ValueError("Choose Pixel or Penny for this idea.")
        if channel in ("ai", "money") and channel != ch:
            raise ValueError("That idea belongs to the other channel.")
        wanted = [s.get("source_id") for s in (g["trend_signals"] or []) if s.get("source_id")]
        stored = {str(r["id"]) for r in db.all_(conn, "select id from research_sources where id::text = any(%s)", (wanted,))}
        source_ids = [i for i in dict.fromkeys(wanted) if i in stored]  # keep the idea's own order
        if not source_ids:
            raise ValueError("This idea has no stored sources to check facts against. Use Research it deeper first.")
        idea = db.one(conn, """insert into content_ideas (channel_slug, title, angle, status, score, score_breakdown,
                                                          explanation, source_ids, batch_week)
                               values (%s,%s,%s,'selected',%s,%s,%s,%s::uuid[],%s) returning *""",
                      (ch, g["title"], g["summary"], g["total"],
                       db.j({**(g["scores"] or {}), "from_generated_idea": str(g["id"])}),
                       g["score_explanation"], source_ids, research.week_start()))
        history = list(g["status_history"] or []) + [
            {"at": datetime.now(timezone.utc).isoformat(), "status": "sent_to_studio", "by": "engine", "note": "package requested"}]
        db.run(conn, """update generated_ideas set content_idea_id=%s, status='sent_to_studio', status_history=%s
                        where id=%s""", (idea["id"], db.j(history), g["id"]))
    return idea


def produce_idea(conn, router: Router, storage, *, content_idea_id=None, generated_idea_id=None,
                 channel: str | None = None) -> dict:
    """Make exactly the selected idea's package. Only this package is planned and (if Auto Review & Post is ON)
    reviewed. Running it again resumes from the step that didn't work; nothing is made or planned twice.
    The publishing pause doesn't apply: this only makes content and posts wait for approval."""
    with db.run_lock(conn, "production") as free:
        if not free:
            raise RuntimeError("Another production run is in progress. Try again when it has finished.")
        apply_brand_overrides(conn)
        idea = idea_for_production(conn, content_idea_id=content_idea_id, generated_idea_id=generated_idea_id,
                                   channel=channel)
        week = idea["batch_week"] or research.week_start()
        project = db.one(conn, "select * from content_projects where idea_id=%s and parent_project_id is null",
                         (idea["id"],))
        job_id = jobs.active_job_id.get()
        if project is None:
            project = ensure_project(conn, idea["channel_slug"], "long", idea["title"], week, idea_id=idea["id"],
                                     key=f"idea:{idea['id']}")
        if job_id:
            db.run(conn, "update generation_jobs set project_id=%s where id=%s and project_id is null", (project["id"], job_id))
        if project["status"] in DECIDED:
            return {"project_id": str(project["id"]), "status": project["status"], "already": True}
        if project["status"] not in ("ready_for_review", "needs_attention"):
            family = [r["id"] for r in db.all_(conn, "select id from content_projects where id=%s or parent_project_id=%s",
                                                (project["id"], project["id"]))]
            # the owner asked again: steps that didn't work may run now (finished steps are kept)
            db.run(conn, """update generation_jobs set status='pending', attempts=0, next_attempt_at=null
                            where project_id = any(%s) and job_type = any(%s)
                              and status in ('failed','retrying','blocked','needs_review','cancelled')""", (family, list(STAGES)))
            db.run(conn, "update content_ideas set status='selected' where id=%s and status <> 'produced'", (idea["id"],))
            out = produce_project(conn, router, storage, idea, week, project=project,
                                  stage=lambda label, n, total: jobs.progress(conn, label, n, total))
            if out.get("error") or out.get("status") in ("failed", "needs_review", "retrying", "blocked"):
                db.run(conn, """update content_projects set status='failed' where id=%s
                                and status in ('draft','scripting','verifying','rendering')""", (project["id"],))
                raise RuntimeError(f"{out.get('error') or out.get('status')}"[:600])
            db.run(conn, "update content_ideas set status='produced' where id=%s", (idea["id"],))
        jobs.progress(conn, "Planning this package's posts")
        posts = plan_project_distribution(conn, project["id"])
        from .review import auto  # no-op unless Auto Review & Post is ON; looks at this package only

        reviewed = auto.run(conn, router, [project["id"]])
        head = db.one(conn, "select id, title, status from content_projects where id=%s", (project["id"],))
        if head["status"] in ("ready_for_review", "needs_attention"):
            notify.send(conn, "package_ready", f"Ready for review: {head['title']}",
                        "Passed every check." if head["status"] == "ready_for_review" else "Something needs a look before approval.",
                        link=f"{config.runtime().dashboard_url}/review/{head['id']}", dedupe_key=f"package_ready:{head['id']}")
        return {"project_id": str(head["id"]), "status": head["status"], "posts_planned": posts, "auto_review": reviewed}


def plan_project_distribution(conn, project_id, now: datetime | None = None) -> int:
    """Posts for one package only. Other projects of the same week are never touched. Each post takes its account's
    next free slot from the posting week on (the week after the package's week), never a slot another post holds."""
    now = now or datetime.now(timezone.utc)
    tz = db.get_setting(conn, "timezone", "Africa/Nairobi")
    head = db.one(conn, "select * from content_projects where id=%s and parent_project_id is null", (project_id,))
    if not head or head["status"] not in ("ready_for_review", "needs_attention"):
        return 0
    shorts = db.all_(conn, """select * from content_projects where parent_project_id=%s
                              and status in ('ready_for_review','needs_attention') order by created_at""", (project_id,))
    accounts = db.all_(conn, """select a.*, c.slug channel from social_accounts a
                                left join channel_profiles c on c.id = a.channel_profile_id where a.enabled order by a.platform""")
    first_week = (head["batch_week"] or research.week_start()) + timedelta(days=7)
    launch = launch_at(conn, head["channel_slug"])
    earliest = max(now, launch) if launch else now
    taken: dict = {}

    def free_slots(acc: dict, prefix: str, n: int) -> list[datetime]:
        if n <= 0:
            return []
        held = taken.setdefault(acc["id"], [r["scheduled_at"] for r in db.all_(conn, """
            select scheduled_at from scheduled_posts where social_account_id=%s and status not in ('cancelled','failed')""",
            (acc["id"],))])
        t = acc["weekly_targets"] or {}
        days, times = t.get(f"{prefix}_days") or [], t.get(f"{prefix}_times") or []
        out: list[datetime] = []
        for w in range(8):
            for slot in schedule.slots(days, times, first_week + timedelta(days=7 * w), tz, not_before=earliest):
                if all(abs((slot - x).total_seconds()) >= 1800 for x in held):
                    out.append(slot)
                    held.append(slot)
                    if len(out) == n:
                        return out
        return out

    def todo(projects: list[dict], acc: dict, kind: str) -> list[dict]:
        return [p for p in projects if not db.one(conn, """select 1 from content_variants
                                                           where project_id=%s and social_account_id=%s and kind=%s""",
                                                    (p["id"], acc["id"], kind))]

    created = 0
    ch = head["channel_slug"]
    for acc in accounts:
        t = acc["weekly_targets"] or {}
        if float((acc["topic_mix"] or {}).get(ch, 0)) <= 0:
            continue  # this account doesn't post this channel's topics
        plan: list[tuple[list[dict], str, str]] = []
        if acc["platform"] == "youtube":
            if acc["channel"] != ch:
                continue
            if t.get("long_video", 0):
                plan.append(([head], "long_video", "posting"))
            if t.get("short_video", 0):
                plan.append((shorts, "short_video", "shorts"))
        elif acc["platform"] == "tiktok" and t.get("short_video", 0):
            plan.append((shorts[:1], "short_video", "posting"))
        elif acc["platform"] == "facebook":
            if t.get("reel", 0):
                plan.append((shorts[-1:], "reel", "posting"))
            if t.get("text_post", 0):
                plan.append(([head], "text_post", "posting"))
        elif acc["platform"] == "x" and t.get("text_post", 0):
            plan.append(([head], "text_post", "posting"))
        for projects, kind, prefix in plan:
            items = todo(projects, acc, kind)
            created += _assign(conn, acc, items, kind, free_slots(acc, prefix, len(items)))
    return created
