from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock, call

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import DoseEvent, Medication, NotificationLog
from app.services.reminder_service import (
    local_occurrence,
    materialize_events,
    process_scheduled_voice_reminders,
    run_scheduler_cycle,
)
from tests.conftest import auth, register


def medication_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Demo medication",
        "instructions": "Use instructions provided by the clinician.",
        "schedule_times": ["08:00", "20:00"],
        "start_date": date.today().isoformat(),
        "timezone": "UTC",
        "repeat_interval_minutes": 30,
        "escalation_delay_minutes": 120,
    }
    payload.update(overrides)
    return payload


def test_register_login_and_reject_weak_password(client: TestClient) -> None:
    response = client.post(
        "/api/auth/register",
        json={"name": "Test Patient", "email": "patient@example.com", "password": "short"},
    )
    assert response.status_code == 422

    token, user = register(
        client, name="Test Patient", email="patient@example.com"
    )
    assert "invitation_code" not in user
    assert client.get("/api/auth/invitation", headers=auth(token)).status_code == 200
    login = client.post(
        "/api/auth/login",
        json={
            "email": "PATIENT@example.com",
            "password": "secure-test-passphrase",
        },
    )
    assert login.status_code == 200
    assert user["role"] == "patient"
    assert client.get("/api/auth/me", headers=auth(token)).json()["email"] == "patient@example.com"
    logout = client.post("/api/auth/logout", headers=auth(token))
    assert logout.status_code == 204
    assert client.get("/api/auth/me", headers=auth(token)).status_code == 401


def test_persistent_cookie_session_requires_csrf_and_can_be_revoked(client: TestClient) -> None:
    created = client.post(
        "/api/auth/register",
        headers={"X-Auth-Mode": "cookie"},
        json={
            "name": "Cookie Patient",
            "email": "cookie@example.com",
            "password": "secure-test-passphrase",
            "role": "patient",
            "timezone": "UTC",
            "remember_me": True,
        },
    )
    assert created.status_code == 201
    assert created.json()["access_token"] is None
    csrf = created.cookies.get("medimate_csrf")
    assert created.cookies.get("medimate_session") and csrf
    assert "httponly" in created.headers["set-cookie"].lower()
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 403
    logout = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    assert logout.status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_patient_cannot_confirm_or_repeat_a_future_dose(
    client: TestClient,
    database: Session,
) -> None:
    token, user = register(client, name="Patient", email="future@example.com")
    medication = client.post(
        "/api/medications",
        json=medication_payload(schedule_times=["08:00"]),
        headers=auth(token),
    ).json()
    event = DoseEvent(
        patient_id=user["id"],
        medication_id=medication["id"],
        scheduled_at=(datetime.now(timezone.utc) + timedelta(hours=1)).replace(
            tzinfo=None
        ),
        status="upcoming",
    )
    database.add(event)
    database.commit()
    database.refresh(event)

    assert client.post(
        f"/api/doses/{event.id}/confirm", headers=auth(token)
    ).status_code == 409
    assert client.post(
        f"/api/doses/{event.id}/remind-again", headers=auth(token)
    ).status_code == 409
    database.refresh(event)
    assert event.status == "upcoming"


def test_patient_can_create_medication_and_dashboard_materializes_unique_events(
    client: TestClient,
) -> None:
    token, _ = register(client, name="Patient", email="patient@example.com")
    headers = auth(token)

    created = client.post(
        "/api/medications", json=medication_payload(), headers=headers
    )
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "Demo medication"
    assert client.get("/api/dashboard/patient", headers=headers).status_code == 200
    dashboard = client.get("/api/dashboard/patient", headers=headers).json()
    dose_ids = {event["id"] for event in dashboard["doses"]}
    client.get("/api/dashboard/patient", headers=headers)
    refreshed = client.get("/api/dashboard/patient", headers=headers).json()
    assert len(refreshed["doses"]) == 2
    assert dose_ids == {event["id"] for event in refreshed["doses"]}


def test_patient_dashboard_clears_confirmed_dose_and_shows_tomorrows_next_occurrence(
    client: TestClient,
    database: Session,
) -> None:
    token, user = register(
        client, name="Recurring Patient", email="recurring@example.com"
    )
    headers = auth(token)
    now = datetime.now(timezone.utc)
    today = now.date()
    medication = Medication(
        patient_id=user["id"],
        name="Daily reminder",
        instructions="Follow prescribed instructions.",
        schedule_times=["00:00"],
        start_date=today,
        timezone="UTC",
        repeat_interval_minutes=30,
        escalation_delay_minutes=10080,
    )
    database.add(medication)
    database.commit()
    database.refresh(medication)
    confirmed = DoseEvent(
        patient_id=user["id"],
        medication_id=medication.id,
        scheduled_at=datetime.combine(today, datetime.min.time()),
        status="confirmed_by_patient",
        confirmed_at=now.replace(tzinfo=None),
        confirmation_method="web",
    )
    database.add(confirmed)
    database.commit()
    database.refresh(confirmed)

    response = client.get("/api/dashboard/patient", headers=headers)

    assert response.status_code == 200
    dashboard = response.json()
    assert all(dose["id"] != confirmed.id for dose in dashboard["doses"])
    assert any(dose["id"] == confirmed.id for dose in dashboard["history"])
    next_dose = dashboard["next_dose"]
    assert next_dose["medication_name"] == medication.name
    assert datetime.fromisoformat(next_dose["scheduled_at"]).date() == today + timedelta(days=1)
    assert datetime.fromisoformat(next_dose["scheduled_at"]).strftime("%H:%M") == "00:00"

    dose_history = client.get("/api/history", headers=headers)
    assert any(event["id"] == confirmed.id for event in dose_history.json()["events"])


def test_medication_update_validates_dates_and_deactivation_cancels_pending_events(
    client: TestClient,
    database: Session,
) -> None:
    token, user = register(client, name="Patient", email="schedule@example.com")
    headers = auth(token)
    medication = client.post(
        "/api/medications",
        json=medication_payload(schedule_times=["08:00"]),
        headers=headers,
    ).json()
    upcoming = DoseEvent(
        patient_id=user["id"],
        medication_id=medication["id"],
        scheduled_at=(datetime.now(timezone.utc) + timedelta(hours=1)).replace(
            tzinfo=None
        ),
        status="upcoming",
    )
    database.add(upcoming)
    database.commit()
    database.refresh(upcoming)

    invalid = client.put(
        f"/api/medications/{medication['id']}",
        json={"end_date": (date.today() - timedelta(days=1)).isoformat()},
        headers=headers,
    )
    assert invalid.status_code == 422

    updated = client.put(
        f"/api/medications/{medication['id']}",
        json={"schedule_times": ["09:00", "13:00"]},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["schedule_times"] == ["09:00", "13:00"]

    deleted = client.delete(
        f"/api/medications/{medication['id']}", headers=headers
    )
    assert deleted.status_code == 204
    database.refresh(upcoming)
    assert upcoming.status == "cancelled"


def test_patient_confirmation_is_explicit_and_idempotent(
    client: TestClient,
    database: Session,
) -> None:
    token, user = register(client, name="Patient", email="patient@example.com")
    headers = auth(token)
    medication = client.post(
        "/api/medications",
        json=medication_payload(schedule_times=["08:00"]),
        headers=headers,
    ).json()
    event = DoseEvent(
        patient_id=user["id"],
        medication_id=medication["id"],
        scheduled_at=datetime.now(timezone.utc).replace(tzinfo=None),
        status="due",
    )
    database.add(event)
    database.commit()
    database.refresh(event)

    first = client.post(f"/api/doses/{event.id}/confirm", headers=headers)
    second = client.post(f"/api/doses/{event.id}/confirm", headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "confirmed_by_patient"
    assert second.json()["confirmation_method"] == "web"
    assert second.json()["confirmed_at"] == first.json()["confirmed_at"]


def test_unrelated_patient_cannot_view_or_confirm_another_dose(
    client: TestClient,
    database: Session,
) -> None:
    token_a, user_a = register(client, name="Patient A", email="a@example.com")
    token_b, _ = register(client, name="Patient B", email="b@example.com")
    medication = client.post(
        "/api/medications",
        json=medication_payload(schedule_times=["08:00"]),
        headers=auth(token_a),
    ).json()
    event = DoseEvent(
        patient_id=user_a["id"],
        medication_id=medication["id"],
        scheduled_at=datetime.now(timezone.utc).replace(tzinfo=None),
        status="due",
    )
    database.add(event)
    database.commit()
    database.refresh(event)

    response = client.get(f"/api/doses/{event.id}", headers=auth(token_b))
    assert response.status_code == 403
    response = client.post(f"/api/doses/{event.id}/confirm", headers=auth(token_b))
    assert response.status_code == 403


def test_only_invited_caregiver_can_access_patient_schedule(client: TestClient) -> None:
    patient_token, patient = register(
        client, name="Patient", email="patient@example.com"
    )
    caregiver_token, _ = register(
        client,
        name="Caregiver",
        email="caregiver@example.com",
        role="caregiver",
    )
    headers = auth(caregiver_token)
    medication = client.post(
        "/api/medications",
        json=medication_payload(patient_id=patient["id"]),
        headers=headers,
    )
    assert medication.status_code == 403

    invitation_code = client.get(
        "/api/auth/invitation", headers=auth(patient_token)
    ).json()["invitation_code"]
    linked = client.post(
        "/api/auth/caregivers/link",
        headers=headers,
        json={
            "patient_email": "patient@example.com",
            "invitation_code": invitation_code,
            "label": "Family caregiver",
        },
    )
    assert linked.status_code == 201
    rotated_code = client.get(
        "/api/auth/invitation", headers=auth(patient_token)
    ).json()["invitation_code"]
    assert rotated_code != invitation_code
    medication = client.post(
        "/api/medications",
        json=medication_payload(patient_id=patient["id"]),
        headers=headers,
    )
    assert medication.status_code == 201

    patient_dashboard = client.get(
        "/api/dashboard/patient", headers=auth(patient_token)
    )
    assert patient_dashboard.status_code == 200
    patient_dose_id = patient_dashboard.json()["doses"][0]["id"]
    assert client.post(
        f"/api/doses/{patient_dose_id}/confirm", headers=headers
    ).status_code == 403
    caregiver_dashboard = client.get("/api/dashboard/caregiver", headers=headers)
    assert caregiver_dashboard.status_code == 200
    assert len(caregiver_dashboard.json()["patients"]) == 1


def test_timezone_materialization_and_scheduler_recovery_are_idempotent(
    database: Session,
) -> None:
    from app.models import User
    from app.security import hash_password

    user = User(
        name="Timezone patient",
        email="timezone@example.test",
        password_hash=hash_password("secure-test-passphrase"),
        role="patient",
        timezone="America/Los_Angeles",
    )
    database.add(user)
    database.commit()
    database.refresh(user)
    medication = Medication(
        patient_id=user.id,
        name="Timezone medication",
        instructions="As prescribed.",
        schedule_times=["08:30"],
        start_date=date.today() - timedelta(days=1),
        timezone="America/Los_Angeles",
        repeat_interval_minutes=30,
        escalation_delay_minutes=120,
    )
    database.add(medication)
    database.commit()
    database.refresh(medication)

    materialize_events(database, user.id, date.today())
    materialize_events(database, user.id, date.today())
    events = database.query(DoseEvent).filter_by(medication_id=medication.id).all()
    assert len(events) == 2
    assert all(event.scheduled_at.tzinfo is None for event in events)

    past_event = DoseEvent(
        patient_id=user.id,
        medication_id=medication.id,
        scheduled_at=(datetime.now(timezone.utc) - timedelta(hours=3)).replace(
            tzinfo=None
        ),
        status="upcoming",
    )
    database.add(past_event)
    database.commit()
    run_scheduler_cycle(database)
    run_scheduler_cycle(database)
    database.refresh(past_event)
    logs = database.query(NotificationLog).filter_by(dose_event_id=past_event.id).all()
    assert past_event.status == "missed_unconfirmed"
    assert past_event.escalation_status == "sent"
    assert len(logs) == 1


def test_reminders_repeat_and_escalation_does_not_duplicate(database: Session) -> None:
    from app.models import User
    from app.security import hash_password

    now = datetime.now(timezone.utc)
    patient = User(
        name="Reminder patient",
        email="reminder@example.com",
        password_hash=hash_password("secure-test-passphrase"),
        role="patient",
        timezone="UTC",
    )
    database.add(patient)
    database.commit()
    database.refresh(patient)
    medication = Medication(
        patient_id=patient.id,
        name="Reminder test",
        instructions="As prescribed.",
        schedule_times=["08:00"],
        start_date=date.today(),
        timezone="UTC",
        repeat_interval_minutes=30,
        escalation_delay_minutes=120,
    )
    database.add(medication)
    database.commit()
    database.refresh(medication)
    event = DoseEvent(
        patient_id=patient.id,
        medication_id=medication.id,
        scheduled_at=(now - timedelta(minutes=20)).replace(tzinfo=None),
        status="upcoming",
    )
    database.add(event)
    database.commit()

    run_scheduler_cycle(database, now)
    run_scheduler_cycle(database, now + timedelta(minutes=10))
    reminders = (
        database.query(NotificationLog)
        .filter_by(dose_event_id=event.id, channel="patient_reminder")
        .count()
    )
    assert reminders == 1

    run_scheduler_cycle(database, now + timedelta(minutes=31))
    reminders = (
        database.query(NotificationLog)
        .filter_by(dose_event_id=event.id, channel="patient_reminder")
        .count()
    )
    assert reminders == 2

    run_scheduler_cycle(database, now + timedelta(hours=3))
    run_scheduler_cycle(database, now + timedelta(hours=4))
    assert (
        database.query(NotificationLog)
        .filter_by(dose_event_id=event.id, channel="caregiver_demo")
        .count()
        == 1
    )


def test_scheduler_restart_backfills_recent_missed_occurrences(database: Session) -> None:
    from app.models import User
    from app.security import hash_password

    now = datetime.now(timezone.utc)
    patient = User(
        name="Recovery patient",
        email="recovery@example.com",
        password_hash=hash_password("secure-test-passphrase"),
        role="patient",
        timezone="UTC",
    )
    database.add(patient)
    database.commit()
    database.refresh(patient)
    medication = Medication(
        patient_id=patient.id,
        name="Recovery test",
        instructions="As prescribed.",
        schedule_times=[(now - timedelta(hours=3)).strftime("%H:%M")],
        start_date=now.date() - timedelta(days=1),
        timezone="UTC",
        repeat_interval_minutes=30,
        escalation_delay_minutes=120,
    )
    database.add(medication)
    database.commit()

    run_scheduler_cycle(database, now, recover=True)
    recovered_event = (
        database.query(DoseEvent)
        .filter_by(patient_id=patient.id, medication_id=medication.id)
        .filter(DoseEvent.scheduled_at < now.replace(tzinfo=None))
        .first()
    )
    assert recovered_event is not None
    assert recovered_event.status == "missed_unconfirmed"


def test_scheduled_voice_call_requires_consent_and_is_not_retried(
    database: Session,
    monkeypatch,
) -> None:
    from app.models import User, VoiceCallConsent, VoiceCallLog
    from app.services import call_service
    from app.security import hash_password

    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    patient = User(
        name="Voice test patient",
        email="scheduled-voice@example.com",
        password_hash=hash_password("secure-test-passphrase"),
        role="patient",
        timezone="UTC",
    )
    database.add(patient)
    database.commit()
    database.refresh(patient)
    medication = Medication(
        patient_id=patient.id,
        name="Scheduled voice test",
        instructions="As prescribed.",
        schedule_times=["18:00"],
        start_date=now.date(),
        timezone="UTC",
        repeat_interval_minutes=30,
        escalation_delay_minutes=60,
    )
    database.add(medication)
    database.commit()
    database.refresh(medication)
    event = DoseEvent(
        patient_id=patient.id,
        medication_id=medication.id,
        scheduled_at=now.replace(tzinfo=None),
        status="upcoming",
    )
    stale_event = DoseEvent(
        patient_id=patient.id,
        medication_id=medication.id,
        scheduled_at=(now - timedelta(minutes=3)).replace(tzinfo=None),
        status="due",
    )
    database.add_all([event, stale_event])
    database.commit()
    database.refresh(event)

    run_scheduler_cycle(database, now)
    assert database.query(VoiceCallLog).filter_by(dose_event_id=event.id).count() == 0

    consent = VoiceCallConsent(
        patient_id=patient.id,
        phone_number="+15551234567",
        enabled=True,
    )
    database.add(consent)
    database.commit()
    provider = Mock(
        return_value={
            "mode": "twilio",
            "status": "failed",
            "provider_call_id": None,
        }
    )
    monkeypatch.setattr(call_service, "place_medication_reminder_call", provider)
    run_scheduler_cycle(database, now)
    run_scheduler_cycle(database, now + timedelta(seconds=30))
    logs = database.query(VoiceCallLog).filter_by(dose_event_id=event.id).all()
    assert len(logs) == 1
    assert logs[0].attempt_number == 1
    assert logs[0].status == "failed"
    provider.assert_called_once_with("+15551234567", "Scheduled voice test")
    assert database.query(VoiceCallLog).filter_by(dose_event_id=stale_event.id).count() == 0


def test_scheduled_voice_call_is_attempted_at_dose_time_without_quiet_hours(
    database: Session,
    monkeypatch,
) -> None:
    from app.models import User, VoiceCallConsent, VoiceCallLog
    from app.security import hash_password
    from app.services import call_service

    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    patient = User(
        name="Quiet hours patient",
        email="quiet-voice@example.com",
        password_hash=hash_password("secure-test-passphrase"),
        role="patient",
        timezone="UTC",
    )
    database.add(patient)
    database.commit()
    database.refresh(patient)
    medication = Medication(
        patient_id=patient.id,
        name="Quiet hours test",
        instructions="As prescribed.",
        schedule_times=["18:00"],
        start_date=now.date(),
        timezone="UTC",
        repeat_interval_minutes=30,
        escalation_delay_minutes=60,
    )
    database.add(medication)
    database.commit()
    database.refresh(medication)
    event = DoseEvent(
        patient_id=patient.id,
        medication_id=medication.id,
        scheduled_at=now.replace(tzinfo=None),
        status="upcoming",
    )
    database.add(event)
    database.add(
        VoiceCallConsent(
            patient_id=patient.id,
            phone_number="+15551234567",
            enabled=True,
        )
    )
    database.commit()
    provider = Mock(return_value={
        "mode": "twilio", "status": "queued", "provider_call_id": "CA-at-dose-time"
    })
    monkeypatch.setattr(call_service, "place_medication_reminder_call", provider)

    run_scheduler_cycle(database, now)

    logs = database.query(VoiceCallLog).filter_by(dose_event_id=event.id).all()
    assert len(logs) == 1
    assert logs[0].status == "queued"
    provider.assert_called_once_with("+15551234567", "Quiet hours test")


def test_failed_voice_call_gets_one_database_tracked_retry(
    database: Session, monkeypatch
) -> None:
    from app.models import User, VoiceCallConsent, VoiceCallLog
    from app.security import hash_password
    from app.services import call_service

    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    patient = User(
        name="Retry patient",
        email="retry-call@example.com",
        password_hash=hash_password("secure-test-passphrase"),
        role="patient",
        timezone="UTC",
    )
    database.add(patient)
    database.commit()
    database.refresh(patient)
    medication = Medication(
        patient_id=patient.id,
        name="Retry test",
        instructions="As prescribed.",
        schedule_times=["12:00"],
        start_date=now.date(),
        timezone="UTC",
        repeat_interval_minutes=30,
        escalation_delay_minutes=60,
    )
    database.add(medication)
    database.commit()
    database.refresh(medication)
    event = DoseEvent(
        patient_id=patient.id,
        medication_id=medication.id,
        scheduled_at=now.replace(tzinfo=None),
        status="due",
    )
    database.add(event)
    database.add(VoiceCallConsent(
        patient_id=patient.id, phone_number="+15551234567", enabled=True
    ))
    database.commit()

    provider = Mock(side_effect=[
        {"mode": "twilio", "status": "failed", "provider_call_id": None},
        {"mode": "twilio", "status": "queued", "provider_call_id": "CA-retry"},
    ])
    monkeypatch.setattr(call_service, "place_medication_reminder_call", provider)

    process_scheduled_voice_reminders(database, now)
    process_scheduled_voice_reminders(database, now + timedelta(minutes=4))
    assert provider.call_count == 1
    process_scheduled_voice_reminders(database, now + timedelta(minutes=5))

    attempts = (
        database.query(VoiceCallLog)
        .filter_by(dose_event_id=event.id)
        .order_by(VoiceCallLog.attempt_number)
        .all()
    )
    assert [call.attempt_number for call in attempts] == [1, 2]
    assert [call.status for call in attempts] == ["failed", "queued"]
    assert attempts[1].provider_call_id == "CA-retry"
    provider.assert_has_calls(
        [call("+15551234567", "Retry test"), call("+15551234567", "Retry test")]
    )


def test_daylight_saving_gap_is_skipped_and_repeated_hour_is_deterministic() -> None:
    nonexistent = local_occurrence(
        date(2026, 3, 8), "02:30", "America/New_York"
    )
    ambiguous = local_occurrence(
        date(2026, 11, 1), "01:30", "America/New_York"
    )
    assert nonexistent is None
    assert ambiguous == datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)


def test_invalid_medication_time_is_rejected(client: TestClient) -> None:
    token, _ = register(client, name="Patient", email="patient@example.com")
    response = client.post(
        "/api/medications",
        json=medication_payload(schedule_times=["25:70"]),
        headers=auth(token),
    )
    assert response.status_code == 422
