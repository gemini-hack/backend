"""
Team Service - Business logic for team/department management.

Handles team CRUD, member management, and patient assignment.
Permission model:
- Team CRUD: ORG_OWNER only
- Add/Remove members: ORG_OWNER or ORG_ADMIN
- Assign patients: ORG_OWNER, ORG_ADMIN, or team member
"""

from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import Team, User, Organization, UserRole
from app.models.patient import Patient
from app.schemas.teams import (
    TeamCreate,
    TeamUpdate,
    TeamResponse,
    TeamDetailResponse,
    TeamMemberInfo,
)
from app.utils.logger import logger


class TeamServiceError(Exception):
    """Base exception for team service errors."""
    pass


class TeamNotFoundError(TeamServiceError):
    """Team not found."""
    pass


class TeamAlreadyExistsError(TeamServiceError):
    """Team with this name already exists."""
    pass


class InsufficientPermissionsError(TeamServiceError):
    """User doesn't have permission for this action."""
    pass


class MemberNotFoundError(TeamServiceError):
    """User not found or not in team."""
    pass


class PatientNotFoundError(TeamServiceError):
    """Patient not found."""
    pass


class TeamService:
    """
    Team management service.
    
    Handles CRUD operations for teams and team membership management.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    # ============== Permission Checks ==============
    
    def _check_org_owner(self, user: User) -> None:
        """
        Check if user is organization owner.
        
        Raises:
            InsufficientPermissionsError: If user is not ORG_OWNER.
        """
        if user.role != UserRole.ORG_OWNER:
            raise InsufficientPermissionsError("Only organization owners can perform this action")
    
    def _check_org_admin_or_owner(self, user: User) -> None:
        """
        Check if user is organization owner or admin.
        
        Raises:
            InsufficientPermissionsError: If user is not ORG_OWNER or ORG_ADMIN.
        """
        if user.role not in (UserRole.ORG_OWNER, UserRole.ORG_ADMIN):
            raise InsufficientPermissionsError("Only organization owners or admins can perform this action")
    
    # ============== Team CRUD ==============
    
    async def create_team(
        self,
        user: User,
        data: TeamCreate,
    ) -> Team:
        """
        Create a new team in the organization.
        
        Only ORG_OWNER can create teams.
        
        Args:
            user: The authenticated user (must be ORG_OWNER).
            data: Team creation data.
        
        Returns:
            The created Team object.
        
        Raises:
            InsufficientPermissionsError: If user is not ORG_OWNER.
            TeamAlreadyExistsError: If team name already exists in org.
        
        Complexity: O(1) - Single insert with unique constraint check.
        """
        self._check_org_owner(user)
        
        # Check if team name already exists in org
        existing = await Team.fetch_one(
            self.db,
            organization_id=user.organization_id,
            name=data.name
        )
        if existing:
            raise TeamAlreadyExistsError(f"Team '{data.name}' already exists")
        
        team = Team(
            organization_id=user.organization_id,
            name=data.name,
            description=data.description,
        )
        await team.insert(self.db)
        
        logger.info(
            "Team created",
            extra={
                "team_id": str(team.id),
                "team_name": team.name,
                "organization_id": str(user.organization_id),
                "created_by": str(user.id),
            }
        )
        
        return team
    
    async def get_team(
        self,
        team_id: UUID,
        organization_id: UUID,
        include_members: bool = False,
    ) -> Team:
        """
        Get a team by ID.
        
        Args:
            team_id: The team ID.
            organization_id: The organization ID (for authorization).
            include_members: Whether to eager load members.
        
        Returns:
            The Team object.
        
        Raises:
            TeamNotFoundError: If team not found or doesn't belong to org.
        
        Complexity: O(1) if not including members, O(n) if including.
        """
        query = Team.query(self.db).filter_by(
            id=team_id,
            organization_id=organization_id
        )
        
        if include_members:
            query = query.with_relations("members")
        
        team = await query.first()
        
        if not team:
            raise TeamNotFoundError(f"Team with ID {team_id} not found")
        
        return team
    
    async def list_teams(
        self,
        organization_id: UUID,
        include_counts: bool = True,
        is_active: Optional[bool] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[TeamResponse], int]:
        """
        List all teams in an organization.
        
        Args:
            organization_id: The organization ID.
            include_counts: Whether to include member/patient counts.
            is_active: Optional filter by active status.
            skip: Pagination offset.
            limit: Maximum records to return (max 100).
        
        Returns:
            Tuple of (list of TeamResponse, total count).
        
        Complexity: O(n) where n is number of teams.
        """
        limit = min(limit, 100)  # Enforce max limit
        
        query = Team.query(self.db).filter_by(organization_id=organization_id)
        
        if is_active is not None:
            query = query.filter(Team.is_active == is_active)
        
        # Get total count
        total = await query.count()
        
        # Get teams with pagination
        teams = await query.order_by(Team.name).offset(skip).limit(limit).all()
        
        # Build response with counts if requested
        result = []
        for team in teams:
            team_response = TeamResponse(
                id=team.id,
                name=team.name,
                description=team.description,
                is_active=team.is_active,
                created_at=team.created_at,
                member_count=0,
                patient_count=0,
            )
            
            if include_counts:
                # Get member count
                member_count_result = await self.db.execute(
                    select(func.count()).where(User.team_id == team.id)
                )
                team_response.member_count = member_count_result.scalar() or 0
                
                # Get patient count
                patient_count_result = await self.db.execute(
                    select(func.count()).where(Patient.team_id == team.id)
                )
                team_response.patient_count = patient_count_result.scalar() or 0
            
            result.append(team_response)
        
        return result, total
    
    async def update_team(
        self,
        user: User,
        team_id: UUID,
        data: TeamUpdate,
    ) -> Team:
        """
        Update a team.
        
        Only ORG_OWNER can update teams.
        
        Args:
            user: The authenticated user (must be ORG_OWNER).
            team_id: The team ID.
            data: Update data.
        
        Returns:
            The updated Team object.
        
        Raises:
            InsufficientPermissionsError: If user is not ORG_OWNER.
            TeamNotFoundError: If team not found.
            TeamAlreadyExistsError: If new name conflicts.
        
        Complexity: O(1)
        """
        self._check_org_owner(user)
        
        team = await self.get_team(team_id, user.organization_id)
        
        # Check for name conflict if updating name
        if data.name and data.name != team.name:
            existing = await Team.fetch_one(
                self.db,
                organization_id=user.organization_id,
                name=data.name
            )
            if existing:
                raise TeamAlreadyExistsError(f"Team '{data.name}' already exists")
            team.name = data.name
        
        if data.description is not None:
            team.description = data.description
        
        if data.is_active is not None:
            team.is_active = data.is_active
        
        await team.save(self.db)
        
        logger.info(
            "Team updated",
            extra={
                "team_id": str(team.id),
                "updated_by": str(user.id),
            }
        )
        
        return team
    
    async def delete_team(
        self,
        user: User,
        team_id: UUID,
    ) -> None:
        """
        Delete a team (soft delete by deactivating).
        
        Members are unassigned but not deleted.
        Patients are unassigned from the team.
        
        Only ORG_OWNER can delete teams.
        """
        self._check_org_owner(user)

        team = await Team.fetch_unique(
            self.db, 
            id=team_id, 
            organization_id=user.organization_id
        )
        
        if not team:
            raise TeamNotFoundError(f"Team with ID {team_id} not found")

        # 1. Delete all members (Users) of this team
        # Note: This is a strict "Delete Team = Delete Users" policy as requested
        await self.db.execute(
            User.__table__.delete()
            .where(User.team_id == team_id)
        )
        
        # 2. Unassign all patients (keep patients, just remove team link)
        await self.db.execute(
            Patient.__table__.update()
            .where(Patient.team_id == team_id)
            .values(team_id=None)
        )
        
        # 3. Hard Delete the Team
        await self.db.delete(team)
        await self.db.commit()
        
        logger.info(
            "Team and its members deleted",
            extra={
                "team_id": str(team_id),
                "deleted_by": str(user.id),
            }
        )
    
    # ============== Member Management ==============
    
    async def add_member(
        self,
        user: User,
        team_id: UUID,
        email: str,
    ) -> User:
        """
        Add a user to a team.
        
        ORG_OWNER or ORG_ADMIN can add members.
        
        Args:
            user: The authenticated user.
            team_id: The team ID.
            email: The email of the user to add.
        
        Returns:
            The updated User object.
        """
        self._check_org_admin_or_owner(user)
        
        # Verify team exists
        team = await self.get_team(team_id, user.organization_id)
        
        # Verify member exists in org
        member = await User.fetch_one(
            self.db,
            email=email,
            organization_id=user.organization_id
        )
        if not member:
            raise MemberNotFoundError(f"User with email '{email}' not found in organization")
        
        # Assign to team
        member.team_id = team_id
        await member.save(self.db)
        
        logger.info(
            "Member added to team",
            extra={
                "team_id": str(team_id),
                "member_email": email,
                "member_id": str(member.id),
                "added_by": str(user.id),
            }
        )
        
        return member
    
    async def remove_member(
        self,
        user: User,
        team_id: UUID,
        member_user_id: UUID,
    ) -> User:
        """
        Remove a user from a team.
        
        ORG_OWNER or ORG_ADMIN can remove members.
        
        Args:
            user: The authenticated user.
            team_id: The team ID.
            member_user_id: The user ID to remove.
        
        Returns:
            The updated User object.
        
        Raises:
            InsufficientPermissionsError: If user lacks permissions.
            MemberNotFoundError: If member not in team.
        
        Complexity: O(1)
        """
        self._check_org_admin_or_owner(user)
        
        # Verify member is in team
        member = await User.fetch_one(
            self.db,
            id=member_user_id,
            organization_id=user.organization_id,
            team_id=team_id
        )
        if not member:
            raise MemberNotFoundError(f"User {member_user_id} not found in team")
        
        # Unassign from team
        member.team_id = None
        await member.save(self.db)
        
        logger.info(
            "Member removed from team",
            extra={
                "team_id": str(team_id),
                "member_id": str(member_user_id),
                "removed_by": str(user.id),
            }
        )
        
        return member
    
    async def list_members(
        self,
        team_id: UUID,
        organization_id: UUID,
    ) -> Sequence[TeamMemberInfo]:
        """
        List all members of a team.
        
        Args:
            team_id: The team ID.
            organization_id: The organization ID.
        
        Returns:
            List of TeamMemberInfo.
        
        Complexity: O(n) where n is number of members.
        """
        # Verify team exists
        await self.get_team(team_id, organization_id)
        
        members = await User.query(self.db).filter_by(
            team_id=team_id,
            organization_id=organization_id
        ).all()
        
        return [
            TeamMemberInfo(
                user_id=m.id,
                first_name=m.first_name,
                last_name=m.last_name,
                email=m.email,
                role=m.role,
                joined_at=m.updated_at,  # Using updated_at as proxy for join date
            )
            for m in members
        ]
    
    # ============== Patient Assignment ==============
    
    async def assign_patient(
        self,
        user: User,
        team_id: UUID,
        patient_id: UUID,
    ) -> Patient:
        """
        Assign a patient to a team.
        
        ORG_OWNER, ORG_ADMIN, or team members can assign patients.
        
        Args:
            user: The authenticated user.
            team_id: The team ID.
            patient_id: The patient ID.
        
        Returns:
            The updated Patient object.
        
        Raises:
            InsufficientPermissionsError: If user lacks permissions.
            TeamNotFoundError: If team not found.
            PatientNotFoundError: If patient not found.
        
        Complexity: O(1)
        """
        # Check permissions
        is_admin_or_owner = user.role in (UserRole.ORG_OWNER, UserRole.ORG_ADMIN)
        is_team_member = user.team_id == team_id
        
        if not (is_admin_or_owner or is_team_member):
            raise InsufficientPermissionsError(
                "Only admins, owners, or team members can assign patients"
            )
        
        # Verify team exists
        team = await self.get_team(team_id, user.organization_id)
        
        # Verify patient exists in org
        patient = await Patient.fetch_one(
            self.db,
            id=patient_id,
            organization_id=user.organization_id
        )
        if not patient:
            raise PatientNotFoundError(f"Patient {patient_id} not found")
        
        # Assign to team
        patient.team_id = team_id
        await patient.save(self.db)
        
        logger.info(
            "Patient assigned to team",
            extra={
                "team_id": str(team_id),
                "patient_id": str(patient_id),
                "assigned_by": str(user.id),
            }
        )
        
        return patient
    
    async def unassign_patient(
        self,
        user: User,
        patient_id: UUID,
    ) -> Patient:
        """
        Unassign a patient from their team.
        
        Args:
            user: The authenticated user.
            patient_id: The patient ID.
        
        Returns:
            The updated Patient object.
        
        Raises:
            PatientNotFoundError: If patient not found.
        
        Complexity: O(1)
        """
        self._check_org_admin_or_owner(user)
        
        patient = await Patient.fetch_one(
            self.db,
            id=patient_id,
            organization_id=user.organization_id
        )
        if not patient:
            raise PatientNotFoundError(f"Patient {patient_id} not found")
        
        old_team_id = patient.team_id
        patient.team_id = None
        await patient.save(self.db)
        
        logger.info(
            "Patient unassigned from team",
            extra={
                "old_team_id": str(old_team_id) if old_team_id else None,
                "patient_id": str(patient_id),
                "unassigned_by": str(user.id),
            }
        )
        
        return patient
    
    async def bulk_assign_patients(
        self,
        user: User,
        team_id: UUID,
        patient_ids: list[UUID],
    ) -> int:
        """
        Bulk assign multiple patients to a team.
        
        Args:
            user: The authenticated user.
            team_id: The team ID.
            patient_ids: List of patient IDs.
        
        Returns:
            Number of patients assigned.
        
        Raises:
            InsufficientPermissionsError: If user lacks permissions.
            TeamNotFoundError: If team not found.
        
        Complexity: O(n) where n is number of patients.
        """
        self._check_org_admin_or_owner(user)
        
        # Verify team exists
        await self.get_team(team_id, user.organization_id)
        
        # Bulk update
        result = await self.db.execute(
            Patient.__table__.update()
            .where(
                and_(
                    Patient.id.in_(patient_ids),
                    Patient.organization_id == user.organization_id
                )
            )
            .values(team_id=team_id)
        )
        await self.db.commit()
        
        count = result.rowcount
        
        logger.info(
            "Bulk patient assignment",
            extra={
                "team_id": str(team_id),
                "patient_count": count,
                "assigned_by": str(user.id),
            }
        )
        
        return count
