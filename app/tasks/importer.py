
from app.celery_app import celery_app
from app.utils.logger import logger
from app.services.storage_service import StorageService
from app.services.patient_service import PatientService
from app.schemas.patient import PatientCreate
from app.schemas.conditions import HIVProfileCreate, HypertensionProfileCreate, DiabetesProfileCreate
from app.db.database import async_session_factory
from app.models.user import User
import asyncio
import csv
import io
import uuid

@celery_app.task(
    name="app.tasks.importer.process_patient_batch_import",
    retry_backoff=True,
    max_retries=3,
    autoretry_for=(Exception,)
)
def process_patient_batch_import(file_key: str, organization_id: str, user_id: str):
    """ Celery task to process batch patient import from CSV. """

    logger.info(f"Starting batch import for {file_key}")
    
    async def run_import():
        storage = StorageService()
        
        # Download file
        try:
            file_obj = storage.get_file(file_key)
            content = file_obj.getvalue().decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to download file {file_key}: {e}")
            raise

        # Parse CSV
        config_file = io.StringIO(content)
        reader = csv.DictReader(config_file)
        
        success_count = 0
        failure_count = 0
        
        async with async_session_factory() as session:
            patient_service = PatientService(session)
            
            # Fetch creator user for context
            creator = await session.get(User, uuid.UUID(user_id))
            if not creator:
                logger.error(f"Creator user {user_id} not found")
                return

            for row in reader:
                try:
                    # Helper to get optional date
                    def parse_date(d_str):
                        return d_str if d_str else None

                    # Helper to get list from comma-separated string
                    def parse_list(l_str):
                        return [i.strip() for i in l_str.split(',')] if l_str else []
                    
                    # Helper to parse optional integer
                    def parse_int(val):
                        if not val:
                            return None
                        try:
                            return int(val)
                        except (ValueError, TypeError):
                            logger.warning(f"Could not parse int from: '{val}'")
                            return None
                    
                    # Helper to parse optional float
                    def parse_float(val):
                        if not val:
                            return None
                        try:
                            return float(val)
                        except (ValueError, TypeError):
                            logger.warning(f"Could not parse float from: '{val}'")
                            return None

                    primary_condition = row.get('primary_condition', 'other')
                    
                    # Build condition-specific profile data
                    hiv_profile = None
                    hypertension_profile = None
                    diabetes_profile = None
                    
                    if primary_condition == 'hiv':
                        hiv_profile = HIVProfileCreate(
                            date_of_diagnosis=parse_date(row.get('date_of_diagnosis')),
                            art_start_date=parse_date(row.get('art_start_date')),
                            baseline_viral_load=parse_int(row.get('baseline_viral_load')),
                            baseline_cd4_count=parse_int(row.get('baseline_cd4_count')),
                            current_art_regimen=row.get('current_art_regimen'),
                            last_refill_date=parse_date(row.get('last_refill_date')),
                            refill_months=parse_int(row.get('refill_months')),
                        )
                    elif primary_condition == 'hypertension':
                        hypertension_profile = HypertensionProfileCreate(
                            date_of_diagnosis=parse_date(row.get('date_of_diagnosis')),
                            baseline_systolic=parse_int(row.get('baseline_systolic')),
                            baseline_diastolic=parse_int(row.get('baseline_diastolic')),
                            current_medication=row.get('current_medication'),
                            has_diabetes=row.get('has_diabetes', '').lower() == 'true',
                            has_kidney_disease=row.get('has_kidney_disease', '').lower() == 'true',
                            has_heart_disease=row.get('has_heart_disease', '').lower() == 'true',
                        )
                    elif primary_condition == 'diabetes':
                        diabetes_profile = DiabetesProfileCreate(
                            date_of_diagnosis=parse_date(row.get('date_of_diagnosis')),
                            diabetes_type=row.get('diabetes_type'),
                            baseline_hba1c=parse_float(row.get('baseline_hba1c')),
                            current_treatment=row.get('current_treatment'),
                            insulin_regimen=row.get('insulin_regimen'),
                        )

                    patient_data = PatientCreate(
                        patient_uid=row.get('patient_uid') or str(uuid.uuid4()),
                        first_name=row.get('first_name'),
                        last_name=row.get('last_name'),
                        email=row.get('email'),
                        phone=row.get('phone'),
                        date_of_birth=row.get('date_of_birth'),
                        gender=row.get('gender') or None,
                        primary_condition=primary_condition,
                        address=row.get('address'),
                        emergency_contact_name=row.get('emergency_contact_name'),
                        emergency_contact_phone=row.get('emergency_contact_phone'),
                        # Medical
                        current_medications=parse_list(row.get('current_medications')),
                        # Condition Profiles
                        hiv_profile=hiv_profile,
                        hypertension_profile=hypertension_profile,
                        diabetes_profile=diabetes_profile,
                        # Defaults
                        status=row.get('status', 'active'),
                    )
                    
                    await patient_service.create_patient(
                        creator=creator,
                        data=patient_data,
                        ip_address="batch_import" 
                    )
                    success_count += 1
                except Exception as e:
                    logger.error(f"Failed to import row {row.get('email')}: {e}")
                    failure_count += 1
            
            logger.info(f"Batch import completed. Success: {success_count}, Failed: {failure_count}")

    asyncio.run(run_import())

