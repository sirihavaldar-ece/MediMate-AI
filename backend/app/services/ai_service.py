import logging
import re
from collections.abc import Sequence

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from app.config import NEBIUS_API_KEY, NEBIUS_BASE_URL, NEBIUS_MODEL

logger = logging.getLogger(__name__)
AI_TIMEOUT_SECONDS = 20.0
MAX_HISTORY_MESSAGES = 12

SYSTEM_PROMPT = """You are MediMate, a friendly and concise medication-companion assistant.
You can explain how this app works and explain schedule statuses using only information
the user provides in this chat. Use short, plain-language replies suitable for older adults.

Safety rules:
- Do not diagnose, prescribe, or recommend changing a medicine, dose, or schedule.
- Never say that a dose was taken or confirmed. Only the patient can confirm using the app.
- Do not tell a user to take an extra dose, skip a dose, or double a dose. If they are
  uncertain, advise them to contact their caregiver, pharmacist, or clinician.
- For a possible emergency, tell the user to contact local emergency services now.
- Do not claim that browser-closed alarms, phone calls, or caregiver messages are active.
- Do not request passwords, API keys, or unnecessary personal or medical details.
- You have no tools and cannot change schedules, send calls, or update dose status.
"""

EMERGENCY_PATTERN = re.compile(
    r"\b(chest pain|can't breathe|cannot breathe|trouble breathing|"
    r"unconscious|stroke|overdose|suicid|severe allergic|emergency)\b",
    re.IGNORECASE,
)
DOSE_DECISION_PATTERN = re.compile(
    r"\b(?:should i|can i|may i|do i)\s+(?:take|skip|double|change|"
    r"increase|decrease)\b|"
    r"\b(?:forgot|missed|unsure|not sure)\b.{0,40}\b(?:dose|medicine|medication)\b|"
    r"\b(?:double|skip|extra|another)\s+(?:(?:my|the|a|an)\s+)?"
    r"(?:dose|medicine|medication)\b|"
    r"\b(?:take|change|increase|decrease)\s+(?:(?:my|the|a|an)\s+)?"
    r"(?:dose|medicine|medication)\b",
    re.IGNORECASE,
)


def integration_mode() -> str:
    return "nebius" if NEBIUS_API_KEY else "mock"


def integration_status() -> dict[str, str | bool]:
    # Inline TwiML is sent in the Calls API request. A public callback is
    # optional for status updates and must not gate call creation.
    voice_configured = twilio_is_configured()
    return {
        "ai_mode": integration_mode(),
        "ai_model": NEBIUS_MODEL,
        "ai_configured": bool(NEBIUS_API_KEY),
        "voice_mode": "twilio" if voice_configured else "demo",
        "voice_configured": voice_configured,
    }


def twilio_is_configured() -> bool:
    from app.config import (
        ENABLE_VOICE_CALLS,
        TWILIO_ACCOUNT_SID,
        TWILIO_AUTH_TOKEN,
        TWILIO_FROM_NUMBER,
        TWILIO_TRIAL_CUSTOM_TWIML,
        TWILIO_TRIAL_VOICE_TEMPLATES,
        TWILIO_VOICE_TEMPLATE_URL,
    )

    if TWILIO_TRIAL_CUSTOM_TWIML:
        call_route_configured = True
    elif TWILIO_VOICE_TEMPLATE_URL:
        call_route_configured = (
            TWILIO_VOICE_TEMPLATE_URL in TWILIO_TRIAL_VOICE_TEMPLATES
        )
    else:
        call_route_configured = bool(
            re.fullmatch(r"\+[1-9]\d{7,14}", TWILIO_FROM_NUMBER)
        )
    return bool(
        ENABLE_VOICE_CALLS
        and TWILIO_ACCOUNT_SID
        and TWILIO_AUTH_TOKEN
        and call_route_configured
    )


def deterministic_safety_response(message: str) -> str | None:
    if EMERGENCY_PATTERN.search(message):
        return (
            "I can’t assess emergencies. Contact your local emergency services now "
            "or ask someone nearby to help."
        )
    if DOSE_DECISION_PATTERN.search(message):
        return (
            "I can’t tell you to take, skip, double, or change a dose. Follow your "
            "prescribed instructions. If you are unsure whether you took it, contact "
            "your caregiver, pharmacist, or clinician before taking more."
        )
    return None


def mock_reply(message: str) -> str:
    safety_reply = deterministic_safety_response(message)
    if safety_reply:
        return safety_reply
    return (
        "I’m the MediMate demo assistant. I can explain how to use this app and "
        "what reminder statuses mean, but I can’t give medical advice or change "
        "a schedule. For your prescribed plan, follow your clinician’s instructions."
    )


def _client() -> OpenAI:
    if not NEBIUS_API_KEY:
        raise RuntimeError("NEBIUS_API_KEY is not configured.")
    return OpenAI(
        api_key=NEBIUS_API_KEY,
        base_url=NEBIUS_BASE_URL,
        timeout=AI_TIMEOUT_SECONDS,
        max_retries=0,
    )


def chat(messages: Sequence[dict[str, str]]) -> dict[str, str]:
    if not messages:
        raise ValueError("At least one user message is required.")
    last_user_message = next(
        (message["content"] for message in reversed(messages) if message["role"] == "user"),
        "",
    )
    safety_reply = deterministic_safety_response(last_user_message)
    mode = integration_mode()
    if safety_reply:
        return {"reply": safety_reply, "mode": mode, "model": NEBIUS_MODEL}
    if not NEBIUS_API_KEY:
        return {
            "reply": mock_reply(last_user_message),
            "mode": "mock",
            "model": NEBIUS_MODEL,
        }

    try:
        response = _client().chat.completions.create(
            model=NEBIUS_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                *messages[-MAX_HISTORY_MESSAGES:],
            ],
            temperature=0.2,
            max_tokens=240,
        )
    except APITimeoutError as exc:
        logger.warning("Nebius assistant request timed out.")
        raise RuntimeError("The AI service timed out. Please try again.") from exc
    except APIConnectionError as exc:
        logger.warning("Could not connect to Nebius Token Factory.")
        raise RuntimeError("Could not connect to the AI service. Please try again later.") from exc
    except APIStatusError as exc:
        logger.warning("Nebius Token Factory returned HTTP %s.", exc.status_code)
        raise RuntimeError(
            "The AI service rejected the request. Check the model and API key configuration."
        ) from exc

    reply = response.choices[0].message.content
    if not reply:
        raise RuntimeError("The AI service returned an empty reply.")
    return {"reply": reply.strip(), "mode": "nebius", "model": NEBIUS_MODEL}


def test_connection() -> dict[str, str | bool]:
    if not NEBIUS_API_KEY:
        return {
            "configured": False,
            "mode": "mock",
            "model": NEBIUS_MODEL,
            "message": "Nebius is not configured. The local mock assistant is ready.",
        }
    result = chat([{"role": "user", "content": "Reply with: Nebius connection successful."}])
    return {
        "configured": True,
        "mode": result["mode"],
        "model": result["model"],
        "message": result["reply"],
    }
