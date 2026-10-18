# Polycast

Schulprojekt für M306: Artikel als Link oder Text eingeben, übersetzen oder vereinfachen und als MP3 anhören. Die App läuft lokal auf dem Desktop im Browser.

## Umfang

- Registrierung, Anmeldung und Abmeldung
- Deutsch, Französisch, Englisch, Portugiesisch, Ukrainisch und Spanisch als Ein- und Ausgabesprache
- Vereinfachung auf A2, B1 oder B2; alternativ nur übersetzen
- Bei gleicher Sprache ohne Vereinfachung bleibt der Text unverändert
- MP3 abspielen und herunterladen
- Inhalte ausdrücklich speichern und später im eigenen Verlauf öffnen
- Audio auch nachträglich zu einem gespeicherten Text hinzufügen

Löschen von Konten/Inhalten und Dialoge mit mehreren Stimmen sind die optionalen US-09/US-10 und gehören nicht zu dieser Umsetzung.

## Lokal starten

Benötigt werden Python ab 3.13, [uv](https://docs.astral.sh/uv/), ein laufender lokaler PostgreSQL-Server und ein OpenRouter-API-Key. Docker wird nicht benötigt. PostgreSQL gibt es beispielsweise über die [offiziellen macOS-Installationsmöglichkeiten](https://www.postgresql.org/download/macosx/). Die PostgreSQL-Werkzeuge müssen im `PATH` liegen.

1. Abhängigkeiten installieren:

   ```sh
   uv sync --locked
   ```

2. Einmalig eine Datenbank anlegen. Die Befehle mit dem lokalen PostgreSQL-Administrationskonto ausführen:

   ```sh
   createuser --pwprompt polycast
   createdb --owner=polycast polycast
   ```

   PostgreSQL soll nur auf `localhost` lauschen (`listen_addresses = 'localhost'` in `postgresql.conf`).

3. Falls noch keine `.env` existiert, `.env.example` nach `.env` kopieren. Den API-Key und die Datenbankverbindung eintragen. Das Passwort in der URL muss dem zuvor vergebenen Passwort entsprechen; Sonderzeichen im Passwort URL-kodieren.

   ```dotenv
   API_KEY=dein-openrouter-key
   DATABASE_URL=postgresql+psycopg://polycast:dein-passwort@127.0.0.1:5432/polycast
   ```

   Im OpenRouter-Konto ein kleines Ausgabenlimit für den Projekt-Key setzen. Die `.env` gehört nicht ins Git-Repository.

4. Backend in einem Terminal starten:

   ```sh
   uv run uvicorn api:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
   ```

   Die vier Tabellen werden beim ersten Start automatisch angelegt. Ein einzelner Backend-Prozess ist beabsichtigt: Die gemeinsame Sperre lässt genau eine Text- oder Audiogenerierung gleichzeitig zu.

5. Oberfläche in einem zweiten Terminal starten:

   ```sh
   uv run streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
   ```

   Im Browser `http://127.0.0.1:8501` öffnen und ein Konto registrieren. Die API-Dokumentation liegt unter `http://127.0.0.1:8000/docs`.

## Aufbau

`app.py` enthält die Streamlit-Oberfläche. Sie spricht ausschliesslich mit `api.py`, dem FastAPI-Backend. Nur das Backend greift auf PostgreSQL und OpenRouter zu.

`database.py` definiert die vier Tabellen. Artikelimport und KI-Aufrufe liegen in den zwei Dateien unter `services/`; der Text-Prompt liegt in `prompts/instructions.py`. Es gibt keine zusätzliche Service- oder Repository-Schicht.

| Tabelle | Gespeicherte Daten |
| --- | --- |
| `users` | UUID, eindeutige E-Mail, Argon2id-Passworthash, Erstellzeit, Fehlversuche und Sperrzeit |
| `sessions` | UUID, Benutzer-ID, Hash des zufälligen Sitzungstokens, Erstellzeit und letzte Aktivität |
| `contents` | UUID, Benutzer-ID, Originaltext, Ergebnistext, optionaler Quelllink, Eingabe-/Ausgabesprache, Modus, optionales Niveau und Erstellzeit |
| `audio_files` | UUID, eindeutige Inhalts-ID, MP3 als Binärdaten, Dateiname, MIME-Typ und Erstellzeit |

Ein Benutzer hat mehrere Sitzungen und Inhalte. Zu einem Inhalt gehört höchstens eine Audiodatei. Fremdschlüssel verbinden die Tabellen. Text und optionales Audio werden zusammen in einer Datenbanktransaktion gespeichert.

Ungespeicherte Ergebnisse bleiben nur in der aktuellen Streamlit-Sitzung. Das Wechseln zum Verlauf verwirft sie nicht. Abmelden oder Schliessen der Sitzung verwirft ungespeicherte Daten.

## KI und Grenzen

Für Texte wird `google/gemini-2.5-flash-lite` verwendet. Für Sprache bleibt es bei `google/gemini-3.1-flash-tts-preview`, Stimme `Orus`. Dieses Modell liefert PCM mit 24 kHz und 16 Bit mono. `lameenc` wandelt es direkt im Speicher in MP3 um; ein zusätzliches Programm wie ffmpeg ist nicht nötig. Die API liefert dem Frontend immer MP3.

OpenRouter-Aufrufe verwenden `provider.data_collection = "deny"`. An den Dienst gehen nur der benötigte Text und die Verarbeitungsangaben, keine Kontodaten. Die Oberfläche weist vor der Verarbeitung auf externe KI-Dienste hin und kennzeichnet Text und synthetische Stimme.

Pro Eingabe sind maximal 20'000 Zeichen vorgesehen. Artikel-Webseiten sind auf 2 MB und drei Weiterleitungen begrenzt, gespeicherte MP3-Dateien auf 20 MB. Lokale/private IP-Adressen werden auch bei Weiterleitungen abgelehnt. Die Verbindung verwendet die zuvor geprüfte IP-Adresse. Artikel hinter Login, Paywall oder ausschliesslich per JavaScript geladene Texte lassen sich gegebenenfalls nur durch direktes Einfügen verwenden.

Sitzungen laufen nach 30 Minuten ohne API-Aktivität ab. Nach fünf falschen Passwörtern ist das Konto für 15 Minuten gesperrt. Das Backend prüft bei jedem gespeicherten Inhalt die Zugehörigkeit zum angemeldeten Benutzer.

## Tests

```sh
uv run pytest -q
```

Standardmässig verwenden die Tests eine kurzlebige SQLite-Datenbank im Speicher. PostgreSQL lässt sich mit derselben Suite testen:

```sh
TEST_DATABASE_URL='postgresql+psycopg://polycast:dein-passwort@127.0.0.1:5432/polycast' uv run pytest -q
```

Jeder Test erstellt dafür ein eigenes zufälliges Schema und entfernt ausschliesslich dieses Schema wieder. Der Testbenutzer benötigt die Berechtigung, Schemas anzulegen.

Die Tests prüfen Anmeldung, Sperre, Sitzungsablauf, Benutzertrennung, Transaktionen, nachträgliches Speichern von Audio, URL-Prüfungen, Fehler bei KI-Aufrufen und den Streamlit-Ablauf. KI-Antworten sind in der automatisierten Suite simuliert; die MP3-Testdatei enthält selbst erzeugte Stille. Damit entstehen beim Testen keine API-Kosten.

Zusätzlich wurden eine echte Übersetzung und MP3-Erzeugung mit OpenRouter sowie ein verschlüsseltes Backup mit anschliessender Wiederherstellung geprüft. Alle 55 Tests liefen erfolgreich gegen PostgreSQL. In Chrome wurden Anmeldung, Desktop-Ansicht, Verlauf, MP3-Wiedergabe und Download geprüft. Die sprachliche Qualität, die 36 Sprachkombinationen und die Wiedergabe in Edge und Safari muss das Team vor der Abnahme noch mit seinen Testfällen beurteilen. Automatisierte Tests bestätigen keine CEFR-Einstufung.

## Backups während des Projekts

An Entwicklungstagen einmal ausführen:

```sh
uv run python backup.py
```

Das Skript verwendet `DATABASE_URL` aus `.env`, fragt ein Backup-Passwort ab und erstellt einen verschlüsselten PostgreSQL-Dump unter `backups/`. Benötigt werden `pg_dump` und OpenSSL mit PBKDF2-Unterstützung. Das gleiche Backup-Passwort sicher aufbewahren. Optional kann es über die Umgebungsvariable `BACKUP_PASSWORD` übergeben werden.

Es gibt eine Datei pro Tag. Beim nächsten Backup werden Dateien entfernt, die älter als sieben Tage sind. Backups liegen nicht im Git-Repository. Das Skript muss an den Entwicklungstagen ausgeführt werden; es richtet keinen Hintergrunddienst ein.

Für einen Wiederherstellungstest eine **neue, leere** Datenbank anlegen und den Dateinamen anpassen:

```sh
createdb --owner=polycast polycast_restore
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in backups/polycast-JJJJ-MM-TT.dump.enc | pg_restore --exit-on-error --no-owner --no-acl --host 127.0.0.1 --username polycast --dbname polycast_restore
```

OpenSSL fragt das Backup-Passwort ab. PostgreSQL fragt bei Bedarf separat nach dem Datenbankpasswort. Danach Benutzer, Texte und eine MP3 in der wiederhergestellten Datenbank prüfen. Spätestens sieben Tage nach Projektabschluss entfernt das Team die Projektdatenbank, Testdatenbanken, heruntergeladene Audiodateien und sämtliche Backups.
