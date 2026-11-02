# Polycast

Lokales Schulprojekt: Artikel-Link oder Text eingeben, übersetzen oder auf A2/B1/B2 vereinfachen, als MP3 anhören und im persönlichen Verlauf speichern. Unterstützt Deutsch, Französisch, Englisch, Portugiesisch, Ukrainisch und Spanisch.

## Voraussetzungen

- Python 3.13 oder neuer und [uv](https://docs.astral.sh/uv/)
- Lokaler PostgreSQL-Server; `createuser` und `createdb` im PATH
- OpenRouter-API-Key mit Zugriff auf die verwendeten Text- und Sprachmodelle
- Für Backups zusätzlich `pg_dump`, `pg_restore` und OpenSSL mit PBKDF2-Unterstützung

## Einrichten

Alle Befehle im Projektordner ausführen.

1. Abhängigkeiten installieren:

   ```sh
   uv sync --locked
   ```

2. Mit dem lokalen PostgreSQL-Administrationskonto einen Benutzer und eine Datenbank anlegen:

   ```sh
   createuser --pwprompt polycast
   createdb --owner=polycast polycast
   ```

3. `.env.example` nach `.env` kopieren, **falls noch keine `.env` existiert**. Beide Werte eintragen; vorhandenen API-Key behalten:

   ```dotenv
   API_KEY=dein-openrouter-key
   DATABASE_URL=postgresql+psycopg://polycast:dein-passwort@127.0.0.1:5432/polycast
   ```

   Das Datenbankpasswort muss zum angelegten Benutzer passen. Sonderzeichen im Passwort URL-kodieren. Ohne `DATABASE_URL` startet das Backend nicht. `.env` bleibt ausserhalb von Git.

4. PostgreSQL nur lokal betreiben (`listen_addresses = 'localhost'`). Im OpenRouter-Konto ein kleines Kostenlimit setzen.

## Starten

Backend im ersten Terminal:

```sh
uv run uvicorn polycast.api:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

Oberfläche im zweiten Terminal:

```sh
uv run streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
```

[Polycast öffnen](http://127.0.0.1:8501) · [API-Dokumentation](http://127.0.0.1:8000/docs)

Die Tabellen werden beim ersten Start angelegt. Genau einen Backend-Prozess verwenden: Eine gemeinsame Sperre erlaubt nur eine KI-Generierung gleichzeitig. Registrierung benötigt zweimal dasselbe Passwort; danach separat anmelden. Der HttpOnly-Cookie erhält die Anmeldung beim Neuladen. Ungespeicherte Ergebnisse können dabei verloren gehen.

## Aufbau

| Datei / Ordner | Aufgabe aus dem Konzept |
| --- | --- |
| `app.py`, `polycast/ui.py`, `polycast/auth_forms.py` | Oberfläche, Formulare und Cookie-Anmeldung |
| `polycast/api.py`, `polycast/schemas.py` | HTTP-Endpunkte, Eingabeprüfung und Fehlerantworten |
| `polycast/services/auth.py` | Benutzerverwaltung und Sitzungen |
| `polycast/services/contents.py` | Inhalte speichern und Verlauf laden |
| `polycast/services/scrape_article.py` | Artikelimport und Prüfung öffentlicher URLs |
| `polycast/services/text.py` | Übersetzung, Vereinfachung und Prompt |
| `polycast/services/audio.py` | Vertonung und PCM→MP3-Konvertierung |
| `polycast/services/openrouter.py` | Externe KI-Aufrufe |
| `polycast/database.py` | Vier Tabellen und Datenbankabfragen |
| `polycast/backup.py` | Verschlüsselte Sicherung und Bereinigung |
| `tests/` | Sieben technische Testfälle TC-01 bis TC-07 |

Streamlit spricht mit FastAPI. Nur das Backend greift auf PostgreSQL und OpenRouter zu. Texte und optionale MP3 werden erst mit «Speichern» dauerhaft abgelegt. Audio lässt sich später demselben Eintrag hinzufügen.

Textmodell: `google/gemini-2.5-flash-lite`. Sprachmodell: `google/gemini-3.1-flash-tts-preview`, Stimme `Orus`. PCM wird mit `lameenc` im Speicher in MP3 umgewandelt; ffmpeg ist nicht nötig. Die Modelle stehen in den jeweiligen Service-Dateien.

Grenzen: 20'000 Zeichen, 2 MB Artikel-HTML, drei Weiterleitungen und 20 MB MP3. Private/lokale Artikel-URLs sind gesperrt. Bei Paywalls oder nicht unterstützten Seiten den Text direkt einfügen. Sitzungen enden nach 30 Minuten ohne API-Aktivität; fünf falsche Passwörter sperren das Konto für 15 Minuten.

## Prüfen

```sh
uv run pytest -q
uv run black --check app.py polycast tests
```

Standardmässig laufen die Tests mit SQLite im Speicher. Für PostgreSQL:

```sh
TEST_DATABASE_URL='postgresql+psycopg://polycast:dein-passwort@127.0.0.1:5432/polycast' uv run pytest -q
```

Jeder Test verwendet ein eigenes Schema und entfernt es danach; der Testbenutzer benötigt das Recht, Schemas anzulegen. Artikel- und KI-Antworten sind simuliert, das Testaudio enthält Stille. Es entstehen keine API-Kosten.

Für die Abnahme TC-01 bis TC-07 mit zwei Konten über die Oberfläche durchgehen: Registrierung/Login/Logout, Kontosperre, Artikel→Französisch A2, Audio/Download, Speichern/Verlauf, ungültige URLs und fremder Datenzugriff. Zusätzlich die 36 Sprachkombinationen, A2/B1/B2, Kernaussagen und vollständige Vertonung mit echten Texten beurteilen. Änderungen am Text müssen alte Ergebnisse verwerfen; API-Fehler müssen Eingaben erhalten. Chrome/Edge, Safari und Offlinewiedergabe prüfen. Ergebnisse mit Datum, Browser und Tester dokumentieren; grüne automatisierte Tests ersetzen diese Abnahme nicht.

## Backups

An Entwicklungstagen sichern; das Skript fragt ein Backup-Passwort ab:

```sh
uv run python -m polycast.backup
```

Pro Tag entsteht eine verschlüsselte Datei unter `backups/`. Das Passwort für die Wiederherstellung aufbewahren; alternativ über `BACKUP_PASSWORD` setzen. Mindestens sieben Tage alte Backups werden beim Backend-Start und vor jeder Sicherung entfernt. Ohne laufende App oder Skript bleiben sie bis zum nächsten Aufruf liegen. Manuell aufräumen:

```sh
python3 -m polycast.backup --cleanup
```

Einmal vor der Abnahme in eine **neue, leere** Datenbank wiederherstellen (Datum anpassen):

```sh
createdb --owner=polycast polycast_restore
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in backups/polycast-JJJJ-MM-TT.dump.enc | pg_restore --exit-on-error --no-owner --no-acl --host 127.0.0.1 --username polycast --dbname polycast_restore
```

Danach Benutzer, Texte und MP3 prüfen. Spätestens sieben Tage nach Projektabschluss Datenbanken, heruntergeladene Audios und Backups löschen.
