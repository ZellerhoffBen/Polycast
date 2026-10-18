import json
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from database import AudioFile, Content

CONTENT = {
    "original_text": "Die Schule öffnet am Montag.",
    "output_text": "The school opens on Monday.",
    "source_url": None,
    "input_language": "de",
    "output_language": "en",
    "mode": "simplify",
    "target_level": "A2",
}
AUDIO = Path(__file__).with_name("fixtures").joinpath("silence.mp3").read_bytes()


def save(client, auth, audio=None):
    files = {"metadata": (None, json.dumps(CONTENT))}
    if audio is not None:
        files["audio"] = ("test.mp3", audio, "audio/mpeg")
    return client.post("/contents", headers=auth, files=files)


def test_save_audio_and_reload_after_login(client, auth):
    first = save(client, auth, AUDIO)
    assert first.status_code == 201
    content_id = first.json()["id"]
    second = save(client, auth).json()["id"]
    client.post("/auth/logout", headers=auth)
    token = client.post(
        "/auth/login", json={"email": "ben@example.com", "password": "school-project"}
    ).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    history = client.get("/contents", headers=auth).json()
    assert [item["id"] for item in history] == [second, content_id]
    assert "mp3_data" not in history[1]
    detail = client.get(f"/contents/{content_id}", headers=auth).json()
    assert all(detail[key] == value for key, value in CONTENT.items())
    assert detail["has_audio"] is True
    response = client.get(f"/contents/{content_id}/audio", headers=auth)
    assert response.content == AUDIO
    assert response.headers["content-type"] == "audio/mpeg"


def test_other_user_cannot_access_or_attach_audio(client, auth):
    content_id = save(client, auth, AUDIO).json()["id"]
    credentials = {"email": "other@example.com", "password": "another-password"}
    client.post("/auth/register", json=credentials)
    token = client.post("/auth/login", json=credentials).json()["token"]
    other = {"Authorization": f"Bearer {token}"}
    assert client.get("/contents", headers=other).json() == []
    assert client.get(f"/contents/{content_id}", headers=other).status_code == 404
    assert client.get(f"/contents/{content_id}/audio", headers=other).status_code == 404
    assert (
        client.put(
            f"/contents/{content_id}/audio",
            headers=other,
            files={"audio": ("test.mp3", AUDIO)},
        ).status_code
        == 404
    )
    assert client.get(f"/contents/{content_id}/audio").status_code == 401


def test_add_audio_later_without_creating_another_content(client, auth, db_engine):
    content_id = save(client, auth).json()["id"]
    assert client.get(f"/contents/{content_id}/audio", headers=auth).status_code == 404
    path = f"/contents/{content_id}/audio"
    assert (
        client.put(
            path, headers=auth, files={"audio": ("bad.mp3", b"not audio")}
        ).status_code
        == 422
    )
    assert not client.get(f"/contents/{content_id}", headers=auth).json()["has_audio"]
    assert (
        client.put(path, headers=auth, files={"audio": ("test.mp3", AUDIO)}).status_code
        == 200
    )
    assert (
        client.put(path, headers=auth, files={"audio": ("test.mp3", AUDIO)}).status_code
        == 409
    )
    with Session(db_engine) as db:
        assert len(db.exec(select(Content)).all()) == 1
        assert len(db.exec(select(AudioFile)).all()) == 1


def test_failed_audio_save_rolls_back_entire_content(client, auth, db_engine):
    def reject_audio(connection, cursor, statement, parameters, context, many):
        if statement.lower().startswith("insert into audio_files"):
            raise SQLAlchemyError("Simulated database failure")

    event.listen(db_engine, "before_cursor_execute", reject_audio)
    try:
        assert save(client, auth, AUDIO).status_code == 503
    finally:
        event.remove(db_engine, "before_cursor_execute", reject_audio)
    assert client.get("/contents", headers=auth).json() == []


def test_reject_invalid_metadata_and_audio(client, auth):
    assert save(client, auth, b"ID3broken").status_code == 422
    response = client.post(
        "/contents",
        headers=auth,
        files={"metadata": (None, json.dumps({**CONTENT, "mode": "translate_only"}))},
    )
    assert response.status_code == 422
    assert client.get("/contents", headers=auth).json() == []
