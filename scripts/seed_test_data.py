"""
Seed script to create mock data for testing.

This creates:
1. An organization with HIV and Hypertension specializations
2. 5 patients (3 HIV, 2 Hypertension)
3. Appointments for testing reminder functionality

Run via Docker:
    docker compose exec app python scripts/seed_test_data.py
"""
import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

from app.utils.security import hash_password
from app.db.database import async_session_factory
from app.models.user import Organization, User, UserRole
from app.models.patient import Patient, Gender, PatientStatus, CommunicationPreference
from app.models.conditions import Condition, HIVProfile, HypertensionProfile
from app.models.appointment import Appointment, AppointmentStatus


async def seed_data():
    """Create test data for the appointments and reminders feature."""
    
    async with async_session_factory() as db:
        print("=" * 60)
        print("SEED DATA SCRIPT - Creating test data")
        print("=" * 60)
        
        # -----------------------------------------------------------------
        # 1. CREATE ORGANIZATION
        # -----------------------------------------------------------------
        org_id = uuid.uuid4()
        org = Organization(
            id=org_id,
            name="Mira Health Clinic",
            type="clinic",
            email="admin@mirahealthclinic.com",
            phone="+2348012345678",
            license_number="LIC-2024-001",
            is_active=True,
            is_onboarded=True,
            disease_specializations=["hiv", "hypertension"],
        )
        db.add(org)
        await db.flush()
        
        print(f"\n✅ Created Organization:")
        print(f"   ID: {org_id}")
        print(f"   Name: {org.name}")
        print(f"   Email: {org.email}")
        
        # -----------------------------------------------------------------
        # 2. CREATE ORG OWNER (Admin user you will login as)
        # -----------------------------------------------------------------
        owner_id = uuid.uuid4()
        owner = User(
            id=owner_id,
            organization_id=org_id,
            email="owner@mirahealthclinic.com",
            password_hash=hash_password("Password123!"),
            first_name="Dr. Amaka",
            last_name="Okonkwo",
            phone="+2348011111111",
            role=UserRole.ORG_OWNER,
            is_active=True,
            email_verified=True,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(owner)
        await db.flush()
        
        print(f"\n✅ Created Org Owner (LOGIN AS THIS USER):")
        print(f"   Email: owner@mirahealthclinic.com")
        print(f"   Password: Password123!")
        print(f"   Role: {owner.role.value}")
        
        # -----------------------------------------------------------------
        # 3. CREATE A DOCTOR (for appointments)
        # -----------------------------------------------------------------
        doctor_id = uuid.uuid4()
        doctor = User(
            id=doctor_id,
            organization_id=org_id,
            email="doctor@mirahealthclinic.com",
            password_hash=hash_password("Password123!"),
            first_name="Dr. Chidi",
            last_name="Eze",
            phone="+2348022222222",
            role=UserRole.DOCTOR,
            is_active=True,
            email_verified=True,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(doctor)
        await db.flush()
        
        print(f"\n✅ Created Doctor:")
        print(f"   Email: doctor@mirahealthclinic.com")
        print(f"   ID: {doctor_id}")
        
        # -----------------------------------------------------------------
        # 4. CREATE PATIENTS (3 HIV, 2 Hypertension)
        # -----------------------------------------------------------------
        patients_data = [
            # HIV Patients
            {
                "patient_uid": "HIV-001",
                "first_name": "Adaeze",
                "last_name": "Nwosu",
                "date_of_birth": date(1985, 3, 15),
                "gender": Gender.FEMALE,
                "phone": "+2348033333333",
                "email": "adaeze@example.com",
                "primary_condition": Condition.HIV,
                "preferred_contact_method": CommunicationPreference.SMS,
                "preferred_contact_time": "09:00-17:00",
                "auto_call_enabled": True,
            },
            {
                "patient_uid": "HIV-002",
                "first_name": "Emeka",
                "last_name": "Okoro",
                "date_of_birth": date(1990, 7, 22),
                "gender": Gender.MALE,
                "phone": "+2348044444444",
                "email": "emeka@example.com",
                "primary_condition": Condition.HIV,
                "preferred_contact_method": CommunicationPreference.CALL,
                "preferred_contact_time": "18:00-21:00",
                "auto_call_enabled": True,
            },
            {
                "patient_uid": "HIV-003",
                "first_name": "Ngozi",
                "last_name": "Ibe",
                "date_of_birth": date(1978, 11, 5),
                "gender": Gender.FEMALE,
                "phone": "+2348055555555",
                "email": "ngozi@example.com",
                "primary_condition": Condition.HIV,
                "preferred_contact_method": CommunicationPreference.EMAIL,
                "preferred_contact_time": "08:00-18:00",
                "auto_call_enabled": False,
            },
            # Hypertension Patients
            {
                "patient_uid": "HTN-001",
                "first_name": "Chukwuma",
                "last_name": "Okafor",
                "date_of_birth": date(1965, 1, 30),
                "gender": Gender.MALE,
                "phone": "+2348066666666",
                "email": "chukwuma@example.com",
                "primary_condition": Condition.HYPERTENSION,
                "preferred_contact_method": CommunicationPreference.SMS,
                "preferred_contact_time": "10:00-16:00",
                "auto_call_enabled": True,
            },
            {
                "patient_uid": "HTN-002",
                "first_name": "Obiageli",
                "last_name": "Aneke",
                "date_of_birth": date(1970, 6, 18),
                "gender": Gender.FEMALE,
                "phone": "+2348077777777",
                "email": "obiageli@example.com",
                "primary_condition": Condition.HYPERTENSION,
                "preferred_contact_method": CommunicationPreference.CALL,
                "preferred_contact_time": "14:00-20:00",
                "auto_call_enabled": True,
            },
        ]
        
        created_patients = []
        
        print(f"\n✅ Created Patients:")
        for pdata in patients_data:
            patient_id = uuid.uuid4()
            patient = Patient(
                id=patient_id,
                organization_id=org_id,
                patient_uid=pdata["patient_uid"],
                first_name=pdata["first_name"],
                last_name=pdata["last_name"],
                date_of_birth=pdata["date_of_birth"],
                gender=pdata["gender"],
                phone=pdata["phone"],
                email=pdata["email"],
                primary_condition=pdata["primary_condition"],
                preferred_contact_method=pdata["preferred_contact_method"],
                preferred_contact_time=pdata["preferred_contact_time"],
                auto_call_enabled=pdata["auto_call_enabled"],
                status=PatientStatus.ACTIVE,
                monitoring_frequency="daily",
                timezone="Africa/Lagos",
                agent_enabled=True,
                primary_physician_id=doctor_id,
            )
            db.add(patient)
            await db.flush()
            created_patients.append(patient)
            
            print(f"   - {pdata['patient_uid']}: {pdata['first_name']} {pdata['last_name']} ({pdata['primary_condition'].value})")
            
            # Create condition-specific profiles
            if pdata["primary_condition"] == Condition.HIV:
                hiv_profile = HIVProfile(
                    patient_id=patient_id,
                    date_of_diagnosis=date(2020, 6, 15),
                    art_start_date=date(2020, 7, 1),
                    current_art_regimen="TLD (Tenofovir/Lamivudine/Dolutegravir)",
                    last_refill_date=date.today() - timedelta(days=30),
                    refill_months=3,
                    next_refill_date=date.today() + timedelta(days=60),
                    baseline_viral_load=50000,
                    baseline_cd4_count=350,
                    last_viral_load_result=40,
                )
                db.add(hiv_profile)
            
            elif pdata["primary_condition"] == Condition.HYPERTENSION:
                htn_profile = HypertensionProfile(
                    patient_id=patient_id,
                    date_of_diagnosis=date(2019, 3, 10),
                    baseline_systolic=160,
                    baseline_diastolic=95,
                    target_systolic=130,
                    target_diastolic=80,
                    current_medication="Amlodipine 10mg",
                    last_checkup_date=date.today() - timedelta(days=14),
                    next_checkup_date=date.today() + timedelta(days=16),
                )
                db.add(htn_profile)
        
        await db.flush()
        
        # -----------------------------------------------------------------
        # 5. CREATE APPOINTMENTS (for testing reminders)
        # -----------------------------------------------------------------
        now = datetime.now(timezone.utc)
        
        appointments_data = [
            # Tomorrow - should trigger 24h reminder
            {
                "patient": created_patients[0],  # HIV-001
                "scheduled_time": now + timedelta(hours=26),
                "type": "ART Refill",
            },
            # In 2 hours - urgent reminder
            {
                "patient": created_patients[1],  # HIV-002
                "scheduled_time": now + timedelta(hours=2),
                "type": "Lab Review",
            },
            # In 3 days - advance notice
            {
                "patient": created_patients[2],  # HIV-003
                "scheduled_time": now + timedelta(days=3),
                "type": "Follow-up Visit",
            },
            # Tomorrow - hypertension patient
            {
                "patient": created_patients[3],  # HTN-001
                "scheduled_time": now + timedelta(hours=30),
                "type": "BP Check",
            },
            # In 4 hours - hypertension patient
            {
                "patient": created_patients[4],  # HTN-002
                "scheduled_time": now + timedelta(hours=4),
                "type": "Medication Review",
            },
        ]
        
        print(f"\n✅ Created Appointments:")
        for appt_data in appointments_data:
            appt_id = uuid.uuid4()
            appt = Appointment(
                id=appt_id,
                patient_id=appt_data["patient"].id,
                organization_id=org_id,
                provider_id=doctor_id,
                scheduled_time=appt_data["scheduled_time"],
                type=appt_data["type"],
                status=AppointmentStatus.SCHEDULED,
                priority_level=0,
                no_show_count=0,
            )
            db.add(appt)
            
            print(f"   - {appt_data['patient'].patient_uid}: {appt_data['type']} at {appt_data['scheduled_time'].strftime('%Y-%m-%d %H:%M')}")
        
        await db.commit()
        
        # -----------------------------------------------------------------
        # SUMMARY
        # -----------------------------------------------------------------
        print("\n" + "=" * 60)
        print("SEED DATA COMPLETE!")
        print("=" * 60)
        print("\n📋 LOGIN CREDENTIALS:")
        print("   Email: owner@mirahealthclinic.com")
        print("   Password: Password123!")
        print("\n📋 WHAT TO TEST ON SWAGGER (http://localhost:8000/docs):")
        print("   1. POST /api/v1/auth/login - Login with credentials above")
        print("   2. GET /api/v1/patients - List the 5 patients")
        print("   3. GET /api/v1/appointments - List appointments")
        print("   4. POST /api/v1/appointments/{id}/mark-no-show - Test escalation")
        print("   5. POST /api/v1/reminders/appointments/{id}/send-now - Trigger reminder")
        print("   6. GET /api/v1/reminders - List all reminders")
        print("\n📋 PATIENT IDs FOR TESTING:")
        for p in created_patients:
            print(f"   {p.patient_uid}: {p.id}")
        print()


if __name__ == "__main__":
    asyncio.run(seed_data())
