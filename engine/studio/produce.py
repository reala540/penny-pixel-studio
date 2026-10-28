"""Weekly batch orchestration: config sync, research (Saturday), production (Sunday), distribution plan."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from . import budget, capacity, config, db, jobs, links, notify, schedule, similarity
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


def _video_wanted(n_stock: int) -> bool:
    """Which stock scenes try a real video clip first (render.stock_video: off, alternate or always)."""
    mode = str(config.services()["render"].get("stock_video", "alternate"))
    return mode == "always" or (mode == "alternate" and n_stock % 2 == 0)


def _license(conn, hit) -> dict:
    return db.one(conn, """insert into license_records (source_url, provider, creator, license, attribution_required,
                              attribution_text)
                          values (%s,%s,%s,%s,%s,%s)
                          on conflict (source_url) do update set downloaded_at=now() returning id""",
                  (hit.source_url, hit.provider, hit.creator, hit.license, hit.attribution_required, hit.attribution_text))


def attach_effects(conn, storage, project_id, recipe: dict, work: Path) -> dict[int, Path]:
    """A soft sound effect for each animated scene when a Freesound key is set (CC0 only, with a licence record)."""
    from .media import sfx

    effects: dict[int, Path] = {}
    for i, sc in enumerate(recipe["scenes"]):
        v = sc["visual"]
        if v.get("type") != "animated":
            continue
        if sc.get("sfx_key"):
            local = work / "sfx" / Path(sc["sfx_key"]).name
            try:
                if not local.exists():
                    storage.download(sc["sfx_key"], local)
                effects[i] = local
                continue
            except Exception:
                sc.pop("sfx_key", None)
        hit = sfx.find_effect(v.get("animation") or "", work / "sfx")
        if hit is None:
            continue
        lic = _license(conn, hit)
        key = storage.upload(f"projects/{project_id}/sfx/{hit.path.name}", hit.path, "audio/mpeg")
        db.run(conn, """insert into media_assets (project_id, kind, storage_path, bytes, license_record_id)
                        values (%s,'music',%s,%s,%s)""", (project_id, key, hit.path.stat().st_size, lic["id"]))
        sc["sfx_key"], sc["sfx_license_record_id"] = key, str(lic["id"])
        effects[i] = hit.path
    return effects


def attach_media(conn, storage, project_id, recipe: dict, work: Path) -> tuple[dict[int, Path], dict[int, Path]]:
    """Licensed stock video clips and photos for 'stock' scenes (a balanced mix: by default every other stock scene
    tries a clip first). A scene with neither becomes an original type card. Every file keeps its licence record."""
    photos: dict[int, Path] = {}
    videos: dict[int, Path] = {}
    orientation = "portrait" if recipe["format"] == "short" else "landscape"
    n_stock = 0
    for i, sc in enumerate(recipe["scenes"]):
        v = sc["visual"]
        if v.get("type") != "stock":
            continue
        query = v.get("stock_query") or v.get("headline") or recipe["title"]
        if sc.get("video_key"):
            local = work / "clips_src" / Path(sc["video_key"]).name
            try:
                if not local.exists():
                    storage.download(sc["video_key"], local)
                videos[i] = local
                n_stock += 1
                continue
            except Exception:  # the clip was cleaned up: look again (a new clip or photo, with its own licence)
                sc.pop("video_key", None)
                sc.pop("license_record_id", None)
        if not sc.get("photo_key") and _video_wanted(n_stock):
            clip = stock.find_video(query, work / "clips_raw", orientation)
            small = None
            if clip is not None:
                try:
                    small = rendering.prepare_clip(clip.path, work / "clips_src" / clip.path.name, recipe["format"])
                except Exception:  # a clip FFmpeg can't read: use a photo instead
                    small = None
                clip.path.unlink(missing_ok=True)  # only the trimmed copy is kept
            if clip is not None and small is not None:
                lic = _license(conn, clip)
                key = storage.upload(f"projects/{project_id}/clips/{small.name}", small, "video/mp4")
                db.run(conn, """insert into media_assets (project_id, kind, storage_path, bytes, license_record_id)
                                values (%s,'video_clip',%s,%s,%s)""", (project_id, key, small.stat().st_size, lic["id"]))
                sc["video_key"], sc["license_record_id"] = key, str(lic["id"])
                videos[i] = small
                n_stock += 1
                continue
        n_stock += 1
        if sc.get("photo_key"):
            local = work / "photos" / Path(sc["photo_key"]).name
            if not local.exists():
                storage.download(sc["photo_key"], local)
            photos[i] = local
            continue
        hit = stock.find_photo(query, work / "photos", orientation)
        if hit is None:
            v["type"] = "title_card"
            continue
        lic = _license(conn, hit)
        key = storage.upload(f"projects/{project_id}/photos/{hit.path.name}", hit.path)
        db.run(conn, """insert into media_assets (project_id, kind, storage_path, bytes, license_record_id)
                        values (%s,'image',%s,%s,%s)""", (project_id, key, hit.path.stat().st_size, lic["id"]))
        sc["photo_key"], sc["license_record_id"] = key, str(lic["id"])
        photos[i] = hit.path
    return photos, videos


def attach_photos(conn, storage, project_id, recipe: dict, work: Path) -> dict[int, Path]:
    """Photos only (kept for callers that don't render clips)."""
    return attach_media(conn, storage, project_id, recipe, work)[0]


def render_preview(conn, storage, project_id, script_body: dict, channel: str, fmt: str) -> dict:
    def do(_):
        recipe = rendering.recipe_from_script(script_body, channel, fmt, script_body.get("title", ""))
        work = config.runtime().work_dir / "render" / str(project_id)
        photos, videos = attach_media(conn, storage, project_id, recipe, work)
        effects = attach_effects(conn, storage, project_id, recipe, work)
        out = work / "preview.mp4"
        res = rendering.render(recipe, out, "preview", work_dir=config.runtime().work_dir / "render" / "shared",
                               photos=photos, videos=videos, effects=effects)
        key = storage.upload(f"projects/{project_id}/preview.mp4", out, "video/mp4")
        asset = db.one(conn, """insert into media_assets (project_id, kind, storage_path, bytes, duration_seconds)
                                values (%s,'preview_video',%s,%s,%s) returning id""",
                       (project_id, key, res.bytes, res.duration))
        db.run(conn, "update content_projects set recipe = recipe || %s where id=%s",
               (db.j({"render": recipe, "preview_key": key, "preview_seconds": res.duration,
                      "timeline": res.scenes}), project_id))
        capacity.record_render(conn, project_id, "preview", res.seconds_taken, res.duration, res.bytes)
        return {"asset_id": str(asset["id"]), "key": key, "seconds": res.duration, "render_seconds": res.seconds_taken}

    out = jobs.run_stage(conn, "render_preview", f"preview:{project_id}:{_script_version(conn, project_id)}", do,
                         project_id=project_id).output
    if fmt == "long" and out and out.get("seconds"):
        use_real_length(conn, project_id, float(out["seconds"]))
    return out


def use_real_length(conn, project_id, seconds: float) -> None:
    """The script's length warning is a word-count estimate; once the video exists, its real length decides."""
    from .script import quality

    row = db.one(conn, "select quality_report from content_projects where id=%s", (project_id,))
    qr = (row or {}).get("quality_report") or {}
    issues = qr.get("issues") or []
    kept = [i for i in issues if not i.startswith(("Too short: about", "Too long: about"))]
    max_min = config.services()["render"]["max_long_minutes"]
    if seconds < quality.MIN_LONG_SECONDS:
        kept.append(f"Too short: {seconds / 60:.1f} min (aim for {quality.MIN_LONG_SECONDS // 60}+ min)")
    elif seconds > max_min * 60:
        kept.append(f"Too long: {seconds / 60:.1f} min (max {max_min})")
    if kept != issues:
        qr["issues"] = kept
        db.run(conn, "update content_projects set quality_report=%s where id=%s", (db.j(qr), project_id))


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
                link=links.needs_you(), dedupe_key=f"week_ready:{week}:{selected_channel or 'all'}")
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
            videos = schedule.balance_by_mix([{**p, "topic": p["channel_slug"]} for p in longs], mix, t.get("long_video", 0))
            free = slots_for(t, "posting", post_week, tz, now)  # each type takes the next free slots
            created += _assign(conn, acc, pick, "reel", free)
            created += _assign(conn, acc, texts, "text_post", free)
            created += _assign(conn, acc, videos, "long_video", free)
            created += _add_stories(conn, acc, [p["id"] for p in pick][: t.get("story", 0)])
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
        if acc["platform"] == "facebook":  # same title and description (with its disclaimer) as YouTube; no tags
            return pkg.get("youtube_title") or project["title"], pkg.get("youtube_description", ""), [], []
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
    """Give each project the earliest free slot. Used slots are removed from `slots`, so several kinds can share it."""
    n = 0
    slots.sort()
    free = slots
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
        _create_variant(conn, acc, project, kind, when)
        n += 1
    return n


HASHTAGS_PER_PLATFORM = {"youtube": 3, "tiktok": 5, "facebook": 3}


def short_caption(sb: dict, platform: str, kind: str, fallback_title: str) -> tuple[str, str, list[str]]:
    """Each platform gets its own words: the TikTok and Reel captions when the writer gave them (else the main
    caption), and only as many topic hashtags as suit that platform. YouTube's go in the text with #Shorts."""
    title = sb.get("title", fallback_title)
    tags = [h.lstrip("#") for h in sb.get("hashtags", []) if h][: HASHTAGS_PER_PLATFORM.get(platform, 3)]
    if platform == "tiktok":
        return title, (sb.get("tiktok_caption") or sb.get("caption", "")).strip(), tags
    if platform == "facebook":
        return title, (sb.get("reel_caption") or sb.get("caption", "")).strip(), tags
    if platform == "youtube":
        text = (sb.get("caption", "") + "\n\n" + " ".join(f"#{h}" for h in tags + ["Shorts"])).strip()
        return title, text, tags
    return title, sb.get("caption", ""), tags


STORY_DELAY = timedelta(hours=3)  # a Story goes up three hours after its Reel


def _create_variant(conn, acc: dict, project: dict, kind: str, when: datetime) -> None:
    title, body, tags, hashtags = variant_text(project, acc, kind)
    if project["format"] == "short":
        sv = db.one(conn, "select body from script_versions where id=%s", (project["current_script_version_id"],))
        sb = (sv or {}).get("body") or {}
        title, body, hashtags = short_caption(sb, acc["platform"], kind, project["title"])
    from .publish import limits

    too_long = limits.problems(acc["platform"], kind, title, body, tags, hashtags)
    status = "ready_for_review" if project["status"] == "ready_for_review" and not too_long else "needs_attention"
    preview = db.one(conn, """select id from media_assets where project_id=%s and kind='preview_video'
                              order by created_at desc limit 1""", (project["id"],))
    with db.transaction(conn):
        v = db.one(conn, """insert into content_variants (project_id, social_account_id, kind, title, body, tags, hashtags,
                                                          preview_asset_id, status, checks)
                            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
                   (project["id"], acc["id"], kind, title, body, tags, hashtags, preview["id"] if preview else None,
                    status, db.j({"project_status": project["status"], "limits": too_long})))
        db.run(conn, """insert into scheduled_posts (variant_id, social_account_id, scheduled_at, status, idempotency_key)
                        values (%s,%s,%s,'pending_approval',%s)""",
               (v["id"], acc["id"], when, f"post:{v['id']}"))


def _add_stories(conn, acc: dict, project_ids: list) -> int:
    """A Story for each of these projects' Reels on this Page, three hours after the Reel. A Story never takes a
    posting slot of its own and is never added twice."""
    n = 0
    for pid in project_ids:
        reel = db.one(conn, """select sp.scheduled_at from scheduled_posts sp join content_variants v on v.id = sp.variant_id
                               where v.project_id=%s and v.social_account_id=%s and v.kind='reel'
                                 and sp.status not in ('cancelled','failed') order by sp.scheduled_at limit 1""", (pid, acc["id"]))
        if not reel or db.one(conn, "select 1 from content_variants where project_id=%s and social_account_id=%s and kind='story'",
                               (pid, acc["id"])):
            continue
        project = db.one(conn, "select * from content_projects where id=%s", (pid,))
        _create_variant(conn, acc, project, "story", reel["scheduled_at"] + STORY_DELAY)
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
                 channel: str | None = None, fresh_attempts: bool = True) -> dict:
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
            # the owner asked again: steps that didn't work may run now (finished steps are kept).
            # An automatic retry (fresh_attempts=False) keeps each step's remaining attempts instead.
            if fresh_attempts:
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
                        link=links.project(head["id"]), dedupe_key=f"package_ready:{head['id']}")
        return {"project_id": str(head["id"]), "status": head["status"], "posts_planned": posts, "auto_review": reviewed}


def resume_due_retries(conn, router: Router, storage, limit: int = 1) -> list[dict]:
    """A step waiting to retry (a busy or rate-limited service) really runs again when its time comes, with only the
    attempts it has left: finished steps are kept and nothing is made twice. A package the owner is working on
    (a request queued or running) or has already decided is left alone. When the last attempt fails, the owner
    is told once."""
    # a step can't usefully retry for a package that's already decided (approved, discarded…): close it
    db.run(conn, """update generation_jobs j set status='cancelled', next_attempt_at=null,
                           error_message=coalesce(j.error_message, '') || ' (not retried: the package was already decided)'
                      from content_projects p join content_projects h on h.id = coalesce(p.parent_project_id, p.id)
                     where j.project_id = p.id and j.status = 'retrying' and j.job_type = any(%s) and h.status = any(%s)""",
           (list(STAGES), list(DECIDED)))
    due = db.all_(conn, """
        select distinct h.id, h.idea_id, h.title from generation_jobs j
          join content_projects p on p.id = j.project_id
          join content_projects h on h.id = coalesce(p.parent_project_id, p.id)
         where j.status = 'retrying' and coalesce(j.next_attempt_at, now()) <= now() and j.attempts < j.max_attempts
           and j.job_type = any(%s) and h.idea_id is not null and h.status <> all(%s)
           and not exists (select 1 from generation_jobs o where o.requested_by = 'owner'
                            and o.status in ('queued', 'running', 'retrying') and o.project_id = h.id)
         limit %s""", (list(STAGES), list(DECIDED), limit))
    out = []
    for h in due:
        try:
            res = produce_idea(conn, router, storage, content_idea_id=h["idea_id"], fresh_attempts=False)
            out.append({"project_id": str(h["id"]), "status": res.get("status")})
        except Exception as exc:  # noqa: BLE001 - recorded on the step itself; the owner hears when retries end
            out.append({"project_id": str(h["id"]), "status": "retrying", "error": str(exc)[:200]})
            left = db.one(conn, """select count(*) n from generation_jobs j join content_projects p on p.id = j.project_id
                                    where coalesce(p.parent_project_id, p.id) = %s and j.status = 'retrying'""", (h["id"],))["n"]
            if not left:
                notify.send(conn, "job_failed", f"Stopped retrying: {h['title']}",
                            f"A step still didn't work after its last automatic attempt: {str(exc)[:200]}. Open the package to try again.",
                            link=links.project(h["id"]), dedupe_key=f"retries_exhausted:{h['id']}")
    return out


def plan_project_distribution(conn, project_id, now: datetime | None = None, shorts_only: bool = False) -> int:
    """Posts for one package only. Other projects of the same week are never touched. Each post takes its account's
    next free slot from the posting week on (the week after the package's week), never a slot another post holds.
    `shorts_only` plans just the Shorts still waiting for review (new Shorts for a package that was already decided):
    the main video's posts are never added or touched."""
    now = now or datetime.now(timezone.utc)
    tz = db.get_setting(conn, "timezone", "Africa/Nairobi")
    head = db.one(conn, "select * from content_projects where id=%s and parent_project_id is null", (project_id,))
    allowed = ("ready_for_review", "needs_attention") + (("approved", "scheduled", "published") if shorts_only else ())
    if not head or head["status"] not in allowed:
        return 0
    shorts = db.all_(conn, """select * from content_projects where parent_project_id=%s
                              and status in ('ready_for_review','needs_attention') order by created_at""", (project_id,))
    accounts = db.all_(conn, """select a.*, c.slug channel from social_accounts a
                                left join channel_profiles c on c.id = a.channel_profile_id where a.enabled order by a.platform""")
    first_week = (head["batch_week"] or research.week_start()) + timedelta(days=7)
    if shorts_only:
        first_week = max(first_week, research.week_start())
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
            if t.get("long_video", 0):
                plan.append(([head], "long_video", "posting"))
        elif acc["platform"] == "x" and t.get("text_post", 0):
            plan.append(([head], "text_post", "posting"))
        if shorts_only:
            plan = [x for x in plan if x[0] is not None and head not in x[0]]
        for projects, kind, prefix in plan:
            items = todo(projects, acc, kind)
            created += _assign(conn, acc, items, kind, free_slots(acc, prefix, len(items)))
        if acc["platform"] == "facebook" and t.get("story", 0):
            created += _add_stories(conn, acc, [p["id"] for p in shorts[-1:]])
    return created


def remake_shorts(conn, router: Router, storage, project_id, job_id=None, note: str = "") -> dict:
    """New Shorts for a package, from its own checked facts, without touching its script, main video or posts.
    The new Shorts and their posts wait for the owner's approval; posts that already exist are never planned again."""
    head = db.one(conn, "select * from content_projects where id=%s", (project_id,))
    if not head or head["parent_project_id"] or head["format"] != "long":
        raise ValueError("Choose the main video of a package; Shorts are made from it")
    if head["status"] in ("rejected", "archived", "failed"):
        raise ValueError(f"This package is {head['status']}; Shorts can't be added to it")
    facts_job = db.one(conn, "select output from generation_jobs where idempotency_key=%s and status='completed'",
                       (f"script:{project_id}",))
    if not facts_job or not (facts_job["output"] or {}).get("facts"):
        raise ValueError("This package's checked facts weren't saved, so its Shorts can't be remade safely")
    from .script.models import FactSheet

    facts = FactSheet.model_validate(facts_job["output"]["facts"])
    sv = db.one(conn, "select body, provider_trail from script_versions where id=%s", (head["current_script_version_id"],))
    script = Script.model_validate(sv["body"])
    shorts, problems, dropped = pipeline.make_shorts(router, head["channel_slug"], script, facts, tries=2, note=note)
    qr = head["quality_report"] or {}
    qr["shorts_remakes"] = (qr.get("shorts_remakes") or []) + [
        {"at": datetime.now(timezone.utc).isoformat(), "made": len(shorts), "problems": problems[-6:]}]
    db.run(conn, "update content_projects set quality_report=%s where id=%s", (db.j(qr), project_id))
    if not shorts:
        notify.send(conn, "job_failed", "Couldn't make new Shorts", "; ".join(problems[-4:])[:1500],
                    link=links.project(project_id, "shorts"), dedupe_key=f"remake_failed:{project_id}:{job_id}")
        return {"made": 0, "problems": problems}
    tag = str(job_id or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))
    children = []
    for n, short in enumerate(shorts, 1):
        child = ensure_project(conn, head["channel_slug"], "short", short.title, head["batch_week"], parent_id=project_id,
                               key=f"{project_id}:short:remake:{tag}:{n}")
        save_script(conn, child["id"], short.model_dump(), "ai", sv["provider_trail"] or [])
        db.run(conn, "update content_projects set fresh_until=%s, quality_report=%s, status='rendering' where id=%s",
               (head["fresh_until"], db.j({"derived_from": str(project_id), "issues": [], "remade": True}), child["id"]))
        render_preview(conn, storage, child["id"], short.model_dump(), head["channel_slug"], "short")
        final_status(conn, child["id"])
        children.append(str(child["id"]))
    posts = plan_project_distribution(conn, project_id, shorts_only=True)
    notify.send(conn, "package_ready", f"New Shorts ready for review ({len(children)})", head["title"],
                link=links.project(project_id, "shorts"), dedupe_key=f"remade:{project_id}:{tag}")
    return {"made": len(children), "children": children, "posts": posts, "problems": problems}


def preview_scene(conn, storage, project_id, index: int) -> dict:
    """One scene of the saved script, rendered on its own with its narration, so an animation (or any scene) can be
    checked without rebuilding the whole video. Nothing is approved, published or replaced by this."""
    p = db.one(conn, "select * from content_projects where id=%s", (project_id,))
    if not p or not p["current_script_version_id"]:
        raise ValueError("This package has no script yet")
    sv = db.one(conn, "select body from script_versions where id=%s", (p["current_script_version_id"],))
    body = sv["body"]
    if not 0 <= index < len(body.get("scenes") or []):
        raise ValueError("That scene doesn't exist in the current script")
    recipe = rendering.recipe_from_script(body, p["channel_slug"], p["format"], body.get("title", p["title"]))
    one = {**recipe, "scenes": [recipe["scenes"][index + 1]]}          # scene 0 of the recipe is the hook
    work = config.runtime().work_dir / "render" / str(project_id)
    photos, videos = attach_media(conn, storage, project_id, one, work)
    effects = attach_effects(conn, storage, project_id, one, work)
    out = work / f"scene_{index}.mp4"
    res = rendering.render(one, out, "preview", work_dir=config.runtime().work_dir / "render" / "shared",
                           photos=photos, videos=videos, effects=effects)
    key = storage.upload(f"projects/{project_id}/scenes/scene_{index}_{str(p['current_script_version_id'])[:8]}.mp4",
                         out, "video/mp4")
    db.run(conn, """update content_projects set recipe = jsonb_set(coalesce(recipe,'{}'::jsonb), '{scene_previews}',
                        coalesce(recipe->'scene_previews','{}'::jsonb) || %s) where id=%s""",
           (db.j({str(index): {"key": key, "version": str(p["current_script_version_id"]), "seconds": res.duration}}),
            project_id))
    return {"scene": index, "key": key, "seconds": res.duration}
