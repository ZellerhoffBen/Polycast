import http.client
from contextlib import asynccontextmanager, contextmanager
from threading import Lock
from typing import Annotated, Literal
from uuid import UUID

import requests
from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, SQLModel

from polycast.auth_forms import API_URL, APP_URL, COOKIE_NAME, auth_page
from polycast.backup import cleanup
from polycast.database import LoginSession, User, engine, get_db
from polycast.schemas import (
    ArticleLink,
    AudioRequest,
    ContentRequest,
    Credentials,
    Registration,
    TextRequest,
    fail,
)
from polycast.services import audio, auth, contents, text
from polycast.services.scrape_article import scrape_article


@asynccontextmanager
async def lifespan(app):
    cleanup()
    SQLModel.metadata.create_all(engine)
    yield


app = FastAPI(title="Polycast", lifespan=lifespan)
DB = Annotated[Session, Depends(get_db)]
bearer = HTTPBearer(auto_error=False)
generation_lock = Lock()


def current_session(
    db: DB, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
):
    return auth.validate_session(db, credentials.credentials if credentials else None)


Auth = Annotated[LoginSession, Depends(current_session)]


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
                "message": "Bitte Eingaben prüfen: E-Mail, Passwort und Bestätigung, Text, Sprache und Niveau müssen gültig sein.",
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


@app.post("/auth/register", status_code=201)
def register(data: Registration, db: DB):
    return auth.register(data, db)


@app.post("/auth/login")
def login(data: Credentials, db: DB):
    return auth.login(data, db)


@app.post("/auth/logout", status_code=204)
def logout(db: DB, session: Auth):
    auth.logout(db, session)


@app.get("/auth/me")
def me(db: DB, session: Auth):
    user = db.get(User, session.user_id)
    return {"id": user.id, "email": user.email}


@app.post("/auth/browser/{action}")
def browser_auth(
    action: Literal["login", "register", "logout"],
    request: Request,
    db: DB,
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    password_confirmation: Annotated[str, Form()] = "",
):
    # These forms run in the browser, unlike Streamlit's server-side API calls.
    if request.headers.get("origin") not in (APP_URL, API_URL):
        fail(403, "invalid_origin", "Bitte das Formular in Polycast verwenden.")
    try:
        if action == "logout":
            session = auth.find_session(db, request.cookies.get(COOKIE_NAME))
            if session:
                auth.logout(db, session)
            response = RedirectResponse(APP_URL, status_code=303)
            response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")
            return response
        if action == "register":
            data = Registration(
                email=email,
                password=password,
                password_confirmation=password_confirmation,
            )
            auth.register(data, db)
            return auth_page("login", "Konto erstellt. Bitte jetzt anmelden.", 201)
        result = auth.login(Credentials(email=email, password=password), db)
        response = RedirectResponse(APP_URL, status_code=303)
        response.set_cookie(
            COOKIE_NAME,
            result["token"],
            httponly=True,
            samesite="lax",
            path="/",
            secure=request.url.scheme == "https",
        )
        return response
    except ValidationError:
        return auth_page(
            action,
            "Bitte eine gültige E-Mail eingeben. Bei Registrierung: mindestens 8 Zeichen und zwei gleiche Passwörter.",
            422,
        )
    except HTTPException as error:
        return auth_page(action, error.detail["message"], error.status_code)
    except SQLAlchemyError:
        return auth_page(
            action,
            "Die Datenbank ist gerade nicht erreichbar. Bitte erneut versuchen.",
            503,
        )


@contextmanager
def generating():
    # One generation at a time; always release the lock if the provider fails.
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
    except (KeyError, IndexError, TypeError, AttributeError):
        fail(
            502, "invalid_result", "Der KI-Dienst hat eine ungültige Antwort geliefert."
        )
    finally:
        generation_lock.release()


# Load an article for the user to check before sending it to the AI.
@app.post("/articles/extract")
def extract_article(data: ArticleLink, session: Auth):
    try:
        original = scrape_article(str(data.url))
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
    return {"original_text": original, "source_url": str(data.url)}


@app.post("/texts/adapt")
def adapt_text(data: TextRequest, session: Auth):
    with generating():
        result = text.adapt_text(
            data.original_text, data.output_language, data.target_level
        )
    return {
        **result,
        "output_language": data.output_language,
        "mode": data.mode,
        "target_level": data.target_level,
    }


@app.post("/audio/generate")
def generate_audio(data: AudioRequest, session: Auth):
    with generating():
        mp3 = audio.generate_audio(data.output_text, data.output_language)
    return Response(mp3, media_type="audio/mpeg")


def read_audio(upload):
    try:
        return audio.validate_audio(upload.file.read(audio.MAX_AUDIO_BYTES + 1))
    except ValueError as error:
        fail(422, "invalid_audio", str(error))


@app.post("/contents", status_code=201)
def save_content(
    db: DB,
    session: Auth,
    metadata: Annotated[str, Form(max_length=150_000)],
    audio: UploadFile | None = None,
):
    try:
        data = ContentRequest.model_validate_json(metadata)
    except ValidationError:
        fail(422, "invalid_content", "Die Angaben zum Inhalt sind ungültig.")
    return contents.save_content(
        db, session.user_id, data, read_audio(audio) if audio else None
    )


@app.get("/contents")
def list_contents(db: DB, session: Auth):
    return contents.list_contents(db, session.user_id)


@app.get("/contents/{content_id}")
def get_content(content_id: UUID, db: DB, session: Auth):
    return contents.get_content(content_id, db, session.user_id)


@app.get("/contents/{content_id}/audio")
def get_audio(content_id: UUID, db: DB, session: Auth):
    saved = contents.get_audio(content_id, db, session.user_id)
    return Response(
        saved.mp3_data,
        media_type="audio/mpeg",
        headers={"Content-Disposition": f'attachment; filename="{saved.filename}"'},
    )


@app.put("/contents/{content_id}/audio")
def save_audio(content_id: UUID, db: DB, session: Auth, audio: UploadFile):
    content = contents.owned_content(content_id, db, session.user_id)
    return contents.save_audio(db, content, read_audio(audio))
