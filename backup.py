"""Encrypted daily backup. Run manually on development days."""

import os
import subprocess
from datetime import datetime, timedelta
from getpass import getpass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url


def backup():
    load_dotenv()
    url = make_url(os.environ["DATABASE_URL"])
    password = os.environ.get("BACKUP_PASSWORD") or getpass("Backup-Passwort: ")
    if not password:
        raise ValueError("Das Backup-Passwort darf nicht leer sein.")
    environment = {
        **os.environ,
        "PGHOST": str(url.query.get("host", url.host or "127.0.0.1")),
        "PGPORT": str(url.query.get("port", url.port or 5432)),
        "PGUSER": url.username or "polycast",
        "PGPASSWORD": url.password or "",
        "PGDATABASE": url.database,
        "BACKUP_PASSWORD": password,
    }
    dump = subprocess.run(
        ["pg_dump", "--format=custom", "--no-acl"],
        env=environment,
        capture_output=True,
        check=True,
    )
    encrypted = subprocess.run(
        [
            "openssl",
            "enc",
            "-aes-256-cbc",
            "-salt",
            "-pbkdf2",
            "-iter",
            "200000",
            "-pass",
            "env:BACKUP_PASSWORD",
        ],
        input=dump.stdout,
        env=environment,
        capture_output=True,
        check=True,
    )
    directory = Path("backups")
    directory.mkdir(mode=0o700, exist_ok=True)
    destination = directory / f"polycast-{datetime.now():%Y-%m-%d}.dump.enc"
    temporary = destination.with_suffix(".tmp")
    temporary.write_bytes(encrypted.stdout)
    temporary.chmod(0o600)
    temporary.replace(destination)
    cutoff = (datetime.now() - timedelta(days=7)).timestamp()
    for old_backup in directory.glob("polycast-*.dump.enc"):
        if old_backup.stat().st_mtime < cutoff:
            old_backup.unlink()
    print(f"Backup erstellt: {destination}")


if __name__ == "__main__":
    try:
        backup()
    except (
        KeyError,
        ValueError,
        FileNotFoundError,
        subprocess.CalledProcessError,
    ):
        raise SystemExit(
            "Backup fehlgeschlagen. DATABASE_URL, Passwort sowie pg_dump und OpenSSL prüfen."
        ) from None
