import json
from datetime import datetime

import requests
import streamlit as st

from polycast.auth_forms import API_URL, COOKIE_NAME, auth_form

LANGUAGES = {
    "de": "Deutsch",
    "fr": "Französisch",
    "en": "Englisch",
    "pt": "Portugiesisch",
    "uk": "Ukrainisch",
    "es": "Spanisch",
}
state = st.session_state


def api_request(method, path, **kwargs):
    headers = (
        {"Authorization": f"Bearer {state['token']}"} if state.get("token") else {}
    )
    try:
        response = requests.request(
            method, API_URL + path, headers=headers, timeout=(5, 240), **kwargs
        )
    except requests.RequestException:
        st.error(
            "Das Backend ist nicht erreichbar oder die Anfrage hat zu lange gedauert. Deine Eingaben bleiben erhalten."
        )
        st.stop()
    if response.status_code == 401 and state.get("token"):
        state.pop("token")
        state["expired"] = True
        st.rerun()
    if not response.ok:
        try:
            message = response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = "Die Anfrage ist fehlgeschlagen. Bitte erneut versuchen."
        st.error(message)
        st.stop()
    return response


def clear_result():
    # A changed text or setting invalidates both the result and its audio.
    for key in ("result", "audio", "saved_id", "audio_saved"):
        state.pop(key, None)


def clear_source():
    clear_result()
    state["original_text"] = ""
    state.pop("source_url", None)


def show_source():
    st.subheader("1. Artikel eingeben")
    source = st.radio(
        "Quelle",
        ["Text", "Link"],
        horizontal=True,
        key="source",
        persist_state="session",
        on_change=clear_source,
    )
    if source == "Link":
        url = st.text_input(
            "Artikel-Link",
            placeholder="https://…",
            key="url",
            persist_state="session",
            on_change=clear_source,
        )
        if st.button("Artikel laden", disabled=not url.strip()):
            with st.spinner("Artikel wird geladen …"):
                article = api_request(
                    "POST", "/articles/extract", json={"url": url}
                ).json()
            clear_result()
            state["original_text"] = article["original_text"]
            state["source_url"] = article["source_url"]
    original = st.text_area(
        "Originaltext",
        height=300,
        max_chars=20_000,
        key="original_text",
        persist_state="session",
        on_change=clear_result,
    )
    st.caption("Bis zu 20'000 Zeichen. Die Eingabesprache wird automatisch erkannt.")
    return original


def show_options():
    language = st.selectbox(
        "Zielsprache",
        list(LANGUAGES),
        format_func=LANGUAGES.get,
        key="output_language",
        persist_state="session",
        on_change=clear_result,
    )
    simplify = st.checkbox(
        "Text vereinfachen",
        value=True,
        key="simplify",
        persist_state="session",
        on_change=clear_result,
    )
    level = st.selectbox(
        "Sprachniveau",
        ["A2", "B1", "B2"],
        disabled=not simplify,
        key="level",
        persist_state="session",
        on_change=clear_result,
    )
    if not simplify:
        st.caption(
            "Der Text wird nur übersetzt. Bei gleicher Sprache bleibt er unverändert."
        )
    return language, level if simplify else None


def show_audio(content, state_key):
    # New results and history entries use the same player, but keep separate audio.
    if st.button("MP3 erstellen", disabled=bool(state.get(state_key))):
        with st.spinner("Audio wird erstellt …"):
            state[state_key] = api_request(
                "POST",
                "/audio/generate",
                json={
                    "output_text": content["output_text"],
                    "output_language": content["output_language"],
                },
            ).content
    mp3 = state.get(state_key)
    if mp3:
        filename = (
            f"polycast-{content['id']}.mp3" if "id" in content else "polycast.mp3"
        )
        st.caption("Synthetisch erzeugte Stimme")
        st.audio(mp3, format="audio/mpeg")
        st.download_button("MP3 herunterladen", mp3, filename, "audio/mpeg")
    return mp3


def save_audio_button(content_id, mp3):
    if not st.button("Audio zum Eintrag speichern", type="primary"):
        return False
    api_request(
        "PUT",
        f"/contents/{content_id}/audio",
        files={"audio": ("polycast.mp3", mp3, "audio/mpeg")},
    )
    return True


def show_result():
    st.subheader("2. Lesen und anhören")
    result = state.get("result")
    if not result:
        st.caption(
            "Dein Ergebnis erscheint hier. Gespeichert wird erst, wenn du auf «Speichern» klickst."
        )
        return
    st.caption(f"Erkannte Eingabesprache: {LANGUAGES[result['input_language']]}")
    st.text_area(
        "Ergebnis · KI-verarbeiteter Text",
        result["output_text"],
        height=300,
        disabled=True,
    )
    mp3 = show_audio(result, "audio")
    if not state.get("saved_id"):
        if st.button("Speichern", type="primary"):
            files = {"metadata": (None, json.dumps(result))}
            if mp3:
                files["audio"] = ("polycast.mp3", mp3, "audio/mpeg")
            saved = api_request("POST", "/contents", files=files).json()
            state["saved_id"] = saved["id"]
            state["audio_saved"] = saved["has_audio"]
            st.rerun()
    elif mp3 and not state.get("audio_saved"):
        if save_audio_button(state["saved_id"], mp3):
            state["audio_saved"] = True
            st.rerun()
    else:
        st.success("Im Verlauf gespeichert.")


def show_creation():
    left, right = st.columns(2, gap="large")
    with left:
        original = show_source()
        language, level = show_options()
        source_url = state.get("source_url") if state["source"] == "Link" else None
        ready = original.strip() and (state["source"] == "Text" or source_url)
        if st.button("Text erstellen", type="primary", disabled=not ready):
            payload = {
                "original_text": original,
                "output_language": language,
                "mode": "simplify" if level else "translate_only",
                "target_level": level,
            }
            with st.spinner("Text wird verarbeitet …"):
                result = api_request("POST", "/texts/adapt", json=payload).json()
            clear_result()
            state["result"] = {**payload, **result, "source_url": source_url}
    with right:
        show_result()


def history_label(item):
    date = (
        datetime.fromisoformat(item["created_at"])
        .astimezone()
        .strftime("%d.%m.%Y %H:%M")
    )
    mode = (
        f"Vereinfacht ({item['target_level']})"
        if item["mode"] == "simplify"
        else "Ohne Vereinfachung"
    )
    audio = "Mit Audio" if item["has_audio"] else "Ohne Audio"
    return f"{date} · {LANGUAGES[item['output_language']]} · {mode} · {audio} · {item['preview']}"


def show_history():
    st.subheader("Gespeicherte Inhalte")
    entries = api_request("GET", "/contents").json()
    if not entries:
        st.caption("Du hast noch keine Inhalte gespeichert.")
        return
    selected = st.selectbox(
        "Eintrag auswählen · neueste zuerst", entries, format_func=history_label
    )["id"]
    content = api_request("GET", f"/contents/{selected}").json()
    level = content["target_level"] or "ohne Vereinfachung"
    st.caption(
        f"{LANGUAGES[content['input_language']]} → {LANGUAGES[content['output_language']]} · {level}"
    )
    if content.get("source_url"):
        st.link_button("Originalartikel öffnen", content["source_url"])
    left, right = st.columns(2, gap="large")
    with left:
        st.text_area(
            "Originaltext", content["original_text"], height=320, disabled=True
        )
    with right:
        st.text_area(
            "Ergebnis · KI-verarbeiteter Text",
            content["output_text"],
            height=320,
            disabled=True,
        )
    if state.get("history_audio_id") != selected:
        state["history_audio_id"] = selected
        state.pop("history_audio", None)
    if content["has_audio"] and not state.get("history_audio"):
        state["history_audio"] = api_request(
            "GET", f"/contents/{selected}/audio"
        ).content
    mp3 = show_audio(content, "history_audio")
    if mp3 and not content["has_audio"] and save_audio_button(selected, mp3):
        st.rerun()


def main():
    st.set_page_config(page_title="Polycast", page_icon="🎧", layout="wide")
    st.title("Polycast")
    st.caption("Artikel lesen, Sprachen lernen und unterwegs zuhören.")
    # Read the HttpOnly cookie on the server to restore login after a reload.
    if not state.get("token") and not state.get("expired"):
        token = st.context.cookies.get(COOKIE_NAME)
        if token:
            state["token"] = token
    if state.get("token") and "email" not in state:
        state["email"] = api_request("GET", "/auth/me").json()["email"]
    if not state.get("token"):
        if state.get("expired"):
            st.info("Die Sitzung ist abgelaufen. Bitte erneut anmelden.")
        choice = st.radio("Konto", ["Anmelden", "Registrieren"], horizontal=True)
        st.html(auth_form("register" if choice == "Registrieren" else "login"))
        return
    with st.sidebar:
        st.write(state["email"])
        page = st.radio("Bereich", ["Neuer Lerninhalt", "Mein Verlauf"])
        st.html(auth_form("logout"))
    st.info(
        "Bei der Generierung wird dein Text an OpenRouter und den ausgewählten KI-Anbieter übermittelt. Kontodaten werden nicht mitgesendet. Anbieter, die die Texte für Training verwenden, sind ausgeschlossen. Bitte keine vertraulichen Texte eingeben."
    )
    if page == "Neuer Lerninhalt":
        show_creation()
    else:
        show_history()
