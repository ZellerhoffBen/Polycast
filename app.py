import json
from datetime import datetime

import requests
import streamlit as st

st.set_page_config(page_title="Polycast", page_icon="🎧", layout="wide")
LANGUAGES = {
    "de": "Deutsch",
    "fr": "Französisch",
    "en": "Englisch",
    "pt": "Portugiesisch",
    "uk": "Ukrainisch",
    "es": "Spanisch",
}
API_URL = "http://127.0.0.1:8000"
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
        del state["token"]
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
    for key in ("result", "audio", "saved_id", "audio_saved"):
        state.pop(key, None)


def clear_source():
    clear_result()
    state["original_text"] = ""
    state.pop("source_url", None)


st.title("Polycast")
st.caption("Artikel lesen, Sprachen lernen und unterwegs zuhören.")

if not state.get("token"):
    if state.get("expired"):
        st.info(
            "Bitte erneut anmelden. Deine ungespeicherten Eingaben bleiben für dein Konto erhalten."
        )
    left, _ = st.columns([1, 2])
    with left:
        choice = st.radio("Konto", ["Anmelden", "Registrieren"], horizontal=True)
        with st.form("login"):
            email = st.text_input("E-Mail")
            password = st.text_input(
                "Passwort", type="password", help="Mindestens 8 Zeichen."
            )
            submitted = st.form_submit_button(choice, type="primary")
        if submitted:
            credentials = {"email": email, "password": password}
            if choice == "Registrieren":
                api_request("POST", "/auth/register", json=credentials)
            login = api_request("POST", "/auth/login", json=credentials).json()
            if state.get("email") != login["user"]["email"]:
                state.clear()
            state["token"] = login["token"]
            state["email"] = login["user"]["email"]
            state.pop("expired", None)
            st.rerun()
    st.stop()

with st.sidebar:
    st.write(state["email"])
    page = st.radio("Bereich", ["Neuer Inhalt", "Verlauf"])
    if st.button("Abmelden", width="stretch"):
        # A failed backend request keeps the session visible so logout can be retried.
        try:
            response = requests.post(
                API_URL + "/auth/logout",
                headers={"Authorization": f"Bearer {state['token']}"},
                timeout=10,
            )
        except requests.RequestException:
            st.error("Abmelden fehlgeschlagen. Bitte erneut versuchen.")
            st.stop()
        if response.status_code not in (204, 401):
            st.error("Abmelden fehlgeschlagen. Bitte erneut versuchen.")
            st.stop()
        state.clear()
        st.rerun()

st.info(
    "Bei der Generierung wird dein Text an OpenRouter und den ausgewählten KI-Anbieter übermittelt. Kontodaten werden nicht mitgesendet. Anbieter, die die Texte für Training verwenden, sind ausgeschlossen. Bitte keine vertraulichen Texte eingeben."
)

if page == "Neuer Inhalt":
    left, right = st.columns(2, gap="large")
    with left:
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
        original_text = st.text_area(
            "Originaltext",
            height=300,
            max_chars=20_000,
            key="original_text",
            persist_state="session",
            on_change=clear_result,
        )
        st.caption(
            "Bis zu 20'000 Zeichen. Die Eingabesprache wird automatisch erkannt."
        )
        output_language = st.selectbox(
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
        if st.button(
            "Text erstellen",
            type="primary",
            disabled=not original_text.strip()
            or (source == "Link" and not state.get("source_url")),
        ):
            payload = {
                "original_text": original_text,
                "output_language": output_language,
                "mode": "simplify" if simplify else "translate_only",
                "target_level": level if simplify else None,
            }
            with st.spinner("Text wird verarbeitet …"):
                result = api_request("POST", "/texts/adapt", json=payload).json()
            clear_result()
            state["result"] = {
                **payload,
                **result,
                "source_url": state.get("source_url") if source == "Link" else None,
            }

    with right:
        st.subheader("2. Lesen und anhören")
        result = state.get("result")
        if not result:
            st.caption(
                "Dein Ergebnis erscheint hier. Gespeichert wird erst, wenn du auf «Speichern» klickst."
            )
        else:
            st.caption(
                f"Erkannte Eingabesprache: {LANGUAGES[result['input_language']]}"
            )
            st.text_area(
                "Ergebnis · KI-verarbeiteter Text",
                result["output_text"],
                height=300,
                disabled=True,
            )
            if st.button("MP3 erstellen", disabled=bool(state.get("audio"))):
                with st.spinner("Audio wird erstellt …"):
                    audio = api_request(
                        "POST",
                        "/audio/generate",
                        json={
                            "output_text": result["output_text"],
                            "output_language": result["output_language"],
                        },
                    ).content
                state["audio"] = audio
            if state.get("audio"):
                st.caption("Synthetisch erzeugte Stimme")
                st.audio(state["audio"], format="audio/mpeg")
                st.download_button(
                    "MP3 herunterladen", state["audio"], "polycast.mp3", "audio/mpeg"
                )
            if not state.get("saved_id"):
                if st.button("Speichern", type="primary"):
                    files = {"metadata": (None, json.dumps(result))}
                    if state.get("audio"):
                        files["audio"] = ("polycast.mp3", state["audio"], "audio/mpeg")
                    saved = api_request("POST", "/contents", files=files).json()
                    state["saved_id"] = saved["id"]
                    state["audio_saved"] = saved["has_audio"]
                    st.rerun()
            elif state.get("audio") and not state.get("audio_saved"):
                if st.button("Audio zum Eintrag speichern", type="primary"):
                    api_request(
                        "PUT",
                        f"/contents/{state['saved_id']}/audio",
                        files={"audio": ("polycast.mp3", state["audio"], "audio/mpeg")},
                    )
                    state["audio_saved"] = True
                    st.rerun()
            else:
                st.success("Im Verlauf gespeichert.")

else:
    st.subheader("Gespeicherte Inhalte")
    contents = api_request("GET", "/contents").json()
    if not contents:
        st.caption("Du hast noch keine Inhalte gespeichert.")
        st.stop()
    entries = {item["id"]: item for item in contents}

    def entry_label(content_id):
        item = entries[content_id]
        date = (
            datetime.fromisoformat(item["created_at"])
            .astimezone()
            .strftime("%d.%m.%Y %H:%M")
        )
        return f"{date} · {LANGUAGES[item['output_language']]} · {item['preview']}"

    selected = st.selectbox(
        "Eintrag auswählen · neueste zuerst", list(entries), format_func=entry_label
    )
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
    if not content["has_audio"] and not state.get("history_audio"):
        if st.button("MP3 erstellen"):
            with st.spinner("Audio wird erstellt …"):
                state["history_audio"] = api_request(
                    "POST",
                    "/audio/generate",
                    json={
                        "output_text": content["output_text"],
                        "output_language": content["output_language"],
                    },
                ).content
    if state.get("history_audio"):
        st.caption("Synthetisch erzeugte Stimme")
        st.audio(state["history_audio"], format="audio/mpeg")
        st.download_button(
            "MP3 herunterladen",
            state["history_audio"],
            f"polycast-{selected}.mp3",
            "audio/mpeg",
        )
        if not content["has_audio"] and st.button(
            "Audio zum Eintrag speichern", type="primary"
        ):
            api_request(
                "PUT",
                f"/contents/{selected}/audio",
                files={"audio": ("polycast.mp3", state["history_audio"], "audio/mpeg")},
            )
            st.rerun()
