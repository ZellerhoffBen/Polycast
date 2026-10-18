from types import SimpleNamespace

import pytest
import requests
from streamlit.testing.v1 import AppTest

from services import process_article
from tests.test_contents import AUDIO, CONTENT


@pytest.fixture
def ui(client, monkeypatch):
    def request(method, url, **kwargs):
        kwargs.pop("timeout", None)
        response = client.request(
            method, url.removeprefix("http://127.0.0.1:8000"), **kwargs
        )
        return SimpleNamespace(
            status_code=response.status_code,
            ok=response.is_success,
            json=response.json,
            content=response.content,
        )

    monkeypatch.setattr(requests, "request", request)
    monkeypatch.setattr(
        requests, "post", lambda url, **kwargs: request("POST", url, **kwargs)
    )
    monkeypatch.setattr(
        process_article,
        "adapt_text",
        lambda *args: {"input_language": "de", "output_text": CONTENT["output_text"]},
    )
    monkeypatch.setattr(process_article, "generate_audio", lambda *args: AUDIO)
    app = AppTest.from_file("../app.py", default_timeout=10).run()
    app.radio[0].set_value("Registrieren").run()
    app.text_input[0].set_value("ui@example.com")
    app.text_input[1].set_value("school-project")
    app.button[0].click().run()
    assert not app.exception
    yield app


def click(ui, label):
    next(button for button in ui.button if button.label == label).click().run()
    assert not ui.exception


def test_full_ui_flow_and_history(ui):
    ui.text_area(key="original_text").set_value(CONTENT["original_text"]).run()
    ui.selectbox(key="output_language").set_value("en").run()
    click(ui, "Text erstellen")
    click(ui, "Speichern")
    assert ui.success
    click(ui, "MP3 erstellen")
    click(ui, "Audio zum Eintrag speichern")
    assert ui.success
    next(radio for radio in ui.radio if radio.label == "Bereich").set_value(
        "Verlauf"
    ).run()
    assert not ui.exception
    assert ui.text_area[0].value == CONTENT["original_text"]
    next(radio for radio in ui.radio if radio.label == "Bereich").set_value(
        "Neuer Inhalt"
    ).run()
    assert ui.text_area(key="original_text").value == CONTENT["original_text"]
    assert ui.session_state["audio"] == AUDIO
    click(ui, "Abmelden")
    assert "token" not in ui.session_state
    assert "result" not in ui.session_state


def test_changed_input_clears_result_and_error_keeps_input(ui, monkeypatch):
    ui.text_area(key="original_text").set_value(CONTENT["original_text"]).run()
    click(ui, "Text erstellen")
    assert "result" in ui.session_state
    ui.selectbox(key="level").set_value("B2").run()
    assert "result" not in ui.session_state

    def failure(*args):
        raise requests.Timeout()

    monkeypatch.setattr(process_article, "adapt_text", failure)
    click(ui, "Text erstellen")
    assert ui.error
    assert ui.text_area(key="original_text").value == CONTENT["original_text"]


def test_expired_session_keeps_draft_only_for_same_user(ui, client):
    ui.text_area(key="original_text").set_value(CONTENT["original_text"]).run()
    client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {ui.session_state['token']}"}
    )
    click(ui, "Text erstellen")
    assert ui.info
    ui.text_input[0].set_value("ui@example.com")
    ui.text_input[1].set_value("school-project")
    ui.button[0].click().run()
    assert not ui.exception
    assert ui.text_area(key="original_text").value == CONTENT["original_text"]
