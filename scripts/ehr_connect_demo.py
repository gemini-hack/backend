import os
import time
import requests
import csv
import io
import random
import uuid
from datetime import datetime, timedelta

# ==========================================
# ⚙️ CONFIGURATION (Edit this section)
# ==========================================

# Toggle this to FALSE when deploying to a real hospital
DEMO_MODE = True 

# API Config
MIRA_API_URL = "http://localhost:8000/api/v1/patients/batch-upload"
# MIRA_API_URL = "https://miraproject.online/api/v1/patients/batch-upload"
MIRA_API_KEY = "your_auth_token_here" # Use a valid JWT or API Key

# Real Database Config (Ignored if DEMO_MODE is True)
EHR_TYPE = "LAMIS" # Options: "LAMIS", "OPENMRS"
DB_HOST = "localhost"
DB_NAME = "lamisplus"
DB_USER = "postgres"
DB_PASS = "postgres"

# ==========================================
# 🧪 MOCK DATA GENERATORS (For Demo)
# ==========================================

def generate_mock_lamis_data(count=10):
    """Generates fake patient records in LAMIS format."""
    print(f"🧪 Generating {count} mock LAMIS patients...")
    
    first_names = ["Chioma", "Emeka", "Aisha", "Musa", "Ngozi", "Tunde", "Femi", "Zainab"]
    last_names = ["Okafor", "Bello", "Adeyemi", "Okon", "Ibrahim", "Eze", "Dangote"]
    regimens = ["TDF/3TC/DTG", "AZT/3TC/NVP", "ABC/3TC/EFV"]
    
    rows = []
    columns = ["HospitalNum", "Surname", "OtherNames", "DateOfBirth", "Sex", 
               "Phone", "DateConfirmedHIV", "DateArvStarted", "CurrentRegimen", 
               "LastViralLoad", "DateLastViralLoad", "DateNextAppointment", 
               "CaseManager", "EnrollmentSetting", "WHOStage", "FunctionalStatus"]

    for _ in range(count):
        # Simulate a patient who missed their appointment 3 days ago
        last_visit = datetime.now() - timedelta(days=33)
        next_app = last_visit + timedelta(days=30) # Missed by 3 days!
        
        rows.append({
            "HospitalNum": f"LMS-{random.randint(10000, 99999)}",
            "Surname": random.choice(last_names),
            "OtherNames": random.choice(first_names),
            "DateOfBirth": "1990-05-12",
            "Sex": random.choice(["Male", "Female"]),
            "Phone": f"080{random.randint(10000000, 99999999)}",
            "DateConfirmedHIV": "2023-01-15",
            "DateArvStarted": "2023-02-01",
            "CurrentRegimen": random.choice(regimens),
            "LastViralLoad": random.choice([20, 400, 15000]), # 15000 is High Risk
            "DateLastViralLoad": "2023-11-20",
            "DateNextAppointment": next_app.strftime("%Y-%m-%d"),
            "CaseManager": "Dr. Chioma",
            "EnrollmentSetting": "OPD",
            "WHOStage": "Stage I",
            "FunctionalStatus": "Working"
        })
    return columns, rows

# ==========================================
# 🏥 REAL DATABASE FETCHERS (For Production)
# ==========================================

def fetch_lamis_real():
    import psycopg2
    conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
    cursor = conn.cursor()
    query = "SELECT hospital_num, surname, ... FROM patient ..." # (Full query from previous chat)
    cursor.execute(query)
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    conn.close()
    return columns, rows

def fetch_openmrs_real():
    import mysql.connector
    conn = mysql.connector.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
    # ... (Full query logic) ...
    return [], []

# ==========================================
# 🚀 MAIN SYNC LOGIC
# ==========================================

def sync_to_mira():
    print(f"\n[{datetime.now()}] 🔄 Starting Mira Connect Sync...")
    
    try:
        # 1. GET DATA (Mock or Real)
        if DEMO_MODE:
            if EHR_TYPE == "LAMIS":
                columns, rows_data = generate_mock_lamis_data(5)
                # Convert list of dicts to list of lists for CSV writer
                rows = [[r[col] for col in columns] for r in rows_data]
            else:
                print("Mock OpenMRS not implemented in demo.")
                return
        else:
            # PROD: Connect to real DB
            if EHR_TYPE == "LAMIS":
                columns, rows = fetch_lamis_real()
            else:
                columns, rows = fetch_openmrs_real()

        print(f"📦 Prepared {len(rows)} patient records.")

        # 2. CONVERT TO CSV
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(columns) # Header
        writer.writerows(rows)   # Data
        csv_content = output.getvalue()

        # 3. PUSH TO MIRA API
        print(f"📡 Uploading to {MIRA_API_URL}...")
        
        # We simulate a file upload named 'sync.csv'
        files = {'file': ('sync.csv', csv_content, 'text/csv')}
        headers = {'Authorization': f'Bearer {MIRA_API_KEY}'}
        
        response = requests.post(MIRA_API_URL, files=files, headers=headers)
        
        if response.status_code in [200, 201, 202]:
            print("✅ SUCCESS! Data synced to Mira.")
            print(f"Response: {response.json()}")
        else:
            print(f"❌ FAILED. Status: {response.status_code}")
            print(f"Reason: {response.text}")

    except Exception as e:
        print(f"❌ CRITICAL ERROR: {e}")

if __name__ == "__main__":
    sync_to_mira()