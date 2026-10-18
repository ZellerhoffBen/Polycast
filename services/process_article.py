import json
import os
from io import BytesIO

import requests
from mutagen import MutagenError
from mutagen.mp3 import MP3

from prompts.instructions import get_system_prompt

LANGUAGES = {
    "de": "Deutsch",
    "fr": "Français",
    "en": "English",
    "pt": "Português",
    "uk": "Українська",
    "es": "Español",
}
MAX_AUDIO_BYTES = 20_000_000


def openrouter(endpoint, payload):
    key = os.environ.get("API_KEY")
    if not key:
        raise ValueError("Der OpenRouter-API-Key fehlt in der .env-Datei des Backends.")
    response = requests.post(
        f"https://openrouter.ai/api/v1/{endpoint}",
        headers={"Authorization": f"Bearer {key}"},
        json={**payload, "provider": {"data_collection": "deny"}},
        timeout=(10, 180),
    )
    response.raise_for_status()
    return response


def adapt_text(original_text, output_language, target_level):
    response = openrouter(
        "chat/completions",
        {
            "model": "google/gemini-2.5-flash-lite",
            "messages": [
                {
                    "role": "system",
                    "content": get_system_prompt(output_language, target_level),
                },
                {"role": "user", "content": original_text},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "article",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "input_language": {
                                "type": "string",
                                "enum": [*LANGUAGES, "unsupported"],
                            },
                            "output_text": {"type": "string"},
                        },
                        "required": ["input_language", "output_text"],
                        "additionalProperties": False,
                    },
                },
            },
            "max_tokens": 10000,
        },
    )
    data = response.json()
    choice = data["choices"][0]
    if choice.get("finish_reason") != "stop":
        raise ValueError(
            "Die Textverarbeitung wurde nicht vollständig abgeschlossen. Bitte einen kürzeren Text versuchen."
        )
    article = json.loads(choice["message"]["content"])
    if article.get("input_language") not in LANGUAGES:
        raise ValueError(
            "Bitte einen Text auf Deutsch, Französisch, Englisch, Portugiesisch, Ukrainisch oder Spanisch verwenden."
        )
    text = article.get("output_text")
    if not isinstance(text, str) or not text.strip() or len(text) > 20_000:
        raise ValueError(
            "Der KI-Dienst hat keinen gültigen vollständigen Text geliefert."
        )
    if target_level is None and article["input_language"] == output_language:
        text = original_text
    return {"input_language": article["input_language"], "output_text": text.strip()}


def validate_audio(data):
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise ValueError("Die MP3-Datei ist leer oder grösser als 20 MB.")
    try:
        audio = MP3(BytesIO(data))
    except MutagenError:
        raise ValueError("Die Audiodaten sind keine gültige MP3-Datei.") from None
    if audio.info.length <= 0:
        raise ValueError("Die MP3-Datei enthält kein Audio.")
    return data


def generate_audio(output_text, output_language):
    response = openrouter(
        "audio/speech",
        {
            "model": "google/gemini-3.1-flash-tts-preview",
            "input": output_text,
            "voice": "Orus",
            "instructions": f"Read this text clearly in {LANGUAGES[output_language]}. Do not add or omit words.",
            "response_format": "mp3",
        },
    )
    return validate_audio(response.content)
