from typing import List, Dict, Type, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.base import BaseWorker
from app.agents.workers.hypertension import HypertensionWorker
from app.agents.workers.disengagement import DisengagementWorker
from app.agents.workers.hiv import HIVWorker
from app.agents.workers.critic import CriticWorker
from app.agents.workers.followup_specialist import FollowUpSpecialist
from app.utils.logger import logger

class AgentFactory:
    """
    Factory to dynamically assemble worker teams based on organization specialization.
    """
    
    @staticmethod
    def get_workers_for_org(db: AsyncSession, specializations: List[str]) -> List[BaseWorker]:
        workers: List[BaseWorker] = []
        
        # 1. Always include core health workers
        workers.append(DisengagementWorker())
        
        # 2. Always include appointment follow-up specialist (not disease-specific)
        workers.append(FollowUpSpecialist(db))
        
        # 3. Add disease-specific specialists
        if "hypertension" in specializations:
            workers.append(HypertensionWorker(db))
            
        if "hiv" in specializations:
            workers.append(HIVWorker(db))
            
        logger.info(f"Factory assembled {len(workers)} specialists for specializations: {specializations}")
        return workers

