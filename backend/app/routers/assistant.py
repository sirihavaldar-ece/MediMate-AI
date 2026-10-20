from typing import Annotated
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, VoiceCallConsent, VoiceCallLog
from app.rate_limit import limiter
from app.schemas_assistant import (
    AssistantChatRequest,
    AssistantChatResponse,
    IntegrationStatusResponse,
    VoiceCallLogResponse,
    VoiceConsentRequest,
    VoiceConsentResponse,
    VoiceTestRequest,
    VoiceTestResponse,
)
from app.security import get_current_user, require_role
from app.config import TWILIO_AUTH_TOKEN, TWILIO_STATUS_CALLBACK_URL
from app.services.ai_service import chat, integration_status, test_connection
from app.services.call_service import send_test_call

router = APIRouter(prefix="/api", tags=["AI and voice integrations"])
CurrentUser = Annotated[User, Depends(get_current_user)]
Database = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("/integrations/status", response_model=IntegrationStatusResponse)
def integrations_status(_user: CurrentUser) -> dict[str, str | bool]:
    return integration_status()


@router.post("/assistant/chat", response_model=AssistantChatResponse)
@limiter.limit("20/minute")
def assistant_chat(
    request: Request,
    payload: AssistantChatRequest,
    _user: CurrentUser,
) -> dict[str, str]:
    messages = [message.model_dump() for message in payload.messages]
    try:
        return chat(messages)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/integrations/nebius/test")
@limiter.limit("5/minute")
def nebius_test(request: Request, _user: CurrentUser) -> dict[str, str | bool]:
    try:
        return test_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/integrations/voice/test", response_model=VoiceTestResponse)
@limiter.limit("3/minute")
def voice_test(
    request: Request,
    payload: VoiceTestRequest,
    user: CurrentUser,
    database: Database,
) -> dict[str, str | None]:
    try:
        result = send_test_call(
            payload.phone_number,
            confirm_live_call=payload.confirm_live_call,
            recipient_consented=payload.recipient_consented,
        )
        if result["provider_call_id"]:
            database.add(
                VoiceCallLog(
                    dose_event_id=None,
                    patient_id=user.id,
                    attempt_number=1,
                    provider_call_id=result["provider_call_id"],
                    status=result["status"] or "initiated",
                )
            )
            database.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/integrations/voice/consent", response_model=VoiceConsentResponse)
def get_voice_consent(user: CurrentUser, database: Database) -> dict[str, object]:
    require_role(user, "patient")
    consent = (
        database.query(VoiceCallConsent)
        .filter_by(patient_id=user.id)
        .first()
    )
    configured = bool(
        integration_status()["voice_configured"]
    )
    return {
        "enabled": bool(consent and consent.enabled),
        "phone_number": consent.phone_number if consent and consent.enabled else None,
        "provider_configured": configured,
    }


@router.put("/integrations/voice/consent", response_model=VoiceConsentResponse)
def update_voice_consent(
    payload: VoiceConsentRequest,
    user: CurrentUser,
    database: Database,
) -> dict[str, object]:
    require_role(user, "patient")
    consent = (
        database.query(VoiceCallConsent)
        .filter_by(patient_id=user.id)
        .first()
    )
    if consent is None:
        consent = VoiceCallConsent(
            patient_id=user.id,
            phone_number=payload.phone_number if payload.enabled else None,
            enabled=payload.enabled,
        )
        database.add(consent)
    else:
        consent.enabled = payload.enabled
        consent.phone_number = payload.phone_number if payload.enabled else None
    database.commit()
    return {
        "enabled": consent.enabled,
        "phone_number": consent.phone_number,
        "provider_configured": bool(integration_status()["voice_configured"]),
    }


@router.get("/integrations/voice/history", response_model=list[VoiceCallLogResponse])
def voice_call_history(
    user: CurrentUser,
    database: Database,
) -> list[dict[str, object]]:
    if user.role == "patient":
        patient_ids = [user.id]
    else:
        patient_ids = [
            link.patient_id for link in user.caregiver_links if link.active
        ]
    call_logs = (
        database.query(VoiceCallLog)
        .filter(VoiceCallLog.patient_id.in_(patient_ids))
        .order_by(VoiceCallLog.attempt_at.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "id": call_log.id,
            "dose_event_id": call_log.dose_event_id,
            "patient_id": call_log.patient_id,
            "attempt_number": call_log.attempt_number,
            "status": call_log.status,
            "attempt_at": call_log.attempt_at.isoformat(),
        }
        for call_log in call_logs
    ]


@router.post("/calls/webhook/status", status_code=204)
async def twilio_status_webhook(request: Request, database: Database) -> Response:
    if not TWILIO_STATUS_CALLBACK_URL.startswith("https://") or not TWILIO_AUTH_TOKEN:
        raise HTTPException(status_code=503, detail="Signed call callbacks are not configured.")
    from twilio.request_validator import RequestValidator

    signature = request.headers.get("X-Twilio-Signature", "")
    raw_form = (await request.body()).decode("utf-8")
    form = dict(parse_qsl(raw_form, keep_blank_values=True))
    validator = RequestValidator(TWILIO_AUTH_TOKEN)
    if not validator.validate(TWILIO_STATUS_CALLBACK_URL, form, signature):
        raise HTTPException(status_code=403, detail="Invalid voice-provider signature.")
    call_id = form.get("CallSid")
    call_status = form.get("CallStatus")
    if not call_id or call_status not in {
        "queued",
        "ringing",
        "in-progress",
        "completed",
        "busy",
        "failed",
        "no-answer",
        "canceled",
    }:
        raise HTTPException(status_code=422, detail="Invalid call status callback payload.")
    call_log = (
        database.query(VoiceCallLog)
        .filter_by(provider_call_id=call_id)
        .first()
    )
    if call_log is None:
        raise HTTPException(status_code=404, detail="Voice call record not found.")
    call_log.status = call_status
    database.commit()
    return Response(status_code=204)
