"""TC-01 to TC-07: technical checks. Real browser and language checks are listed in README.md."""

import json
import socket
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from polycast.auth_forms import APP_URL, COOKIE_NAME
from polycast.database import Content, LoginSession, User, now
from polycast.services import audio, openrouter, scrape_article
from polycast.services import auth as accounts

CREDENTIALS = {"email": "ben@example.com", "password": "school-project"}
CONTENT = {
    "original_text": "Die Schule öffnet am Montag.",
    "output_text": "L'école ouvre lundi.",
    "source_url": None,
    "input_language": "de",
    "output_language": "fr",
    "mode": "simplify",
    "target_level": "A2",
}
AUDIO = Path(__file__).with_name("fixtures").joinpath("silence.mp3").read_bytes()


def text_response(content):
    return SimpleNamespace(
        json=lambda: {
            "choices": [{"finish_reason": "stop", "message": {"content": content}}]
        }
    )


def save(client, headers, content=CONTENT, audio=None):
    files = {"metadata": (None, json.dumps(content))}
    if audio is not None:
        files["audio"] = ("test.mp3", audio, "audio/mpeg")
    return client.post("/contents", headers=headers, files=files)


def other_user(client):
    credentials = {"email": "other@example.com", "password": "school-project"}
    response = client.post(
        "/auth/register",
        json={**credentials, "password_confirmation": credentials["password"]},
    )
    user_id = UUID(response.json()["id"])
    token = client.post("/auth/login", json=credentials).json()["token"]
    return user_id, {"Authorization": f"Bearer {token}"}


def test_tc01_registration_login_logout(client, db_engine, monkeypatch):
    origin = {"Origin": APP_URL}
    registration = {**CREDENTIALS, "password_confirmation": "different"}
    assert (
        client.post(
            "/auth/browser/register", data=registration, headers=origin
        ).status_code
        == 422
    )
    registration["password_confirmation"] = CREDENTIALS["password"]
    response = client.post("/auth/browser/register", data=registration, headers=origin)
    assert response.status_code == 201
    assert "Bitte jetzt anmelden" in response.text
    assert COOKIE_NAME not in client.cookies
    with Session(db_engine) as db:
        assert db.exec(select(LoginSession)).all() == []
        assert db.exec(select(User)).one().password_hash.startswith("$argon2id$")
    assert client.post("/auth/register", json=registration).status_code == 409
    assert client.get("/contents").status_code == 401
    assert (
        client.post(
            "/auth/browser/login",
            data=CREDENTIALS,
            headers={"Origin": "https://other.example"},
        ).status_code
        == 403
    )
    response = client.post(
        "/auth/browser/login", data=CREDENTIALS, headers=origin, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == APP_URL
    cookie = response.headers["set-cookie"]
    assert all(flag in cookie for flag in ("HttpOnly", "SameSite=lax", "Path=/"))
    token = client.cookies[COOKIE_NAME]
    headers = {"Authorization": f"Bearer {token}"}
    assert (
        client.get("/auth/me", headers=headers).json()["email"] == CREDENTIALS["email"]
    )
    with Session(db_engine) as db:
        assert db.exec(select(LoginSession)).one().token_hash != token
    response = client.post(
        "/auth/browser/logout", headers=origin, follow_redirects=False
    )
    assert response.status_code == 303
    assert COOKIE_NAME not in client.cookies
    assert client.get("/contents", headers=headers).status_code == 401
    # IS-03: exactly 30 minutes after the last authenticated request.
    instant = now()
    monkeypatch.setattr(accounts, "now", lambda: instant)
    token = client.post("/auth/login", json=CREDENTIALS).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/auth/me", headers=headers).status_code == 200
    monkeypatch.setattr(accounts, "now", lambda: instant + timedelta(minutes=30))
    assert (
        client.get("/auth/me", headers=headers).json()["error"]["code"]
        == "session_expired"
    )


def test_tc02_five_failed_logins_lock_for_15_minutes(client, auth, monkeypatch):
    instant = now()
    monkeypatch.setattr(accounts, "now", lambda: instant)
    for _ in range(5):
        assert (
            client.post(
                "/auth/login", json={**CREDENTIALS, "password": "x"}
            ).status_code
            == 401
        )
    assert client.post("/auth/login", json=CREDENTIALS).status_code == 429
    monkeypatch.setattr(
        accounts, "now", lambda: instant + timedelta(minutes=15) - timedelta(seconds=1)
    )
    assert client.post("/auth/login", json=CREDENTIALS).status_code == 429
    monkeypatch.setattr(accounts, "now", lambda: instant + timedelta(minutes=15))
    assert client.post("/auth/login", json=CREDENTIALS).status_code == 200


@pytest.mark.parametrize("level", ["A1", "A2", "B1", "B2", "C1", "C2"])
def test_tc03_article_to_french(client, auth, monkeypatch, level):
    html = b"<nav>Menu</nav><article><p>Die Schule oeffnet am Montag.</p><aside>Werbung</aside></article>"
    response = SimpleNamespace(
        status=200, getheader=lambda *args: "text/html", read=lambda size: html
    )
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 80))],
    )
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        scrape_article.http.client,
        "HTTPConnection",
        lambda *args, **kwargs: SimpleNamespace(
            request=lambda *args, **kwargs: None,
            getresponse=lambda: response,
            close=lambda: None,
        ),
    )
    article = client.post(
        "/articles/extract", headers=auth, json={"url": "http://example.test/article"}
    )
    assert article.status_code == 200
    assert article.json()["original_text"] == "Die Schule oeffnet am Montag."

    def provider(endpoint, payload):
        assert endpoint == "chat/completions"
        assert "fr" in payload["messages"][0]["content"]
        assert f"CEFR level {level}" in payload["messages"][0]["content"]
        return text_response(
            json.dumps({"input_language": "de", "output_text": CONTENT["output_text"]})
        )

    monkeypatch.setattr(openrouter, "request", provider)
    request = {
        **CONTENT,
        "original_text": article.json()["original_text"],
        "target_level": level,
    }
    result = client.post("/texts/adapt", headers=auth, json=request)
    assert result.status_code == 200
    assert result.json()["output_text"] == CONTENT["output_text"]
    assert client.get("/contents", headers=auth).json() == []
    saved = save(client, auth, content={**request, **result.json()})
    assert saved.status_code == 201
    history = client.get("/contents", headers=auth).json()
    assert history[0]["target_level"] == level
    # Malformed provider output must still return the agreed error JSON.
    monkeypatch.setattr(openrouter, "request", lambda *args: text_response("null"))
    failed = client.post("/texts/adapt", headers=auth, json=request)
    assert failed.status_code == 502
    assert failed.json()["error"]["message"]


def test_tc04_audio_download_and_atomic_save(client, auth, db_engine, monkeypatch):
    monkeypatch.setattr(
        openrouter,
        "request",
        lambda *args: SimpleNamespace(
            content=bytes(24000), headers={"Content-Type": "audio/pcm"}
        ),
    )
    generated = client.post(
        "/audio/generate",
        headers=auth,
        json={"output_text": CONTENT["output_text"], "output_language": "fr"},
    )
    assert generated.status_code == 200
    assert generated.headers["content-type"] == "audio/mpeg"
    assert audio.validate_audio(generated.content) == generated.content
    saved = save(client, auth, audio=generated.content)
    assert saved.status_code == 201
    downloaded = client.get(f"/contents/{saved.json()['id']}/audio", headers=auth)
    assert downloaded.content == generated.content
    assert ".mp3" in downloaded.headers["content-disposition"]

    def reject_audio(connection, cursor, statement, parameters, context, many):
        if statement.lower().startswith("insert into audio_files"):
            raise SQLAlchemyError("Simulated save failure")

    event.listen(db_engine, "before_cursor_execute", reject_audio)
    try:
        assert save(client, auth, audio=AUDIO).status_code == 503
    finally:
        event.remove(db_engine, "before_cursor_execute", reject_audio)
    assert len(client.get("/contents", headers=auth).json()) == 1


def test_tc05_history_and_second_user(client, auth):
    first = save(client, auth, audio=AUDIO).json()["id"]
    second = save(client, auth).json()["id"]
    assert (
        client.put(
            f"/contents/{second}/audio",
            headers=auth,
            files={"audio": ("test.mp3", AUDIO)},
        ).status_code
        == 200
    )
    client.post("/auth/logout", headers=auth)
    token = client.post("/auth/login", json=CREDENTIALS).json()["token"]
    history = client.get(
        "/contents", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert [item["id"] for item in history] == [second, first]
    assert all(item["has_audio"] and item["mode"] == "simplify" for item in history)
    _, other = other_user(client)
    assert client.get("/contents", headers=other).json() == []


def test_tc06_invalid_local_and_unreachable_urls(client, auth, monkeypatch):
    def resolve(host, *args, **kwargs):
        if host == "unreachable.example":
            raise socket.gaierror("No address")
        return [(None, None, None, None, ("127.0.0.1", 80))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    for url, status in [
        ("file:///etc/passwd", 422),
        ("http://127.0.0.1", 422),
        ("http://unreachable.example", 502),
    ]:
        response = client.post("/articles/extract", headers=auth, json={"url": url})
        assert response.status_code == status
        assert response.json()["error"]["message"]


def test_tc07_foreign_content_and_forged_owner(client, auth, db_engine):
    first = save(client, auth, audio=AUDIO).json()["id"]
    with Session(db_engine) as db:
        owner = str(db.exec(select(Content)).one().user_id)
    other_id, other = other_user(client)
    assert client.get(f"/contents/{first}", headers=other).status_code == 404
    assert client.get(f"/contents/{first}/audio", headers=other).status_code == 404
    assert (
        client.put(
            f"/contents/{first}/audio",
            headers=other,
            files={"audio": ("test.mp3", AUDIO)},
        ).status_code
        == 404
    )
    assert client.get(f"/contents/{first}/audio").status_code == 401
    forged = save(client, other, content={**CONTENT, "user_id": owner})
    assert forged.status_code == 201
    with Session(db_engine) as db:
        content = db.exec(select(Content).where(Content.user_id == other_id)).one()
        assert str(content.id) == forged.json()["id"]
    assert len(client.get("/contents", headers=auth).json()) == 1
