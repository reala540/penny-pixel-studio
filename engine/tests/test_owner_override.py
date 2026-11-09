"""The owner's switch to post approved content without the final fact check and the freshness stop (9 Nov), and the
website's picture placeholder."""

from datetime import datetime, timedelta, timezone

from studio import db, website
from studio.publish import runner


def _set(conn, value):
    db.run(conn, "insert into settings (key, value) values ('publish_without_checks', %s) on conflict (key) do update set value=excluded.value",
           (db.j(value),))


def test_the_switch_is_off_by_default_and_ends_by_itself(synced):
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    assert runner.checks_off(synced, now) is False
    _set(synced, {"on": True, "until": "2026-11-16T21:00:00Z"})
    assert runner.checks_off(synced, now) is True
    assert runner.checks_off(synced, now + timedelta(days=7)) is False      # switched itself off after the week
    _set(synced, {"on": False})
    assert runner.checks_off(synced, now) is False


def test_expired_facts_stop_a_post_only_while_the_switch_is_off(synced):
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    ctx = {"social_account_id": "a", "account_enabled": True, "variant_status": "approved", "id": "00000000-0000-0000-0000-000000000009",
           "project_id": "00000000-0000-0000-0000-000000000008", "current_script_version_id": None, "approved_script_version_id": None,
           "project_status": "approved", "fresh_until": now - timedelta(days=1), "recipe": {}}
    post = {"social_account_id": "a"}
    assert any("content expired" in p for p in runner.safety_problems(synced, post, ctx, now))
    _set(synced, {"on": True})
    problems = runner.safety_problems(synced, post, ctx, now)
    assert not any("content expired" in p for p in problems)
    assert any("approval" in p for p in problems)                            # approvals are still required


def test_an_article_without_a_picture_shows_the_brand_mark_not_a_blank_box(tmp_path):
    a = website.Article("p1", "money", "a-1", "How to check whether your raise beats inflation", "d", ["Text."] * 3,
                        datetime(2026, 11, 7, tzinfo=timezone.utc))
    out = tmp_path / "site"
    website.build([a], out, options={})
    home = (out / "index.html").read_text()
    assert 'class="noimg money"' in home and 'aria-label="Money"' in home
