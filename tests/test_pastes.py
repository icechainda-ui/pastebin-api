from datetime import datetime
from unittest.mock import Mock

import pytest
from app.database import SessionLocal, engine
from app.models import Paste
from app.routers import pastes
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session


def test_create_persist_and_get_exact_text(client):
    content = "  Привет 👋\r\n\tdef example():\n    return 'text'  \r\n\n"
    with engine.connect() as connection:
        before = connection.scalar(select(func.clock_timestamp()))
    created = client.post("/pastes", json={"content": content})
    assert created.status_code == 201
    body = created.json()
    assert set(body) == {"id", "created_at", "title", "language", "management_key"}
    assert body["title"] is None
    assert body["language"] is None
    assert len(body["id"]) == 22
    assert created.headers["location"] == f"/pastes/{body['id']}"

    # A different session proves the write was committed, not merely flushed.
    with SessionLocal() as session:
        stored = session.get(Paste, body["id"])
        assert stored.content == content
        assert stored.created_at == datetime.fromisoformat(
            body["created_at"].replace("Z", "+00:00")
        )
        assert stored.created_at.utcoffset().total_seconds() == 0
        assert (
            before
            <= stored.created_at
            <= session.scalar(select(func.clock_timestamp()))
        )
    fetched = client.get(created.headers["location"])
    assert fetched.status_code == 200
    public = {key: value for key, value in body.items() if key != "management_key"}
    assert fetched.json() == {**public, "content": content}


def test_timestamp_default_is_set_by_postgres(client):
    # Direct SQL omits created_at entirely; PostgreSQL supplies transaction time.
    with engine.begin() as connection:
        row = connection.execute(
            text(
                "INSERT INTO pastes (id, content) VALUES (:id, :content) "
                "RETURNING created_at, now() AS database_now"
            ),
            {"id": "a" * 22, "content": "from SQL"},
        ).one()
        assert row.created_at == row.database_now
    fetched = client.get("/pastes/" + "a" * 22)
    assert (
        datetime.fromisoformat(fetched.json()["created_at"].replace("Z", "+00:00"))
        == row.created_at
    )


@pytest.mark.parametrize(
    "content",
    [" ", "\t\r\n  ", "a" * 100_000, "🙂" * 100_000],
    ids=["space", "whitespace", "max_ascii", "max_unicode"],
)
def test_valid_content_is_not_stripped(client, content):
    response = client.post("/pastes", json={"content": content})
    assert response.status_code == 201
    assert client.get(response.headers["location"]).json()["content"] == content


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"content": ""},
        {"content": "a" * 100_001},
        {"content": None},
        {"content": 123},
        {"content": ["text"]},
        {"content": "before\x00after"},
        {"content": "x", "created_at": "2000-01-01T00:00:00Z"},
    ],
)
def test_invalid_payload_does_not_insert(client, payload):
    assert client.post("/pastes", json=payload).status_code == 422
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Paste)) == 0


def test_malformed_json(client):
    response = client.post(
        "/pastes", content="{", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422


def test_unknown_id(client):
    assert client.get("/pastes/" + "z" * 22).status_code == 404


def test_identical_text_creates_independent_pastes(client):
    first = client.post("/pastes", json={"content": "same"})
    second = client.post("/pastes", json={"content": "same"})
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


def test_id_collision_rolls_back_then_retries(client, monkeypatch):
    first = client.post("/pastes", json={"content": "original"}).json()
    generate = Mock(side_effect=[first["id"], "b" * 22])
    monkeypatch.setattr(pastes.secrets, "token_urlsafe", generate)
    result = client.post("/pastes", json={"content": "new"})
    assert result.status_code == 201
    assert result.json()["id"] == "b" * 22
    assert generate.call_count == 2
    assert client.get("/pastes/" + first["id"]).json()["content"] == "original"
    assert client.get(result.headers["location"]).json()["content"] == "new"


def test_id_collision_attempts_are_bounded(client, monkeypatch):
    first = client.post("/pastes", json={"content": "original"}).json()
    generate = Mock(return_value=first["id"])
    monkeypatch.setattr(pastes.secrets, "token_urlsafe", generate)
    result = client.post("/pastes", json={"content": "new"})
    assert result.status_code == 503
    assert generate.call_count == pastes.MAX_ID_ATTEMPTS
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Paste)) == 1


@pytest.mark.parametrize(
    "constraint",
    [
        "CONSTRAINT test_content_check CHECK (content <> 'blocked')",
        "CONSTRAINT test_content_unique UNIQUE (content)",
    ],
)
def test_other_integrity_errors_do_not_retry(client, monkeypatch, constraint, caplog):
    # Real PostgreSQL errors: CHECK violation and UNIQUE on a different field.
    if "UNIQUE" in constraint:
        assert client.post("/pastes", json={"content": "blocked"}).status_code == 201
    constraint_name = constraint.split()[1]
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE pastes ADD {constraint}"))
    generate = Mock(return_value="c" * 22)
    monkeypatch.setattr(pastes.secrets, "token_urlsafe", generate)
    try:
        result = client.post("/pastes", json={"content": "blocked"})
        assert result.status_code == 503
        assert result.json() == {"detail": "Database operation failed"}
        assert generate.call_count == 1
        assert "blocked" not in caplog.text
        assert "Database operation failed" in caplog.text
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(f"ALTER TABLE pastes DROP CONSTRAINT {constraint_name}")
            )
    # A failed transaction must not poison subsequent requests.
    assert client.post("/pastes", json={"content": "after failure"}).status_code == 201


def test_operational_error_is_not_retried_and_rolls_back(client, monkeypatch, caplog):
    generate = Mock(return_value="d" * 22)
    original_rollback = Session.rollback
    calls = []

    def track_rollback(self):
        calls.append(True)
        return original_rollback(self)

    def fail_commit(self):
        raise OperationalError("INSERT secret SQL", {}, Exception("secret password"))

    monkeypatch.setattr(pastes.secrets, "token_urlsafe", generate)
    monkeypatch.setattr(Session, "commit", fail_commit)
    monkeypatch.setattr(Session, "rollback", track_rollback)
    result = client.post("/pastes", json={"content": "secret text"})
    assert result.status_code == 503
    assert generate.call_count == 1
    assert calls
    assert "secret" not in result.text + caplog.text
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Paste)) == 0
