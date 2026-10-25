"""Stage 2 rules: money math recalculated by code, no invented hands-on tests, country-specific titles,
per-channel YouTube categories and a repetition check."""

import json
from datetime import datetime, timedelta, timezone

import httpx

from studio import db, produce
from studio.publish import adapters, runner
from studio.script import quality, verify
from studio.script.models import Claim, Fact, FactSheet, Scene, Script, Visual

from .test_end_to_end import Platform, _approve_all, _connect_all, produced, silent_tts  # noqa: F401


def _script(text: str, claims: list[Claim], title: str = "Money basics") -> Script:
    return Script(title=title, hook="Here's the math.", promise="You'll know.", cta="Subscribe.", claims=claims,
                  scenes=[Scene(narration=text, visual=Visual(type="title_card", headline="x"), claim_keys=[c.key for c in claims])])


def test_money_math_is_recalculated_by_code_not_judged_by_a_model():
    facts = FactSheet(facts=[Fact(key="F1", text="The average savings rate was 5% in 2026.", source_ref="S1")], context="")
    good = Claim(key="C1", kind="calculation", text="At 5% a year, $10,000 grows to about $16,289 in 10 years",
                 expression="10000*(1+0.05)**10")
    wrong = Claim(key="C2", kind="calculation", text="At 5% a year, $10,000 doubles to $20,000 in 10 years",
                  expression="10000*(1+0.05)**10")
    invented = Claim(key="C3", kind="calculation", text="That's about $31,000", expression="200*12*13")
    missing = Claim(key="C4", kind="calculation", text="That's $24,000", expression="")
    script = _script("Numbers.", [good, wrong, invented, missing])
    out = {r["key"]: r for r in verify.check_claims(None, script, facts, [])}  # no model call: code decides
    assert out["C1"]["status"] == "supported" and "Recalculated by code" in out["C1"]["note"]
    assert out["C2"]["status"] == "contradicted" and "16,288.95" in out["C2"]["note"]
    assert out["C3"]["status"] == "unsupported" and "200" in out["C3"]["note"]  # $200 and 13 years came from nowhere
    assert out["C4"]["status"] == "unsupported"
    for bad in ("__import__('os').system('x')", "open('f')", "(9**9)**(9**9)", "1/0"):
        assert verify.check_calculation("That's 1", bad, set())[0] == "unsupported"


def test_scripts_and_posts_never_claim_a_hands_on_test():
    s = _script("I tested five apps last week and one won. Researchers tested the model too.", [], title="I Tested 5 AI Apps")
    issues = quality.check_long(s, "ai")
    assert any("Claims a hands-on test" in i and "i tested" in i.lower() for i in issues)
    assert quality.invented_tests("Researchers tested the model. Reviewers tried it.") == []
    assert quality.drop_invented_tests("Big update. We tried it for a week. Here's what changed.") == "Big update. Here's what changed."


def test_money_titles_say_which_countrys_rules_they_use():
    assert quality.main_country("Max your 401(k) before your Roth IRA") == "US"
    assert quality.main_country("Use your ISA allowance before April") == "UK"
    assert quality.main_country("Use your TFSA and RRSP room") == "Canada"
    assert quality.main_country("How to budget on any income") is None
    assert quality.with_country("Retirement accounts explained", "US") == "Retirement accounts explained (US)"
    assert quality.with_country("How a Roth IRA works for Americans", "US") == "How a Roth IRA works for Americans"
    assert quality.with_country("x" * 98, "US") == "x" * 98  # never past YouTube's 100-character limit


def test_each_channel_uploads_in_its_own_category(produced):
    conn, storage = produced
    _connect_all(conn)
    _approve_all(conn)
    db.run(conn, "update content_projects set fresh_until = now() + interval '60 days'")
    db.run(conn, "update scheduled_posts set status='scheduled'")
    bodies = []

    def platform(req: httpx.Request):
        if "upload/youtube/v3/videos" in str(req.url) and req.method == "POST":
            bodies.append(json.loads(req.content))
        return Platform()(req)
    client = httpx.Client(transport=httpx.MockTransport(platform))
    ads = {"youtube": adapters.YouTube(client), "facebook": adapters.Facebook(client),
           "tiktok": adapters.TikTok(client), "x": adapters.X(client)}
    for label in ("YouTube AI", "YouTube Money"):
        post = db.one(conn, """select sp.* from scheduled_posts sp join social_accounts a on a.id = sp.social_account_id
                               where a.label=%s and sp.status='scheduled' order by sp.scheduled_at limit 1""", (label,))
        assert runner.publish_post(conn, storage, post, ads, now=datetime.now(timezone.utc) + timedelta(days=30)) in (
            "published", "published_needs_followup")
    cats = [b["snippet"]["categoryId"] for b in bodies]
    assert cats == ["28", "27"]  # Pixel: Science & Technology, Penny: Education
    assert all(b["snippet"]["defaultAudioLanguage"] == "en" and b["status"]["containsSyntheticMedia"] is False for b in bodies)


def test_a_near_copy_of_an_earlier_video_is_held_back(produced):
    conn, _ = produced
    p = db.one(conn, "select * from content_projects where channel_slug='ai' and format='long'")
    sv = db.one(conn, "select body from script_versions where id=%s", (p["current_script_version_id"],))
    copy = Script.model_validate(sv["body"])
    other = db.one(conn, """insert into content_projects (channel_slug, format, title, status, batch_week)
                            values ('ai','long','Another','scripting', current_date) returning id""")["id"]
    issue = produce.repeats_earlier(conn, "ai", other, copy)
    assert issue and issue.startswith("Too similar to an earlier video")
    fresh = copy.model_copy(update={"title": "Credit scores, explained",
                                    "scenes": [copy.scenes[0].model_copy(update={"narration": "Payment history matters most for a credit score."})]})
    assert produce.repeats_earlier(conn, "ai", other, fresh) is None
