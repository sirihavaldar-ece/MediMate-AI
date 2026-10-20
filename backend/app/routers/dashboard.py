from datetime import datetime, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CaregiverRelationship, DoseEvent, Medication, User
from app.schemas import (
    CaregiverDashboardResponse,
    CaregiverSummary,
    DoseResponse,
    HistoryResponse,
    PatientDashboardResponse,
    PatientSummary,
    UserResponse,
)
from app.security import get_current_user, require_role
from app.services.reminder_service import (
    dose_response,
    run_scheduler_cycle,
)

router = APIRouter(prefix="/api", tags=["dashboards"])
Database = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("/dashboard/patient", response_model=PatientDashboardResponse)
def patient_dashboard(database: Database, user: CurrentUser) -> PatientDashboardResponse:
    require_role(user, "patient")
    today = datetime.now(ZoneInfo(user.timezone)).date()
    run_scheduler_cycle(database)
    events = (
        database.query(DoseEvent)
        .filter_by(patient_id=user.id)
        .order_by(DoseEvent.scheduled_at.asc())
        .all()
    )
    todays_events = [
        event
        for event in events
        if event.scheduled_at.replace(tzinfo=timezone.utc)
        .astimezone(ZoneInfo(user.timezone))
        .date()
        == today
    ]
    caregivers = (
        database.query(CaregiverRelationship)
        .filter_by(patient_id=user.id, active=True)
        .all()
    )
    medications = (
        database.query(Medication)
        .filter_by(patient_id=user.id)
        .order_by(Medication.is_active.desc(), Medication.name)
        .all()
    )
    caregiver_summaries = [
        CaregiverSummary(
            id=link.caregiver.id,
            name=link.caregiver.name,
            email=link.caregiver.email,
            label=link.label,
        )
        for link in caregivers
    ]
    doses = [
        dose_response(event)
        for event in todays_events
        if event.status not in ("confirmed_by_patient", "cancelled")
    ]
    upcoming = [
        dose_response(event)
        for event in events
        if event.status == "upcoming"
        and event.scheduled_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
    ]
    next_dose = upcoming[0] if upcoming else None
    history = [
        dose_response(event)
        for event in todays_events
        if event.status in ("confirmed_by_patient", "missed_unconfirmed")
    ]
    return PatientDashboardResponse(
        user=UserResponse.model_validate(user),
        today=today,
        invitation_code=user.invitation_code,
        medications=medications,
        doses=[DoseResponse.model_validate(event) for event in doses],
        next_dose=DoseResponse.model_validate(next_dose) if next_dose else None,
        caregivers=caregiver_summaries,
        history=[DoseResponse.model_validate(event) for event in history],
    )


@router.get("/dashboard/caregiver", response_model=CaregiverDashboardResponse)
def caregiver_dashboard(database: Database, user: CurrentUser) -> CaregiverDashboardResponse:
    require_role(user, "caregiver")
    run_scheduler_cycle(database)
    links = (
        database.query(CaregiverRelationship)
        .filter_by(caregiver_id=user.id, active=True)
        .all()
    )
    patients = []
    now = datetime.now(timezone.utc)
    for link in links:
        patient = link.patient
        patient_today = now.astimezone(ZoneInfo(patient.timezone)).date()
        medications = (
            database.query(Medication)
            .filter_by(patient_id=patient.id)
            .all()
        )
        patient_events = (
            database.query(DoseEvent)
            .filter_by(patient_id=patient.id)
            .order_by(DoseEvent.scheduled_at.asc())
            .all()
        )
        patient_events = [
            event
            for event in patient_events
            if event.scheduled_at.replace(tzinfo=timezone.utc)
            .astimezone(ZoneInfo(patient.timezone))
            .date()
            == patient_today
            and event.status not in ("confirmed_by_patient", "cancelled")
        ]
        patients.append(
            PatientSummary(
                id=patient.id,
                name=patient.name,
                email=patient.email,
                timezone=patient.timezone,
                medications=medications,
                doses=[DoseResponse.model_validate(dose_response(event)) for event in patient_events],
            )
        )
    return CaregiverDashboardResponse(
        user=UserResponse.model_validate(user),
        patients=patients,
    )


@router.get("/history", response_model=HistoryResponse)
def history(database: Database, user: CurrentUser) -> HistoryResponse:
    if user.role == "patient":
        patient_ids = [user.id]
    else:
        patient_ids = [
            link.patient_id for link in user.caregiver_links if link.active
        ]
    events = (
        database.query(DoseEvent)
        .filter(DoseEvent.patient_id.in_(patient_ids))
        .order_by(DoseEvent.scheduled_at.desc())
        .limit(500)
        .all()
    )
    return HistoryResponse(
        events=[DoseResponse.model_validate(dose_response(event)) for event in events]
    )
