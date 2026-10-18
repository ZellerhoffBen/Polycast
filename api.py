import hashlib
import http.client
import re
import secrets
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, timedelta
from threading import Lock
from typing import Annotated, Literal
from uuid import UUID

import requests
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, FastAPI, Form, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import Session, SQLModel, select

from database import AudioFile, Content, LoginSession, User, engine, get_db, now
from services import process_article
from services.scrape_article import scrape_article


@asynccontextmanager
async def lifespan(app):
    SQLModel.metadata.create_all(engine)
    yield


app = FastAPI(title="Polycast", lifespan=lifespan)
passwords = PasswordHasher()
bearer = HTTPBearer(auto_error=False)
DB = Annotated[Session, Depends(get_db)]
generation_lock = Lock()


def fail(status, code, message):
    raise HTTPException(status, detail={"code": code, "message": message})


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


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


@app.exception_handler(SQLAlchemyError)
async def database_error(request, error):
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "database_unavailable",
                "message": "Die Datenbank ist gerade nicht erreichbar. Bitte erneut versuchen.",
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


Language = Literal["de", "fr", "en", "pt", "uk", "es"]
ArticleText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
]


class ArticleLink(BaseModel):
    url: HttpUrl = Field(max_length=2048)


class TextRequest(BaseModel):
    original_text: ArticleText
    output_language: Language
    mode: Literal["simplify", "translate_only"]
    target_level: Literal["A2", "B1", "B2"] | None = None

    @model_validator(mode="after")
    def check_level(self):
        if (self.mode == "simplify") != (self.target_level is not None):
            raise ValueError(
                "Nur für die Vereinfachung ist ein Sprachniveau erforderlich."
            )
        return self


class ContentRequest(TextRequest):
    input_language: Language
    output_text: ArticleText
    source_url: HttpUrl | None = Field(default=None, max_length=2048)


class AudioRequest(BaseModel):
    output_text: ArticleText
    output_language: Language


@contextmanager
def generating():
    if not generation_lock.acquire(blocking=False):
        fail(
            409,
            "generation_busy",
            "Es läuft bereits eine Generierung. Bitte kurz warten.",
        )
    try:
        yield
    except requests.Timeout:
        fail(
            504,
            "provider_timeout",
            "Der KI-Dienst hat zu lange gebraucht. Bitte erneut versuchen.",
        )
    except requests.RequestException:
        fail(
            502,
            "provider_error",
            "Der KI-Dienst ist nicht verfügbar. Bitte API-Key, Guthaben und Modellzugriff prüfen.",
        )
    except ValueError as error:
        fail(502, "invalid_result", str(error))
    except (KeyError, IndexError, TypeError):
        fail(
            502, "invalid_result", "Der KI-Dienst hat eine ungültige Antwort geliefert."
        )
    finally:
        generation_lock.release()


@app.post("/articles/extract")
def extract_article(data: ArticleLink, auth: Auth):
    try:
        text = scrape_article(str(data.url))
    except ValueError as error:
        fail(422, "invalid_article", str(error))
    except TimeoutError:
        fail(
            504,
            "article_timeout",
            "Die Webseite hat zu lange gebraucht. Bitte den Text direkt einfügen.",
        )
    except (OSError, http.client.HTTPException):
        fail(
            502,
            "article_unavailable",
            "Die Webseite konnte nicht geladen werden. Bitte den Text direkt einfügen.",
        )
    return {"original_text": text, "source_url": str(data.url)}


@app.post("/texts/adapt")
def adapt_text(data: TextRequest, auth: Auth):
    with generating():
        result = process_article.adapt_text(
            data.original_text, data.output_language, data.target_level
        )
    return {
        **result,
        "output_language": data.output_language,
        "mode": data.mode,
        "target_level": data.target_level,
    }


@app.post("/audio/generate")
def generate_audio(data: AudioRequest, auth: Auth):
    with generating():
        audio = process_article.generate_audio(data.output_text, data.output_language)
    return Response(audio, media_type="audio/mpeg")


def read_audio(audio):
    try:
        return process_article.validate_audio(
            audio.file.read(process_article.MAX_AUDIO_BYTES + 1)
        )
    except ValueError as error:
        fail(422, "invalid_audio", str(error))


def owned_content(content_id, db, auth):
    content = db.get(Content, content_id)
    if content is None or content.user_id != auth.user_id:
        fail(404, "not_found", "Dieser Eintrag wurde nicht gefunden.")
    return content


@app.post("/contents", status_code=201)
def save_content(
    db: DB,
    auth: Auth,
    metadata: Annotated[str, Form(max_length=150_000)],
    audio: UploadFile | None = None,
):
    try:
        data = ContentRequest.model_validate_json(metadata)
    except ValidationError:
        fail(422, "invalid_content", "Die Angaben zum Inhalt sind ungültig.")
    mp3 = read_audio(audio) if audio else None
    content = Content(user_id=auth.user_id, **data.model_dump(mode="json"))
    db.add(content)
    db.flush()
    if mp3:
        db.add(
            AudioFile(
                content_id=content.id,
                mp3_data=mp3,
                filename=f"polycast-{content.id}.mp3",
            )
        )
    db.commit()
    return {"id": content.id, "has_audio": mp3 is not None}


@app.get("/contents")
def list_contents(db: DB, auth: Auth):
    rows = db.exec(
        select(Content, AudioFile.id)
        .outerjoin(AudioFile, AudioFile.content_id == Content.id)
        .where(Content.user_id == auth.user_id)
        .order_by(Content.created_at.desc())
    ).all()
    return [
        {
            "id": content.id,
            "preview": content.original_text[:100],
            "input_language": content.input_language,
            "output_language": content.output_language,
            "mode": content.mode,
            "target_level": content.target_level,
            "created_at": content.created_at,
            "has_audio": audio_id is not None,
        }
        for content, audio_id in rows
    ]


@app.get("/contents/{content_id}")
def get_content(content_id: UUID, db: DB, auth: Auth):
    content = owned_content(content_id, db, auth)
    audio_id = db.exec(
        select(AudioFile.id).where(AudioFile.content_id == content.id)
    ).first()
    return {
        **content.model_dump(exclude={"user_id"}),
        "has_audio": audio_id is not None,
    }


@app.get("/contents/{content_id}/audio")
def get_audio(content_id: UUID, db: DB, auth: Auth):
    owned_content(content_id, db, auth)
    audio = db.exec(select(AudioFile).where(AudioFile.content_id == content_id)).first()
    if audio is None:
        fail(404, "no_audio", "Für diesen Eintrag ist noch kein Audio gespeichert.")
    return Response(
        audio.mp3_data,
        media_type="audio/mpeg",
        headers={"Content-Disposition": f'attachment; filename="{audio.filename}"'},
    )


@app.put("/contents/{content_id}/audio")
def save_audio(content_id: UUID, db: DB, auth: Auth, audio: UploadFile):
    owned_content(content_id, db, auth)
    mp3 = read_audio(audio)
    saved_audio = db.exec(
        select(AudioFile).where(AudioFile.content_id == content_id)
    ).first()
    if saved_audio:
        fail(409, "audio_exists", "Für diesen Eintrag ist bereits Audio gespeichert.")
    db.add(
        AudioFile(
            content_id=content_id, mp3_data=mp3, filename=f"polycast-{content_id}.mp3"
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail(409, "audio_exists", "Für diesen Eintrag ist bereits Audio gespeichert.")
    return {"id": content_id, "has_audio": True}
