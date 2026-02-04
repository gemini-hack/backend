import csv
import random
from datetime import date, datetime, timedelta
import uuid

# Output file
OUTPUT_FILE = "/tmp/mira_patient_scenarios.csv"
NUM_RANDOM_PATIENTS = 47 # Total 50 (3 fixed + 47 random)

# Extended Headers matching user request + EMAIL
FIELDNAMES = [
    'uid', 'first_name', 'last_name', 'email', 'gender', 'dob',
    'status', 'treatment_status',
    # Vitals
    'weight_kg', 'height_m', 'bmi', 'temperature_c', 'pulse_bpm', 
    'bp_systolic', 'bp_diastolic',
    # HIV History / Biodata
    'date_of_diagnosis', 'art_start_date', 
    'cd4_count_baseline', 'baseline_viral_load', 'art_regimen_baseline',
    # Current Status / Visits
    'current_art_regimen', 'current_viral_load', 
    'date_vl_sample', 'date_vl_result',
    'last_refill_date', 'refill_months', 'next_refill_date',
    'adherence_missed_doses'
]

GENDERS = ["MALE", "FEMALE"]
FIRST_NAMES_M = ["James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Charles"]
FIRST_NAMES_F = ["Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan", "Jessica", "Sarah", "Karen"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Jones", "Brown", "Davis", "Miller", "Wilson", "Moore", "Taylor"]
STATUSES = ["ACTIVE", "ACTIVE", "ACTIVE", "ACTIVE", "IIT", "ACTIVE_DEFAULTER", "TRANSFERRED_OUT"] 
REGIMENS = ["TDF/3TC/DTG", "TDF/FTC/DTG", "ABC/3TC/DTG", "AZT/3TC/NVP"]

# Extra personas to use in random generation
EXTRA_PERSONAS = [
    {"first": "Dongesit", "last": "Inyang", "email": "inyangidongesit22@gmail.com", "gender": "FEMALE"},
    {"first": "Busayo", "last": "Fasheun", "email": "fasheunbusayo16@gmail.com", "gender": "FEMALE"},
    {"first": "Ukeme", "last": "Etim", "email": "Ukemeetim2222@gmail.com", "gender": "MALE"}
]

def calculate_bmi(weight, height):
    if weight and height:
        return round(weight / (height * height), 1)
    return None

def get_dob(age):
    today = date.today()
    return (today - timedelta(days=age*365 + random.randint(0, 364))).isoformat()

def generate_random_patient(index, persona=None):
    if persona:
        gender = persona["gender"]
        first_name = persona["first"]
        last_name = persona["last"]
        email = persona["email"]
    else:
        gender = random.choice(GENDERS)
        first_name = random.choice(FIRST_NAMES_M) if gender == "MALE" else random.choice(FIRST_NAMES_F)
        last_name = random.choice(LAST_NAMES)
        email = f"{first_name.lower()}.{last_name.lower()}{index}@example.com"
    
    # Status
    status = random.choice(STATUSES)
    treatment_status = "Active" if status in ["ACTIVE", "ACTIVE_DEFAULTER"] else "IIT" if status == "IIT" else "Transferred Out"
    
    # Vitals
    weight = random.randint(50, 95)
    height = random.randint(155, 185) / 100
    bmi = calculate_bmi(weight, height)
    bp_sys = random.randint(110, 140)
    bp_dia = random.randint(70, 90)
    
    # Dates
    today = date.today()
    years_diagnosed = random.randint(1, 15)
    date_diag = (today - timedelta(days=years_diagnosed*365)).isoformat()
    art_start = (today - timedelta(days=years_diagnosed*365 - random.randint(10, 60))).isoformat()
    
    # Regimen
    regimen = random.choice(REGIMENS)
    
    # Viral Load
    suppressed = random.random() > 0.15 # 85% suppressed
    vl = random.randint(0, 50) if suppressed else random.randint(1000, 50000)
    
    last_refill_days = random.randint(10, 100)
    last_refill = (today - timedelta(days=last_refill_days)).isoformat()
    
    return {
        "uid": f"MIRA-GEN-{1000+index}",
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "gender": gender,
        "dob": get_dob(random.randint(18, 65)),
        "status": status,
        "treatment_status": treatment_status,
        
        # Vitals
        "weight_kg": weight,
        "height_m": height,
        "bmi": bmi,
        "temperature_c": round(random.uniform(36.1, 37.5), 1),
        "pulse_bpm": random.randint(60, 100),
        "bp_systolic": bp_sys,
        "bp_diastolic": bp_dia,
        
        # HIV Data
        "date_of_diagnosis": date_diag,
        "art_start_date": art_start,
        "cd4_count_baseline": random.randint(50, 400),
        "baseline_viral_load": random.randint(1000, 100000) if random.random() > 0.3 else "",
        "art_regimen_baseline": regimen,
        
        # Current
        "current_art_regimen": regimen,
        "current_viral_load": vl,
        "date_vl_sample": (today - timedelta(days=random.randint(30, 180))).isoformat(),
        "date_vl_result": (today - timedelta(days=random.randint(10, 29))).isoformat(),
        "last_refill_date": last_refill,
        "refill_months": 3,
        "next_refill_date": "", 
        "adherence_missed_doses": random.choice([0, 0, 0, 1, 2, 5, 10])
    }

def generate_scenarios():
    scenarios = []
    today = date.today()

    # ==========================================
    # SCENARIO 1: New Client (Bruno Steel)
    # ==========================================
    scenarios.append({
        "uid": "MIRA-NEW-001",
        "first_name": "Bruno", "last_name": "Steel",
        "email": "brunosteel270@gmail.com",
        "gender": "MALE", "dob": get_dob(45),
        "status": "ACTIVE", "treatment_status": "Not Commenced",
        "weight_kg": 70, "height_m": 1.56, "bmi": calculate_bmi(70, 1.56),
        "temperature_c": 37.0, "pulse_bpm": 71, "bp_systolic": 113, "bp_diastolic": 78,
        "date_of_diagnosis": "2025-01-23", "art_start_date": "", 
        "cd4_count_baseline": 180, "baseline_viral_load": "", "art_regimen_baseline": "",
        "current_art_regimen": "", "current_viral_load": "", 
        "date_vl_sample": "", "date_vl_result": "",
        "last_refill_date": "", "refill_months": "", "next_refill_date": "", "adherence_missed_doses": ""
    })

    # ==========================================
    # SCENARIO 2: Returning Client (Elizabeth Okon)
    # ==========================================
    scenarios.append({
        "uid": "MIRA-RET-002",
        "first_name": "Elizabeth", "last_name": "Okon",
        "email": "okonelizabeth636@gmail.com",
        "gender": "FEMALE", "dob": get_dob(35),
        "status": "ACTIVE", "treatment_status": "Active",
        "weight_kg": 66, "height_m": 1.52, "bmi": calculate_bmi(66, 1.52),
        "temperature_c": 36.4, "pulse_bpm": 80, "bp_systolic": 120, "bp_diastolic": 78,
        "date_of_diagnosis": "2009-10-02", "art_start_date": "2009-10-04",
        "cd4_count_baseline": 150, "baseline_viral_load": 2300, "art_regimen_baseline": "TDF/3TC/DTG",
        "current_art_regimen": "TDF/3TC/DTG", "current_viral_load": 20,
        "date_vl_sample": "2025-10-10", "date_vl_result": "2025-10-15",
        "last_refill_date": "2025-10-10", "refill_months": 3, "next_refill_date": "", "adherence_missed_doses": 0
    })

    # ==========================================
    # SCENARIO 3: Simulated "5th Visit" (Dongesit Imoh)
    # ==========================================
    diag_date = (today - timedelta(days=185)).isoformat()
    start_date = (today - timedelta(days=180)).isoformat() 
    
    scenarios.append({
        "uid": "MIRA-SIM-003",
        "first_name": "Dongesit", "last_name": "Imoh",
        "email": "iidongesit32@gmail.com",
        "gender": "MALE", "dob": get_dob(28),
        "status": "ACTIVE", "treatment_status": "Active",
        "weight_kg": 75, "height_m": 1.75, "bmi": calculate_bmi(75, 1.75),
        "temperature_c": 36.8, "pulse_bpm": 72, "bp_systolic": 118, "bp_diastolic": 76,
        "date_of_diagnosis": diag_date, "art_start_date": start_date,
        "cd4_count_baseline": 350, "baseline_viral_load": "", "art_regimen_baseline": "TDF/3TC/DTG",
        "current_art_regimen": "TDF/3TC/DTG", "current_viral_load": "", 
        "date_vl_sample": "", "date_vl_result": "",
        "last_refill_date": (today - timedelta(days=30)).isoformat(), 
        "refill_months": 1, "next_refill_date": today.isoformat(), "adherence_missed_doses": 2
    })
    
    # Generate Randoms (using Extra Personas first)
    for i in range(NUM_RANDOM_PATIENTS):
        persona = None
        if i < len(EXTRA_PERSONAS):
            persona = EXTRA_PERSONAS[i]
        scenarios.append(generate_random_patient(i+1, persona))

    return scenarios

def main():
    print(f"Generating scenarios to {OUTPUT_FILE}...")
    data = generate_scenarios()
    
    with open(OUTPUT_FILE, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in data:
            writer.writerow(row)
            
    print(f"✅ Generated {len(data)} detailed scenarios (3 Fixed + {NUM_RANDOM_PATIENTS} Random).")

if __name__ == "__main__":
    main()
