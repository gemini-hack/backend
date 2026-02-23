from pydantic import BaseModel, ConfigDict
from typing import Dict, List
from datetime import datetime

class PatientStats(BaseModel):
    total_active: int
    new_this_week: int
    by_condition: Dict[str, int]
    by_status: Dict[str, int]

class AlertStats(BaseModel):
    total_pending: int
    critical_count: int
    high_priority_count: int
    by_category: Dict[str, int]

class AgentStats(BaseModel):
    actions_today: int
    actions_pending: int
    top_actions: List[Dict[str, int]]

class AdminDashboardResponse(BaseModel):
    organization_id: str
    organization_name: str
    generated_at: datetime
    
    patients: PatientStats
    alerts: AlertStats
    agents: AgentStats


class WorkerDashboardStats(BaseModel):
    """Stats for worker dashboard derived from agent actions."""
    total_patients: int          
    needs_attention: int        
    pending_actions: int         
    resolved_today: int           
    generated_at: datetime
