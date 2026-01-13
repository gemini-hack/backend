
from app.celery_app import celery_app
from app.utils.logger import logger
from app.services.storage_service import StorageService
from app.services.patient_service import PatientService
from app.schemas.patient import PatientCreate
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
    """
    Celery task to process batch patient import from CSV.
    """
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

                    patient_data = PatientCreate(
                        patient_uid=row.get('patient_uid') or str(uuid.uuid4()),
                        first_name=row.get('first_name'),
                        last_name=row.get('last_name'),
                        email=row.get('email'),
                        phone=row.get('phone'),
                        date_of_birth=row.get('date_of_birth'),
                        gender=row.get('gender') or None,
                        primary_condition=row.get('primary_condition', 'other'),
                        address=row.get('address'),
                        emergency_contact_name=row.get('emergency_contact_name'),
                        emergency_contact_phone=row.get('emergency_contact_phone'),
                        # Medical
                        date_of_diagnosis=parse_date(row.get('date_of_diagnosis')),
                        current_medications=parse_list(row.get('current_medications')),
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
