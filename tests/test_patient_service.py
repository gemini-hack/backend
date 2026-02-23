import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock

from app.services.patient_service import PatientService
from app.models.patient import Patient, PatientStatus
from app.models.conditions import Condition, HIVProfile

class TestPatientServiceHIVTransitions:
    @pytest.mark.asyncio
    async def test_update_hiv_clinical_data_active(self):
        mock_db = AsyncMock()
        service = PatientService(mock_db)

        patient = Patient(status=PatientStatus.ACTIVE, primary_condition=Condition.HIV)
        # Next refill date is in the future
        profile = HIVProfile(
            last_refill_date=date.today() - timedelta(days=10),
            refill_months=1 # 30 days
        )
        patient.hiv_profile = profile

        await service.update_hiv_clinical_data(patient)
        
        # next_refill_date = today - 10 + 30 = today + 20
        # now (today) <= next_refill_date -> ACTIVE
        assert patient.status == PatientStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_update_hiv_clinical_data_active_defaulter(self):
        mock_db = AsyncMock()
        service = PatientService(mock_db)

        patient = Patient(status=PatientStatus.ACTIVE, primary_condition=Condition.HIV)
        # Next refill date is in the past (10 days overdue < 28 days)
        profile = HIVProfile(
            last_refill_date=date.today() - timedelta(days=40),
            refill_months=1 # 30 days
        )
        patient.hiv_profile = profile

        await service.update_hiv_clinical_data(patient)
        
        # next_refill_date = today - 40 + 30 = today - 10
        # now > next_refill_date (10 days overdue) -> ACTIVE_DEFAULTER
        assert patient.status == PatientStatus.ACTIVE_DEFAULTER

    @pytest.mark.asyncio
    async def test_update_hiv_clinical_data_iit(self):
        mock_db = AsyncMock()
        service = PatientService(mock_db)

        patient = Patient(status=PatientStatus.ACTIVE_DEFAULTER, primary_condition=Condition.HIV)
        # Next refill date is in the past (30 days overdue > 28 days)
        profile = HIVProfile(
            last_refill_date=date.today() - timedelta(days=60),
            refill_months=1 # 30 days
        )
        patient.hiv_profile = profile

        await service.update_hiv_clinical_data(patient)
        
        # next_refill_date = today - 60 + 30 = today - 30
        # now > next_refill_date (30 days overdue) -> IIT
        assert patient.status == PatientStatus.IIT
        
    @pytest.mark.asyncio
    async def test_update_hiv_clinical_data_return_after_iit(self):
        mock_db = AsyncMock()
        service = PatientService(mock_db)

        patient = Patient(status=PatientStatus.IIT, primary_condition=Condition.HIV)
        # Patient came back today for a refill
        profile = HIVProfile(
            last_refill_date=date.today(),
            refill_months=1 # 30 days
        )
        patient.hiv_profile = profile

        await service.update_hiv_clinical_data(patient)
        
        # next_refill_date = today + 30
        # now <= next_refill_date -> ACTIVE
        assert patient.status == PatientStatus.ACTIVE
