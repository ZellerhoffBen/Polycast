from datetime import timedelta

from sqlmodel import Session, select

from database import LoginSession, User, now

CREDENTIALS = {"email": "BEN@example.com", "password": "school-project"}


def test_registration_and_logout(client, db_engine):
    response = client.post("/auth/register", json=CREDENTIALS)
    assert response.status_code == 201
    assert response.json()["email"] == "ben@example.com"
    assert "password_hash" not in response.json()
    assert client.post("/auth/register", json=CREDENTIALS).status_code == 409
    with Session(db_engine) as db:
        user = db.exec(select(User)).one()
        assert user.password_hash.startswith("$argon2id$")
    response = client.post("/auth/login", json=CREDENTIALS)
    token = response.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    with Session(db_engine) as db:
        assert db.exec(select(LoginSession)).one().token_hash != token
    assert client.post("/auth/logout", headers=headers).status_code == 204
    assert client.post("/auth/logout", headers=headers).status_code == 401


def test_lock_after_five_failed_logins(client, db_engine):
    client.post("/auth/register", json=CREDENTIALS)
    for _ in range(5):
        response = client.post(
            "/auth/login", json={**CREDENTIALS, "password": "incorrect"}
        )
        assert response.status_code == 401
    assert client.post("/auth/login", json=CREDENTIALS).status_code == 429
    with Session(db_engine) as db:
        user = db.exec(select(User)).one()
        user.locked_until = now() - timedelta(seconds=1)
        db.add(user)
        db.commit()
    assert client.post("/auth/login", json=CREDENTIALS).status_code == 200


def test_session_expires_after_inactivity(client, db_engine, auth):
    with Session(db_engine) as db:
        session = db.exec(select(LoginSession)).one()
        session.last_activity_at = now() - timedelta(minutes=31)
        db.add(session)
        db.commit()
    response = client.post("/auth/logout", headers=auth)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_expired"


def test_invalid_registration(client):
    for email, password in [("invalid", "long-password"), ("a@b.ch", "short")]:
        assert (
            client.post(
                "/auth/register", json={"email": email, "password": password}
            ).status_code
            == 422
        )
