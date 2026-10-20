import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    DoseEvent,
    Medication,
    NotificationLog,
    User,
    VoiceCallConsent,
    VoiceCallLog,
)
from app.security import can_access_patient

logger = logging.getLogger(__name__)
SCHEDULER_RECOVERY_DAYS = 30
VOICE_CALL_GRACE_MINUTES = 2
VOICE_CALL_MAX_ATTEMPTS = 2
VOICE_CALL_RETRY_DELAY = timedelta(minutes=5)


def utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def local_occurrence(day: date, time_text: str, timezone_name: str) -> datetime | None:
    local_tz = ZoneInfo(timezone_name)
    naive = datetime.combine(day, time.fromisoformat(time_text))
    localized = naive.replace(tzinfo=local_tz, fold=0)
    # A wall-clock time skipped by a daylight-saving transition is not a real dose time.
    if localized.astimezone(timezone.utc).astimezone(local_tz).replace(tzinfo=None) != naive:
        return None
    return localized.astimezone(timezone.utc)


def materialize_events(
    database: Session,
    patient_id: int,
    today: date | None = None,
    now: datetime | None = None,
    recovery_days: int = 0,
) -> None:
    current = utc_datetime(now or datetime.now(timezone.utc))
    medications = (
        database.query(Medication)
        .filter_by(patient_id=patient_id, is_active=True)
        .all()
    )
    for medication in medications:
        local_today = (
            today
            if today is not None
            else current.astimezone(ZoneInfo(medication.timezone)).date()
        )
        first_day = max(
            medication.start_date,
            local_today - timedelta(days=recovery_days),
        )
        day_count = (local_today + timedelta(days=1) - first_day).days + 1
        for day_offset in range(max(0, day_count)):
            scheduled_day = first_day + timedelta(days=day_offset)
            if medication.end_date is not None and scheduled_day > medication.end_date:
                continue
            for time_text in medication.schedule_times:
                scheduled_at = local_occurrence(
                    scheduled_day, time_text, medication.timezone
                )
                if scheduled_at is None:
                    continue
                exists = (
                    database.query(DoseEvent.id)
                    .filter_by(
                        medication_id=medication.id,
                        scheduled_at=scheduled_at.replace(tzinfo=None),
                    )
                    .first()
                )
                if exists is None:
                    database.add(
                        DoseEvent(
                            patient_id=patient_id,
                            medication_id=medication.id,
                            scheduled_at=scheduled_at.replace(tzinfo=None),
                            status="upcoming",
                        )
                    )
                else:
                    existing = database.get(DoseEvent, exists[0])
                    if existing is not None and existing.status == "cancelled":
                        existing.status = "upcoming"
    database.commit()


def materialize_active_schedules(
    database: Session,
    now: datetime | None = None,
    recovery_days: int = 0,
) -> None:
    current = utc_datetime(now or datetime.now(timezone.utc))
    patient_ids = (
        database.query(Medication.patient_id)
        .filter_by(is_active=True)
        .distinct()
        .all()
    )
    for (patient_id,) in patient_ids:
        materialize_events(
            database, patient_id, now=current, recovery_days=recovery_days
        )


def dose_response(event: DoseEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "patient_id": event.patient_id,
        "medication_id": event.medication_id,
        "medication_name": event.medication.name,
        "instructions": event.medication.instructions,
        "scheduled_at": utc_datetime(event.scheduled_at),
        "timezone": event.medication.timezone,
        "status": event.status,
        "confirmed_at": (
            utc_datetime(event.confirmed_at) if event.confirmed_at is not None else None
        ),
        "confirmation_method": event.confirmation_method,
        "escalation_status": event.escalation_status,
    }


def get_dose(database: Session, dose_id: int, user: User) -> DoseEvent:
    event = database.get(DoseEvent, dose_id)
    if event is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Dose event not found.")
    if not can_access_patient(database, user, event.patient_id):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="You are not authorized to view this dose.")
    return event


def run_scheduler_cycle(
    database: Session,
    now: datetime | None = None,
    recover: bool = False,
) -> None:
    current = utc_datetime(now or datetime.now(timezone.utc))
    materialize_active_schedules(
        database,
        current,
        recovery_days=SCHEDULER_RECOVERY_DAYS if recover else 0,
    )
    events = (
        database.query(DoseEvent)
        .filter(DoseEvent.status.in_(("upcoming", "due")))
        .all()
    )
    for event in events:
        medication = event.medication
        scheduled = utc_datetime(event.scheduled_at)
        scheduled_day = scheduled.astimezone(ZoneInfo(medication.timezone)).date()
        if (
            not medication.is_active
            or scheduled_day < medication.start_date
            or (
                medication.end_date is not None
                and scheduled_day > medication.end_date
            )
        ):
            event.status = "cancelled"
            event.reminder_at = None
            continue
        if scheduled > current:
            continue
        if event.status == "upcoming":
            event.status = "due"
            event.reminder_at = scheduled

        if event.status != "due":
            continue

        elapsed_minutes = (current - scheduled).total_seconds() / 60
        if elapsed_minutes >= medication.escalation_delay_minutes:
            event.status = "missed_unconfirmed"
            if event.escalation_status == "none":
                event.escalation_status = "sent"
                database.add(
                    NotificationLog(
                        dose_event_id=event.id,
                        channel="caregiver_demo",
                        result="simulated",
                        detail="Caregiver escalation due; no external notification configured.",
                    )
                )
            continue

        last_attempt = (
            database.query(NotificationLog)
            .filter_by(dose_event_id=event.id, channel="patient_reminder")
            .order_by(NotificationLog.attempt_at.desc())
            .first()
        )
        can_send = (
            last_attempt is None
            or (current - utc_datetime(last_attempt.attempt_at)).total_seconds()
            >= medication.repeat_interval_minutes * 60
        )
        if can_send:
            database.add(
                NotificationLog(
                    dose_event_id=event.id,
                    channel="patient_reminder",
                    result="simulated",
                    detail="Reminder recorded by the local prototype scheduler.",
                )
            )
            event.reminder_at = current.replace(tzinfo=None)
    database.commit()
    process_scheduled_voice_reminders(database, current)


def process_scheduled_voice_reminders(database: Session, current: datetime) -> None:
    current_utc = utc_datetime(current)
    earliest_call = current_utc - timedelta(minutes=10)
    events = (
        database.query(DoseEvent)
        .filter(
            DoseEvent.status == "due",
            DoseEvent.scheduled_at >= earliest_call.replace(tzinfo=None),
            DoseEvent.scheduled_at <= current_utc.replace(tzinfo=None),
        )
        .all()
    )
    for event in events:
        attempts = (
            database.query(VoiceCallLog)
            .filter_by(dose_event_id=event.id)
            .order_by(VoiceCallLog.attempt_number.desc())
            .first()
        )
        elapsed = current_utc - utc_datetime(event.scheduled_at)
        if attempts is None and elapsed > timedelta(minutes=VOICE_CALL_GRACE_MINUTES):
            # Explicit catch-up policy: skip calls more than two minutes late.
            continue
        attempt_number = (attempts.attempt_number + 1) if attempts else 1
        if attempts:
            if (
                elapsed > timedelta(minutes=10)
                or
                attempts.status not in {"failed", "busy", "no-answer"}
                or attempt_number > VOICE_CALL_MAX_ATTEMPTS
                or current_utc < utc_datetime(attempts.attempt_at) + VOICE_CALL_RETRY_DELAY
            ):
                continue
        consent = (
            database.query(VoiceCallConsent)
            .filter_by(patient_id=event.patient_id, enabled=True)
            .first()
        )
        if consent is None:
            continue
        patient = database.get(User, event.patient_id)
        if patient is None:
            logger.error(
                "Skipping voice escalation for dose event %s because its patient is missing.",
                event.id,
            )
            continue
        call_log = VoiceCallLog(
            dose_event_id=event.id,
            patient_id=event.patient_id,
            attempt_number=attempt_number,
            status="queued",
            attempt_at=current_utc.replace(tzinfo=None),
        )
        database.add(call_log)
        try:
            database.commit()
        except IntegrityError:
            # The database uniqueness constraint is the final guard when two
            # scheduler processes claim the same attempt concurrently.
            database.rollback()
            logger.info("Voice reminder attempt already claimed for dose event %s.", event.id)
            continue

        from app.services.call_service import place_medication_reminder_call

        try:
            result = place_medication_reminder_call(
                consent.phone_number,
                event.medication.name,
            )
            call_log.status = result["status"] or "failed"
            call_log.provider_call_id = result["provider_call_id"]
        except Exception:
            logger.exception("Could not complete a scheduled voice reminder.")
            call_log.status = "failed"
        database.add(
            NotificationLog(
                dose_event_id=event.id,
                channel="voice_call",
                result=call_log.status,
                detail=(
                    "Scheduled voice reminder attempt recorded; answering a call "
                    "never confirms a dose."
                ),
            )
        )
        database.commit()


def require_patient_event(database: Session, event: DoseEvent, user: User) -> None:
    from fastapi import HTTPException

    if user.role != "patient" or event.patient_id != user.id:
        raise HTTPException(
            status_code=403,
            detail="Only the patient assigned to this dose can confirm or repeat its reminder.",
        )
