from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.services import ai_service, call_service
from app.models import DoseEvent, Medication, VoiceCallLog
from tests.conftest import auth, register


def test_chat_uses_safe_local_mock_without_nebius_key(monkeypatch) -> None:
    monkeypatch.setattr(ai_service, "NEBIUS_API_KEY", "")

    result = ai_service.chat([{"role": "user", "content": "How do I use the app?"}])

    assert result["mode"] == "mock"
    assert "demo assistant" in result["reply"]
    assert result["model"] == ai_service.NEBIUS_MODEL


def test_chat_gives_deterministic_safe_response_for_dose_decision(monkeypatch) -> None:
    monkeypatch.setattr(ai_service, "NEBIUS_API_KEY", "configured-for-test")

    result = ai_service.chat([{"role": "user", "content": "I forgot, should I take another dose?"}])

    assert result["mode"] == "nebius"
    assert "tell you to take" in result["reply"]
    assert "contact your caregiver" in result["reply"]


def test_emergency_message_never_calls_model(monkeypatch) -> None:
    monkeypatch.setattr(ai_service, "NEBIUS_API_KEY", "configured-for-test")
    with patch.object(ai_service, "_client") as create_client:
        result = ai_service.chat(
            [{"role": "user", "content": "I have chest pain and trouble breathing"}]
        )

    create_client.assert_not_called()
    assert "emergency services now" in result["reply"]


def test_nebius_chat_uses_configured_model_and_openai_compatible_client(monkeypatch) -> None:
    monkeypatch.setattr(ai_service, "NEBIUS_API_KEY", "private-test-key")
    fake_completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Hello from Nemotron."))]
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=Mock())
        )
    )
    fake_client.chat.completions.create.return_value = fake_completion

    with patch.object(ai_service, "OpenAI") as openai_constructor:
        openai_constructor.return_value = fake_client
        result = ai_service.chat([{"role": "user", "content": "Explain due status."}])

    openai_constructor.assert_called_once_with(
        api_key="private-test-key",
        base_url="https://api.tokenfactory.nebius.com/v1/",
        timeout=20.0,
        max_retries=0,
    )
    fake_client.chat.completions.create.assert_called_once()
    assert fake_client.chat.completions.create.call_args.kwargs["model"] == ai_service.NEBIUS_MODEL
    assert result == {
        "reply": "Hello from Nemotron.",
        "mode": "nebius",
        "model": ai_service.NEBIUS_MODEL,
    }


def test_nebius_test_without_key_reports_mock_mode(monkeypatch) -> None:
    monkeypatch.setattr(ai_service, "NEBIUS_API_KEY", "")

    result = ai_service.test_connection()

    assert result["configured"] is False
    assert result["mode"] == "mock"
    assert ai_service.NEBIUS_MODEL in result["model"]


def test_voice_test_uses_simulation_without_twilio_credentials(monkeypatch) -> None:
    monkeypatch.setattr(call_service, "twilio_is_configured", lambda: False)

    result = call_service.send_test_call(
        None, confirm_live_call=False, recipient_consented=False
    )

    assert result["mode"] == "demo"
    assert result["status"] == "simulated"
    assert result["provider_call_id"] is None


def test_medication_call_uses_inline_twiml_without_callback_and_returns_sid(monkeypatch):
    monkeypatch.setattr(call_service, "twilio_is_configured", lambda: True)
    monkeypatch.setattr(call_service, "callback_is_secure", lambda: False)
    fake_call = SimpleNamespace(status="queued", sid="CA-medication-test")
    with patch("twilio.rest.Client") as twilio_client:
        twilio_client.return_value.calls.create.return_value = fake_call
        result = call_service.place_medication_reminder_call("+15551234567")

    kwargs = twilio_client.return_value.calls.create.call_args.kwargs
    assert kwargs["to"] == "+15551234567"
    assert "Please take it as prescribed" in kwargs["twiml"]
    assert "status_callback" not in kwargs
    assert result == {
        "mode": "twilio",
        "status": "queued",
        "provider_call_id": "CA-medication-test",
    }


def test_twilio_readiness_requires_credentials_and_e164_caller_but_not_callback(
    monkeypatch,
) -> None:
    from app import config

    import app.services.call_service as call_module

    monkeypatch.setattr(config, "TWILIO_ACCOUNT_SID", "AC" + "a" * 32)
    monkeypatch.setattr(config, "TWILIO_AUTH_TOKEN", "a" * 32)
    monkeypatch.setattr(config, "TWILIO_FROM_NUMBER", "invalid")
    monkeypatch.setattr(
        config, "TWILIO_STATUS_CALLBACK_URL", "https://backend.example.test/callback"
    )
    monkeypatch.setattr(
        call_module,
        "TWILIO_STATUS_CALLBACK_URL",
        "https://backend.example.test/callback",
    )
    assert ai_service.twilio_is_configured() is False
    assert ai_service.integration_status()["voice_configured"] is False

    monkeypatch.setattr(config, "TWILIO_FROM_NUMBER", "+15551234567")
    monkeypatch.setattr(config, "TWILIO_STATUS_CALLBACK_URL", "https://")
    monkeypatch.setattr(call_module, "TWILIO_STATUS_CALLBACK_URL", "https://")
    assert ai_service.twilio_is_configured() is True
    assert ai_service.integration_status()["voice_configured"] is True

    monkeypatch.setattr(
        config,
        "TWILIO_STATUS_CALLBACK_URL",
        "https://backend.example.test/api/calls/webhook/status",
    )
    monkeypatch.setattr(
        call_module,
        "TWILIO_STATUS_CALLBACK_URL",
        "https://backend.example.test/api/calls/webhook/status",
    )
    assert ai_service.integration_status()["voice_configured"] is True


def test_live_voice_call_requires_explicit_confirmation_and_consent(monkeypatch) -> None:
    monkeypatch.setattr(call_service, "twilio_is_configured", lambda: True)

    simulated = call_service.send_test_call(
        "+15551234567",
        confirm_live_call=False,
        recipient_consented=False,
    )
    assert simulated["mode"] == "demo"
    assert simulated["provider_call_id"] is None

    try:
        call_service.send_test_call(
            "+15551234567",
            confirm_live_call=True,
            recipient_consented=False,
        )
    except ValueError as error:
        assert "consent" in str(error)
    else:
        raise AssertionError("A live call must require recorded consent.")

    monkeypatch.setattr(call_service, "callback_is_secure", lambda: False)
    fake_call = SimpleNamespace(status="queued", sid="CA-test")
    with patch("twilio.rest.Client") as twilio_client:
        twilio_client.return_value.calls.create.return_value = fake_call
        result = call_service.send_test_call(
            "+15551234567",
            confirm_live_call=True,
            recipient_consented=True,
        )
    assert result["provider_call_id"] == "CA-test"
    assert "status_callback" not in twilio_client.return_value.calls.create.call_args.kwargs


def test_authenticated_integration_endpoints_work_in_demo_mode(
    client: TestClient,
    monkeypatch,
) -> None:
    token, _ = register(client, name="Assistant User", email="assistant@example.com")
    headers = auth(token)
    monkeypatch.setattr(ai_service, "NEBIUS_API_KEY", "")
    monkeypatch.setattr(call_service, "twilio_is_configured", lambda: False)

    status_response = client.get("/api/integrations/status", headers=headers)
    assert status_response.status_code == 200
    assert status_response.json()["ai_mode"] == "mock"
    assert status_response.json()["ai_model"] == ai_service.NEBIUS_MODEL

    test_response = client.post("/api/integrations/nebius/test", headers=headers)
    assert test_response.status_code == 200
    assert test_response.json()["mode"] == "mock"

    chat_response = client.post(
        "/api/assistant/chat",
        headers=headers,
        json={"messages": [{"role": "user", "content": "What does due mean?"}]},
    )
    assert chat_response.status_code == 200
    assert chat_response.json()["mode"] == "mock"

    voice_response = client.post(
        "/api/integrations/voice/test", headers=headers, json={}
    )
    assert voice_response.status_code == 200
    assert voice_response.json()["status"] == "simulated"
    assert voice_response.json()["provider_call_id"] is None


def test_live_voice_test_is_saved_for_callback_tracking(
    client: TestClient, monkeypatch
) -> None:
    import app.routers.assistant as assistant_router

    token, _ = register(
        client, name="Voice Test Patient", email="voice-test@example.com"
    )
    monkeypatch.setattr(
        assistant_router,
        "send_test_call",
        lambda *_args, **_kwargs: {
            "mode": "twilio",
            "status": "initiated",
            "provider_call_id": "CA-test-voice",
            "message": "Test call initiated.",
        },
    )

    response = client.post(
        "/api/integrations/voice/test",
        headers=auth(token),
        json={
            "phone_number": "+15551234567",
            "confirm_live_call": True,
            "recipient_consented": True,
        },
    )

    assert response.status_code == 200
    history = client.get(
        "/api/integrations/voice/history", headers=auth(token)
    )
    assert history.status_code == 200
    assert history.json()[0]["status"] == "initiated"
    assert history.json()[0]["dose_event_id"] is None


def test_assistant_endpoint_requires_user_final_message(client: TestClient) -> None:
    token, _ = register(client, name="Assistant User", email="assistant2@example.com")
    response = client.post(
        "/api/assistant/chat",
        headers=auth(token),
        json={"messages": [{"role": "assistant", "content": "Untrusted assistant text"}]},
    )
    assert response.status_code == 422


def test_patient_can_enable_and_withdraw_voice_call_consent(
    client: TestClient, monkeypatch
) -> None:
    import app.routers.assistant as assistant_router

    monkeypatch.setattr(
        assistant_router,
        "integration_status",
        lambda: {
            "voice_configured": False,
            "voice_mode": "demo",
            "ai_configured": False,
            "ai_mode": "mock",
            "ai_model": ai_service.NEBIUS_MODEL,
        },
    )
    token, _ = register(client, name="Voice Patient", email="voice-patient@example.com")
    headers = auth(token)
    enabled = client.put(
        "/api/integrations/voice/consent",
        headers=headers,
        json={
            "phone_number": "+15551234567",
            "enabled": True,
            "quiet_start": "21:00",
            "quiet_end": "08:00",
        },
    )
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert enabled.json()["phone_number"] == "+15551234567"
    assert enabled.json()["provider_configured"] is False

    revoked = client.put(
        "/api/integrations/voice/consent",
        headers=headers,
        json={
            "phone_number": "+15551234567",
            "enabled": False,
            "quiet_start": "21:00",
            "quiet_end": "08:00",
        },
    )
    assert revoked.status_code == 200
    assert revoked.json()["enabled"] is False
    assert revoked.json()["phone_number"] is None


def test_caregiver_cannot_change_patient_voice_call_consent(client: TestClient) -> None:
    token, _ = register(
        client,
        name="Voice Caregiver",
        email="voice-caregiver@example.com",
        role="caregiver",
    )
    response = client.put(
        "/api/integrations/voice/consent",
        headers=auth(token),
        json={
            "phone_number": "+15551234567",
            "enabled": True,
            "quiet_start": "21:00",
            "quiet_end": "08:00",
        },
    )
    assert response.status_code == 403


def test_twilio_status_webhook_requires_valid_signature_and_updates_call(
    client: TestClient,
    database,
    monkeypatch,
) -> None:
    import app.routers.assistant as assistant_router
    from twilio.request_validator import RequestValidator

    token, user = register(
        client, name="Webhook Patient", email="webhook@example.com"
    )
    medication = Medication(
        patient_id=user["id"],
        name="Webhook test medication",
        instructions="As prescribed.",
        schedule_times=["08:00"],
        start_date=date.today(),
        timezone="UTC",
        repeat_interval_minutes=30,
        escalation_delay_minutes=60,
    )
    database.add(medication)
    database.commit()
    database.refresh(medication)
    event = DoseEvent(
        patient_id=user["id"],
        medication_id=medication.id,
        scheduled_at=datetime.now(timezone.utc).replace(tzinfo=None),
        status="due",
    )
    database.add(event)
    database.commit()
    database.refresh(event)
    call_log = VoiceCallLog(
        dose_event_id=event.id,
        patient_id=user["id"],
        attempt_number=1,
        provider_call_id="CA123456",
        status="initiated",
    )
    database.add(call_log)
    database.commit()
    monkeypatch.setattr(
        assistant_router, "TWILIO_STATUS_CALLBACK_URL",
        "https://example.test/api/calls/webhook/status",
    )
    monkeypatch.setattr(assistant_router, "TWILIO_AUTH_TOKEN", "test-auth-token")
    callback_url = "https://example.test/api/calls/webhook/status"
    form = {"CallSid": "CA123456", "CallStatus": "completed"}
    signature = RequestValidator("test-auth-token").compute_signature(
        callback_url, form
    )

    invalid = client.post(
        "/api/calls/webhook/status",
        data=form,
        headers={"X-Twilio-Signature": "incorrect"},
    )
    assert invalid.status_code == 403

    valid = client.post(
        "/api/calls/webhook/status",
        data=form,
        headers={"X-Twilio-Signature": signature},
    )
    assert valid.status_code == 204
    database.refresh(call_log)
    assert call_log.status == "completed"
    assert client.get(
        "/api/integrations/voice/history", headers=auth(token)
    ).json()[0]["status"] == "completed"
