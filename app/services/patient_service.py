import uuid
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import select, and_, func

from app.models.patient import Patient, PatientStatus
from app.models.user import User
from app.schemas.patient import PatientCreate, PatientResponse, PatientListResponse
from app.services.base import BaseService
from app.utils.logger import logger
from app.utils.exceptions import NotFoundException, BadRequestException

class PatientService(BaseService):
    """Service for managing patient records."""

    async def create_patient(
        self,
        creator: User,
        data: PatientCreate,
        ip_address: Optional[str] = None,
    ) -> PatientResponse:
        """Create a new patient record using BaseModel methods."""
        
        # Check if patient UID already exists in the organization

        existing = await Patient.fetch_unique(
            self.db, 
            patient_uid=data.patient_uid, 
            organization_id=creator.organization_id
        )
        
        if existing:
            raise BadRequestException(f"Patient with UID {data.patient_uid} already exists in this organization")

        # Validate care team IDs if provided
        care_team_ids = []
        if data.primary_physician_id:
            care_team_ids.append(data.primary_physician_id)
        if data.assigned_nurse_id:
            care_team_ids.append(data.assigned_nurse_id)
        if data.care_coordinator_id:
            care_team_ids.append(data.care_coordinator_id)
        
        if care_team_ids:
            # do these users exist in the same organization?
            user_check = await self.db.execute(
                select(User.id).where(
                    and_(
                        User.id.in_(care_team_ids),
                        User.organization_id == creator.organization_id
                    )
                )
            )
            found_ids = set(user_check.scalars().all())
            for requested_id in care_team_ids:
                if requested_id not in found_ids:
                    raise BadRequestException(f"Care team member with ID {requested_id} not found in your organization")

        # Create patient
        patient = Patient(
            organization_id=creator.organization_id,
            patient_uid=data.patient_uid,
            first_name=data.first_name,
            last_name=data.last_name,
            date_of_birth=data.date_of_birth,
            gender=data.gender,
            phone=data.phone,
            email=data.email,
            address=data.address,
            primary_condition=data.primary_condition,
            secondary_conditions=data.secondary_conditions,
            medical_history=data.medical_history,
            current_medications=data.current_medications,
            allergies=data.allergies,
            primary_physician_id=data.primary_physician_id,
            assigned_nurse_id=data.assigned_nurse_id,
            care_coordinator_id=data.care_coordinator_id,
            monitoring_frequency=data.monitoring_frequency,
            preferred_contact_method=data.preferred_contact_method,
            preferred_language=data.preferred_language,
            status=PatientStatus.ACTIVE,
        )
        

        await patient.insert(self.db, commit=True)
        
        # Log audit
        await self._log_audit(
            user_id=creator.id,
            organization_id=creator.organization_id,
            action="patient_created",
            resource_type="patient",
            resource_id=str(patient.id),
            details={"patient_uid": data.patient_uid},
            ip_address=ip_address,
        )
        
        logger.info(f"Patient {data.patient_uid} created by {creator.email}")
        
        return PatientResponse.model_validate(patient)

    async def get_patients(
        self,
        organization_id: uuid.UUID,
        status: Optional[PatientStatus] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> PatientListResponse:
        """Get patients for an organization."""

        query = select(Patient).where(Patient.organization_id == organization_id)
        
        if status:
            query = query.where(Patient.status == status)
            
        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()
        
        # Get patients
        query = query.order_by(Patient.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        patients = result.scalars().all()
        
        return PatientListResponse(
            patients=[PatientResponse.model_validate(p) for p in patients],
            total=total
        )

    async def get_patient_by_id(self, patient_id: uuid.UUID, organization_id: uuid.UUID) -> Patient:
        """Get a patient by ID using BaseModel methods."""
        
        patient = await Patient.fetch_unique(
            self.db, 
            id=patient_id, 
            organization_id=organization_id
        )
        if not patient:
            raise NotFoundException("Patient not found")
        return patient
