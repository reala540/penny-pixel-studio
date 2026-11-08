import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from studio import backup, db, website
from studio.script.verify import check_calculation
from studio.website import editorial, enhance, resources


@pytest.mark.parametrize("text,expression,expected", [
    ("The answer is $0.05 after adjusting $0.05 by 0.6%", "0.05/1.006-0.05", "contradicted"),
    ("The result is $0.02 from $0.05 minus $0.03", "0.05-0.03", "supported"),
    ("The result is $0.03 from $0.05 minus $0.03", "0.05-0.03", "unsupported"),
    ("A result of -$0.02 from $0.03 minus $0.05", "0.03-0.05", "supported"),
    ("A result of $0.02 from $0.03 minus $0.05", "0.03-0.05", "contradicted"),
    ("The nominal increase from $20 to $21 is 5%", "21/20-1", "supported"),
    ("The nominal increase from $20 to $21 is 0.05%", "21/20-1", "contradicted"),
])
def test_small_money_results_and_units(text, expression, expected):
    assert check_calculation(text, expression, {"0.05","0.03","1.006","20","21"})[0] == expected


def test_backup_authentication_and_large_stream(tmp_path):
    original, encrypted, restored = [tmp_path / n for n in ("source","backup.enc","restored")]
    original.write_bytes(b"private data" * 100000)
    key = bytes(range(32))
    backup.encrypt_file(original, encrypted, key)
    assert b"private data" not in encrypted.read_bytes()
    backup.decrypt_file(encrypted, restored, key)
    assert original.read_bytes() == restored.read_bytes()
    corrupted = bytearray(encrypted.read_bytes())
    corrupted[-20] ^= 1
    encrypted.write_bytes(corrupted)
    with pytest.raises(Exception):
        backup.decrypt_file(encrypted, restored, key)
    assert not restored.exists()


def test_editorial_example_and_resources_are_useful(tmp_path):
    assert editorial.example() == pytest.approx(2.94117647)
    summary = website.build([], tmp_path / "site", options={})
    assert (tmp_path / "site/tools/raise-inflation/index.html").exists()
    assert (tmp_path / "site/downloads/raise-inflation-worksheet.csv").exists()
    assert len(resources.pages()) == 5


def test_manual_posts_need_a_real_link(synced):
    # The insert trigger also protects direct Data API writes, not just the dashboard.
    with pytest.raises(Exception, match="public post URL"):
        db.run(synced, """insert into published_posts(scheduled_post_id,platform,url,visibility,method,social_account_id)
            values (gen_random_uuid(),'x',null,'public','manual',gen_random_uuid())""")


def test_youtube_records_returned_visibility(synced, tmp_path, monkeypatch):
    from studio.publish.adapters import YouTube
    monkeypatch.setattr("studio.publish.adapters._connected", lambda *a: True)
    captured = []
    def handler(req):
        if req.method == "POST":
            captured.append(json.loads(req.content))
            return httpx.Response(200, headers={"location":"https://upload.test/session"})
        if req.method == "PUT":
            return httpx.Response(200, json={"id":"video123","status":{"privacyStatus":"private"}})
        return httpx.Response(200, json={"items":[{"status":{"privacyStatus":"private"}}]})
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"sample")
    out = YouTube(httpx.Client(transport=httpx.MockTransport(handler))).publish(
        synced, {}, {"title":"Checked title","body":"Checked text"}, video, None, "test-token")
    assert captured[0]["status"]["privacyStatus"] == "public"
    assert out.visibility == "private" and out.method == "api_draft" and out.manual_followup


def test_rewrite_with_changed_meaning_is_rejected(tmp_path):
    from studio.storage import LocalStorage
    class Router:
        def complete(self, role, prompt, schema, **kw):
            if schema is enhance.MeaningReview:
                return SimpleNamespace(data=enhance.MeaningReview(faithful=False, issues=["Changed causation"]))
            return SimpleNamespace(data=enhance.Draft(intro="Prices rose because of wages.", sections=[]))
    got = enhance.enhance(Router(), LocalStorage(tmp_path / "store"), "version", "Prices", "money",
        [("p", "Prices rose alongside changes in wages.")], tmp_path / "work", german=False)
    assert got["en"] is None and "meaning check failed" in got["en_note"]


def test_article_approval_does_not_wait_for_video_and_slug_survives_title_change(synced, tmp_path, monkeypatch):
    from studio import preflight, produce
    from studio.storage import LocalStorage
    p = produce.ensure_project(synced, "ai", "long", "Original title", datetime.now().date())
    body = {"title":"Original title", "hook":"", "scenes":[{"narration":"A checked source explains this workflow.","visual":{}}]}
    sv = produce.save_script(synced, p["id"], body, "ai", [])
    db.run(synced, "update content_projects set status='ready_for_review' where id=%s", (p["id"],))
    monkeypatch.setattr(website, "why_left_out", lambda *a: None)
    monkeypatch.setattr(website, "_options", lambda: {"ai_rewrite":False})
    monkeypatch.setattr(preflight, "check", lambda *a, **kw: [])
    monkeypatch.setattr(enhance, "check_meaning", lambda *a, **kw: enhance.MeaningReview(faithful=True))
    monkeypatch.setattr(website, "_image", lambda *a: None)
    storage = LocalStorage(tmp_path / "storage")
    first, skipped = website.collect(synced, storage, tmp_path / "first", router=object())
    assert len(first) == 1 and not skipped and first[0].video_id is None
    assert db.one(synced,"select count(*) n from published_posts")["n"] == 0
    body["title"] = "A clearer title"
    produce.save_script(synced, p["id"], body, "ai", [])
    second, skipped = website.collect(synced, storage, tmp_path / "second", router=object())
    assert not skipped and second[0].slug == first[0].slug
    assert second[0].title == "A clearer title"
    assert second[0].modified >= first[0].modified


def test_failed_meaning_review_cannot_publish_an_article(synced, tmp_path, monkeypatch):
    from studio import preflight, produce
    from studio.storage import LocalStorage
    p = produce.ensure_project(synced,"ai","long","Title",datetime.now().date())
    produce.save_script(synced,p["id"],{"title":"Title","scenes":[]},"ai",[])
    db.run(synced,"update content_projects set status='ready_for_review' where id=%s",(p["id"],))
    monkeypatch.setattr(website,"why_left_out",lambda *a:None)
    monkeypatch.setattr(website,"_options",lambda:{"ai_rewrite":False})
    monkeypatch.setattr(preflight,"check",lambda *a,**kw:[])
    monkeypatch.setattr(enhance,"check_meaning",lambda *a,**kw:enhance.MeaningReview(faithful=False,issues=["Unsupported statement"]))
    articles, skipped = website.collect(synced,LocalStorage(tmp_path/"storage"),tmp_path/"work",router=object())
    assert not articles and "independent review" in skipped[0]
    assert db.one(synced,"select count(*) n from website_articles")["n"] == 0


def test_backup_preserves_storage_objects_and_manifest(synced, tmp_path, monkeypatch):
    import hashlib
    import tarfile
    from contextlib import nullcontext
    from studio.storage import LocalStorage
    store = LocalStorage(tmp_path / "store")
    original = tmp_path / "sample"
    original.write_bytes(b"A private media object")
    store.upload("nested/sample.txt", original)
    db.run(synced,"insert into storage.objects(bucket_id,name) values ('studio','nested/sample.txt')")
    monkeypatch.setattr(backup,"default_storage",lambda:store)
    monkeypatch.setattr(backup.config,"runtime",lambda:SimpleNamespace(require_db=lambda:synced.info.dsn))
    monkeypatch.setattr(backup.oauth,"_key",lambda:bytes(range(32)))
    monkeypatch.setattr(backup.db,"connect",lambda _:nullcontext(synced))
    def dump(args, **kwargs):
        Path(args[args.index("--file")+1]).write_bytes(b"database dump")
    monkeypatch.setattr(backup.subprocess,"run",dump)
    encrypted = tmp_path / "backup.enc"
    assert backup.export(encrypted)["objects"] == 1
    decrypted = tmp_path / "backup.tar"
    backup.decrypt_file(encrypted,decrypted,bytes(range(32)))
    with tarfile.open(decrypted) as tar:
        manifest = json.load(tar.extractfile("manifest.json"))
        item = manifest["objects"][0]
        restored = tar.extractfile(item["file"]).read()
        assert restored == original.read_bytes()
        assert hashlib.sha256(restored).hexdigest() == item["sha256"]
        assert item["name"] == "nested/sample.txt"


@pytest.mark.parametrize("receipt", [[], None, {}, {"status": "malformed"}])
def test_youtube_missing_receipt_never_retries_upload(tmp_path, receipt):
    from studio.errors import AmbiguousPublish
    from studio.publish.adapters import YouTube
    def handler(req):
        if req.method == "POST":
            return httpx.Response(200, headers={"location":"https://upload.test/session"})
        return httpx.Response(200, content=json.dumps(receipt).encode(), headers={"content-type":"application/json"})
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"sample")
    with pytest.raises(AmbiguousPublish):
        YouTube(httpx.Client(transport=httpx.MockTransport(handler))).publish(
            None, {}, {"title":"Checked title"}, video, None, "test-token")
