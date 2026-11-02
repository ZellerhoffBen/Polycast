import hashlib
import secrets
from datetime import UTC, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy.exc import IntegrityError

from polycast import database
from polycast.database import LoginSession, User, now
from polycast.schemas import fail

passwords = PasswordHasher()


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def find_session(db, token):
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return database.find_session(db, token_hash)


def validate_session(db, token):
    if not token:
        fail(401, "login_required", "Bitte anmelden.")
    session = find_session(db, token)
    if session is None:
        fail(401, "login_required", "Bitte erneut anmelden.")
    if now() - utc(session.last_activity_at) >= timedelta(minutes=30):
        db.delete(session)
        db.commit()
        fail(
            401, "session_expired", "Die Sitzung ist abgelaufen. Bitte erneut anmelden."
        )
    session.last_activity_at = now()
    db.add(session)
    db.commit()
    return session


def register(data, db):
    user = User(email=data.email, password_hash=passwords.hash(data.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail(409, "email_exists", "Diese E-Mail-Adresse ist bereits registriert.")
    return {"id": user.id, "email": user.email}


def login(data, db):
    user = database.find_user(db, data.email)
    if user is None:
        fail(401, "invalid_login", "E-Mail oder Passwort ist falsch.")
    if user.locked_until and utc(user.locked_until) > now():
        fail(
            429,
            "account_locked",
            "Nach fünf Fehlversuchen ist die Anmeldung für 15 Minuten gesperrt.",
        )
    if user.locked_until:
        user.failed_login_attempts = 0
        user.locked_until = None
    try:
        passwords.verify(user.password_hash, data.password)
    except VerifyMismatchError:
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= 5:
            user.locked_until = now() + timedelta(minutes=15)
        db.add(user)
        db.commit()
        fail(401, "invalid_login", "E-Mail oder Passwort ist falsch.")
    user.failed_login_attempts = 0
    user.locked_until = None
    # The browser gets the token; the database only keeps its hash.
    token = secrets.token_urlsafe(32)
    db.add(user)
    db.add(
        LoginSession(
            user_id=user.id, token_hash=hashlib.sha256(token.encode()).hexdigest()
        )
    )
    db.commit()
    return {"token": token, "user": {"id": user.id, "email": user.email}}


def logout(db, session):
    db.delete(session)
    db.commit()
