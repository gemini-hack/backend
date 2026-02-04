import asyncio
import csv
import uuid
import random
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select, delete

from app.db.database import async_session_factory
from app.models.user import Organization, User, Team
from app.models.patient import Patient, Gender, PatientStatus, CommunicationPreference, HealthReading
from app.models.conditions import Condition, HIVProfile, RegimenLine, EnrollmentSetting

CSV_FILE = "/tmp/mira_patient_scenarios.csv"

# Admin & Worker Emails to PRESERVE (Though we aren't deleting Users anyway)
PRESERVED_EMAILS = ["koko4lyfe@gmail.com", "winterfell856@gmail.com", "admin@lagosgeneralhospital.ng"]

def random_phone():
    # Generate plausible Nigerian phone numbers
    prefixes = ["0803", "0806", "0703", "0909", "0818", "0706", "0906"]
    return f"+234{random.choice(prefixes)[1:]}{random.randint(1000000, 9999999)}"

async def reset_and_import():
    async with async_session_factory() as db:
        print("==" * 40)
        print("🚀 STARTING DB RESET & IMPORT")
        print("==" * 40)

        # 1. DELETE EXISTING PATIENTS (Cascade will handle profiles/readings)
        # =================================================================
        print("\n🗑️  Clearing Patient Data...")
        stmt_count = select(Patient)
        result = await db.execute(stmt_count)
        count_before = len(result.scalars().all())
        print(f"   Found {count_before} existing patients.")
        
        await db.execute(delete(Patient))
        await db.commit()
        print(f"✅ Deleted all {count_before} patients.")
        
        # 2. VERIFY ORGANIZATION & CARE TEAM (Provide context for new patients)
        # =================================================================
        org_email = "admin@lagosgeneralhospital.ng"
        stmt_org = select(Organization).where(Organization.email == org_email)
        org = (await db.execute(stmt_org)).scalar_one_or_none()
        
        if not org:
            print("❌ ERROR: Organization 'Lagos General Hospital' not found. Please run seed_hackathon_data.py first to create Org/Users.")
            return
        
        org_id = org.id
        
        # Get Worker (Doctor) to assign as primary physician
        worker_email = "winterfell856@gmail.com"
        stmt_worker = select(User).where(User.email == worker_email)
        worker = (await db.execute(stmt_worker)).scalar_one_or_none()
        worker_id = worker.id if worker else None
        
        stmt_team = select(Team).where(Team.organization_id == org_id)
        team = (await db.execute(stmt_team)).scalars().first() # Just grab the first team
        team_id = team.id if team else None

        # 3. IMPORT CSV
        # =================================================================
        print(f"\n📂 Importing from {CSV_FILE}...")
        
        patients_to_add = []
        profiles_to_add = []
        readings_to_add = []
        
        with open(CSV_FILE, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            print(f"   Found {len(rows)} records to import.")
            
            for row in rows:
                patient_id = uuid.uuid4()
                
                # --- PATIENT ---
                try:
                    dob = datetime.strptime(row['dob'], "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    dob = date(1980, 1, 1) # Fallback

                status_map = {
                    "ACTIVE": PatientStatus.ACTIVE,
                    "IIT": PatientStatus.IIT,
                    "ACTIVE_DEFAULTER": PatientStatus.ACTIVE_DEFAULTER,
                    "TRANSFERRED_OUT": PatientStatus.TRANSFERRED_OUT
                }
                status = status_map.get(row['status'], PatientStatus.ACTIVE)
                
                # Use provided email from CSV
                email = row.get('email')
                if not email:
                    # Fallback just in case, though generator should provide it
                    email = f"{row['first_name'].lower()}.{row['last_name'].lower()}.{random.randint(100,999)}@example.com"
                
                p = Patient(
                    id=patient_id,
                    organization_id=org_id,
                    team_id=team_id,
                    patient_uid=row['uid'],
                    first_name=row['first_name'],
                    last_name=row['last_name'],
                    
                    email=email,
                    phone=random_phone(), # Generate a phone number because user wants communication
                    
                    date_of_birth=dob,
                    gender=Gender(row['gender'].lower()) if row['gender'] else Gender.OTHER,
                    status=status,
                    
                    # Defaults
                    primary_condition=Condition.HIV,
                    preferred_contact_method=CommunicationPreference.EMAIL, # SET TO EMAIL AS REQUESTED
                    monitoring_frequency="daily",
                    timezone="Africa/Lagos",
                    agent_enabled=True,
                    primary_physician_id=worker_id,
                    last_reading_at=datetime.now(timezone.utc)
                )
                patients_to_add.append(p)
                
                # --- HIV PROFILE ---
                diag_date = parse_date(row.get('date_of_diagnosis'))
                art_start = parse_date(row.get('art_start_date'))
                last_refill = parse_date(row.get('last_refill_date'))
                vl_date = parse_date(row.get('date_vl_result'))
                
                next_refill = None
                if last_refill and row.get('refill_months'):
                    try:
                        months = int(row['refill_months'])
                        next_refill = last_refill + timedelta(days=months*30)
                    except ValueError:
                        pass
                
                profile = HIVProfile(
                    patient_id=patient_id,
                    date_of_diagnosis=diag_date,
                    art_start_date=art_start,
                    
                    initial_art_regimen=row.get('art_regimen_baseline'),
                    current_art_regimen=row.get('current_art_regimen'),
                    regimen_line=RegimenLine.FIRST_LINE, 
                    
                    baseline_cd4_count=parse_int(row.get('cd4_count_baseline')),
                    baseline_viral_load=parse_int(row.get('baseline_viral_load')),
                    last_viral_load_result=parse_int(row.get('current_viral_load')),
                    last_viral_load_result_date=vl_date,
                    
                    last_refill_date=last_refill,
                    refill_months=parse_int(row.get('refill_months')),
                    next_refill_date=next_refill,
                    
                    enrollment_setting=EnrollmentSetting.OPD
                )
                profiles_to_add.append(profile)
                
                # --- VITALS (Health Reading) ---
                if row.get('bp_systolic') and row.get('weight_kg'):
                    # 1. Weight
                    r_weight = HealthReading(
                        id=uuid.uuid4(),
                        patient_id=patient_id, organization_id=org_id, recorded_by_id=worker_id,
                        reading_type="weight", value=float(row['weight_kg']), unit="kg",
                        reading_time=datetime.now(timezone.utc)
                    )
                    readings_to_add.append(r_weight)
                    
                    # 2. BP
                    if row.get('bp_systolic'):
                        r_bp = HealthReading(
                            id=uuid.uuid4(),
                            patient_id=patient_id, organization_id=org_id, recorded_by_id=worker_id,
                            reading_type="blood_pressure", 
                            value=float(row['bp_systolic']), unit="mmHg",
                            secondary_value=float(row['bp_diastolic']), secondary_unit="mmHg",
                            reading_time=datetime.now(timezone.utc)
                        )
                        readings_to_add.append(r_bp)
                        
                    # 3. Pulse
                    if row.get('pulse_bpm'):
                        r_pulse = HealthReading(
                            id=uuid.uuid4(),
                            patient_id=patient_id, organization_id=org_id, recorded_by_id=worker_id,
                            reading_type="heart_rate",
                            value=float(row['pulse_bpm']), unit="bpm",
                            reading_time=datetime.now(timezone.utc)
                        )
                        readings_to_add.append(r_pulse)

        db.add_all(patients_to_add)
        await db.flush()
        
        db.add_all(profiles_to_add)
        db.add_all(readings_to_add)
        
        await db.commit()
        print(f"✅ Successfully Imported: {len(patients_to_add)} Patients.")
        print(f"✅ Successfully Imported: {len(readings_to_add)} Vitals Readings.")

def parse_date(d_str):
    if not d_str: return None
    try:
        return datetime.strptime(d_str, "%Y-%m-%d").date()
    except:
        return None

def parse_int(v):
    if not v: return None
    try:
        return int(float(v))
    except:
        return None

if __name__ == "__main__":
    asyncio.run(reset_and_import())
