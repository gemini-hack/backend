#!/usr/bin/env python3
"""
🎬 MIRA EHR Connection Demo
============================
This script simulates connecting to a hospital's LAMIS/OpenMRS database
and importing patient data into MIRA. Perfect for video demos!

Run: docker compose exec app python scripts/ehr_demo_video.py

For video recording, this script has:
- Dramatic pauses for visual effect
- Colorful terminal output
- Step-by-step progress display
- Realistic Nigerian patient data
"""

import time
import random
import requests
import csv
import io
from datetime import datetime, timedelta

# ==========================================
# 🎨 COLORS FOR TERMINAL OUTPUT
# ==========================================
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_step(emoji, message, delay=0.5):
    """Print a step with animation effect."""
    print(f"\n{Colors.CYAN}{emoji} {message}{Colors.END}")
    time.sleep(delay)

def print_success(message):
    print(f"{Colors.GREEN}✅ {message}{Colors.END}")

def print_data(label, value):
    print(f"   {Colors.BLUE}→{Colors.END} {label}: {Colors.BOLD}{value}{Colors.END}")

# ==========================================
# 🏥 MOCK HOSPITAL DATABASE
# ==========================================

# Realistic Nigerian names and regimens
MOCK_PATIENTS = [
    {
        "HospitalNum": "LUTH-HIV-2024-001",
        "Surname": "Adeyemi",
        "OtherNames": "Oluwaseun Grace",
        "DateOfBirth": "1989-03-15",
        "Sex": "Female",
        "Phone": "08034567890",
        "Email": "adeyemi.grace@gmail.com",
        "DateConfirmedHIV": "2021-06-10",
        "DateArvStarted": "2021-07-01",
        "CurrentRegimen": "TDF/3TC/DTG",  # Good regimen
        "LastViralLoad": 32,  # Suppressed ✓
        "DateLastViralLoad": "2025-11-15",
        "DateNextAppointment": (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d"),
        "CaseManager": "Dr. Okonkwo",
        "EnrollmentSetting": "VCT",
        "WHOStage": "Stage I",
        "FunctionalStatus": "Working"
    },
    {
        "HospitalNum": "LUTH-HIV-2024-002",
        "Surname": "Mohammed",
        "OtherNames": "Fatima Aisha",
        "DateOfBirth": "1975-08-22",
        "Sex": "Female",
        "Phone": "07012345678",
        "Email": "fatima.mohammed@yahoo.com",
        "DateConfirmedHIV": "2015-03-20",
        "DateArvStarted": "2015-04-10",
        "CurrentRegimen": "AZT/3TC/NVP",  # ⚠️ OLD REGIMEN - needs switch!
        "LastViralLoad": 89,  # Suppressed but on bad regimen
        "DateLastViralLoad": "2025-10-01",
        "DateNextAppointment": (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d"),
        "CaseManager": "Dr. Okonkwo",
        "EnrollmentSetting": "OPD",
        "WHOStage": "Stage II",
        "FunctionalStatus": "Working"
    },
    {
        "HospitalNum": "LUTH-HIV-2024-003",
        "Surname": "Okafor",
        "OtherNames": "Chukwuemeka Peter",
        "DateOfBirth": "1992-11-08",
        "Sex": "Male",
        "Phone": "09087654321",
        "Email": "peter.okafor@gmail.com",
        "DateConfirmedHIV": "2023-01-15",
        "DateArvStarted": "2023-02-01",
        "CurrentRegimen": "TDF/3TC/DTG",
        "LastViralLoad": 8500,  # ⚠️ HIGH VL - unsuppressed!
        "DateLastViralLoad": "2025-12-01",
        "DateNextAppointment": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
        "CaseManager": "Dr. Eze",
        "EnrollmentSetting": "OPD",
        "WHOStage": "Stage III",
        "FunctionalStatus": "Ambulatory"
    },
    {
        "HospitalNum": "LUTH-HIV-2024-004",
        "Surname": "Bello",
        "OtherNames": "Ibrahim Yusuf",
        "DateOfBirth": "1988-05-30",
        "Sex": "Male",
        "Phone": "08123456789",
        "Email": "ibrahim.bello@hotmail.com",
        "DateConfirmedHIV": "2020-09-12",
        "DateArvStarted": "2020-10-01",
        "CurrentRegimen": "ABC/3TC/DTG",
        "LastViralLoad": 45,
        "DateLastViralLoad": "2025-08-20",
        "DateNextAppointment": (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d"),  # ⚠️ IIT!
        "CaseManager": "Dr. Eze",
        "EnrollmentSetting": "Outreach",
        "WHOStage": "Stage I",
        "FunctionalStatus": "Working"
    },
    {
        "HospitalNum": "LUTH-HIV-2024-005",
        "Surname": "Nwachukwu",
        "OtherNames": "Chidinma Joy",
        "DateOfBirth": "1995-02-14",
        "Sex": "Female",
        "Phone": "07065432198",
        "Email": "joy.nwachukwu@gmail.com",
        "DateConfirmedHIV": "2024-01-05",
        "DateArvStarted": "2024-01-20",
        "CurrentRegimen": "TDF/FTC/DTG",
        "LastViralLoad": 18,  # Excellent suppression
        "DateLastViralLoad": "2025-12-10",
        "DateNextAppointment": (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
        "CaseManager": "Dr. Okonkwo",
        "EnrollmentSetting": "PMTCT",
        "WHOStage": "Stage I",
        "FunctionalStatus": "Working"
    },
]

# ==========================================
# 🎬 MAIN DEMO FLOW
# ==========================================

def run_demo():
    print("\n" + "="*60)
    print(f"{Colors.HEADER}{Colors.BOLD}")
    print("  🏥 MIRA EHR INTEGRATION DEMO")
    print("  Lagos University Teaching Hospital → MIRA")
    print(f"{Colors.END}")
    print("="*60)
    time.sleep(1)
    
    # STEP 1: Connect to EHR
    print_step("🔌", "Connecting to hospital EHR system...", 1.5)
    print(f"   {Colors.BLUE}Host:{Colors.END} 192.168.1.100 (LAMIS Server)")
    print(f"   {Colors.BLUE}Database:{Colors.END} lamisplus_production")
    print(f"   {Colors.BLUE}Protocol:{Colors.END} PostgreSQL (SSL/TLS)")
    time.sleep(0.5)
    print_success("Connection established!")
    
    # STEP 2: Query Patient Records
    print_step("📋", "Querying patient records from LAMIS...", 1)
    print(f"   {Colors.CYAN}SQL:{Colors.END} SELECT * FROM patient_art_info...")
    time.sleep(1)
    print_success(f"Found {len(MOCK_PATIENTS)} patients to sync")
    
    # STEP 3: Display Records
    print_step("👥", "Preparing patient data for import:", 0.5)
    print("-" * 50)
    
    for i, patient in enumerate(MOCK_PATIENTS, 1):
        time.sleep(0.3)
        name = f"{patient['OtherNames'].split()[0]} {patient['Surname']}"
        vl = patient['LastViralLoad']
        regimen = patient['CurrentRegimen']
        
        # Highlight issues
        vl_status = f"{Colors.GREEN}✓ Suppressed{Colors.END}" if vl < 200 else f"{Colors.RED}⚠ HIGH ({vl}){Colors.END}"
        regimen_warning = f" {Colors.WARNING}(Phased out){Colors.END}" if "NVP" in regimen else ""
        
        print(f"\n   {Colors.BOLD}Patient {i}:{Colors.END} {name}")
        print(f"   └─ Hospital #: {patient['HospitalNum']}")
        print(f"   └─ Regimen: {regimen}{regimen_warning}")
        print(f"   └─ Viral Load: {vl_status}")
    
    print("\n" + "-" * 50)
    
    # STEP 4: Transform Data
    print_step("🔄", "Transforming LAMIS format → MIRA schema...", 1)
    print("   Mapping columns: HospitalNum → patient_uid")
    print("   Mapping columns: OtherNames → first_name")
    print("   Mapping columns: Surname → last_name")
    print("   Normalizing dates to ISO 8601...")
    time.sleep(0.5)
    print_success("Data transformation complete!")
    
    # STEP 5: Upload to MIRA
    print_step("📤", "Uploading to MIRA API...", 1)
    
    # Convert to CSV
    columns = list(MOCK_PATIENTS[0].keys())
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    writer.writerows(MOCK_PATIENTS)
    csv_content = output.getvalue()
    
    # Get auth token (you need to replace this with a real token)
    # For demo, we'll try without auth first
    print(f"   {Colors.CYAN}Endpoint:{Colors.END} POST /api/v1/patients/batch-upload")
    print(f"   {Colors.CYAN}Records:{Colors.END} {len(MOCK_PATIENTS)} patients")
    print(f"   {Colors.CYAN}Format:{Colors.END} CSV (transformed)")
    
    try:
        # Try to upload
        files = {'file': ('lamis_sync.csv', csv_content, 'text/csv')}
        
        # For demo, we'll print what WOULD happen
        time.sleep(1.5)
        print_success("Upload complete! Patients imported to MIRA.")
        
    except Exception as e:
        print(f"{Colors.WARNING}⚠️ Demo mode - simulating upload success{Colors.END}")
    
    # STEP 6: Trigger Agents
    print_step("🤖", "Triggering MIRA AI Agents...", 1)
    print("   DisengagementWorker: Checking patient engagement...")
    print("   HIVWorker: Analyzing viral loads and regimens...")
    print("   FollowUpSpecialist: Checking appointment compliance...")
    time.sleep(1)
    
    # STEP 7: Summary
    print("\n" + "="*60)
    print(f"{Colors.GREEN}{Colors.BOLD}")
    print("  ✅ EHR SYNC COMPLETE!")
    print(f"{Colors.END}")
    print("="*60)
    
    print(f"\n{Colors.BOLD}Summary:{Colors.END}")
    print(f"   • {Colors.GREEN}5 patients imported{Colors.END}")
    print(f"   • {Colors.RED}1 patient with high viral load flagged{Colors.END}")
    print(f"   • {Colors.WARNING}1 patient on outdated regimen flagged{Colors.END}")
    print(f"   • {Colors.WARNING}1 patient IIT (>28 days overdue) flagged{Colors.END}")
    
    print(f"\n{Colors.CYAN}AI agents are now analyzing and taking action...{Colors.END}")
    print(f"Check the worker dashboard to see flagged patients.\n")

if __name__ == "__main__":
    run_demo()
