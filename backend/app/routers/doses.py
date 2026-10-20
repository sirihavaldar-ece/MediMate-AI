from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DoseEvent, NotificationLog, User, utc_now
from app.schemas import DoseResponse, NotificationResponse
from app.security import get_current_user
from app.services.reminder_service import (
    dose_response,
    get_dose,
    require_patient_event,
    run_scheduler_cycle,
)

router = APIRouter(prefix="/api/doses", tags=["dose events"])
Database = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("", response_model=list[DoseResponse])
def list_doses(
    database: Database,
    user: CurrentUser,
    patient_id: int | None = None,
) -> list[dict[str, object]]:
    from app.security import can_access_patient

    if user.role == "patient":
        target_ids = [user.id]
    else:
        links = user.caregiver_links
        target_ids = [
            link.patient_id
            for link in links
            if link.active
            and (patient_id is None or link.patient_id == patient_id)
        ]
        if patient_id is not None and not can_access_patient(database, user, patient_id):
            raise HTTPException(status_code=403, detail="You are not authorized to view this patient's doses.")
    run_scheduler_cycle(database)
    events = (
        database.query(DoseEvent)
        .filter(DoseEvent.patient_id.in_(target_ids))
        .order_by(DoseEvent.scheduled_at.desc())
        .limit(500)
        .all()
    )
    return [dose_response(event) for event in events]


@router.post("/{dose_id}/confirm", response_model=DoseResponse)
def confirm_dose(dose_id: int, database: Database, user: CurrentUser) -> dict[str, object]:
    event = get_dose(database, dose_id, user)
    require_patient_event(database, event, user)
    run_scheduler_cycle(database)
    database.refresh(event)
    if event.status == "cancelled":
        raise HTTPException(status_code=409, detail="This dose event has been cancelled.")
    if event.status == "upcoming":
        raise HTTPException(status_code=409, detail="This dose is not due yet.")
    if event.status != "confirmed_by_patient":
        event.status = "confirmed_by_patient"
        event.confirmed_at = utc_now()
        event.confirmation_method = "web"
        event.reminder_at = None
        database.commit()
        database.refresh(event)
    return dose_response(event)


@router.post("/{dose_id}/remind-again", response_model=NotificationResponse)
def remind_again(
    dose_id: int,
    database: Database,
    user: CurrentUser,
) -> NotificationResponse:
    event = get_dose(database, dose_id, user)
    require_patient_event(database, event, user)
    run_scheduler_cycle(database)
    database.refresh(event)
    if event.status not in ("due", "missed_unconfirmed"):
        raise HTTPException(status_code=409, detail="This dose is no longer awaiting a reminder.")
    event.status = "due"
    event.reminder_at = utc_now()
    database.add(
        NotificationLog(
            dose_event_id=event.id,
            channel="patient_reminder",
            result="simulated",
            detail="Patient requested another in-app reminder.",
        )
    )
    database.commit()
    database.refresh(event)
    return NotificationResponse(message="Reminder recorded in demo mode.", dose=dose_response(event))


@router.post("/{dose_id}/need-help", response_model=NotificationResponse)
def need_help(
    dose_id: int,
    database: Database,
    user: CurrentUser,
) -> NotificationResponse:
    event = get_dose(database, dose_id, user)
    require_patient_event(database, event, user)
    run_scheduler_cycle(database)
    database.refresh(event)
    if event.status not in ("due", "missed_unconfirmed"):
        raise HTTPException(status_code=409, detail="This dose is no longer awaiting help.")
    database.add(
        NotificationLog(
            dose_event_id=event.id,
            channel="caregiver_demo",
            result="simulated",
            detail="Patient requested caregiver help; no external notification is configured.",
        )
    )
    event.escalation_status = "requested"
    database.commit()
    database.refresh(event)
    return NotificationResponse(
        message="Help request recorded in demo mode. Contact your caregiver directly if you need immediate help.",
        dose=dose_response(event),
    )


@router.get("/{dose_id}", response_model=DoseResponse)
def get_dose_route(
    dose_id: int,
    database: Database,
    user: CurrentUser,
) -> dict[str, object]:
    return dose_response(get_dose(database, dose_id, user))
