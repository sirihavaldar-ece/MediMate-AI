from datetime import date, datetime
import re
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.config import ESCALATION_DELAY_MINUTES, REMINDER_INTERVAL_MINUTES

class HealthResponse(BaseModel):
    status: str
    application: str


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    role: Literal["patient", "caregiver"] = "patient"
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    remember_me: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name cannot be blank.")
        return value.strip()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    remember_me: bool = False


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: EmailStr
    role: Literal["patient", "caregiver"]
    timezone: str


class TokenResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    user: UserResponse


class LinkCaregiverRequest(BaseModel):
    patient_email: EmailStr
    invitation_code: str = Field(min_length=8, max_length=32)
    label: str = Field(default="Caregiver", min_length=1, max_length=80)

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Relationship label cannot be blank.")
        return value.strip()


class MedicationCreate(BaseModel):
    patient_id: int | None = None
    name: str = Field(min_length=1, max_length=120)
    instructions: str = Field(default="", max_length=1000)
    schedule_times: list[str] = Field(min_length=1, max_length=12)
    start_date: date
    end_date: date | None = None
    timezone: str = Field(min_length=1, max_length=64)
    repeat_interval_minutes: int = Field(default=REMINDER_INTERVAL_MINUTES, ge=5, le=1440)
    escalation_delay_minutes: int = Field(default=ESCALATION_DELAY_MINUTES, ge=10, le=10080)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Medication name cannot be blank.")
        return value.strip()

    @field_validator("schedule_times")
    @classmethod
    def validate_times(cls, values: list[str]) -> list[str]:
        return validate_schedule_times(values)

    @model_validator(mode="after")
    def validate_date_range(self) -> "MedicationCreate":
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date.")
        return self


class MedicationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    instructions: str | None = Field(default=None, max_length=1000)
    schedule_times: list[str] | None = Field(default=None, min_length=1, max_length=12)
    start_date: date | None = None
    end_date: date | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    repeat_interval_minutes: int | None = Field(default=None, ge=5, le=1440)
    escalation_delay_minutes: int | None = Field(default=None, ge=10, le=10080)
    is_active: bool | None = None

    @field_validator("schedule_times")
    @classmethod
    def validate_times(cls, values: list[str] | None) -> list[str] | None:
        return validate_schedule_times(values) if values is not None else values

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Medication name cannot be blank.")
        return value.strip() if value is not None else value

    @model_validator(mode="after")
    def validate_date_range(self) -> "MedicationUpdate":
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("End date must be on or after start date.")
        return self


def validate_schedule_times(values: list[str]) -> list[str]:
    from datetime import time

    if len(values) != len(set(values)):
        raise ValueError("Schedule times must not contain duplicates.")
    try:
        for value in values:
            if re.fullmatch(r"\d{2}:\d{2}", value) is None:
                raise ValueError
            time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Schedule times must use HH:MM 24-hour format.") from exc
    return values


class MedicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    name: str
    instructions: str
    schedule_times: list[str]
    start_date: date
    end_date: date | None
    timezone: str
    is_active: bool
    repeat_interval_minutes: int
    escalation_delay_minutes: int


class DoseResponse(BaseModel):
    id: int
    patient_id: int
    medication_id: int
    medication_name: str
    instructions: str
    scheduled_at: datetime
    timezone: str
    status: str
    confirmed_at: datetime | None
    confirmation_method: str | None
    escalation_status: str


class CaregiverSummary(BaseModel):
    id: int
    name: str
    email: EmailStr
    label: str


class PatientSummary(BaseModel):
    id: int
    name: str
    email: EmailStr
    timezone: str
    medications: list[MedicationResponse]
    doses: list[DoseResponse]


class PatientDashboardResponse(BaseModel):
    user: UserResponse
    today: date
    invitation_code: str
    medications: list[MedicationResponse]
    doses: list[DoseResponse]
    next_dose: DoseResponse | None
    caregivers: list[CaregiverSummary]
    history: list[DoseResponse]


class CaregiverDashboardResponse(BaseModel):
    user: UserResponse
    patients: list[PatientSummary]


class HistoryResponse(BaseModel):
    events: list[DoseResponse]


class NotificationResponse(BaseModel):
    message: str
    dose: DoseResponse
