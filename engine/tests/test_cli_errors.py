import psycopg

from studio.cli import explain_error


def test_hides_password_and_explains_wrong_password():
    e = psycopg.OperationalError(
        'connection to server at "aws-0-eu-central-1.pooler.supabase.com" failed: FATAL: password authentication '
        "failed for user postgres.abc (postgresql://postgres.abc:Sup3rS3cret@aws-0-eu-central-1.pooler.supabase.com:5432/postgres)")
    msg = explain_error(e)
    assert "Sup3rS3cret" not in msg
    assert "password in SUPABASE_DB_URL is wrong" in msg


def test_missing_url_message_passes_through():
    assert "SUPABASE_DB_URL is not set" in explain_error(SystemExit("SUPABASE_DB_URL is not set. See GUIDE.md step 4."))


def test_direct_address_unreachable():
    msg = explain_error(psycopg.OperationalError("connection failed: Network is unreachable"))
    assert "Session pooler" in msg
