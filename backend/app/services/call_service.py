import logging
import re
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

import httpx

from app.config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_FROM_NUMBER,
    TWILIO_STATUS_CALLBACK_URL,
    TWILIO_TRIAL_CUSTOM_TWIML,
    TWILIO_TRIAL_VOICE_TEMPLATES,
    TWILIO_VOICE_TEMPLATE_URL,
)
from app.services.ai_service import twilio_is_configured

logger = logging.getLogger(__name__)
PHONE_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")
TEST_CALL_MESSAGE = (
    "Hello. This is MediMate, your medication reminder assistant. This is a "
    "test call only. Please open the MediMate app if you need to review a reminder."
)
def callback_is_secure() -> bool:
    callback = urlsplit(TWILIO_STATUS_CALLBACK_URL)
    return callback.scheme == "https" and bool(callback.netloc)


def medication_reminder_twiml(medication_name: str) -> str:
    safe_name = escape(medication_name)
    return (
        "<Response><Say>Hey! It is time to take your medication, "
        f"{safe_name}. Please take it as prescribed. After taking it, visit the "
        "MediMate website and confirm by clicking the confirmation button. "
        "Thank you, and have a good day.</Say></Response>"
    )


def _submit_trial_call(payload: dict[str, str]) -> dict[str, str | None]:
    endpoint = (
        "https://api.twilio.com/2010-04-01/Accounts/"
        f"{TWILIO_ACCOUNT_SID}/Calls.json"
    )
    response = httpx.post(
        endpoint,
        data=payload,
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        timeout=20.0,
    )
    if not response.is_success:
        try:
            error_code = response.json().get("code")
        except (ValueError, AttributeError):
            error_code = None
        logger.error(
            "Twilio trial call failed (HTTP %s, code %s).",
            response.status_code,
            error_code,
        )
        response.raise_for_status()

    call = response.json()
    return {
        "mode": "twilio",
        "status": str(call.get("status") or "queued"),
        "provider_call_id": str(call.get("sid") or "") or None,
    }


def _trial_callback_payload() -> dict[str, str]:
    return {"StatusCallback": TWILIO_STATUS_CALLBACK_URL} if callback_is_secure() else {}


def _create_trial_custom_twiml_call(
    phone_number: str,
    twiml: str,
) -> dict[str, str | None]:
    return _submit_trial_call(
        {
            "To": phone_number,
            "Twiml": twiml,
            **_trial_callback_payload(),
        }
    )


def _create_trial_template_call(phone_number: str) -> dict[str, str | None]:
    if TWILIO_VOICE_TEMPLATE_URL not in TWILIO_TRIAL_VOICE_TEMPLATES:
        raise ValueError(
            "TWILIO_VOICE_TEMPLATE_URL must be an approved Twilio trial template URL."
        )

    return _submit_trial_call(
        {
            "To": phone_number,
            "Url": TWILIO_VOICE_TEMPLATE_URL,
            **_trial_callback_payload(),
        }
    )


def _create_call(
    phone_number: str,
    twiml: str,
    *,
    allow_trial_template_fallback: bool = True,
) -> dict[str, str | None]:
    if TWILIO_TRIAL_CUSTOM_TWIML:
        try:
            return _create_trial_custom_twiml_call(phone_number, twiml)
        except httpx.HTTPStatusError as exc:
            if (
                exc.response.status_code != 400
                or not TWILIO_VOICE_TEMPLATE_URL
                or not allow_trial_template_fallback
            ):
                if exc.response.status_code == 400 and not allow_trial_template_fallback:
                    logger.error(
                        "Twilio rejected personalized medication TwiML; the static trial template was not used."
                    )
                raise
            logger.warning(
                "Twilio rejected trial custom TwiML; falling back to the approved voice template."
            )
            return _create_trial_template_call(phone_number)
    if TWILIO_VOICE_TEMPLATE_URL:
        return _create_trial_template_call(phone_number)

    from twilio.rest import Client

    callback_options = ({
        "status_callback": TWILIO_STATUS_CALLBACK_URL,
        "status_callback_method": "POST",
        "status_callback_event": ["initiated", "ringing", "answered", "completed"],
    } if callback_is_secure() else {})
    call = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN).calls.create(
        to=phone_number,
        from_=TWILIO_FROM_NUMBER,
        twiml=twiml,
        timeout=20,
        **callback_options,
    )
    return {
        "mode": "twilio",
        "status": str(call.status),
        "provider_call_id": str(call.sid),
    }


def place_medication_reminder_call(
    phone_number: str,
    medication_name: str = "your medicine",
) -> dict[str, str | None]:
    if not twilio_is_configured():
        return {
            "mode": "demo",
            "status": "simulated",
            "provider_call_id": None,
        }
    try:
        return _create_call(
            phone_number,
            medication_reminder_twiml(medication_name),
        )
    except Exception as exc:
        # Provider exceptions may include phone/account data; keep logs sanitized.
        logger.error("Twilio medication reminder failed (%s).", type(exc).__name__)
        return {
            "mode": "twilio",
            "status": "failed",
            "provider_call_id": None,
        }
def send_test_call(
    phone_number: str | None,
    *,
    confirm_live_call: bool,
    recipient_consented: bool,
) -> dict[str, str | None]:
    if not twilio_is_configured():
        logger.info("Simulated MediMate voice test; no call provider configured.")
        return {
            "mode": "demo",
            "status": "simulated",
            "message": (
                "Demo call recorded. No phone number was called. Add Twilio credentials "
                "and enable recipient consent before making a live call."
            ),
            "provider_call_id": None,
        }
    if not confirm_live_call:
        logger.info("Simulated MediMate voice test; live-call confirmation was not supplied.")
        return {
            "mode": "demo",
            "status": "simulated",
            "message": "Demo call recorded. No phone number was called.",
            "provider_call_id": None,
        }
    if not recipient_consented:
        raise ValueError("Record recipient consent before placing a live test call.")
    if phone_number is None or not PHONE_PATTERN.fullmatch(phone_number):
        raise ValueError("Enter a phone number in international E.164 format.")
    try:
        result = _create_call(
            phone_number,
            "<Response><Say voice=\"alice\">"
            "Hello. This is MediMate. This is a test call only. "
            "Please open the MediMate app if you need to review a reminder."
            "</Say></Response>",
        )
    except Exception as exc:
        logger.error("Twilio test call request failed (%s).", type(exc).__name__)
        raise RuntimeError("The voice provider could not place the test call.") from exc

    return {
        "mode": result["mode"],
        "status": result["status"],
        "message": "Test call submitted. Answering a call never confirms a dose.",
        "provider_call_id": result["provider_call_id"],
    }
