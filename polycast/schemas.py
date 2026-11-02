import re
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)


# Login accepts short passwords too, so failed attempts are counted.
class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str

    @field_validator("email")
    @classmethod
    def valid_email(cls, email):
        email = email.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise ValueError("Ungültige E-Mail-Adresse")
        return email


class Registration(Credentials):
    password: str = Field(min_length=8, max_length=128)
    password_confirmation: str

    @model_validator(mode="after")
    def matching_passwords(self):
        if self.password != self.password_confirmation:
            raise ValueError("Die Passwörter stimmen nicht überein.")
        return self


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
    target_level: Literal["A1", "A2", "B1", "B2", "C1", "C2"] | None = None

    @model_validator(mode="after")
    def check_level(self):
        if self.mode == "simplify" and self.target_level is None:
            raise ValueError("Bitte ein Sprachniveau für die Vereinfachung wählen.")
        if self.mode == "translate_only" and self.target_level is not None:
            raise ValueError("Ohne Vereinfachung darf kein Sprachniveau gesetzt sein.")
        return self


class ContentRequest(TextRequest):
    input_language: Language
    output_text: ArticleText
    source_url: HttpUrl | None = Field(default=None, max_length=2048)


class AudioRequest(BaseModel):
    output_text: ArticleText
    output_language: Language


def fail(status, code, message):
    raise HTTPException(status, detail={"code": code, "message": message})
