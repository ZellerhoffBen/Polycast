from html import escape

from fastapi.responses import HTMLResponse

API_URL = "http://127.0.0.1:8000"
APP_URL = "http://127.0.0.1:8501"
COOKIE_NAME = "polycast_session"


def auth_form(action, message=""):
    # Submit in the browser so the backend can set the HttpOnly cookie.
    label = {"login": "Anmelden", "register": "Registrieren", "logout": "Abmelden"}[
        action
    ]
    fields = ""
    if action != "logout":
        minimum = 'minlength="8"' if action == "register" else ""
        autocomplete = "new-password" if action == "register" else "current-password"
        fields = f"""
            <label>E-Mail<br><input type="email" name="email" required maxlength="254" autocomplete="username"></label><br>
            <label>Passwort<br><input type="password" name="password" required {minimum} autocomplete="{autocomplete}"></label><br>
        """
    if action == "register":
        fields += '<label>Passwort bestätigen<br><input type="password" name="password_confirmation" required minlength="8" autocomplete="new-password"></label><br>'
    return f"""
        <form method="post" action="{API_URL}/auth/browser/{action}">
            <p role="status">{escape(message)}</p>
            {fields}
            <button type="submit">{label}</button>
        </form>
    """


def auth_page(action, message, status):
    return HTMLResponse(
        '<!doctype html><html lang="de"><meta charset="utf-8"><title>Polycast</title>'
        '<body style="font-family: sans-serif; max-width: 480px; margin: 4rem auto"><h1>Polycast</h1>'
        + auth_form(action, message)
        + f'<p><a href="{APP_URL}">Zurück zu Polycast</a></p></body></html>',
        status_code=status,
    )
