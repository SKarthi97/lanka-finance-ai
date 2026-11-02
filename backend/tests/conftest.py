import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import login_limiter
from app.main import app
from app.models import Bank, Base

PASSWORD = "correct horse battery"

LONG_TEXT = "Statement of account. " * 10  # comfortably above the text threshold


def make_pdf(pages: list[str] | None = None, password: str | None = None) -> bytes:
    """Build a small PDF. Each entry is one page's text ('' = blank page)."""
    doc = pymupdf.open()
    for text in pages if pages is not None else [LONG_TEXT]:
        page = doc.new_page()
        if text:
            page.insert_textbox(pymupdf.Rect(40, 40, 550, 800), text)
    try:
        if password:
            return doc.tobytes(
                encryption=pymupdf.PDF_ENCRYPT_AES_256,
                user_pw=password,
                owner_pw=password + "-owner",
            )
        return doc.tobytes()
    finally:
        doc.close()


@pytest.fixture()
def test_settings(tmp_path):
    return Settings(documents_dir=str(tmp_path / "documents"))


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with factory() as db:  # mirrors the seed row in migration 0002
        db.add(Bank(code="boc", name="Bank of Ceylon"))
        db.commit()

    return factory


@pytest.fixture()
def client(session_factory, test_settings):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: test_settings
    login_limiter._failures.clear()

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture()
def logged_in(client):
    """A client with a completed setup and an active session. Returns (client, csrf)."""
    response = client.post(
        "/api/auth/setup", json={"username": "owner", "password": PASSWORD}
    )
    assert response.status_code == 201
    return client, response.json()["csrf_token"]
