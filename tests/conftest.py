import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url

# Fail before importing app.database or opening any connection.
test_url = os.environ.get("TEST_DATABASE_URL")
if not test_url:
    raise pytest.UsageError(
        "Set TEST_DATABASE_URL to a dedicated PostgreSQL database ending in _test"
    )
parsed_url = make_url(test_url)
if parsed_url.drivername != "postgresql+psycopg" or not (
    parsed_url.database or ""
).endswith("_test"):
    raise pytest.UsageError(
        "TEST_DATABASE_URL must use postgresql+psycopg and a database ending in _test"
    )
os.environ["DATABASE_URL"] = test_url

from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrate_database():
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_pastes(migrate_database):
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE pastes"))
    yield
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE pastes"))


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
