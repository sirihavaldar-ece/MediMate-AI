from collections.abc import Generator
import os

# Never load a developer's private Twilio settings during automated tests.
for key in (
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_FROM_NUMBER",
    "TWILIO_PHONE_NUMBER",
    "TWILIO_STATUS_CALLBACK_URL",
):
    os.environ[key] = ""
os.environ["TWILIO_VOICE_TEMPLATE_URL"] = ""
os.environ["TWILIO_TRIAL_CUSTOM_TWIML"] = "false"
os.environ["ENABLE_VOICE_CALLS"] = "true"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app import main as app_main
from app.database import get_db
from app.main import app
from app.rate_limit import limiter

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def database() -> Generator[Session, None, None]:
    models.Base.metadata.create_all(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        models.Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(database: Session, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    limiter.reset()
    # Tests call scheduler cycles explicitly with the isolated fixture DB.
    monkeypatch.setattr(app_main, "start_scheduler", lambda: None)
    monkeypatch.setattr(app_main, "stop_scheduler", lambda: None)

    def override_get_db() -> Generator[Session, None, None]:
        yield database

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def register(
    client: TestClient,
    *,
    name: str,
    email: str,
    role: str = "patient",
) -> tuple[str, dict[str, object]]:
    response = client.post(
        "/api/auth/register",
        json={
            "name": name,
            "email": email,
            "password": "secure-test-passphrase",
            "role": role,
            "timezone": "UTC",
        },
    )
    assert response.status_code == 201, response.text
    result = response.json()
    return result["access_token"], result["user"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
