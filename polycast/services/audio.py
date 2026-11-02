from io import BytesIO

import lameenc
from mutagen import MutagenError
from mutagen.mp3 import MP3

from polycast.services import openrouter
from polycast.services.text import LANGUAGES

MAX_AUDIO_BYTES = 20_000_000


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
    response = openrouter.request(
        "audio/speech",
        {
            "model": "google/gemini-3.1-flash-tts-preview",
            "input": output_text,
            "voice": "Orus",
            "instructions": f"Read this text clearly in {LANGUAGES[output_language]}. Do not add or omit words.",
            "response_format": "pcm",
        },
    )
    pcm = response.content
    if (
        not pcm
        or len(pcm) % 2
        or not response.headers.get("Content-Type", "").startswith("audio/pcm")
    ):
        raise ValueError(
            "Der Sprachdienst hat keine vollständigen PCM-Audiodaten geliefert."
        )
    # OpenRouter returns 24 kHz mono PCM, so we convert it to MP3 here.
    encoder = lameenc.Encoder()
    encoder.set_in_sample_rate(24000)
    encoder.set_channels(1)
    encoder.set_bit_rate(96)
    encoder.set_quality(2)
    return validate_audio(bytes(encoder.encode(pcm) + encoder.flush()))
