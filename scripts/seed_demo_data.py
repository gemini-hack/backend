"""
Seed script to create test data for MIRA Agent System.

Creates:
1. Admin user: koko4lyfe@gmail.com / SecurePass123
2. Worker user: winterfell856@gmail.com / SecurePass123
3. 5 HIV patients with different clinical scenarios

Run via Docker:
    docker compose exec app python scripts/seed_demo_data.py
"""
import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

from app.utils.security import hash_password
from app.db.database import async_session_factory
from app.models.user import Organization, User, UserRole, Team
from app.models.patient import Patient, Gender, PatientStatus, CommunicationPreference
from app.models.conditions import Condition, HIVProfile, RegimenLine
from app.models.appointment import Appointment, AppointmentStatus


async def seed_demo_data():
    """Create demo data for testing."""
    
    async with async_session_factory() as db:
        print("=" * 60)
        print("🏥 MIRA DEMO SEED")
        print("=" * 60)
        
        # -----------------------------------------------------------------
        # 1. ORGANIZATION
        # -----------------------------------------------------------------
        org_id = uuid.uuid4()
        org = Organization(
            id=org_id,
            name="Lagos General Hospital",
            type="hospital",
            email="admin@lagosgeneralhospital.ng",
            phone="+2349012345678",
            license_number="LAGOS-HIV-2024-001",
            is_active=True,
            is_onboarded=True,
            disease_specializations=["hiv"],
        )
        db.add(org)
        await db.flush()
        print(f"\n✅ Organization: {org.name}")
        
        # -----------------------------------------------------------------
        # 2. TEAM
        # -----------------------------------------------------------------
        team_id = uuid.uuid4()
        team = Team(
            id=team_id,
            organization_id=org_id,
            name="HIV Care Unit",
        )
        db.add(team)
        await db.flush()
        print(f"✅ Team: HIV Care Unit")
        
        # -----------------------------------------------------------------
        # 3. ADMIN USER
        # -----------------------------------------------------------------
        admin_id = uuid.uuid4()
        admin = User(
            id=admin_id,
            organization_id=org_id,
            email="koko4lyfe@gmail.com",
            password_hash=hash_password("SecurePass123"),
            first_name="Dr. Koko",
            last_name="Administrator",
            phone="+2348000000001",
            role=UserRole.ORG_OWNER,
            is_active=True,
            email_verified=True,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(admin)
        await db.flush()
        print(f"\n✅ ADMIN: koko4lyfe@gmail.com / SecurePass123")
        
        # -----------------------------------------------------------------
        # 4. WORKER (DOCTOR)
        # -----------------------------------------------------------------
        worker_id = uuid.uuid4()
        worker = User(
            id=worker_id,
            organization_id=org_id,
            team_id=team_id,
            email="winterfell856@gmail.com",
            password_hash=hash_password("SecurePass123"),
            first_name="Dr. Winter",
            last_name="Fell",
            phone="+2348000000002",
            role=UserRole.DOCTOR,
            is_active=True,
            email_verified=True,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(worker)
        await db.flush()
        print(f"✅ WORKER: winterfell856@gmail.com / SecurePass123")
        
        # -----------------------------------------------------------------
        # 5. PATIENTS - Each designed to trigger different agent actions
        # -----------------------------------------------------------------
        today = date.today()
        now = datetime.now(timezone.utc)
        
        patients_data = [
            # Patient 1: HIGH VIRAL LOAD → Agent should flag for intervention
            {
                "uid": "HIV-001",
                "first_name": "Bruno",
                "last_name": "Steel",
                "email": "brunosteel270@gmail.com",
                "dob": date(1988, 5, 15),
                "gender": Gender.MALE,
                "status": PatientStatus.ACTIVE,
                "last_reading": now - timedelta(days=1),
                "vl": 5200,  # HIGH - unsuppressed
                "regimen": "TDF/3TC/DTG",  # Good regimen
                "refill_date": today - timedelta(days=15),
                "refill_months": 3,
            },
            # Patient 2: BAD REGIMEN (old NVP) → Agent should flag for switch
            {
                "uid": "HIV-002",
                "first_name": "Dongesit",
                "last_name": "Inyang",
                "email": "inyangidongesit22@gmail.com",
                "dob": date(1975, 11, 22),
                "gender": Gender.FEMALE,
                "status": PatientStatus.ACTIVE,
                "last_reading": now - timedelta(days=2),
                "vl": 45,  # Suppressed
                "regimen": "AZT/3TC/NVP",  # OLD regimen with Nevirapine
                "refill_date": today - timedelta(days=10),
                "refill_months": 3,
            },
            # Patient 3: IIT (>28 days overdue) → Agent should flag for recovery
            {
                "uid": "HIV-003",
                "first_name": "Dongesit",
                "last_name": "Imoh",
                "email": "iidongesit32@gmail.com",
                "dob": date(1992, 7, 14),
                "gender": Gender.MALE,
                "status": PatientStatus.IIT,
                "last_reading": now - timedelta(days=45),
                "vl": 180,
                "regimen": "TDF/3TC/DTG",
                "refill_date": today - timedelta(days=120),  # WAY overdue
                "refill_months": 3,
            },
            # Patient 4: DEFAULTER (<28 days overdue) → Agent should trace
            {
                "uid": "HIV-004",
                "first_name": "Elizabeth",
                "last_name": "Okon",
                "email": "okonelizabeth636@gmail.com",
                "dob": date(1985, 3, 8),
                "gender": Gender.FEMALE,
                "status": PatientStatus.ACTIVE_DEFAULTER,
                "last_reading": now - timedelta(days=20),
                "vl": 38,
                "regimen": "TDF/FTC/DTG",
                "refill_date": today - timedelta(days=105),  # 15 days overdue
                "refill_months": 3,
            },
            # Patient 5: NO RECENT READINGS → Agent should nudge
            {
                "uid": "HIV-005",
                "first_name": "Busayo",
                "last_name": "Fasheun",
                "email": "fasheunbusayo16@gmail.com",
                "dob": date(1995, 12, 25),
                "gender": Gender.FEMALE,
                "status": PatientStatus.ACTIVE,
                "last_reading": now - timedelta(days=10),  # 10 days no reading
                "vl": 25,
                "regimen": "ABC/3TC/DTG",
                "refill_date": today - timedelta(days=20),
                "refill_months": 3,
            },
        ]
        
        print(f"\n✅ PATIENTS (all with EMAIL preference):")
        print("-" * 50)
        
        created_patients = []
        for p in patients_data:
            patient_id = uuid.uuid4()
            
            # Calculate next refill date
            next_refill = p["refill_date"] + timedelta(days=p["refill_months"] * 30)
            
            patient = Patient(
                id=patient_id,
                organization_id=org_id,
                team_id=team_id,
                patient_uid=p["uid"],
                first_name=p["first_name"],
                last_name=p["last_name"],
                date_of_birth=p["dob"],
                gender=p["gender"],
                email=p["email"],
                phone=None,
                primary_condition=Condition.HIV,
                preferred_contact_method=CommunicationPreference.EMAIL,
                preferred_contact_time="09:00-21:00",
                auto_call_enabled=False,
                status=p["status"],
                monitoring_frequency="daily",
                timezone="Africa/Lagos",
                agent_enabled=True,
                primary_physician_id=worker_id,
                last_reading_at=p["last_reading"],
            )
            db.add(patient)
            await db.flush()
            
            # Create HIV Profile
            hiv_profile = HIVProfile(
                patient_id=patient_id,
                date_of_diagnosis=date(2020, 6, 15),
                art_start_date=date(2020, 7, 1),
                current_art_regimen=p["regimen"],
                regimen_line=RegimenLine.FIRST_LINE,
                baseline_viral_load=50000,
                baseline_cd4_count=300,
                last_viral_load_result=p["vl"],
                last_viral_load_sample_date=today - timedelta(days=30),
                last_viral_load_result_date=today - timedelta(days=15),
                last_refill_date=p["refill_date"],
                refill_months=p["refill_months"],
                next_refill_date=next_refill,
            )
            db.add(hiv_profile)
            created_patients.append(patient)
            
            print(f"   {p['uid']}: {p['first_name']} {p['last_name']}")
            print(f"           Email: {p['email']} | VL: {p['vl']} | Regimen: {p['regimen']}")
        
        await db.flush()
        
        # -----------------------------------------------------------------
        # 6. APPOINTMENTS
        # -----------------------------------------------------------------
        print(f"\n✅ APPOINTMENTS:")
        print("-" * 50)
        
        # Define appointment notes based on patient condition
        appointment_notes = [
            "High viral load detected (VL=5200). Needs urgent adherence counseling.",
            "Patient on outdated NVP regimen. Discuss switch to TLD.",
            "IIT patient (>28 days overdue). Recovery visit to re-engage in care.",
            "Active defaulter (15 days overdue). Urgent refill needed.",
            "Routine follow-up. Patient doing well but disengaged from app.",
        ]
        
        for i, patient in enumerate(created_patients):
            appt = Appointment(
                id=uuid.uuid4(),
                patient_id=patient.id,
                organization_id=org_id,
                provider_id=worker_id,
                scheduled_time=now + timedelta(hours=(i+1)*24),
                appointment_type="Follow-up",
                status=AppointmentStatus.SCHEDULED,
                notes=appointment_notes[i],  # Agents can read this!
            )
            db.add(appt)
            print(f"   {patient.first_name}: Follow-up in {i+1} day(s)")
        
        await db.commit()
        
        # -----------------------------------------------------------------
        # SUMMARY
        # -----------------------------------------------------------------
        print("\n" + "=" * 60)
        print("🎉 SEED COMPLETE!")
        print("=" * 60)
        
        print("\n📋 LOGIN:")
        print("   Admin:  koko4lyfe@gmail.com / SecurePass123")
        print("   Worker: winterfell856@gmail.com / SecurePass123")
        
        print("\n📋 TEST ENDPOINTS:")
        print("   1. POST /api/v1/auth/login")
        print("   2. GET  /api/v1/patients")
        print("   3. POST /api/v1/agent/morning-rounds  ← Trigger agents!")
        print("   4. GET  /api/v1/patients/{id}/agent-actions")
        
        print(f"\n📋 ORG ID: {org_id}")
        print()


if __name__ == "__main__":
    asyncio.run(seed_demo_data())
