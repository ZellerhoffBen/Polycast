import json
from types import SimpleNamespace

import pytest
import requests

import api
from services import process_article
from tests.test_contents import AUDIO, CONTENT


@pytest.mark.parametrize("language", ["de", "fr", "en", "pt", "uk", "es"])
@pytest.mark.parametrize("level", ["A2", "B1", "B2", None])
def test_languages_levels_and_no_automatic_save(
    client, auth, monkeypatch, language, level
):
    monkeypatch.setattr(
        process_article,
        "adapt_text",
        lambda text, output, target: {"input_language": "de", "output_text": "Example"},
    )
    payload = {
        "original_text": CONTENT["original_text"],
        "output_language": language,
        "mode": "simplify" if level else "translate_only",
        "target_level": level,
    }
    result = client.post("/texts/adapt", headers=auth, json=payload)
    assert result.status_code == 200
    assert result.json()["output_language"] == language
    assert result.json()["target_level"] == level
    assert client.get("/contents", headers=auth).json() == []


def test_busy_timeout_and_retry_release_lock(client, auth, monkeypatch):
    payload = {"output_text": "Hallo Welt.", "output_language": "de"}
    api.generation_lock.acquire()
    try:
        assert (
            client.post("/audio/generate", headers=auth, json=payload).status_code
            == 409
        )
    finally:
        api.generation_lock.release()

    def timeout(*args):
        raise requests.Timeout()

    monkeypatch.setattr(process_article, "generate_audio", timeout)
    assert client.post("/audio/generate", headers=auth, json=payload).status_code == 504
    monkeypatch.setattr(process_article, "generate_audio", lambda *args: AUDIO)
    response = client.post("/audio/generate", headers=auth, json=payload)
    assert response.status_code == 200
    assert response.content == AUDIO
    assert client.get("/contents", headers=auth).json() == []


def test_invalid_options_do_not_call_provider(client, auth, monkeypatch):
    def unexpected(*args):
        pytest.fail("Provider must not be called for invalid input")

    monkeypatch.setattr(process_article, "adapt_text", unexpected)
    for changes in (
        {"output_language": "it"},
        {"target_level": "C1"},
        {"mode": "translate_only"},
        {"original_text": " "},
        {"original_text": "x" * 20001},
    ):
        assert (
            client.post(
                "/texts/adapt", headers=auth, json={**CONTENT, **changes}
            ).status_code
            == 422
        )
    assert client.post("/texts/adapt", json=CONTENT).status_code == 401


def test_provider_payload_and_same_language_without_simplifying(monkeypatch):
    def post(url, **kwargs):
        payload = kwargs["json"]
        assert url.startswith("https://openrouter.ai/")
        assert payload["provider"] == {"data_collection": "deny"}
        assert payload["messages"][1]["content"] == CONTENT["original_text"]
        result = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(
                            {"input_language": "de", "output_text": "Changed text"}
                        )
                    },
                }
            ]
        }
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: result)

    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setattr(requests, "post", post)
    result = process_article.adapt_text(CONTENT["original_text"], "de", None)
    assert result["output_text"] == CONTENT["original_text"]


def test_tts_encodes_pcm_as_mp3_and_rejects_broken_audio(monkeypatch):
    def post(url, **kwargs):
        assert url.endswith("/audio/speech")
        assert kwargs["json"]["response_format"] == "pcm"
        assert kwargs["json"]["provider"]["data_collection"] == "deny"
        return SimpleNamespace(
            raise_for_status=lambda: None,
            content=bytes(24000),
            headers={"Content-Type": "audio/pcm"},
        )

    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setattr(requests, "post", post)
    audio = process_article.generate_audio("Hallo.", "de")
    assert process_article.validate_audio(audio) == audio
    with pytest.raises(ValueError):
        process_article.validate_audio(b"ID3invalid")


def test_truncated_model_output_is_not_accepted(monkeypatch):
    monkeypatch.setattr(
        process_article,
        "openrouter",
        lambda *args: SimpleNamespace(
            json=lambda: {"choices": [{"finish_reason": "length"}]}
        ),
    )
    with pytest.raises(ValueError, match="vollständig"):
        process_article.adapt_text("Text", "en", "A2")
