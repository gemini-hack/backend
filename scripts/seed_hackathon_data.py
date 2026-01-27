import asyncio
import uuid
import random
from datetime import date, datetime, timedelta, timezone

# Ensure you are running this from the root folder
from app.db.database import async_session_factory
from app.models.user import User, Organization, UserRole
from app.models.patient import Patient, PatientStatus, Gender, Condition, CommunicationPreference
from app.models.conditions import HIVProfile
from app.models.agent import AgentAction
from app.utils.security import hash_password

# --- CONFIGURATION ---
ORG_NAME = "Lagos General Hospital (Staging)"

ADMIN_EMAIL = "koko4lyfe@gmail.com" 
ADMIN_PASS = "SecurePass123"

async def seed_data():
    async with async_session_factory() as db:
        print(f"🌱 Seeding Staging Data for: {ORG_NAME}...")

        # 1. Create/Get Organization
        existing_org = await Organization.fetch_unique(db, email="admin@lagos-general.ng")
        if existing_org:
            org = existing_org
        else:
            org = Organization(
                name=ORG_NAME,
                email="admin@lagos-general.ng",
                type="Public Hospital",
                is_active=True,
                is_onboarded=True,
                disease_specializations=["hiv", "hypertension"]
            )
            db.add(org)
            await db.flush()
        
        # 2. Create YOUR User (Force Verified)
        existing_user = await User.fetch_unique(db, email=ADMIN_EMAIL)
        if not existing_user:
            doctor = User(
                organization_id=org.id,
                email=ADMIN_EMAIL,
                password_hash=hash_password(ADMIN_PASS),
                first_name="Chioma",
                last_name="Okeke",
                role=UserRole.ORG_OWNER, # <--- UPGRADED TO OWNER
                is_active=True,
                email_verified=True,  # <--- FORCE VERIFIED
                avatar_url="https://i.pravatar.cc/150?u=chioma"
            )
            db.add(doctor)
            await db.flush()
            print(f"✅ Created User: {doctor.email} / {ADMIN_PASS}")
            user_id = doctor.id
        else:
            print(f"ℹ️ User {ADMIN_EMAIL} already exists.")
            # Ensure the existing user is verified
            existing_user.email_verified = True
            existing_user.organization_id = org.id # Ensure linked to this org
            user_id = existing_user.id
            await db.flush()

        # 3. Create Patients (Linked to YOU)
        
        # Patient A: The "Red" Flag
        existing_patient_red = await Patient.fetch_unique(db, patient_uid="PT-RED-001")
        if not existing_patient_red:
            patient_red = Patient(
                organization_id=org.id,
                patient_uid="PT-RED-001",
                first_name="Ukeme",
                last_name="Etim",
                date_of_birth=date(1978, 3, 15),
                gender=Gender.FEMALE,
                phone="+2348000000001",
                primary_condition=Condition.HIV,
                primary_physician_id=user_id, # Linked to YOU
                status=PatientStatus.ACTIVE,
                email="ukemeetim2222@gmail.com", # <--- UPDATED EMAIL
                preferred_contact_method=CommunicationPreference.EMAIL # <--- PREF CHANGED
            )
            db.add(patient_red)
            await db.flush()

            profile_red = HIVProfile(
                patient_id=patient_red.id,
                date_of_diagnosis=date(2010, 1, 1),
                art_start_date=date(2010, 2, 1),
                current_art_regimen="AZT/3TC/NVP", # Bad Drug
                last_refill_date=date.today() - timedelta(days=20),
                refill_months=3
            )
            db.add(profile_red)

            # Action for Red Patient
            action_red = AgentAction(
                organization_id=org.id,
                patient_id=patient_red.id,
                action_type="regimen_optimization",
                status="pending",
                confidence_score=1.0,
                ai_reasoning="Patient is on Nevirapine (NVP). Recommended switch to TLD.",
                content={"current_regimen": "AZT/3TC/NVP", "suggested": "TDF/3TC/DTG"}
            )
            db.add(action_red)
        else:
             print("ℹ️ Updating Patient PT-RED-001 info...")
             existing_patient_red.email = "ukemeetim2222@gmail.com"
             existing_patient_red.preferred_contact_method = CommunicationPreference.EMAIL
             existing_patient_red.primary_physician_id = user_id
             db.add(existing_patient_red)

        # Patient B: The "Green" Flag (Stable)
        # Patient B: The "Green" Flag
        existing_patient_green = await Patient.fetch_unique(db, patient_uid="PT-GRN-002")
        if not existing_patient_green:
            patient_green = Patient(
                organization_id=org.id,
                patient_uid="PT-GRN-002",
                first_name="Bruno",
                last_name="Steel",
                date_of_birth=date(1985, 11, 30),
                gender=Gender.MALE,
                phone="+2348000000002",
                primary_condition=Condition.HIV,
                primary_physician_id=user_id, # Linked to YOU
                status=PatientStatus.ACTIVE,
                email="brunostee270@gmail.com", # <--- UPDATED EMAIL
                preferred_contact_method=CommunicationPreference.EMAIL # <--- PREF CHANGED
            )
            db.add(patient_green)
            await db.flush()

            profile_green = HIVProfile(
                patient_id=patient_green.id,
                date_of_diagnosis=date(2019, 5, 10),
                current_art_regimen="TDF/3TC/DTG", # Good Drug
                last_refill_date=date.today() - timedelta(days=85),
                refill_months=3
            )
            db.add(profile_green)
            
            # Completed Action for Green Patient
            action_green = AgentAction(
                organization_id=org.id,
                patient_id=patient_green.id,
                action_type="engagement_nudge",
                status="completed",
                confidence_score=0.95,
                ai_reasoning="Routine check-in sent.",
                content={"execution_status": "SENT_AUTOMATICALLY"}
            )
            db.add(action_green)
        else:
             print("ℹ️ Updating Patient PT-GRN-002 info...")
             existing_patient_green.email = "brunostee270@gmail.com"
             existing_patient_green.preferred_contact_method = CommunicationPreference.EMAIL
             existing_patient_green.primary_physician_id = user_id
             db.add(existing_patient_green)

        await db.commit()
        print("\n✅ SEEDING COMPLETE! Login with:")
        print(f"👉 Email: {ADMIN_EMAIL}")
        print(f"👉 Pass:  {ADMIN_PASS}")

if __name__ == "__main__":
    asyncio.run(seed_data())