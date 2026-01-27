"""add_decision_trace_column

Revision ID: 4d7e9cf6b47d
Revises: 3c6d8bc5a36c
Create Date: 2026-01-27 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4d7e9cf6b47d'
down_revision: Union[str, Sequence[str], None] = '3c6d8bc5a36c' # Points to your last migration
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add the missing column 'decision_trace'
    # I am using JSONB because 'trace' data is usually complex. 
    # If your model defines it as String, change sa.JSON() to sa.String().
    op.add_column('agent_actions', sa.Column('decision_trace', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('agent_actions', 'decision_trace')