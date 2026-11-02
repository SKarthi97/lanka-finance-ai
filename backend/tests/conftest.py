import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.deps import login_limiter
from app.main import app
from app.models import Base


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    login_limiter._failures.clear()

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


PASSWORD = "correct horse battery"


@pytest.fixture()
def logged_in(client):
    """A client with a completed setup and an active session. Returns (client, csrf)."""
    response = client.post(
        "/api/auth/setup", json={"username": "owner", "password": PASSWORD}
    )
    assert response.status_code == 201
    return client, response.json()["csrf_token"]
