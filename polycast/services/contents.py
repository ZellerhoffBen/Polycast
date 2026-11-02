from sqlalchemy.exc import IntegrityError

from polycast import database
from polycast.database import AudioFile, Content
from polycast.schemas import fail


def owned_content(content_id, db, user_id):
    content = database.load_content(db, content_id, user_id)
    if content is None:
        fail(404, "not_found", "Dieser Eintrag wurde nicht gefunden.")
    return content


def save_content(db, user_id, data, mp3=None):
    # Commit text and audio together, so a failed upload leaves no half-saved entry.
    content = Content(user_id=user_id, **data.model_dump(mode="json"))
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


def list_contents(db, user_id):
    rows = database.list_contents(db, user_id)
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


def get_content(content_id, db, user_id):
    content = owned_content(content_id, db, user_id)
    audio = database.load_audio(db, content.id)
    return {
        **content.model_dump(exclude={"user_id"}),
        "has_audio": audio is not None,
    }


def get_audio(content_id, db, user_id):
    owned_content(content_id, db, user_id)
    audio = database.load_audio(db, content_id)
    if audio is None:
        fail(404, "no_audio", "Für diesen Eintrag ist noch kein Audio gespeichert.")
    return audio


def save_audio(db, content, mp3):
    content_id = content.id
    saved_audio = database.load_audio(db, content_id)
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
