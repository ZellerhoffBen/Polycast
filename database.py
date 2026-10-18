import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

from dotenv import load_dotenv
from sqlalchemy import CheckConstraint, Column, DateTime
from sqlmodel import Field, Session, SQLModel, create_engine

load_dotenv()


def now():
    return datetime.now(UTC)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    email: str = Field(unique=True, index=True)
    password_hash: str
    created_at: datetime = Field(
        default_factory=now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    failed_login_attempts: int = 0
    locked_until: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


class LoginSession(SQLModel, table=True):
    __tablename__ = "sessions"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", ondelete="CASCADE", index=True)
    token_hash: str = Field(unique=True, index=True)
    created_at: datetime = Field(
        default_factory=now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    last_activity_at: datetime = Field(
        default_factory=now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class Content(SQLModel, table=True):
    __tablename__ = "contents"
    __table_args__ = (
        CheckConstraint("input_language IN ('de','fr','en','pt','uk','es')"),
        CheckConstraint("output_language IN ('de','fr','en','pt','uk','es')"),
        CheckConstraint(
            "(mode = 'translate_only' AND target_level IS NULL) OR "
            "(mode = 'simplify' AND target_level IS NOT NULL AND target_level IN ('A2','B1','B2'))"
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", ondelete="CASCADE", index=True)
    original_text: str
    output_text: str
    source_url: str | None = None
    input_language: str
    output_language: str
    mode: str
    target_level: str | None = None
    created_at: datetime = Field(
        default_factory=now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class AudioFile(SQLModel, table=True):
    __tablename__ = "audio_files"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    content_id: UUID = Field(foreign_key="contents.id", ondelete="CASCADE", unique=True)
    mp3_data: bytes
    filename: str = "polycast.mp3"
    mime_type: str = "audio/mpeg"
    created_at: datetime = Field(
        default_factory=now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


engine = create_engine(
    os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://polycast:polycast@127.0.0.1:5432/polycast"
    )
)


def get_db():
    with Session(engine) as db:
        yield db
