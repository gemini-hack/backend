import asyncio
import uuid
import sys
import os
from datetime import date, timedelta, datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Add parent directory to path to import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import async_session_factory, engine
from app.models.user import Organization
from app.models.patient import Patient, Condition, PatientStatus, HealthReading, AgentAction, Alert
from app.workflows.daily_analysis import DailyAnalysisWorkflow
from app.utils.logger import logger

async def setup_test_data(db: AsyncSession):
    """Seed a test organization and some patients."""
    logger.info("Setting up test data...")
    
    # 1. Create Organization with specializations
    org_id = uuid.uuid4()
    org = Organization(
        id=org_id,
        name="Test Health Clinic",
        type="clinic",
        email="test@clinic.com",
        disease_specializations=["hiv", "hypertension"],
        is_active=True,
        is_onboarded=True
    )
    db.add(org)
    
    # 2. Create HIV patient (Unsuppressed)
    p1_id = uuid.uuid4()
    p1 = Patient(
        id=p1_id,
        organization_id=org_id,
        patient_uid=f"HIV-{p1_id.hex[:6]}",
        first_name="John",
        last_name="Doe",
        date_of_birth=date(1990, 1, 1),
        primary_condition=Condition.HIV,
        status=PatientStatus.ACTIVE,
        last_viral_load_result=1500,  # Unsuppressed
        last_refill_date=date.today() - timedelta(days=40), # Missed
        refill_months=1
    )
    db.add(p1)
    
    # 3. Create Hypertension patient (Crisis)
    p2_id = uuid.uuid4()
    p2 = Patient(
        id=p2_id,
        organization_id=org_id,
        patient_uid=f"HTN-{p2_id.hex[:6]}",
        first_name="Jane",
        last_name="Smith",
        date_of_birth=date(1985, 5, 10),
        primary_condition=Condition.HYPERTENSION,
        status=PatientStatus.ACTIVE
    )
    db.add(p2)
    
    # Add a critical reading for the HTN patient
    reading = HealthReading(
        patient_id=p2_id,
        organization_id=org_id,
        reading_type="blood_pressure",
        value=190,  # Systolic
        secondary_value=125, # Diastolic
        unit="mmHg",
        reading_time=datetime.now(),
        source="device"
    )
    db.add(reading)
    
    await db.commit()
    return org_id

async def run_verification():
    """Main verification flow."""
    logger.info("Mira AI: Starting Multi-Agent System Verification")
    
    async with async_session_factory() as db:
        # Step 1: Data Setup
        org_id = await setup_test_data(db)
        
        # Step 2: Trigger Daily Analysis
        logger.info(f"Triggering Morning Rounds for Org: {org_id}")
        workflow = DailyAnalysisWorkflow(db)
        await workflow.execute_for_org(org_id)
        
        # Step 3: Check Persistence
        logger.info("--- Verification Results ---")
        
        # Check Agent Actions
        actions_query = select(AgentAction).where(AgentAction.organization_id == org_id)
        actions_result = await db.execute(actions_query)
        actions = actions_result.scalars().all()
        
        print(f"\n[AGENT ACTIONS GENERATED: {len(actions)}]")
        for a in actions:
            print(f"- Type: {a.action_type}")
            print(f"  Patient: {a.patient_id}")
            print(f"  Reasoning: {a.ai_reasoning}")
            print(f"  Confidence: {a.confidence_score}\n")

        # Check Alerts
        alerts_query = select(Alert).where(Alert.organization_id == org_id)
        alerts_result = await db.execute(alerts_query)
        alerts = alerts_result.scalars().all()
        
        print(f"[ALERTS CREATED: {len(alerts)}]")
        for al in alerts:
            print(f"- Severity: {al.severity}")
            print(f"  Title: {al.title}")
            print(f"  Description: {al.description}\n")

        # Check Critic Findings (WorkerResults)
        # We need the context from the workflow
        # (This script doesn't capture the context object from workflow.execute_for_org,
        # but the Critic logs will be visible in the console. 
        # For the script output, let's just finish up.)
        print("[CHECK CONSOLE LOGS ABOVE FOR CRITIC 'APPROVED/REJECTED' DECISIONS]")

async def main():
    try:
        await run_verification()
    except Exception as e:
        print(f"FAILED: {e}")
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
