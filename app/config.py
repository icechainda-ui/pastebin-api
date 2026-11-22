import os


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Set DATABASE_URL to a postgresql+psycopg connection URL")
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("DATABASE_URL must use the postgresql+psycopg driver")
    return url
