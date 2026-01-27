"""
Medical guidelines and approved regimens.
Source: National Guidelines.
"""

# Adult 1st Line Green List
APPROVED_ADULT_FIRST_LINE = {
    "TDF(300mg)+FTC(200mg)+DTG(50mg)",
    "TDF(300mg)/3TC(300mg)/DTG(50mg)",
    "ABC(600mg)+3TC(300mg)+DTG(50mg)",
    "TDF(300mg)+3TC(300mg)+EFV 400mg", 
    "TAF (25mg) + 3TC (300mg)+DTG (50mg)",
    "TAF (25mg) + 3TC (300mg) + EFV (600mg)",
}

# Adult 2nd & 3rd Line Green List
APPROVED_ADULT_SECOND_THIRD_LINE = {
    "AZT(300mg)+3TC(150mg)+ATV/r(300mg/100mg)",
    "TDF(300mg)+3TC(300mg)+ATV/r(300/100mg)",
    "TDF/FTC(300mg/200mg)+ATV/r(300/100mg)",
    "ABC(600mg)+3TC(300mg)+ATV/r(300/100mg)",
    "AZT(300mg)+3TC(150mg)+DRV/r(400mg/50mg)",
    "TDF(300mg)+3TC(300mg)+DRV/r(400mg/50mg)",
    "TDF/FTC(300mg/200mg)+DRV/r(400mg/50mg)",
    "ABC(600mg)+3TC(300mg)+DRV/r(400/50mg)",
    "TDF/FTC(300mg/200mg)+DRV/r(600mg/100mg)+DTG(50mg)",
    "TDF/3TC(300mg/300mg)+DRV/r(600mg/100mg)+DTG(50mg)",
    "ABC/3TC(600mg/300mg)+DRV/r(600mg/100mg)+DTG(50mg)",
    "AZT/3TC(300mg/150mg)+DRV/r(600mg/100mg)+DTG(50mg)",
}

# Paediatric Green List
APPROVED_PEDIATRIC_REGIMENS = {
    "ABC(120mg)/3TC(60mg)+DTG(50mg)",
    "ABC(600mg)/3TC(300mg)+DTG(50mg)",
    "ABC(120mg)/3TC(60mg)+DTG(10mg)",
    "TDF(300mg)/3TC(300mg)/DTG(50mg)",
    "ABC(60mg)/3TC(30mg)+DTG(10mg)",
    "ABC(120mg)+3TC(60mg)+LPV/r(100/25mg)",
    "AZT(60mg)+3TC(30mg)+LPV/r(100/25mg)",
    "ABC (60mg) /3TC (30mg)/ DTG (5mg)",
    "AZT(60mg)+3TC(30mg)+ DTG (10mg)",
}

# Combine all for fast lookup
ALL_APPROVED_REGIMENS = (
    APPROVED_ADULT_FIRST_LINE |
    APPROVED_ADULT_SECOND_THIRD_LINE |
    APPROVED_PEDIATRIC_REGIMENS
)

def is_regimen_valid(regimen_string: str) -> bool:
    """
    Checks if the regimen is in the 'Green List'.
    Normalizes string by removing extra spaces/case sensitivity/dosage variations if strictly needed.
    """
    if not regimen_string:
        return False
    
    # Simple normalization: Remove spaces, lowercase
    def normalize(s): return s.replace(" ", "").lower().strip()
    
    input_norm = normalize(regimen_string)
    
    for valid in ALL_APPROVED_REGIMENS:
        # Check if the core drugs match (simplified check) OR exact match
        if normalize(valid) in input_norm or input_norm in normalize(valid):
            return True
            
    return False