"""Test fixtures: temporary SQLite database + FastAPI TestClient."""

# The app resolves the current date as UTC for users without a timezone.
# Pin the process timezone to UTC so `date.today()` (server-local) matches,
# regardless of the developer machine's timezone.
import os
import time

os.environ["TZ"] = "UTC"
time.tzset()

# Import models before app to (a) register them in Base.metadata for create_all
# and (b) avoid shadowing the `app` FastAPI instance with the `app` package name.
import app.models.bill  # noqa: F401
import app.models.category  # noqa: F401
import app.models.payment  # noqa: F401
import app.models.reset_token  # noqa: F401
import app.models.restore_snapshot  # noqa: F401
import app.models.import_draft  # noqa: F401
import app.models.app_setting  # noqa: F401
import app.models.user  # noqa: F401

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.database import Base, configure_sqlite_engine, get_db
from app.main import app

# Raise per-scope rate limits to an effectively unbounded value so the suite's
# shared 127.0.0.1 (and per-user) buckets never trip 429. Limits are read at
# request time, so mutating the settings singleton here is sufficient.
from app.core.config import settings as _settings

for _scope in (
    "login",
    "login_account",
    "register",
    "forgot_password",
    "reset_password",
    "change_password",
    "change_email",
    "send_now",
    "restore",
    "import",
):
    setattr(_settings, f"{_scope}_rate_limit", 100000)


@pytest.fixture(scope="session")
def sqlite_engine(tmp_path_factory):
    """One temp-file SQLite database for the whole session.

    A file (rather than :memory:) keeps every connection pointed at the same
    data without StaticPool tricks, and each test still starts from an empty
    schema via create_all/drop_all.
    """
    db_path = tmp_path_factory.mktemp("platybill") / "test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    configure_sqlite_engine(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_tables(sqlite_engine):
    Base.metadata.create_all(bind=sqlite_engine)
    yield
    Base.metadata.drop_all(bind=sqlite_engine)


@pytest.fixture()
def db_session(sqlite_engine, db_tables):
    Session = sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False)
    db = Session()
    yield db
    db.close()


@pytest.fixture()
def db_sessionmaker(sqlite_engine, db_tables):
    return sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False)


@pytest.fixture()
def client(sqlite_engine):
    Base.metadata.create_all(bind=sqlite_engine)
    _SessionLocal = sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False)

    def _override_get_db():
        db = _SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=sqlite_engine)


@pytest.fixture()
def client_db(sqlite_engine):
    """TestClient + direct DB session sharing the same engine."""
    Base.metadata.create_all(bind=sqlite_engine)
    SessionLocal = sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        db = SessionLocal()
        yield c, db
        db.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=sqlite_engine)


def register_and_login(
    client: TestClient, email: str, password: str = "pw123456"
) -> str:
    """Register a user and return their Bearer token.

    The JWT is no longer returned in the body: it is set as an HttpOnly
    cookie, which the TestClient exposes on the response.
    """
    r = client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.cookies["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def sync_payments(client: TestClient, token: str, month: str | None = None) -> None:
    """Seed payment instances for the current month (or a given month), then return."""
    from datetime import date as _date

    target = month or _date.today().strftime("%Y-%m")
    r = client.post(f"/bills/sync-instances?month={target}", headers=auth(token))
    assert r.status_code == 204, r.text
