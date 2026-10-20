from datetime import date, datetime, timezone
from secrets import token_urlsafe

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    invitation_code: Mapped[str] = mapped_column(
        String(32), unique=True, default=lambda: token_urlsafe(12)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    medications: Mapped[list["Medication"]] = relationship(back_populates="patient")
    caregiver_links: Mapped[list["CaregiverRelationship"]] = relationship(
        foreign_keys="CaregiverRelationship.caregiver_id", back_populates="caregiver"
    )
    patient_links: Mapped[list["CaregiverRelationship"]] = relationship(
        foreign_keys="CaregiverRelationship.patient_id", back_populates="patient"
    )


class CaregiverRelationship(Base):
    __tablename__ = "caregiver_relationships"
    __table_args__ = (
        UniqueConstraint("patient_id", "caregiver_id", name="uq_patient_caregiver"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    caregiver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    label: Mapped[str] = mapped_column(String(80), default="Caregiver")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    patient: Mapped[User] = relationship(foreign_keys=[patient_id], back_populates="patient_links")
    caregiver: Mapped[User] = relationship(foreign_keys=[caregiver_id], back_populates="caregiver_links")


class Medication(Base):
    __tablename__ = "medications"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    instructions: Mapped[str] = mapped_column(Text, default="")
    schedule_times: Mapped[list[str]] = mapped_column(JSON)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    repeat_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    escalation_delay_minutes: Mapped[int] = mapped_column(Integer, default=120)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    patient: Mapped[User] = relationship(back_populates="medications")
    doses: Mapped[list["DoseEvent"]] = relationship(back_populates="medication")


class DoseEvent(Base):
    __tablename__ = "dose_events"
    __table_args__ = (
        UniqueConstraint(
            "medication_id", "scheduled_at", name="uq_medication_scheduled_occurrence"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    medication_id: Mapped[int] = mapped_column(ForeignKey("medications.id"), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(32), default="upcoming", index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmation_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalation_status: Mapped[str] = mapped_column(String(20), default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    medication: Mapped[Medication] = relationship(back_populates="doses")


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    dose_event_id: Mapped[int] = mapped_column(ForeignKey("dose_events.id"), index=True)
    channel: Mapped[str] = mapped_column(String(32))
    result: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(String(240), default="")
    attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class VoiceCallConsent(Base):
    __tablename__ = "voice_call_consents"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, index=True
    )
    phone_number: Mapped[str | None] = mapped_column(String(24), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Retained for compatibility with existing SQLite tables. They are no
    # longer configurable through the API or used to decide whether to call.
    quiet_start: Mapped[str] = mapped_column(String(5), default="21:00")
    quiet_end: Mapped[str] = mapped_column(String(5), default="08:00")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class VoiceCallLog(Base):
    __tablename__ = "voice_call_logs"
    __table_args__ = (
        UniqueConstraint(
            "dose_event_id", "attempt_number", name="uq_voice_event_attempt"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dose_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("dose_events.id"), index=True, nullable=True
    )
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    provider_call_id: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), index=True)
    attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


__all__ = [
    "Base",
    "CaregiverRelationship",
    "DoseEvent",
    "Medication",
    "NotificationLog",
    "RevokedToken",
    "VoiceCallConsent",
    "VoiceCallLog",
    "User",
    "utc_now",
]
