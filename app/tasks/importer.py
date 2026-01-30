import asyncio
import json
import uuid
from io import BytesIO

import pandas as pd
from sqlalchemy.exc import IntegrityError

from app.celery_app import celery_app
from app.db.database import get_celery_session
from app.models.user import User
from app.schemas.conditions import (
    DiabetesProfileCreate,
    HIVProfileCreate,
    HypertensionProfileCreate,
)
from app.schemas.patient import PatientCreate
from app.services.patient_service import PatientService
from app.services.storage_service import StorageService
from app.utils.logger import logger
from app.utils.normalization import normalize_regimen_string


def parse_json_column(value):
    """Parse a JSON array from CSV cell, handling various formats."""
    if pd.isna(value) or value == "" or value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("["):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass
        # Fall back to semicolon-separated, then comma-separated
        if ";" in value:
            return [item.strip() for item in value.split(";") if item.strip()]
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def safe_str(value, default=None):
    """Safely convert to string, handling NaN/None."""
    if pd.isna(value) or value is None:
        return default
    return str(value).strip() if value else default


def safe_int(value):
    """Safely convert to int, handling NaN/None."""
    if pd.isna(value) or value is None or value == "":
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def safe_float(value):
    """Safely convert to float, handling NaN/None."""
    if pd.isna(value) or value is None or value == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def safe_bool(value, default=False):
    """Safely convert to bool, handling various string formats."""
    if pd.isna(value) or value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "yes", "1", "t", "y")
    return bool(value)


@celery_app.task(
    name="app.tasks.importer.process_patient_batch_import",
    retry_backoff=True,
    max_retries=3,
    autoretry_for=(Exception,),
)
def process_patient_batch_import(file_key: str, organization_id: str, user_id: str):
    """Celery task to process batch patient import from CSV using pandas."""
    logger.info(f"Starting batch import for {file_key}")

    async def run_import():
        storage = StorageService()

        # Download file
        try:
            file_obj = storage.get_file(file_key)
            content = file_obj.getvalue()
        except Exception as e:
            logger.error(f"Failed to download file {file_key}: {e}")
            raise

        # Parse CSV with pandas
        try:
            df = pd.read_csv(
                BytesIO(content),
                dtype=str,  # Read all as strings initially
                na_values=["", "NA", "N/A", "null", "None"],
                keep_default_na=True,
            )
            # Replace NaN with None for cleaner handling
            df = df.where(pd.notna(df), None)
        except Exception as e:
            logger.error(f"Failed to parse CSV: {e}")
            raise

        logger.info(f"Parsed {len(df)} rows from CSV")

        success_count = 0
        failure_count = 0
        skipped_count = 0

        async with get_celery_session() as session:
            patient_service = PatientService(session)

            # Fetch creator user for context
            creator = await session.get(User, uuid.UUID(user_id))
            if not creator:
                logger.error(f"Creator user {user_id} not found")
                return

            for idx, row in df.iterrows():
                try:
                    primary_condition = safe_str(row.get("primary_condition"), "other")

                    # Build condition-specific profile data
                    hiv_profile = None
                    hypertension_profile = None
                    diabetes_profile = None

                    if primary_condition == "hiv":
                        # AI Normalization for Regimen
                        raw_regimen = safe_str(row.get("current_art_regimen"))
                        normalized_regimen = None
                        
                        if raw_regimen:
                            # Call the AI Normalizer!
                            try:
                                normalized_regimen = await normalize_regimen_string(raw_regimen)
                            except Exception as e:
                                logger.warning(f"Normalization failed for {raw_regimen}: {e}")
                                normalized_regimen = raw_regimen

                        hiv_profile = HIVProfileCreate(
                            date_of_diagnosis=safe_str(row.get("date_of_diagnosis")),
                            art_start_date=safe_str(row.get("art_start_date")),
                            baseline_viral_load=safe_int(row.get("baseline_viral_load")),
                            baseline_cd4_count=safe_int(row.get("baseline_cd4_count")),
                            current_art_regimen=normalized_regimen or raw_regimen, # Fallback to raw if normalized is None (though normalizer handles it)
                            last_refill_date=safe_str(row.get("last_refill_date")),
                            refill_months=safe_int(row.get("refill_months")),
                        )
                    elif primary_condition == "hypertension":
                        hypertension_profile = HypertensionProfileCreate(
                            date_of_diagnosis=safe_str(row.get("date_of_diagnosis")),
                            baseline_systolic=safe_int(row.get("baseline_systolic")),
                            baseline_diastolic=safe_int(row.get("baseline_diastolic")),
                            current_medication=safe_str(row.get("current_medication")),
                            has_diabetes=safe_bool(row.get("has_diabetes")),
                            has_kidney_disease=safe_bool(row.get("has_kidney_disease")),
                            has_heart_disease=safe_bool(row.get("has_heart_disease")),
                        )
                    elif primary_condition == "diabetes":
                        diabetes_profile = DiabetesProfileCreate(
                            date_of_diagnosis=safe_str(row.get("date_of_diagnosis")),
                            diabetes_type=safe_str(row.get("diabetes_type")),
                            baseline_hba1c=safe_float(row.get("baseline_hba1c")),
                            current_treatment=safe_str(row.get("current_treatment")),
                            insulin_regimen=safe_str(row.get("insulin_regimen")),
                        )

                    patient_data = PatientCreate(
                        patient_uid=safe_str(row.get("patient_uid")) or str(uuid.uuid4()),
                        first_name=safe_str(row.get("first_name")),
                        last_name=safe_str(row.get("last_name")),
                        email=safe_str(row.get("email")),
                        phone=safe_str(row.get("phone")),
                        date_of_birth=safe_str(row.get("date_of_birth")),
                        gender=safe_str(row.get("gender")),
                        primary_condition=primary_condition,
                        address=safe_str(row.get("address")),
                        emergency_contact_name=safe_str(row.get("emergency_contact_name")),
                        emergency_contact_phone=safe_str(row.get("emergency_contact_phone")),
                        emergency_contact_relationship=safe_str(row.get("emergency_contact_relationship")),
                        # Medical - Parse JSON arrays
                        secondary_conditions=parse_json_column(row.get("secondary_conditions")),
                        current_medications=parse_json_column(row.get("current_medications")),
                        allergies=parse_json_column(row.get("allergies")),
                        # Contact preferences
                        preferred_contact_method=safe_str(row.get("preferred_contact_method"), "sms"),
                        preferred_contact_time=safe_str(row.get("preferred_contact_time")),
                        timezone=safe_str(row.get("timezone"), "UTC"),
                        preferred_language=safe_str(row.get("preferred_language"), "en"),
                        monitoring_frequency=safe_str(row.get("monitoring_frequency"), "daily"),
                        # Condition Profiles
                        hiv_profile=hiv_profile,
                        hypertension_profile=hypertension_profile,
                        diabetes_profile=diabetes_profile,
                        # Defaults
                        status=safe_str(row.get("status"), "active"),
                    )

                    await patient_service.create_patient(
                        creator=creator,
                        data=patient_data,
                        ip_address="batch_import",
                    )
                    success_count += 1

                except IntegrityError:
                    await session.rollback()
                    logger.warning(f"Skipping duplicate patient {row.get('patient_uid')}: already exists")
                    skipped_count += 1

                except Exception as e:
                    error_str = str(e).lower()
                    if "already exists" in error_str:
                        logger.warning(f"Skipping duplicate patient {row.get('patient_uid')}: already exists")
                        skipped_count += 1
                    else:
                        logger.error(
                            f"Failed to import row {idx + 1} (UID: {row.get('patient_uid')}): {e}"
                        )
                        failure_count += 1

            logger.info(
                f"Batch import completed. Success: {success_count}, "
                f"Skipped (duplicates): {skipped_count}, Failed: {failure_count}"
            )

    asyncio.run(run_import())
