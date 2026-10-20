import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
load_dotenv(PROJECT_DIR / ".env")

DEFAULT_DATABASE_PATH = BACKEND_DIR / "medimate.db"

APP_NAME = os.getenv("APP_NAME", "MediMate AI")
DATABASE_URL = os.getenv("DATABASE_URL") or (
    f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"
)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL.removeprefix("postgres://")
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL.removeprefix("postgresql://")
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]
SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_urlsafe(48)
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "60"))
PERSISTENT_SESSION_DAYS = max(1, int(os.getenv("PERSISTENT_SESSION_DAYS", "30")))
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}
SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "lax").strip().lower()
REMINDER_INTERVAL_MINUTES = int(os.getenv("REMINDER_INTERVAL_MINUTES", "1"))
SCHEDULER_INTERVAL_SECONDS = max(
    1, int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "10"))
)
ESCALATION_DELAY_MINUTES = int(os.getenv("ESCALATION_DELAY_MINUTES", "60"))
NEBIUS_API_KEY = os.getenv("NEBIUS_API_KEY", "").strip()
NEBIUS_MODEL = os.getenv(
    "NEBIUS_MODEL", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
).strip()
NEBIUS_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
TWILIO_FROM_NUMBER = (
    os.getenv("TWILIO_FROM_NUMBER") or os.getenv("TWILIO_PHONE_NUMBER", "")
).strip()
TWILIO_VOICE_TEMPLATE_URL = os.getenv("TWILIO_VOICE_TEMPLATE_URL", "").strip()
TWILIO_TRIAL_CUSTOM_TWIML = os.getenv(
    "TWILIO_TRIAL_CUSTOM_TWIML", "false"
).strip().lower() in {"1", "true", "yes", "on"}
TWILIO_TRIAL_VOICE_TEMPLATES = frozenset(
    {
        "https://webhooks.twilio.com/v1/Voice/Template/voice_speech_recognition",
        "https://webhooks.twilio.com/v1/Voice/Template/voice_text_to_speech",
        "https://webhooks.twilio.com/v1/Voice/Template/voice_keyboard_input",
        "https://webhooks.twilio.com/v1/Voice/Template/voice_play_audio",
    }
)
TWILIO_STATUS_CALLBACK_URL = os.getenv("TWILIO_STATUS_CALLBACK_URL", "").strip()
ENABLE_VOICE_CALLS = os.getenv("ENABLE_VOICE_CALLS", "true").strip().lower() in {
    "1", "true", "yes", "on"
}
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
if SESSION_COOKIE_SAMESITE not in {"lax", "strict", "none"}:
    raise RuntimeError("SESSION_COOKIE_SAMESITE must be lax, strict, or none.")
if APP_ENV == "production" and not os.getenv("SECRET_KEY"):
    raise RuntimeError("SECRET_KEY must be configured in production.")
if APP_ENV == "production" and DATABASE_URL.startswith("sqlite"):
    raise RuntimeError("Production requires a persistent shared database, not SQLite.")
if APP_ENV == "production" and not SESSION_COOKIE_SECURE:
    raise RuntimeError("SESSION_COOKIE_SECURE must be true in production.")
if APP_ENV == "production" and SESSION_COOKIE_SAMESITE == "none":
    raise RuntimeError("Production SameSite=None cookies require a same-origin deployment or additional review.")
