"""Encrypted database + Storage backup. Plaintext never enters workflow artifacts."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from psycopg.conninfo import conninfo_to_dict

from . import config, db, oauth
from .storage import default_storage

MAGIC = b"PENNY-BACKUP-1\n"


def encrypt_file(source, target, key):
    iv = os.urandom(12)
    enc = Cipher(algorithms.AES(key), modes.GCM(iv)).encryptor()
    with Path(source).open("rb") as src, Path(target).open("wb") as dst:
        dst.write(MAGIC + iv)
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            dst.write(enc.update(chunk))
        dst.write(enc.finalize())
        dst.write(enc.tag)


def decrypt_file(source, target, key):
    """Used for restore verification; failed authentication removes the partial file."""
    target = Path(target)
    try:
        with Path(source).open("rb") as src, target.open("wb") as dst:
            if src.read(len(MAGIC)) != MAGIC:
                raise ValueError("Unknown backup format")
            iv = src.read(12)
            src.seek(-16, 2)
            tag = src.read(16)
            end = src.tell() - 16
            src.seek(len(MAGIC) + 12)
            dec = Cipher(algorithms.AES(key), modes.GCM(iv, tag)).decryptor()
            while src.tell() < end:
                dst.write(dec.update(src.read(min(1024 * 1024, end - src.tell()))))
            dst.write(dec.finalize())
    except Exception:
        target.unlink(missing_ok=True)
        raise


def export(target):
    rt = config.runtime()
    key = oauth._key()  # validate before downloading or dumping anything
    storage = default_storage()
    with db.connect(rt.require_db()) as conn, tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        dump = work / "database.dump"
        # Connection info may redact the password. Keep the original secret,
        # but use the actual connected pooler host/user selected by db.connect.
        params = conninfo_to_dict(rt.require_db())
        params.update(conninfo_to_dict(conn.info.dsn))
        env = dict(os.environ)
        for k, name in {"host":"PGHOST","port":"PGPORT","user":"PGUSER","password":"PGPASSWORD","dbname":"PGDATABASE","sslmode":"PGSSLMODE"}.items():
            if k in params:
                env[name] = params[k]
        subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--schema=public",
                        "--schema=auth", "--schema=storage", "--schema=studio_meta", "--file", str(dump)],
                       env=env, check=True, capture_output=True)
        entries = []
        for i, obj in enumerate(db.all_(conn, "select bucket_id,name from storage.objects order by bucket_id,name")):
            if obj["bucket_id"] != "studio":
                raise ValueError("Backup needs an adapter for an unexpected storage bucket")
            # Use numbered local names; object keys can never escape the backup folder.
            local = storage.download(obj["name"], work / "objects" / str(i))
            digest = hashlib.sha256()
            with local.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    digest.update(chunk)
            entries.append({**obj, "file": f"objects/{i}", "sha256": digest.hexdigest(), "bytes": local.stat().st_size})
        (work / "manifest.json").write_text(json.dumps({"version":1,"objects":entries,
            "excludes":["managed platform settings","external service accounts","GitHub secrets"]}))
        archive = work / "snapshot.tar"
        with tarfile.open(archive, "w") as tar:
            for f in [dump, work / "manifest.json", *sorted((work / "objects").glob("*") if (work / "objects").exists() else [])]:
                tar.add(f, arcname=str(f.relative_to(work)))
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        encrypt_file(archive, target, key)
    return {"objects":len(entries),"encrypted":True}


if __name__ == "__main__":
    import sys
    print(json.dumps(export(sys.argv[1])))
