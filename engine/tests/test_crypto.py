from studio import oauth

# Produced by worker/src/crypto.ts encryptJson(KEY, {"access_token": "from-worker"})
TS_BLOB = "F077tq1SMKrKtPosQUOlRuUze6GGXohy9t5ld2ccJ7qKNqSUKi3GyY4Hsm0wy0pQC99mxpMSGTjEow=="


def test_decrypts_tokens_encrypted_by_worker(monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=")
    assert oauth.decrypt(TS_BLOB) == {"access_token": "from-worker"}


def test_round_trip(monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=")
    assert oauth.decrypt(oauth.encrypt({"a": 1})) == {"a": 1}
