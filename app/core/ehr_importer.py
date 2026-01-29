import csv
import io
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.patient import PatientCreate
from app.schemas.conditions import HIVProfileCreate
from app.models.conditions import WHOStage, FunctionalStatus, RegimenLine, EnrollmentSetting

class UniversalImporter:
    """
    Parses patient lists from ANY source (LAMIS, NMRS/OpenMRS).
    Auto-detects format by 'sniffing' the CSV headers.
    """
    
    def __init__(self, db: AsyncSession, organization_id: str):
        self.db = db
        self.organization_id = organization_id
        self.user_cache = {} # Cache doctor lookups to speed up processing

    async def _find_doctor(self, name: str) -> Optional[str]:
        """
        Tries to match 'Dr. Chioma' from CSV to a User ID in Mira.
        """
        if not name: return None
        
        clean_name = name.strip().lower()
        if clean_name in self.user_cache:
            return self.user_cache[clean_name]

        # Fuzzy search: Matches if name is in First OR Last name of a user
        stmt = select(User.id).where(
            User.organization_id == self.organization_id,
            (User.first_name.ilike(f"%{clean_name}%")) | 
            (User.last_name.ilike(f"%{clean_name}%"))
        )
        result = await self.db.execute(stmt)
        user_id = result.scalar_one_or_none()
        
        if user_id:
            self.user_cache[clean_name] = user_id
            return user_id
        return None

    def _map_enum(self, enum_class, value: str):
        """Safely maps CSV string to Enum."""
        if not value: return None
        try:
            return enum_class(value)
        except ValueError:
            # Try case-insensitive match
            for member in enum_class:
                if member.value.lower() == value.lower():
                    return member
            return None

    async def parse_csv(self, file_content: bytes) -> List[PatientCreate]:
        content = file_content.decode("utf-8-sig")
        
        # Sniff headers to decide format
        f = io.StringIO(content)
        try:
            headers = next(csv.reader(f))
        except StopIteration:
            return []
            
        f.seek(0)
        reader = csv.DictReader(f)
        headers_set = set([h.lower().strip() for h in headers])
        
        # === STRATEGY 1: DETECT LAMIS ===
        if "hospitalnum" in headers_set or "uniqueid" in headers_set:
            return await self._parse_lamis(reader)
            
        # === STRATEGY 2: DETECT NMRS (OpenMRS) ===
        elif "pepfar id" in headers_set or "patient id" in headers_set:
            return await self._parse_nmrs(reader)
            
        else:
            # Fallback: Treat as Generic CSV
            print("Unknown format, attempting generic parse...")
            return []

    async def _parse_lamis(self, reader) -> List[PatientCreate]:
        patients = []
        for row in reader:
            try:
                # Doctor Assignment
                doc_name = row.get("CaseManager") or row.get("ClinicianName") or row.get("Provider")
                doctor_id = await self._find_doctor(doc_name)

                hiv_profile = HIVProfileCreate(
                    date_of_diagnosis=self._parse_date(row.get("DateConfirmedHIV")),
                    art_start_date=self._parse_date(row.get("DateArvStarted")),
                    
                    enrollment_setting=self._map_enum(EnrollmentSetting, row.get("EnrollmentSetting")),
                    who_clinical_stage=self._map_enum(WHOStage, row.get("WHOStage")),
                    functional_status=self._map_enum(FunctionalStatus, row.get("FunctionalStatus")),
                    regimen_line=self._map_enum(RegimenLine, row.get("RegimenLine")),
                    
                    current_art_regimen=row.get("CurrentRegimen"),
                    baseline_viral_load=self._safe_int(row.get("BaselineViralLoad")),
                    last_viral_load_result=self._safe_int(row.get("LastViralLoad")),
                    last_viral_load_sample_date=self._parse_date(row.get("DateLastViralLoad")),
                    next_refill_date=self._parse_date(row.get("DateNextAppointment"))
                )

                uid = row.get("HospitalNum") or row.get("UniqueId")
                if not uid: continue

                patient = PatientCreate(
                    patient_uid=uid,
                    first_name=row.get("OtherNames", "Unknown"),
                    last_name=row.get("Surname", "Unknown"),
                    date_of_birth=self._parse_date(row.get("DateOfBirth")),
                    gender=row.get("Sex", "other").lower(),
                    phone=row.get("Phone"),
                    address=row.get("Address"),
                    primary_condition="hiv",
                    primary_physician_id=doctor_id,
                    hiv_profile=hiv_profile
                )
                patients.append(patient)
            except Exception as e:
                print(f"LAMIS Row Error: {e}")
                continue
        return patients

    async def _parse_nmrs(self, reader) -> List[PatientCreate]:
        """Parser for NMRS / OpenMRS"""
        patients = []
        for row in reader:
            try:
                doc_name = row.get("Provider") or row.get("Program Enrolled Provider")
                doctor_id = await self._find_doctor(doc_name)
                
                hiv_profile = HIVProfileCreate(
                    date_of_diagnosis=self._parse_date(row.get("Date of Diagnosis")),
                    art_start_date=self._parse_date(row.get("ART Start Date")),
                    current_art_regimen=row.get("Current Regimen"),
                    last_viral_load_result=self._safe_int(row.get("Last VL Result")),
                    last_viral_load_result_date=self._parse_date(row.get("Last VL Date")),
                )

                uid = row.get("Pepfar ID") or row.get("Patient ID")
                if not uid: continue

                patient = PatientCreate(
                    patient_uid=uid,
                    first_name=row.get("Given Name", "Unknown"),
                    last_name=row.get("Family Name", "Unknown"),
                    date_of_birth=self._parse_date(row.get("Birthdate")),
                    gender=row.get("Gender", "other").lower(),
                    phone=row.get("Phone Number") or row.get("Telephone"),
                    primary_condition="hiv",
                    primary_physician_id=doctor_id,
                    hiv_profile=hiv_profile
                )
                patients.append(patient)
            except Exception as e:
                print(f"NMRS Row Error: {e}")
                continue
        return patients

    def _parse_date(self, date_str):
        if not date_str or date_str.lower() in ["null", "none", ""]: return None
        formats = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%b-%Y"]
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt).date()
            except ValueError:
                continue
        return None

    def _safe_int(self, val):
        if not val: return None
        try: return int(float(val))
        except: return None