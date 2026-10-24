from studio.db import candidate_urls


def test_direct_address_tries_session_pooler_first():
    url = "postgresql://postgres:pa55word@db.eazmczmnunzrmrpsrhvx.supabase.co:5432/postgres"
    got = candidate_urls(url, "eu-central-1")
    assert got[:2] == [
        "postgresql://postgres.eazmczmnunzrmrpsrhvx:pa55word@aws-0-eu-central-1.pooler.supabase.com:5432/postgres",
        "postgresql://postgres.eazmczmnunzrmrpsrhvx:pa55word@aws-1-eu-central-1.pooler.supabase.com:5432/postgres",
    ]
    assert got[-1] == url


def test_pooler_and_other_addresses_are_left_alone():
    pooled = "postgresql://postgres.abc:pw@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
    assert candidate_urls(pooled, "eu-central-1") == [pooled]
    assert candidate_urls("postgresql://u:p@localhost/db", "eu-central-1") == ["postgresql://u:p@localhost/db"]
