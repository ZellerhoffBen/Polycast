import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import api
from database import get_db


@pytest.fixture
def db_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        admin = create_engine(url)
        schema = "test_" + uuid4().hex
        with admin.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {schema}"))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()
    if url:
        with admin.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


@pytest.fixture
def client(db_engine, monkeypatch):
    monkeypatch.setattr(api, "engine", db_engine)

    def test_db():
        with Session(db_engine) as db:
            yield db

    api.app.dependency_overrides[get_db] = test_db
    with TestClient(api.app) as client:
        yield client
    api.app.dependency_overrides.clear()


@pytest.fixture
def auth(client):
    credentials = {"email": "ben@example.com", "password": "school-project"}
    assert client.post("/auth/register", json=credentials).status_code == 201
    token = client.post("/auth/login", json=credentials).json()["token"]
    return {"Authorization": f"Bearer {token}"}
