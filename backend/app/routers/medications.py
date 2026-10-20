from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DoseEvent, Medication, NotificationLog, User, VoiceCallLog
from app.schemas import MedicationCreate, MedicationResponse, MedicationUpdate
from app.security import can_access_patient, get_current_user, validate_timezone

router = APIRouter(prefix="/api/medications", tags=["medications"])
Database = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def get_authorized_patient_id(
    database: Session,
    user: User,
    requested_patient_id: int | None,
) -> int:
    patient_id = user.id if user.role == "patient" else requested_patient_id
    if patient_id is None:
        raise HTTPException(status_code=422, detail="patient_id is required for caregiver requests.")
    if not can_access_patient(database, user, patient_id):
        raise HTTPException(status_code=403, detail="You are not authorized to manage this patient.")
    return patient_id


@router.get("", response_model=list[MedicationResponse])
def list_medications(
    database: Database,
    user: CurrentUser,
    patient_id: int | None = None,
) -> list[Medication]:
    target_id = get_authorized_patient_id(database, user, patient_id)
    return (
        database.query(Medication)
        .filter_by(patient_id=target_id)
        .order_by(Medication.is_active.desc(), Medication.name)
        .all()
    )


@router.post("", response_model=MedicationResponse, status_code=201)
def create_medication(
    payload: MedicationCreate,
    database: Database,
    user: CurrentUser,
) -> Medication:
    patient_id = get_authorized_patient_id(database, user, payload.patient_id)
    if not validate_timezone(payload.timezone):
        raise HTTPException(status_code=422, detail="Choose a valid time zone, such as Europe/London.")
    medication = Medication(
        patient_id=patient_id,
        name=payload.name.strip(),
        instructions=payload.instructions.strip(),
        schedule_times=payload.schedule_times,
        start_date=payload.start_date,
        end_date=payload.end_date,
        timezone=payload.timezone,
        repeat_interval_minutes=payload.repeat_interval_minutes,
        escalation_delay_minutes=payload.escalation_delay_minutes,
    )
    database.add(medication)
    database.commit()
    database.refresh(medication)
    return medication


@router.put("/{medication_id}", response_model=MedicationResponse)
def update_medication(
    medication_id: int,
    payload: MedicationUpdate,
    database: Database,
    user: CurrentUser,
) -> Medication:
    medication = database.get(Medication, medication_id)
    if medication is None:
        raise HTTPException(status_code=404, detail="Medication not found.")
    if not can_access_patient(database, user, medication.patient_id):
        raise HTTPException(status_code=403, detail="You are not authorized to manage this medication.")

    changes = payload.model_dump(exclude_unset=True)
    non_nullable_fields = set(changes) - {"end_date"}
    if any(changes[field] is None for field in non_nullable_fields):
        raise HTTPException(status_code=422, detail="Schedule fields cannot be null.")
    new_start_date = changes.get("start_date", medication.start_date)
    new_end_date = changes.get("end_date", medication.end_date)
    if new_end_date is not None and new_end_date < new_start_date:
        raise HTTPException(
            status_code=422, detail="End date must be on or after start date."
        )
    if "timezone" in changes and changes["timezone"] and not validate_timezone(changes["timezone"]):
        raise HTTPException(status_code=422, detail="Choose a valid time zone.")
    for field, value in changes.items():
        if isinstance(value, str) and field in {"name", "instructions"}:
            value = value.strip()
        setattr(medication, field, value)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    (
        database.query(DoseEvent)
        .filter(
            DoseEvent.medication_id == medication.id,
            DoseEvent.status.in_(("upcoming", "due")),
            DoseEvent.scheduled_at > now,
        )
        .update({DoseEvent.status: "cancelled"}, synchronize_session=False)
    )
    database.commit()
    database.refresh(medication)
    return medication


@router.delete("/{medication_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_medication(
    medication_id: int,
    database: Database,
    user: CurrentUser,
    permanent: bool = False,
) -> Response:
    medication = database.get(Medication, medication_id)
    if medication is None:
        raise HTTPException(status_code=404, detail="Medication not found.")
    if not can_access_patient(database, user, medication.patient_id):
        raise HTTPException(status_code=403, detail="You are not authorized to manage this medication.")
    if permanent:
        if medication.is_active:
            raise HTTPException(
                status_code=409,
                detail="Deactivate this schedule before deleting it permanently.",
            )
        dose_ids = [
            dose_id
            for (dose_id,) in database.query(DoseEvent.id)
            .filter_by(medication_id=medication.id)
            .all()
        ]
        if dose_ids:
            database.query(VoiceCallLog).filter(
                VoiceCallLog.dose_event_id.in_(dose_ids)
            ).delete(synchronize_session=False)
            database.query(NotificationLog).filter(
                NotificationLog.dose_event_id.in_(dose_ids)
            ).delete(synchronize_session=False)
            database.query(DoseEvent).filter(
                DoseEvent.id.in_(dose_ids)
            ).delete(synchronize_session=False)
        database.delete(medication)
        database.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    medication.is_active = False
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    (
        database.query(DoseEvent)
        .filter(
            DoseEvent.medication_id == medication.id,
            DoseEvent.status.in_(("upcoming", "due")),
        )
        .update({DoseEvent.status: "cancelled"}, synchronize_session=False)
    )
    database.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
