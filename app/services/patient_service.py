import uuid
from datetime import datetime, date, timedelta, timezone
from typing import Optional, List

from sqlalchemy import select, and_, func, or_
from sqlalchemy.orm import selectinload

from app.models.patient import Patient, PatientStatus
from app.models.conditions import Condition, HIVProfile, HypertensionProfile, DiabetesProfile
from app.models.user import User
from app.schemas.patient import PatientCreate, PatientResponse, PatientListResponse, PatientDetailResponse
from app.services.base import BaseService
from app.utils.logger import logger
from app.utils.exceptions import NotFoundException, BadRequestException

class PatientService(BaseService):
    """Service for managing patient records."""

    async def find_existing_patient(
        self,
        organization_id: uuid.UUID,
        first_name: str,
        last_name: str,
        date_of_birth: date,
        phone: Optional[str] = None
    ) -> Optional[Patient]:
        """Find a patient by precise demographic match."""
        query = select(Patient).where(
            Patient.organization_id == organization_id,
            func.lower(Patient.first_name) == first_name.lower().strip(),
            func.lower(Patient.last_name) == last_name.lower().strip(),
            Patient.date_of_birth == date_of_birth
        )
        result = await self.db.execute(query)
        match = result.scalars().first()
        
        if not match and phone:
             # Fallback: try matching by phone if names didn't match (optional - usually name+dob is better)
             # But let's stick to Name+DOB as primary strict match for safety.
             pass
             
        return match

    async def upsert_patient_from_ingestion(
        self,
        creator: User,
        data: PatientCreate,
        ip_address: Optional[str] = None,
    ) -> tuple[Patient, bool]:
        """
        Create or Update a patient based on demographic matching.
        Returns: (Patient, is_created)
        """
        # 1. Try to find existing
        existing = await self.find_existing_patient(
            creator.organization_id,
            data.first_name,
            data.last_name,
            data.date_of_birth
        )
        
        if existing:
            # UPDATE LOGIC
            logger.info(f"Ingestion found existing patient {existing.id} for {data.first_name} {data.last_name}")
            
            # Update core fields if provided in ingestion (prefer new data?)
            # Usually for ingestion, we might want to fill MISSING data vs overwrite existing good data.
            # But let's assume ingestion implies "latest info".
            if data.phone: existing.phone = data.phone
            if data.address: existing.address = data.address
            if data.email: existing.email = data.email
            
            # Update/Create Profile
            # Since data.hiv_profile is a Pydantic model, we can dump it
            if data.primary_condition == Condition.HIV and data.hiv_profile:
                if existing.hiv_profile:
                     # Update existing profile
                     for k, v in data.hiv_profile.model_dump(exclude_unset=True).items():
                         setattr(existing.hiv_profile, k, v)
                else:
                     # Create new profile
                     existing.hiv_profile = HIVProfile(**data.hiv_profile.model_dump())
                     
            elif data.primary_condition == Condition.HYPERTENSION and data.hypertension_profile:
                 if existing.hypertension_profile:
                     for k, v in data.hypertension_profile.model_dump(exclude_unset=True).items():
                         setattr(existing.hypertension_profile, k, v)
                 else:
                     existing.hypertension_profile = HypertensionProfile(**data.hypertension_profile.model_dump())
            
            await existing.save(self.db)
            
            # Log audit
            await self._log_audit(
                user_id=creator.id,
                organization_id=creator.organization_id,
                action="patient_updated_via_ingestion",
                resource_type="patient",
                resource_id=str(existing.id),
                details={"source": "document_ingestion"},
                ip_address=ip_address,
            )
            return existing, False

        else:
            # CREATE NEW
            new_patient = await self.create_patient(creator, data, ip_address)
            return new_patient, True

    async def create_patient(
        self,
        creator: User,
        data: PatientCreate,
        ip_address: Optional[str] = None,
    ) -> Patient: # Changed return type hint to Patient for internal consistency, though it was PatientResponse

        """Create a new patient record with optional condition profiles."""
        
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

        # Create patient core record
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
            emergency_contact_name=data.emergency_contact_name,
            emergency_contact_phone=data.emergency_contact_phone,
            emergency_contact_relationship=data.emergency_contact_relationship,
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
            preferred_contact_time=data.preferred_contact_time,
            timezone=data.timezone,
            preferred_language=data.preferred_language,
            status=data.status if data.status else PatientStatus.ACTIVE,
            team_id=data.team_id,
        )

        
        # Handle HIV Profile if provided
        if data.primary_condition == Condition.HIV and data.hiv_profile:
            patient.hiv_profile = HIVProfile(
                **data.hiv_profile.model_dump()
            )
        
        # Handle Hypertension Profile if provided
        if data.primary_condition == Condition.HYPERTENSION and data.hypertension_profile:
            patient.hypertension_profile = HypertensionProfile(
                **data.hypertension_profile.model_dump()
            )
        
        # Handle Diabetes Profile if provided
        if data.primary_condition == Condition.DIABETES and data.diabetes_profile:
            patient.diabetes_profile = DiabetesProfile(
                **data.diabetes_profile.model_dump()
            )

        await patient.insert(self.db, commit=True)
        
        # Refresh with eager-loaded relationships
        await self.db.refresh(patient, ["hiv_profile", "hypertension_profile", "diabetes_profile"])
        
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
        
        return patient

    async def get_patients(
        self,
        organization_id: uuid.UUID,
        status: Optional[PatientStatus] = None,
        condition: Optional[Condition] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> PatientListResponse:
        """Get patients for an organization using QueryBuilder."""
        conditions = [Patient.organization_id == organization_id]
        
        if status:
            conditions.append(Patient.status == status)
            
        if condition:
            conditions.append(Patient.primary_condition == condition)
            
        if search:
            search_term = f"%{search}%"
            conditions.append(
                or_(
                    Patient.first_name.ilike(search_term),
                    Patient.last_name.ilike(search_term),
                    Patient.patient_uid.ilike(search_term),
                    func.concat(Patient.first_name, ' ', Patient.last_name).ilike(search_term),
                )
            )

        # Get count (separate query builder instance)
        total = await Patient.query(self.db).filter(*conditions).count()
        logger.info(f"Patient count for org {organization_id}: {total}")
        
        # Get patients (fresh query builder instance)
        patients = await (
            Patient.query(self.db)
            .filter(*conditions)
            .with_relations("hiv_profile", "hypertension_profile", "diabetes_profile")
            .order_by(Patient.created_at, desc=True)
            .offset(skip)
            .limit(limit)
            .all()
        )
        logger.info(f"Fetched {len(patients)} patients")
        
        return PatientListResponse(
            patients=[PatientResponse.model_validate(p) for p in patients],
            total=total,
            skip=skip,
            limit=limit,
        )

    async def update_hiv_clinical_data(self, patient: Patient) -> None:
        """
        Calculate HIV treatment status and next refill date within the HIVProfile.
        """
        profile = patient.hiv_profile
        if not profile or not profile.last_refill_date or not profile.refill_months:
            return

        # 1. Calculate Next Refill Date
        profile.next_refill_date = profile.last_refill_date + timedelta(days=profile.refill_months * 30)
        
        # 2. Update Status based on current date
        now = date.today()
        if patient.status in [PatientStatus.ACTIVE, PatientStatus.ACTIVE_DEFAULTER, PatientStatus.IIT]:
            if now > profile.next_refill_date:
                days_overdue = (now - profile.next_refill_date).days
                if days_overdue > 28:
                    patient.status = PatientStatus.IIT
                else:
                    patient.status = PatientStatus.ACTIVE_DEFAULTER
            else:
                patient.status = PatientStatus.ACTIVE

        await self.db.commit()

    async def get_patient_by_id(self, patient_id: uuid.UUID, organization_id: uuid.UUID) -> Patient:
        """Get a patient by ID with eager loaded relationships."""
        patient = await Patient.fetch_one_with(
            self.db,
            "hiv_profile",
            "alerts",
            "agent_actions",
            id=patient_id,
            organization_id=organization_id
        )
        
        if not patient:
            raise NotFoundException("Patient not found")
            
        if patient.primary_condition == Condition.HIV:
            await self.update_hiv_clinical_data(patient)
            
        return patient

    async def update_patient(
        self,
        patient_id: uuid.UUID,
        organization_id: uuid.UUID,
        data: dict,
        user: Optional[User] = None,
    ) -> Patient:
        """Update a patient record."""
        patient = await Patient.fetch_one_with(
            self.db,
            "hiv_profile",
            "hypertension_profile",
            "diabetes_profile",
            id=patient_id,
            organization_id=organization_id
        )
        
        if not patient:
            raise NotFoundException("Patient not found")
        
        # Update only provided fields
        update_data = {k: v for k, v in data.items() if v is not None}
        
        for field, value in update_data.items():
            if hasattr(patient, field):
                setattr(patient, field, value)
        
        await patient.save(self.db)
        logger.info(f"Patient {patient.patient_uid} updated")
        
        return patient

    async def delete_patient(
        self,
        patient_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> None:
        """Soft delete a patient by setting status to INACTIVE."""
        patient = await Patient.fetch_unique(
            self.db,
            id=patient_id,
            organization_id=organization_id
        )
        
        if not patient:
            raise NotFoundException("Patient not found")
        
        patient.status = PatientStatus.INACTIVE
        await patient.save(self.db)
        logger.info(f"Patient {patient.patient_uid} marked inactive")
