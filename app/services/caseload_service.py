import uuid
from typing import List, Optional

from sqlalchemy import or_, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.patient import Patient, PatientStatus
from app.models.conditions import Condition
from app.models.user import User, UserRole
from app.models.agent import Alert, AlertStatus, AlertSeverity, AgentAction
from app.utils.logger import logger
from app.utils.exceptions import NotFoundException, BadRequestException


class CaseloadService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_my_caseload(
        self,
        worker: User,
        search: Optional[str] = None,
        condition: Optional[Condition] = None,
        status: Optional[PatientStatus] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> dict:
        """
        Get patients assigned to the worker, sorted by priority.
        
        Uses QueryBuilder for cleaner query construction.
        """
        # Build filter conditions
        conditions = [
            Patient.organization_id == worker.organization_id,
            or_(
                Patient.assigned_nurse_id == worker.id,
                Patient.care_coordinator_id == worker.id,
                Patient.primary_physician_id == worker.id,
            ),
        ]
        
        # Apply optional filters
        if status:
            conditions.append(Patient.status == status)
        else:
            conditions.append(Patient.status == PatientStatus.ACTIVE)
            
        if condition:
            conditions.append(Patient.primary_condition == condition)
            
        if search:
            search_term = f"%{search}%"
            conditions.append(
                or_(
                    Patient.first_name.ilike(search_term),
                    Patient.last_name.ilike(search_term),
                    Patient.patient_uid.ilike(search_term),
                    # Full name search: "John Doe"
                    func.concat(Patient.first_name, ' ', Patient.last_name).ilike(search_term),
                )
            )

        # Use QueryBuilder for count
        total = await Patient.query(self.db).filter(*conditions).count()

        # Use QueryBuilder for fetching with eager loading
        patients = await (
            Patient.query(self.db)
            .filter(*conditions)
            .with_relations(
                "hiv_profile",
                "hypertension_profile", 
                "diabetes_profile",
                "alerts",
                "agent_actions",
            )
            .all()
        )

        # Calculate priority for each patient
        scored_patients = [
            (self._calculate_priority_sync(p), p) for p in patients
        ]
        scored_patients.sort(key=lambda x: x[0], reverse=True)
        
        # Apply pagination after sorting
        paginated = scored_patients[skip : skip + limit]

        return {
            "patients": [p for _, p in paginated],
            "total": total,
            "skip": skip,
            "limit": limit,
        }

    async def get_unassigned_patients(
        self,
        organization_id: uuid.UUID,
        search: Optional[str] = None,
        condition: Optional[Condition] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> dict:
        """Get active patients with no care team members assigned (no physician, nurse, or coordinator)."""
        conditions = [
            Patient.organization_id == organization_id,
            Patient.status == PatientStatus.ACTIVE,
            # Patient must have NO care team members assigned
            and_(
                Patient.primary_physician_id.is_(None),
                Patient.assigned_nurse_id.is_(None),
                Patient.care_coordinator_id.is_(None),
            ),
        ]
        
        if condition:
            conditions.append(Patient.primary_condition == condition)
            
        if search:
            search_term = f"%{search}%"
            conditions.append(
                or_(
                    Patient.first_name.ilike(search_term),
                    Patient.last_name.ilike(search_term),
                    Patient.patient_uid.ilike(search_term),
                    # Full name search: "John Doe"
                    func.concat(Patient.first_name, ' ', Patient.last_name).ilike(search_term),
                )
            )

        # Use fresh QueryBuilder instances to avoid mutation issues
        total = await Patient.query(self.db).filter(*conditions).count()
        
        patients = await (
            Patient.query(self.db)
            .filter(*conditions)
            .with_relations("hiv_profile", "hypertension_profile", "diabetes_profile")
            .order_by(Patient.created_at, desc=True)
            .offset(skip)
            .limit(limit)
            .all()
        )
        
        return {
            "patients": patients,
            "total": total,
            "skip": skip,
            "limit": limit,
        }

    async def assign_patient(
        self,
        patient_uid: str,
        worker_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> Patient:
        """Assign a patient to a worker based on their role."""
        # Fetch patient
        patient = await Patient.fetch_unique(
            self.db,
            patient_uid=patient_uid,
            organization_id=organization_id,
        )
        if not patient:
            raise NotFoundException("Patient not found")

        # Fetch and verify worker exists and belongs to org
        worker = await User.fetch_unique(
            self.db,
            id=worker_id,
            organization_id=organization_id,
        )
        if not worker:
            raise NotFoundException("Worker not found or not in your organization")

        # Determine which field to assign based on worker's role
        role_field_map = {
            UserRole.DOCTOR: "primary_physician_id",
            UserRole.ORG_ADMIN: "primary_physician_id",
            UserRole.ORG_OWNER: "primary_physician_id",
            UserRole.NURSE: "assigned_nurse_id",
            UserRole.COORDINATOR: "care_coordinator_id",
        }
        
        role_name_map = {
            "primary_physician_id": "physician",
            "assigned_nurse_id": "nurse", 
            "care_coordinator_id": "coordinator",
        }
        
        field_name = role_field_map.get(worker.role)
        if not field_name:
            raise BadRequestException(f"Workers with role '{worker.role.value}' cannot be assigned to patients")
        
        role_display = role_name_map[field_name]
        
        # Check if this role slot is already filled
        current_assignee_id = getattr(patient, field_name)
        if current_assignee_id:
            if current_assignee_id == worker_id:
                raise BadRequestException(f"This patient is already assigned to you as {role_display}")
            else:
                # Get the current assignee's name for a better error message
                current_worker = await User.fetch_unique(
                    self.db,
                    id=current_assignee_id,
                    organization_id=organization_id,
                )
                worker_name = current_worker.full_name if current_worker else "another worker"
                raise BadRequestException(f"This patient already has a {role_display} assigned: {worker_name}")

        # Assign worker to the appropriate field
        setattr(patient, field_name, worker_id)
        await patient.save(self.db)

        logger.info(f"Assigned patient {patient_uid} to {worker.full_name} as {role_display}")
        return patient

    def _calculate_priority_sync(self, patient: Patient) -> int:
        """Calculate priority score (0-100) using eagerly loaded relationships."""
        score = 0

        for alert in patient.alerts:
            if alert.status == AlertStatus.PENDING:
                if alert.severity == AlertSeverity.CRITICAL:
                    score += 50
                elif alert.severity == AlertSeverity.URGENT:
                    score += 30
                elif alert.severity == AlertSeverity.WARNING:
                    score += 15
                else:
                    score += 5

        pending_actions = [a for a in patient.agent_actions if a.status == "pending"]
        score += 20 * len(pending_actions)

        return min(score, 100)
