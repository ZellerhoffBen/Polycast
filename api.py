import hashlib
import re
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, select

from database import LoginSession, User, engine, get_db, now


@asynccontextmanager
async def lifespan(app):
    SQLModel.metadata.create_all(engine)
    yield


app = FastAPI(title="Polycast", lifespan=lifespan)
passwords = PasswordHasher()
bearer = HTTPBearer(auto_error=False)
DB = Annotated[Session, Depends(get_db)]


def fail(status, code, message):
    raise HTTPException(status, detail={"code": code, "message": message})


@app.exception_handler(HTTPException)
async def http_error(request, error):
    return JSONResponse(status_code=error.status_code, content={"error": error.detail})


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_input",
                "message": "Bitte Eingaben prüfen: E-Mail, Text, Sprache und Sprachniveau müssen gültig sein.",
            }
        },
    )


class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, email):
        email = email.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise ValueError("Ungültige E-Mail-Adresse")
        return email


def current_session(
    db: DB, auth: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
):
    if auth is None:
        fail(401, "login_required", "Bitte anmelden.")
    token_hash = hashlib.sha256(auth.credentials.encode()).hexdigest()
    session = db.exec(
        select(LoginSession).where(LoginSession.token_hash == token_hash)
    ).first()
    if session is None:
        fail(401, "login_required", "Bitte erneut anmelden.")
    if now() - session.last_activity_at.replace(tzinfo=UTC) >= timedelta(minutes=30):
        db.delete(session)
        db.commit()
        fail(
            401, "session_expired", "Die Sitzung ist abgelaufen. Bitte erneut anmelden."
        )
    session.last_activity_at = now()
    db.add(session)
    db.commit()
    return session


Auth = Annotated[LoginSession, Depends(current_session)]


@app.post("/auth/register", status_code=201)
def register(data: Credentials, db: DB):
    user = User(email=data.email, password_hash=passwords.hash(data.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail(409, "email_exists", "Diese E-Mail-Adresse ist bereits registriert.")
    return {"id": user.id, "email": user.email}


@app.post("/auth/login")
def login(data: Credentials, db: DB):
    user = db.exec(
        select(User).where(User.email == data.email).with_for_update()
    ).first()
    if user is None:
        fail(401, "invalid_login", "E-Mail oder Passwort ist falsch.")
    if user.locked_until and user.locked_until.replace(tzinfo=UTC) > now():
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
    token = secrets.token_urlsafe(32)
    db.add(user)
    db.add(
        LoginSession(
            user_id=user.id, token_hash=hashlib.sha256(token.encode()).hexdigest()
        )
    )
    db.commit()
    return {"token": token, "user": {"id": user.id, "email": user.email}}


@app.post("/auth/logout", status_code=204)
def logout(db: DB, auth: Auth):
    db.delete(auth)
    db.commit()
