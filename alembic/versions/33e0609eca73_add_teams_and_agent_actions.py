"""add_teams_and_agent_actions

Revision ID: 33e0609eca73
Revises: 934a9f8abf9f
Create Date: 2026-01-23 18:06:04.890712

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '33e0609eca73'
down_revision: Union[str, Sequence[str], None] = '934a9f8abf9f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### Teams Table ###
    op.create_table('teams',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_teams_org_name', 'teams', ['organization_id', 'name'], unique=True)
    op.create_index(op.f('ix_teams_organization_id'), 'teams', ['organization_id'], unique=False)
    
    # ### Add Team ID to Users ###
    op.add_column('users', sa.Column('team_id', sa.Uuid(), nullable=True))
    op.create_index('idx_users_team', 'users', ['team_id'], unique=False)
    op.create_index(op.f('ix_users_team_id'), 'users', ['team_id'], unique=False)
    op.create_foreign_key(None, 'users', 'teams', ['team_id'], ['id'], ondelete='SET NULL')

    # ### Add Team ID to Patients ###
    op.add_column('patients', sa.Column('team_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_patients_team_id'), 'patients', ['team_id'], unique=False)
    op.create_foreign_key(None, 'patients', 'teams', ['team_id'], ['id'], ondelete='SET NULL')

    # ### Add Team ID to Invitations ###
    op.add_column('invitations', sa.Column('team_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_invitations_team_id'), 'invitations', ['team_id'], unique=False)
    op.create_foreign_key(None, 'invitations', 'teams', ['team_id'], ['id'], ondelete='SET NULL')

    # ### Agent Actions Table ###
    op.create_table('agent_actions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('patient_id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('triggered_by_reading_id', sa.Uuid(), nullable=True),
    sa.Column('triggered_by_alert_id', sa.Uuid(), nullable=True),
    sa.Column('action_type', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('recipient', sa.String(length=255), nullable=True),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('retry_count', sa.Integer(), nullable=False),
    sa.Column('ai_reasoning', sa.Text(), nullable=True),
    sa.Column('confidence_score', sa.Float(), nullable=True),
    sa.Column('decision_trace', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['triggered_by_alert_id'], ['alerts.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['triggered_by_reading_id'], ['health_readings.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_actions_action_type'), 'agent_actions', ['action_type'], unique=False)
    op.create_index(op.f('ix_agent_actions_organization_id'), 'agent_actions', ['organization_id'], unique=False)
    op.create_index(op.f('ix_agent_actions_patient_id'), 'agent_actions', ['patient_id'], unique=False)
    op.create_index(op.f('ix_agent_actions_status'), 'agent_actions', ['status'], unique=False)


def downgrade() -> None:
    # ### Downgrade Agent Actions ###
    op.drop_index(op.f('ix_agent_actions_status'), table_name='agent_actions')
    op.drop_index(op.f('ix_agent_actions_patient_id'), table_name='agent_actions')
    op.drop_index(op.f('ix_agent_actions_organization_id'), table_name='agent_actions')
    op.drop_index(op.f('ix_agent_actions_action_type'), table_name='agent_actions')
    op.drop_table('agent_actions')

    # ### Downgrade Teams Feature ###
    op.drop_constraint(None, 'invitations', type_='foreignkey')
    op.drop_index(op.f('ix_invitations_team_id'), table_name='invitations')
    op.drop_column('invitations', 'team_id')

    op.drop_constraint(None, 'patients', type_='foreignkey')
    op.drop_index(op.f('ix_patients_team_id'), table_name='patients')
    op.drop_column('patients', 'team_id')

    op.drop_constraint(None, 'users', type_='foreignkey')
    op.drop_index(op.f('ix_users_team_id'), table_name='users')
    op.drop_index('idx_users_team', table_name='users')
    op.drop_column('users', 'team_id')

    op.drop_index(op.f('ix_teams_organization_id'), table_name='teams')
    op.drop_index('idx_teams_org_name', table_name='teams')
    op.drop_table('teams')
