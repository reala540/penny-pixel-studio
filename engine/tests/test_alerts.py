"""Telegram alerts (simulated Telegram only): secrets never stored or sent, routine updates can stay in the app,
identical repeats are grouped, unconfigured is not a failure, and failed delivery never undoes the work."""
import httpx

from studio import db, notify


def _telegram(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-not-a-real-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "test-chat")
    sent = []
    client = httpx.Client(transport=httpx.MockTransport(lambda req: sent.append(req.read()) or httpx.Response(200, json={"ok": True})))
    return sent, client


def test_secrets_in_errors_are_hidden_before_storing_and_sending(synced, monkeypatch):
    c = synced
    sent, client = _telegram(monkeypatch)
    notify.send(c, "job_failed", "Request failed",
                "GET https://x.test/v1?key=AIzaSyA1234567890abcdefghijk failed; Authorization: Bearer abcdefghijklmnop",
                dedupe_key="s1", client=client)
    row = db.one(c, "select body from notifications")
    assert "AIza" not in row["body"] and "abcdefghijklmnop" not in row["body"] and "[hidden]" in row["body"]
    assert b"AIza" not in sent[0] and b"abcdefghijklmnop" not in sent[0]


def test_routine_updates_can_stay_in_the_app_but_problems_always_go_out(synced, monkeypatch):
    c = synced
    sent, client = _telegram(monkeypatch)
    db.run(c, "insert into settings (key, value) values ('telegram_alerts', '\"important\"')")
    assert notify.send(c, "ideas_ready", "12 new ideas", dedupe_key="r1", client=client) is False
    assert notify.send(c, "publish_blocked", "Post blocked", "paused", dedupe_key="p1", client=client) is True
    assert len(sent) == 1
    routine = db.one(c, "select sent_at, error, delivery_attempts from notifications where dedupe_key='r1'")
    assert routine["sent_at"] is None and "routine updates are off" in routine["error"] and routine["delivery_attempts"] == notify.MAX_ATTEMPTS
    assert notify.retry_pending(c, client=client) == 0 and len(sent) == 1   # never retried
    db.run(c, "update settings set value='\"all\"' where key='telegram_alerts'")
    assert notify.send(c, "ideas_ready", "More ideas", dedupe_key="r2", client=client) is True


def test_identical_repeated_failures_are_sent_once(synced, monkeypatch):
    c = synced
    sent, client = _telegram(monkeypatch)
    for i in range(3):
        notify.send(c, "job_failed", "Request failed", "All providers failed for 'critic'", dedupe_key=f"jf{i}", client=client)
    assert len(sent) == 1
    assert db.one(c, "select count(*) n from notifications")["n"] == 3   # all three are still in the app
    notify.send(c, "job_failed", "Request failed", "A different problem", dedupe_key="jf-other", client=client)
    assert len(sent) == 2


def test_unconfigured_telegram_is_not_a_failure_and_work_continues(synced, monkeypatch):
    c = synced
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert notify.send(c, "package_ready", "Ready for review: Prompts", dedupe_key="u1") is False
    row = db.one(c, "select sent_at, error from notifications")
    assert row["sent_at"] is None and row["error"] == "telegram not configured"
