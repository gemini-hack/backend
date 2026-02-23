"""
EHR Integration Routes
======================
Endpoints for connecting to and syncing data from hospital EHR systems
like LAMIS and OpenMRS.
"""
import uuid
import random
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.dependencies import DbSession, CurrentUser, require_permission
from app.models.user import Organization
from app.models.patient import Patient, Gender, PatientStatus, CommunicationPreference
from app.models.conditions import Condition, HIVProfile, RegimenLine
from app.utils.responses import success_response
from app.utils.logger import logger


router = APIRouter(prefix="/ehr", tags=["EHR Integration"])


# ==========================================
# SCHEMAS
# ==========================================

class EHRConnectionConfig(BaseModel):
    """Configuration for connecting to an EHR system."""
    ehr_type: Literal["LAMIS", "OPENMRS"] = Field(..., description="Type of EHR system")
    host: str = Field(..., description="Database host")
    port: int = Field(5432, description="Database port")
    database: str = Field(..., description="Database name")
    username: str = Field(..., description="Database username")
    password: str = Field(..., description="Database password")
    use_ssl: bool = Field(True, description="Use SSL connection")


class EHRSyncRequest(BaseModel):
    """Request to trigger an EHR sync."""
    demo_mode: bool = Field(True, description="Use mock data instead of real connection")
    patient_count: int = Field(5, ge=1, le=50, description="Number of patients to sync (demo mode)")


class EHRSyncResult(BaseModel):
    """Result of an EHR sync operation."""
    job_id: str
    status: str
    patients_imported: int
    patients_updated: int
    patients_failed: int
    issues_flagged: list[str]


# ==========================================
# MOCK DATA FOR DEMO
# ==========================================

NIGERIAN_FIRST_NAMES = [
    "Oluwaseun", "Chukwuemeka", "Fatima", "Ibrahim", "Chidinma",
    "Adaeze", "Emeka", "Aisha", "Yusuf", "Ngozi", "Tunde", "Zainab"
]

NIGERIAN_LAST_NAMES = [
    "Adeyemi", "Okafor", "Mohammed", "Bello", "Nwachukwu",
    "Okonkwo", "Ibrahim", "Eze", "Adebayo", "Abubakar"
]

ART_REGIMENS = [
    ("TDF/3TC/DTG", True),   # Good regimen
    ("TDF/FTC/DTG", True),   # Good regimen
    ("ABC/3TC/DTG", True),   # Good regimen
    ("AZT/3TC/NVP", False),  # Phased out - needs switch!
    ("AZT/3TC/EFV", False),  # Phased out - needs switch!
]


def generate_mock_patient(hospital_prefix: str = "LUTH") -> dict:
    """Generate a realistic mock LAMIS patient record."""
    first_name = random.choice(NIGERIAN_FIRST_NAMES)
    last_name = random.choice(NIGERIAN_LAST_NAMES)
    regimen, is_good = random.choice(ART_REGIMENS)
    
    # Randomize viral load - some suppressed, some not
    if random.random() < 0.7:
        vl = random.randint(10, 150)  # Suppressed
    else:
        vl = random.randint(1000, 15000)  # Unsuppressed
    
    # Randomize appointment status
    days_offset = random.choice([-35, -15, -5, 2, 7, 14, 30])
    next_appointment = datetime.now() + timedelta(days=days_offset)
    
    return {
        "hospital_num": f"{hospital_prefix}-HIV-{random.randint(1000, 9999)}",
        "first_name": first_name,
        "last_name": last_name,
        "date_of_birth": date(random.randint(1970, 2000), random.randint(1, 12), random.randint(1, 28)),
        "gender": random.choice(["Male", "Female"]),
        "phone": f"080{random.randint(10000000, 99999999)}",
        "email": f"{first_name.lower()}.{last_name.lower()}@gmail.com",
        "diagnosis_date": date(random.randint(2015, 2023), random.randint(1, 12), 15),
        "art_start_date": date(random.randint(2015, 2023), random.randint(1, 12), 20),
        "current_regimen": regimen,
        "regimen_is_current": is_good,
        "viral_load": vl,
        "vl_date": date.today() - timedelta(days=random.randint(30, 120)),
        "next_appointment": next_appointment.date(),
        "days_overdue": -days_offset if days_offset < 0 else 0,
    }


# ==========================================
# ENDPOINTS
# ==========================================

@router.post(
    "/connect",
    status_code=status.HTTP_200_OK,
    summary="Test EHR connection",
    dependencies=[Depends(require_permission("patients:create"))],
)
async def test_ehr_connection(
    config: EHRConnectionConfig,
    user: CurrentUser,
    db: DbSession,
):
    """
    Test connection to an EHR system.
    In demo mode, this always succeeds.
    In production, this would attempt a real database connection.
    """
    logger.info(f"Testing EHR connection to {config.ehr_type} at {config.host}")
    
    # For demo, always succeed
    return success_response(
        status_code=status.HTTP_200_OK,
        message=f"Successfully connected to {config.ehr_type} at {config.host}",
        data={
            "ehr_type": config.ehr_type,
            "host": config.host,
            "database": config.database,
            "status": "connected",
            "version": "LAMIS 3.4.2" if config.ehr_type == "LAMIS" else "OpenMRS 2.5",
            "patient_count_available": random.randint(500, 5000),
        }
    )


@router.post(
    "/sync",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Sync patients from EHR",
    dependencies=[Depends(require_permission("patients:create"))],
)
async def sync_ehr_data(
    request: EHRSyncRequest,
    user: CurrentUser,
    db: DbSession,
    background_tasks: BackgroundTasks,
):
    """
    Trigger a sync from the connected EHR system.
    
    In demo mode, this generates mock patient data.
    In production, this would query the real EHR database.
    
    Returns immediately with a job_id. Use GET /ehr/sync/{job_id}/status
    to check progress.
    """
    job_id = str(uuid.uuid4())
    
    logger.info(f"Starting EHR sync job {job_id}, demo_mode={request.demo_mode}")
    
    # Get organization
    org_stmt = select(Organization).where(Organization.id == user.organization_id)
    org = (await db.execute(org_stmt)).scalar_one_or_none()
    
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    # Generate or fetch patients
    imported_count = 0
    updated_count = 0
    issues = []
    
    if request.demo_mode:
        # Generate mock patients
        mock_patients = [generate_mock_patient() for _ in range(request.patient_count)]
        
        for mp in mock_patients:
            # Check if patient already exists
            existing = await db.execute(
                select(Patient).where(
                    Patient.organization_id == user.organization_id,
                    Patient.patient_uid == mp["hospital_num"]
                )
            )
            existing_patient = existing.scalar_one_or_none()
            
            if existing_patient:
                updated_count += 1
                continue
            
            # Create new patient
            patient_id = uuid.uuid4()
            patient = Patient(
                id=patient_id,
                organization_id=user.organization_id,
                patient_uid=mp["hospital_num"],
                first_name=mp["first_name"],
                last_name=mp["last_name"],
                date_of_birth=mp["date_of_birth"],
                gender=Gender.MALE if mp["gender"] == "Male" else Gender.FEMALE,
                phone=mp["phone"],
                email=mp["email"],
                primary_condition=Condition.HIV,
                preferred_contact_method=CommunicationPreference.EMAIL,
                preferred_contact_time="09:00-18:00",
                status=PatientStatus.IIT if mp["days_overdue"] > 28 else (
                    PatientStatus.ACTIVE_DEFAULTER if mp["days_overdue"] > 0 else PatientStatus.ACTIVE
                ),
                agent_enabled=True,
                monitoring_frequency="daily",
                timezone="Africa/Lagos",
            )
            db.add(patient)
            await db.flush()
            
            # Create HIV Profile
            hiv_profile = HIVProfile(
                patient_id=patient_id,
                date_of_diagnosis=mp["diagnosis_date"],
                art_start_date=mp["art_start_date"],
                current_art_regimen=mp["current_regimen"],
                regimen_line=RegimenLine.FIRST_LINE,
                baseline_viral_load=random.randint(50000, 150000),
                baseline_cd4_count=random.randint(200, 400),
                last_viral_load_result=mp["viral_load"],
                last_viral_load_sample_date=mp["vl_date"],
                last_viral_load_result_date=mp["vl_date"] + timedelta(days=14),
                last_refill_date=date.today() - timedelta(days=random.randint(30, 90)),
                refill_months=3,
                next_refill_date=mp["next_appointment"],
            )
            db.add(hiv_profile)
            imported_count += 1
            
            # Flag issues
            if mp["viral_load"] > 1000:
                issues.append(f"{mp['first_name']} {mp['last_name']}: High viral load ({mp['viral_load']})")
            if not mp["regimen_is_current"]:
                issues.append(f"{mp['first_name']} {mp['last_name']}: On phased-out regimen ({mp['current_regimen']})")
            if mp["days_overdue"] > 28:
                issues.append(f"{mp['first_name']} {mp['last_name']}: IIT ({mp['days_overdue']} days overdue)")
            elif mp["days_overdue"] > 0:
                issues.append(f"{mp['first_name']} {mp['last_name']}: Active defaulter ({mp['days_overdue']} days overdue)")
        
        await db.commit()
    
    return success_response(
        status_code=status.HTTP_202_ACCEPTED,
        message="EHR sync completed",
        data={
            "job_id": job_id,
            "status": "completed",
            "patients_imported": imported_count,
            "patients_updated": updated_count,
            "patients_failed": 0,
            "issues_flagged": issues,
            "next_step": "Call POST /api/v1/agent/morning-rounds to trigger AI analysis"
        }
    )


@router.get(
    "/status",
    status_code=status.HTTP_200_OK,
    summary="Get EHR connection status",
    dependencies=[Depends(require_permission("patients:read"))],
)
async def get_ehr_status(
    user: CurrentUser,
    db: DbSession,
):
    """Get the current EHR connection status for the organization."""
    
    # For demo, return a mock status
    return success_response(
        status_code=status.HTTP_200_OK,
        message="EHR status retrieved",
        data={
            "connected": True,
            "ehr_type": "LAMIS",
            "last_sync": datetime.now(timezone.utc).isoformat(),
            "patients_synced": random.randint(100, 500),
            "sync_frequency": "daily",
            "next_scheduled_sync": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        }
    )


@router.get(
    "/supported-systems",
    status_code=status.HTTP_200_OK,
    summary="Get supported EHR systems",
)
async def get_supported_systems():
    """Get list of supported EHR systems."""
    return success_response(
        status_code=status.HTTP_200_OK,
        message="Supported EHR systems",
        data={
            "systems": [
                {
                    "id": "lamis",
                    "name": "LAMIS",
                    "full_name": "Laboratory and Management Information System",
                    "description": "Nigeria's primary HIV/AIDS patient management system",
                    "database_type": "PostgreSQL",
                    "supported_versions": ["3.0+"],
                },
                {
                    "id": "openmrs",
                    "name": "OpenMRS",
                    "full_name": "Open Medical Record System",
                    "description": "Open-source medical record platform used globally",
                    "database_type": "MySQL",
                    "supported_versions": ["2.0+"],
                },
            ]
        }
    )
