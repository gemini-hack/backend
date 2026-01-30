"""add_action_outcome_tracking

Revision ID: ae19f873840b
Revises: bc3f1a896da0
Create Date: 2026-01-30 09:53:38.585804

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ae19f873840b'
down_revision: Union[str, Sequence[str], None] = 'bc3f1a896da0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add outcome tracking fields to agent_actions."""
    # Create the enum type first
    actionoutcome_enum = sa.Enum('PENDING', 'SENT', 'FAILED', 'RESOLVED', 'EXPIRED', name='actionoutcome')
    actionoutcome_enum.create(op.get_bind(), checkfirst=True)
    
    # Add outcome columns
    op.add_column('agent_actions', sa.Column('outcome', actionoutcome_enum, nullable=False, server_default='PENDING'))
    op.add_column('agent_actions', sa.Column('outcome_detected_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('agent_actions', sa.Column('outcome_reason', sa.String(length=255), nullable=True))
    op.create_index(op.f('ix_agent_actions_outcome'), 'agent_actions', ['outcome'], unique=False)


def downgrade() -> None:
    """Remove outcome tracking fields from agent_actions."""
    op.drop_index(op.f('ix_agent_actions_outcome'), table_name='agent_actions')
    op.drop_column('agent_actions', 'outcome_reason')
    op.drop_column('agent_actions', 'outcome_detected_at')
    op.drop_column('agent_actions', 'outcome')
    
    # Drop the enum type
    sa.Enum(name='actionoutcome').drop(op.get_bind(), checkfirst=True)

