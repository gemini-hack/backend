from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from app.db.database import async_session_factory
from app.models import Patient, Appointment, Alert, AgentAction
from app.utils.logger import logger

__all__ = [
    "SessionCache",
    "get_session_cache",
    "set_session_cache",
    "clear_session_cache",
    "preload_session_data",
]


@dataclass
class SessionCache:
    """Cached data for a voice session."""

    organization_id: UUID
    user_id: UUID
    loaded_at: datetime = field(default_factory=datetime.utcnow)

    # Cached data
    patients: dict[str, Any] = field(default_factory=dict)
    patients_by_name: dict[str, str] = field(default_factory=dict)
    today_appointments: list[dict] = field(default_factory=list)
    active_alerts: list[dict] = field(default_factory=list)
    caseload_summary: dict[str, int] = field(default_factory=dict)

    def is_stale(self, max_age_seconds: int = 300) -> bool:
        """Check if cache is older than max_age_seconds."""
        age = (datetime.utcnow() - self.loaded_at).total_seconds()
        return age > max_age_seconds

    def get_patient_by_name(self, name: str) -> dict | None:
        """Search cached patients by name (case-insensitive)."""
        name_lower = name.lower()
        for patient in self.patients.values():
            full_name = f"{patient['first_name']} {patient['last_name']}".lower()
            if (
                name_lower in patient["first_name"].lower()
                or name_lower in patient["last_name"].lower()
                or name_lower in full_name
            ):
                return patient
        return None

    def get_patient_by_id(self, patient_uid: str) -> dict | None:
        """Get cached patient by UID."""
        uid_lower = patient_uid.lower()
        for uid, patient in self.patients.items():
            if uid_lower in uid.lower():
                return patient
        return None


# Context variable for the session cache
_session_cache: ContextVar[SessionCache | None] = ContextVar(
    "voice_session_cache",
    default=None,
)


def get_session_cache() -> SessionCache | None:
    """Get the current session cache."""
    return _session_cache.get()


def set_session_cache(cache: SessionCache) -> None:
    """Set the session cache."""
    _session_cache.set(cache)


def clear_session_cache() -> None:
    """Clear the session cache."""
    _session_cache.set(None)


async def preload_session_data(organization_id: UUID, user_id: UUID) -> SessionCache:
    """Preload frequently-accessed data for a voice session.

    Args:
        organization_id: Organization to load data for
        user_id: User initiating the session

    Returns:
        SessionCache with preloaded data
    """
    logger.info(f"Preloading session data for org={organization_id}")
    start_time = datetime.utcnow()

    cache = SessionCache(organization_id=organization_id, user_id=user_id)

    async with async_session_factory() as session:
        # Load active patients for this organization
        patients_query = select(Patient).where(
            and_(
                Patient.organization_id == organization_id,
                Patient.status == "active",
            )
        )
        result = await session.execute(patients_query)
        patients = result.scalars().all()

        for p in patients:
            cache.patients[p.patient_uid] = {
                "id": str(p.id),
                "patient_uid": p.patient_uid,
                "first_name": p.first_name,
                "last_name": p.last_name,
                "status": p.status,
                "primary_condition": p.primary_condition,
                "phone": p.phone,
                "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            }

        # Load today's appointments
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)

        apt_query = (
            select(Appointment)
            .where(
                and_(
                    Appointment.organization_id == organization_id,
                    Appointment.scheduled_time >= today,
                    Appointment.scheduled_time < tomorrow,
                )
            )
            .options(selectinload(Appointment.patient))
        )
        result = await session.execute(apt_query)
        appointments = result.scalars().all()

        for apt in appointments:
            cache.today_appointments.append({
                "id": str(apt.id),
                "scheduled_time": apt.scheduled_time.isoformat(),
                "appointment_type": apt.appointment_type,
                "status": apt.status.value if apt.status else None,
                "patient_name": f"{apt.patient.first_name} {apt.patient.last_name}" if apt.patient else "Unknown",
                "patient_uid": apt.patient.patient_uid if apt.patient else None,
            })

        # Load active alerts
        alerts_query = (
            select(Alert)
            .where(
                and_(
                    Alert.organization_id == organization_id,
                    Alert.status == "pending",
                )
            )
            .options(selectinload(Alert.patient))
            .order_by(Alert.severity.desc())
            .limit(20)
        )
        result = await session.execute(alerts_query)
        alerts = result.scalars().all()

        for alert in alerts:
            cache.active_alerts.append({
                "id": str(alert.id),
                "title": alert.title,
                "severity": alert.severity,
                "patient_name": f"{alert.patient.first_name} {alert.patient.last_name}" if alert.patient else "Unknown",
                "patient_uid": alert.patient.patient_uid if alert.patient else None,
            })

        # Caseload summary counts
        patient_count = len(patients)
        alert_count = len(alerts)

        action_count_result = await session.execute(
            select(func.count(AgentAction.id)).where(
                and_(
                    AgentAction.organization_id == organization_id,
                    AgentAction.status == "pending",
                )
            )
        )
        action_count = action_count_result.scalar() or 0

        cache.caseload_summary = {
            "active_patients": patient_count,
            "active_alerts": alert_count,
            "pending_actions": action_count,
        }

    elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
    logger.info(
        f"Session data preloaded: {len(cache.patients)} patients, "
        f"{len(cache.today_appointments)} appointments, "
        f"{len(cache.active_alerts)} alerts in {elapsed:.1f}ms"
    )

    return cache
